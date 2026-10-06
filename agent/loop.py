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
from agent.prompt import SYSTEM_PROMPT
from agent.context import maybe_compress
from agent.memory import load_memory
from agent.resilience import chat_with_retries, RunAborted
from agent import sessions
from tools.registry import schemas, dispatch

MAX_TURNS = 25
MAX_TOOL_OUTPUT = 2000


def _make_renderer():
    """Returns (render, state). `render` prints text deltas live; `state`
    tracks whether anything was rendered so the loop can close the line.
    Sub-agent output gets a prefix — children stream from their own threads
    and would otherwise interleave illegibly with the parent's."""
    state = {"started": False}

    def render(token: str):
        if not state["started"]:
            try:
                from agent.subagents import depth
                who = "sub-agent" if depth() > 0 else "thinking"
            except Exception:
                who = "thinking"
            print(f"\n💭 [{who}] ", end="", flush=True)
            state["started"] = True
        print(token, end="", flush=True)

    return render, state


def run(user_message: str, history: list = None, session_id: str = None,
        max_turns: int = MAX_TURNS, allow_delegate: bool = True,
        on_text=None, on_event=None, on_reasoning=None):
    """Returns (final_answer, history_without_system_prompt).
    UI callbacks (web frontend): on_text -> text deltas; on_reasoning ->
    reasoning deltas; on_event -> {"kind": "turn"|"act"|"observe", "text": str}
    with FULL tool args and FULL post-truncation tool output (ACT/OBSERVE).
    When omitted, a CLI adapter reproduces the classic console output."""
    # Phase 7: semantic memory injected into the system prompt tier — the
    # "always true" knowledge. Safe to do on EVERY run(): messages are rebuilt
    # fresh each call and history excludes the system prompt, so it never
    # duplicates or compounds.
    sys_content = SYSTEM_PROMPT
    memory = load_memory()
    if memory:
        sys_content += "\n\n[PERSISTENT MEMORY — facts from past sessions]\n" + memory
    messages = [{"role": "system", "content": sys_content}] + (history or [])
    messages.append({"role": "user", "content": user_message})
    if session_id:
        sessions.append(session_id, "user", user_message)

    if on_event is None:   # CLI adapter: dicts -> the classic console lines
        def on_event(ev):
            if ev["kind"] == "turn":
                print(f"\n--- turn {ev['text']} ---")
            elif ev["kind"] == "act":
                print(f"⚡ ACT: {ev['text'][:100]}")
            elif ev["kind"] == "observe":
                print(f"👁 OBSERVE: {ev['text'][:150]}")

    for turn in range(1, max_turns + 1):
        on_event({"kind": "turn", "text": f"{turn}/{max_turns}"})

        # HOOK 1: preflight compression (Hermes does the same before every
        # API call). Under budget it returns messages unchanged — a no-op.
        messages = maybe_compress(messages)

        # Phase 8: stream tokens live. AGENT_STREAM=0 restores the old
        # silent-until-done behavior. Internal calls (summaries, reflection)
        # pass no callback, so they never print. An injected on_text (web UI)
        # always streams, regardless of the env flag.
        if on_text is not None:
            render, streamed = on_text, {"started": False}
        else:
            render, streamed = _make_renderer()
        on_text_cb = render if (on_text is not None
                                or os.getenv("AGENT_STREAM", "1") == "1") else None

        # Phase 6: the harness layer handles API failures below the model's
        # awareness (backoff+jitter, emergency compression, circuit breaker).
        # Nothing was appended yet, so retries can never double-persist.
        try:
            assistant_msg = chat_with_retries(messages, schemas(),
                                              on_text=on_text_cb,
                                              on_reasoning=on_reasoning)
        except RunAborted as e:
            # honest stop — the session stays valid for /resume
            return f"Run aborted: {e}", messages[1:]
        finally:
            if streamed["started"] and on_text is None:
                print()   # close the streamed line before ACT/OBSERVE output

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
            # full raw args go to the UI; the CLI adapter truncates for display
            on_event({"kind": "act",
                      "text": f"{name}({tc['function']['arguments'] or ''})"})
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
            # the UI gets the FULL post-truncation output; CLI keeps it short
            on_event({"kind": "observe", "text": result or "(no output)"})

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
