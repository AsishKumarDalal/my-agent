# Phase 7: semantic memory — MEMORY.md. The third tier of the hierarchy:
# working memory (context) -> episodic (sessions.db) -> semantic (this file).
# Durable FACTS only (user prefs, project facts, decisions+reasons, gotchas) —
# NOT task progress (todo.md's job) and NOT history (sessions.db's job).
# One cheap LLM call merges new facts into the file; a hard size cap forces
# curation, because memory that only grows becomes context rot one level up.
import os

from agent.llm import chat

MEMORY_PATH = os.path.join(os.getenv("AGENT_WORKSPACE", "."), "MEMORY.md")
MAX_MEMORY_CHARS = 8000   # ~2k tokens — the "always loaded" budget

REFLECT_SYSTEM = (
    "You maintain an agent's persistent memory file. From the conversation "
    "extract only DURABLE facts worth remembering across future sessions:\n"
    "- user preferences and working style\n"
    "- stable project facts (stacks, commands, endpoints, constraints)\n"
    "- decisions AND their reasons\n"
    "- gotchas and pitfalls discovered\n"
    "Do NOT include: task progress, one-off details, anything derivable "
    "from the repo, or conversation history. Merge with the existing memory "
    "(drop facts it contradicts). Output ONLY the new memory file as bullet "
    "lines starting with '- '. Maximum 40 lines. If nothing changed, return "
    "the existing memory unchanged."
)


def load_memory() -> str:
    if not os.path.exists(MEMORY_PATH):
        return ""
    with open(MEMORY_PATH, encoding="utf-8") as f:
        return f.read().strip()


def reflect_and_save(history: list) -> str:
    """One cheap LLM call: existing memory + recent transcript -> new memory.
    Called at session end / every N messages / on compression. Deterministic
    cap afterwards: prune OLDEST lines if the model came back verbose."""
    current = load_memory()
    if not history:
        return current

    transcript = "\n".join(
        f"[{m['role']}] {(m.get('content') or '')[:400]}"
        for m in history if m["role"] != "system"
    )[-6000:]   # most recent slice — reflection is about what just happened

    try:
        out = chat([
            {"role": "system", "content": REFLECT_SYSTEM},
            {"role": "user",
             "content": f"CURRENT MEMORY:\n{current or '(empty)'}\n\n"
                        f"RECENT CONVERSATION:\n{transcript}"},
        ], tools=None)
        new = (out.get("content") or "").strip()
    except Exception as e:
        # degradation ladder: reflection failing must never break the session
        print(f"[memory] reflection failed ({e}); keeping existing memory")
        return current

    if not new or new.lower().startswith("(nothing"):
        return current

    # deterministic size cap — prune oldest lines past the budget
    if len(new) > MAX_MEMORY_CHARS:
        lines, kept = new.splitlines(), []
        size = 0
        for line in reversed(lines):        # newest last -> walk backwards
            if size + len(line) > MAX_MEMORY_CHARS:
                break
            kept.insert(0, line)
            size += len(line) + 1
        new = "\n".join(kept) if kept else new[:MAX_MEMORY_CHARS]

    with open(MEMORY_PATH, "w", encoding="utf-8") as f:
        f.write(new + "\n")
    return new
