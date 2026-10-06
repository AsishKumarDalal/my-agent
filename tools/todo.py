# Phase 5: structured note-taking (agentic memory). The plan lives in a
# FILE, not in context — it survives Phase 3 compression, and re-reading it
# corrects drift ("I planned the import fix first, but I've been on CSS").
# Agent-owned scratch state: freely rewritten, unlike append-only sessions.
import os

TODO_PATH = os.path.join(os.getenv("AGENT_WORKSPACE", "."), "todo.md")


def handle_todo(args: dict) -> str:
    items = args.get("items")
    if not isinstance(items, list) or not items:
        return "ERROR: 'items' must be a non-empty list of plan lines."
    with open(TODO_PATH, "w", encoding="utf-8") as f:
        f.write("# Plan\n" + "\n".join(f"- {i}" for i in items) + "\n")
    return f"Plan written to {TODO_PATH} ({len(items)} items)."


def read_todo() -> str:
    if not os.path.exists(TODO_PATH):
        return "(no plan yet)"
    with open(TODO_PATH, encoding="utf-8") as f:
        return f.read()
