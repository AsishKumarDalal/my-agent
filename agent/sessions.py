# Phase 3: SQLite session persistence. Append-only diary (never UPDATE/DELETE
# messages). Storage is truth; context is a view rebuilt by load().
# Full protocol is stored (tool_call_id, tool_calls JSON) so /resume produces
# a history the API accepts exactly. FTS5 search on this same table = Phase 7.
import json
import sqlite3
import uuid
from datetime import datetime

DB_PATH = "sessions.db"


def _conn():
    conn = sqlite3.connect(DB_PATH)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS sessions (
            id TEXT PRIMARY KEY,
            title TEXT,
            parent_id TEXT,
            created_at TEXT NOT NULL
        )""")
    conn.execute("""
        CREATE TABLE IF NOT EXISTS messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id TEXT NOT NULL,
            seq INTEGER NOT NULL,
            role TEXT NOT NULL,
            content TEXT,
            tool_call_id TEXT,
            tool_calls TEXT,
            created_at TEXT NOT NULL
        )""")
    return conn


def new_session(title: str = None, parent_id: str = None) -> str:
    """parent_id links a compressed continuation to the original session
    (lineage): compression never destroys the full verbatim history."""
    sid = uuid.uuid4().hex[:12]
    with _conn() as conn:
        conn.execute(
            "INSERT INTO sessions (id, title, parent_id, created_at) "
            "VALUES (?, ?, ?, ?)",
            (sid, title, parent_id, datetime.now().isoformat(timespec="seconds")))
    return sid


def set_title(session_id: str, title: str):
    """One of the few allowed writes: session metadata, never messages."""
    with _conn() as conn:
        conn.execute("UPDATE sessions SET title=? WHERE id=?",
                     (title, session_id))


def append(session_id: str, role: str, content: str,
           tool_call_id: str = None, tool_calls: str = None):
    with _conn() as conn:
        seq = conn.execute(
            "SELECT COALESCE(MAX(seq), -1) + 1 FROM messages WHERE session_id=?",
            (session_id,)).fetchone()[0]
        conn.execute(
            "INSERT INTO messages (session_id, seq, role, content, "
            "tool_call_id, tool_calls, created_at) VALUES (?,?,?,?,?,?,?)",
            (session_id, seq, role, content, tool_call_id, tool_calls,
             datetime.now().isoformat(timespec="seconds")))


def load(session_id: str) -> list:
    """Rebuild the exact message list run() expects (no system prompt here)."""
    with _conn() as conn:
        rows = conn.execute(
            "SELECT role, content, tool_call_id, tool_calls FROM messages "
            "WHERE session_id=? ORDER BY seq",
            (session_id,)).fetchall()
    out = []
    for role, content, tcid, tcs in rows:
        msg = {"role": role, "content": content or ""}
        if role == "assistant" and tcs:
            msg["tool_calls"] = json.loads(tcs)
        if role == "tool" and tcid:
            msg["tool_call_id"] = tcid
        out.append(msg)
    return out


def list_sessions(limit: int = 10) -> list:
    with _conn() as conn:
        return conn.execute(
            "SELECT s.id, s.title, s.parent_id, COUNT(m.id), s.created_at "
            "FROM sessions s LEFT JOIN messages m ON m.session_id = s.id "
            "GROUP BY s.id ORDER BY s.created_at DESC LIMIT ?",
            (limit,)).fetchall()
