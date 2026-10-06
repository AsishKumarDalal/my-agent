# Phase 1: the ReAct loop lives here.
# Loop: messages -> LLM -> tool_calls? -> execute -> observe -> repeat.
# Rules: always append assistant msg before tool results; errors are
# observations; truncate tool output; hard max_turns budget.
# Phase 3: two dumb hooks added — maybe_compress before each model call,
# sessions.append for every message produced. The loop never learns HOW
# compression or storage work; it just calls them.
# Phase 5: run() gains max_turns/allow_delegate (sub-agent budgets), and
# independent tool calls in one message run in a thread pool — results are
# re-inserted in ORIGINAL call order regardless of completion order.

import json
import os
from concurrent.futures import ThreadPoolExecutor
from agent.llm import chat
from agent.prompt import SYSTEM_PROMPT
from agent.context import maybe_compress
from agent import sessions
from tools.registry import schemas, dispatch

MAX_TURNS = 25
MAX_TOOL_OUTPUT = 2000


def run(user_message: str, history: list = None, session_id: str = None,
        max_turns: int = MAX_TURNS, allow_delegate: bool = True):
    """Returns (final_answer, history_without_system_prompt)."""
    messages = [{"role": "system", "content": SYSTEM_PROMPT}] + (history or [])
    messages.append({"role": "user", "content": user_message})
    if session_id:
        sessions.append(session_id, "user", user_message)

    for turn in range(1, max_turns + 1):
        print(f"\n--- turn {turn}/{max_turns} ---")

        # HOOK 1: preflight compression (Hermes does the same before every
        # API call). Under budget it returns messages unchanged — a no-op.
        messages = maybe_compress(messages)

        assistant_msg = chat(messages, schemas())
        messages.append(assistant_msg)  # RULE 1: assistant msg BEFORE tool results
        if session_id:
            # store tool_calls JSON too — /resume must be protocol-valid
            sessions.append(session_id, "assistant",
                            assistant_msg.get("content") or "(tool calls)",
                            tool_calls=(json.dumps(assistant_msg["tool_calls"])
                                        if assistant_msg.get("tool_calls")
                                        else None))

        tool_calls = assistant_msg.get("tool_calls", [])
        if not tool_calls:
            return assistant_msg["content"], messages[1:]  # stop condition

        def _one(tc):
            # RULE 2: defensive arg parsing — broken JSON is an observation
            name = tc["function"]["name"]
            if name == "delegate_task" and not allow_delegate:
                return ("DENIED: sub-agents cannot delegate. "
                        "Report findings to the parent agent.")
            try:
                args = json.loads(tc["function"]["arguments"] or "{}")
                if not isinstance(args, dict):
                    raise ValueError("arguments must be a JSON object")
            except (json.JSONDecodeError, ValueError) as e:
                return f"ERROR: could not parse tool arguments: {e}"
            print(f"⚡ ACT: {name}({str(args)[:100]})")
            return dispatch(name, args)

        # Phase 5: the model asserting several calls in ONE message declares
        # them independent — license to parallelize. pool.map preserves the
        # original call order in the RESULT list (protocol-safe reinsertion).
        if os.getenv("AGENT_PARALLEL_TOOLS", "1") == "1" and len(tool_calls) > 1:
            with ThreadPoolExecutor(max_workers=4) as pool:
                results = list(pool.map(_one, tool_calls))
        else:
            results = [_one(tc) for tc in tool_calls]

        finished = None
        for tc, result in zip(tool_calls, results):  # ORIGINAL order
            # RULE 3: truncate — one big file must not eat your context
            if result and len(result) > MAX_TOOL_OUTPUT:
                result = result[:MAX_TOOL_OUTPUT] + "\n...[truncated]"
            print(f"👁 OBSERVE: {(result or '')[:150]}")

            messages.append({
                "role": "tool",
                "tool_call_id": tc["id"],
                "content": result or "(no output)",
            })
            # HOOK 2: persist what the model actually saw (post-truncation),
            # with the id so tool results pair with their call on /resume.
            if session_id:
                sessions.append(session_id, "tool", result or "(no output)",
                                tool_call_id=tc["id"])
            if tc["function"]["name"] == "finish":
                try:
                    fargs = json.loads(tc["function"]["arguments"] or "{}")
                except json.JSONDecodeError:
                    fargs = {}
                finished = fargs.get("summary", "(no summary)")

        if finished is not None:  # RULE 4: explicit stop via finish
            return finished, messages[1:]

    return "Iteration budget exhausted — task incomplete.", messages[1:]
