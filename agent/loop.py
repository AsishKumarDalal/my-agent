# Phase 1: the ReAct loop lives here.
# Loop: messages -> LLM -> tool_calls? -> execute -> observe -> repeat.
# Rules: always append assistant msg before tool results; errors are
# observations; truncate tool output; hard max_turns budget.

import json
from agent.llm import chat
from agent.prompt import SYSTEM_PROMPT
from tools.registry import schemas, dispatch
 
MAX_TURNS = 25
MAX_TOOL_OUTPUT = 2000
 
 
def run(user_message: str, history: list = None):
    """Returns (final_answer, history_without_system_prompt)."""
    messages = [{"role": "system", "content": SYSTEM_PROMPT}] + (history or [])
    messages.append({"role": "user", "content": user_message})
 
    for turn in range(1, MAX_TURNS + 1):
        print(f"\n--- turn {turn}/{MAX_TURNS} ---")
 
        assistant_msg = chat(messages, schemas())
        messages.append(assistant_msg)  # RULE 1: assistant msg BEFORE tool results
 
        tool_calls = assistant_msg.get("tool_calls", [])
        if not tool_calls:
            return assistant_msg["content"], messages[1:]  # stop condition
 
        finished = None
        for tc in tool_calls:
            name = tc["function"]["name"]
 
            # RULE 2: defensive arg parsing — broken JSON is an observation
            try:
                args = json.loads(tc["function"]["arguments"] or "{}")
                if not isinstance(args, dict):
                    raise ValueError("arguments must be a JSON object")
            except (json.JSONDecodeError, ValueError) as e:
                result = f"ERROR: could not parse tool arguments: {e}"
            else:
                print(f"⚡ ACT: {name}({args})")
                result = dispatch(name, args)
                if name == "finish":
                    finished = args.get("summary", "(no summary)")
 
            # RULE 3: truncate — one big file must not eat your context
            if result and len(result) > MAX_TOOL_OUTPUT:
                result = result[:MAX_TOOL_OUTPUT] + "\n...[truncated]"
            print(f"👁 OBSERVE: {(result or '')[:150]}")
 
            messages.append({
                "role": "tool",
                "tool_call_id": tc["id"],
                "content": result or "(no output)",
            })
 
        if finished is not None:  # RULE 4: explicit stop via finish
            return finished, messages[1:]
 
    return "Iteration budget exhausted — task incomplete.", messages[1:]
