# Phase 3: token accounting + context compression.
# maybe_compress() fires BEFORE each model call, cuts ONLY at turn boundaries.
# Pure-ish: message list in -> message list out. No SQLite, no UI.
import os

try:
    import tiktoken
    _enc = tiktoken.get_encoding("cl100k_base")

    def count_tokens(text: str) -> int:
        return len(_enc.encode(text))
except ImportError:
    def count_tokens(text: str) -> int:
        return max(1, len(text) // 4)   # heuristic fallback (~4 chars/token)


# Hermes uses 50% soft threshold; both configurable for testing.
CONTEXT_BUDGET = int(os.getenv("AGENT_CONTEXT_BUDGET", "24000"))
KEEP_RECENT = int(os.getenv("AGENT_KEEP_RECENT", "6"))   # turns kept verbatim
COMPRESS_TO = 0.4                                        # compress down to 40%


def context_size(messages: list) -> int:
    return sum(count_tokens(m.get("content") or "") for m in messages)


def _turn_start(messages: list, assistant_i: int) -> int:
    """First index of the turn that assistant_i belongs to.
    A turn = assistant msg (maybe with tool_calls) + its tool results."""
    j = assistant_i
    while j - 1 >= 0 and messages[j - 1].get("role") == "tool":
        j -= 1
    return j


def _find_cut(messages: list) -> int:
    """Walk backwards, find where 'recent verbatim' zone starts.
    MUST land on a turn boundary (never between tool call and its results)."""
    cut = len(messages)
    kept = 0
    while cut > 1 and kept < KEEP_RECENT:
        prev = messages[cut - 1]
        if prev.get("role") == "assistant" and prev.get("tool_calls"):
            cut = _turn_start(messages, cut - 1)
            kept += 1
        else:
            cut -= 1
            if prev.get("role") in ("user", "assistant"):
                kept += 1
    return cut


def maybe_compress(messages: list) -> list:
    """Under budget -> return as-is. Over budget -> [system, summary, recent]."""
    if context_size(messages) <= CONTEXT_BUDGET:
        return messages

    cut = _find_cut(messages)
    old = messages[1:cut]          # skip system prompt (index 0)
    recent = messages[cut:]
    if not old:
        return messages            # nothing compressible yet; overflow
                                   # recovery (hard API errors) is Phase 6

    summary = _summarize(old)
    return [messages[0], summary] + recent


def _summarize(old: list) -> dict:
    """One cheap LLM call. Recall first (Anthropic): keep goal, actions,
    files, state, remaining work. Trim later once you see real traces."""
    from agent.llm import chat
    transcript = "\n".join(
        f"[{m['role']}] {(m.get('content') or '')[:500]}"
        for m in old if m["role"] != "system"
    )
    out = chat([
        {"role": "system", "content":
         "Summarize an agent's earlier work. Terse but complete. Include: "
         "(1) the user's goal, (2) actions taken and results, "
         "(3) files created/modified with paths, (4) current state, "
         "(5) what remains. Max 250 words."},
        {"role": "user", "content": transcript[:8000]},
    ], tools=None)
    text = out.get("content") or "(summary unavailable)"
    return {"role": "user",
            "content": f"[CONTEXT SUMMARY of earlier turns]\n{text}"}
