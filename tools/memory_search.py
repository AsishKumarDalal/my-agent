# Phase 7: the session_search tool — episodic recall via FTS5.
# Just-in-time retrieval: the agent doesn't HOLD past sessions in context,
# it holds the ABILITY to look. Results are snippets with session ids (so the
# agent can ask the user to /resume or dig deeper), BM25-ranked, size-capped.
from agent import sessions


def handle_session_search(args: dict) -> str:
    query = str(args.get("query", "")).strip()
    if not query:
        return "ERROR: 'query' is required (keywords, e.g. 'auth bug fix')."
    try:
        limit = max(1, min(int(args.get("limit", 5)), 10))
    except (TypeError, ValueError):
        limit = 5

    try:
        sessions.rebuild_index()   # no-op if index is current
        hits = sessions.search(query, limit=limit)
    except Exception as e:
        return f"ERROR: session search failed: {e}"

    if not hits:
        return f"No past session matches '{query}'."

    lines = [f"[{sid} | {role}] {snippet.strip()}"
             for sid, role, snippet in hits]
    return ("Past session matches (BM25-ranked; session ids can be /resume-d):\n"
            + "\n".join(lines))
