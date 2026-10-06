# Web frontend server: ChatGPT-style UI over the existing harness.
# Storage is truth — every /api/chat reloads history from sessions.db, so the
# web UI and the CLI (main.py) share the exact same sessions and memory.
# Approvals fail CLOSED in web mode (no human prompt available): dangerous
# commands are denied and the denial is streamed as an event.
import queue
import sys
import threading
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dotenv import load_dotenv
load_dotenv()  # same contract as main.py: BASE_URL/API_KEY/MODEL + AGENT_* knobs

from flask import Flask, Response, jsonify, request, send_from_directory

from agent import sessions
from agent.loop import run
from agent.memory import reflect_and_save
import tools.approval as approval

REFLECT_EVERY = 5

app = Flask(__name__, static_folder="static", static_url_path="/static")

# queue of the currently streaming chat run (single-user local app; the lock
# guards against two browser tabs streaming at once)
_stream_q = None
_stream_lock = threading.Lock()


def _web_approval(command: str, tool_name: str) -> bool:
    """Fail-closed: the web UI cannot prompt safely, so dangerous commands
    are denied and the denial is surfaced in the stream."""
    if _stream_q is not None:
        _stream_q.put(("event",
                       f"APPROVAL DENIED ({tool_name}): {command[:150]}"))
    return False


approval.APPROVAL_CALLBACK = _web_approval


def _sse(obj) -> str:
    import json
    return f"data: {json.dumps(obj)}\n\n"


@app.get("/")
def index():
    return send_from_directory(app.static_folder, "index.html")


@app.get("/api/sessions")
def api_sessions():
    out = [{"id": sid, "title": title or "(untitled)", "count": count,
            "created": created}
           for sid, title, parent, count, created in sessions.list_sessions(100)]
    return jsonify(out)


@app.post("/api/sessions")
def api_new_session():
    title = (request.get_json(silent=True) or {}).get("title")
    sid = sessions.new_session(title=title)
    return jsonify({"id": sid, "title": title or "(untitled)", "count": 0})


@app.get("/api/sessions/<sid>")
def api_session_messages(sid):
    msgs = [{"role": m["role"], "content": m["content"]}
            for m in sessions.load(sid)
            if m["role"] in ("user", "assistant") and m["content"]]
    meta = next(({"id": s, "title": t or "(untitled)", "count": c}
                 for s, t, _p, c, _cr in sessions.list_sessions(100)
                 if s == sid), {"id": sid, "title": "(untitled)", "count": 0})
    return jsonify({"meta": meta, "messages": msgs})


def _maybe_reflect(sid: str):
    with sessions._conn() as conn:
        n = conn.execute(
            "SELECT COUNT(*) FROM messages WHERE session_id=? AND role='user'",
            (sid,)).fetchone()[0]
    if n and n % REFLECT_EVERY == 0:
        reflect_and_save(sessions.load(sid))


@app.post("/api/chat")
def api_chat():
    global _stream_q
    data = request.get_json(silent=True) or {}
    sid, message = (data.get("session_id") or "").strip(), \
                   (data.get("message") or "").strip()
    if not sid or not message:
        return jsonify({"error": "session_id and message are required"}), 400

    # auto-title a fresh session from its first real message
    known = {s for s, *_ in sessions.list_sessions(1000)}
    if sid not in known:
        return jsonify({"error": f"unknown session '{sid}'"}), 404
    if not sessions.load(sid):
        sessions.set_title(sid, message[:60])

    if not _stream_lock.acquire(blocking=False):
        return jsonify({"error": "another run is already streaming"}), 409

    history = sessions.load(sid)
    q: queue.Queue = queue.Queue()

    def on_text(delta: str):
        q.put(("delta", delta))

    def on_reasoning(delta: str):
        q.put(("reasoning", delta))

    def on_event(ev: dict):
        q.put(("event", ev))

    def worker():
        try:
            answer, _ = run(message, history=history, session_id=sid,
                            on_text=on_text, on_event=on_event,
                            on_reasoning=on_reasoning)
            q.put(("done", answer))
        except Exception as e:  # surface anything to the UI, never 500 mid-stream
            q.put(("error", f"{type(e).__name__}: {e}"))

    threading.Thread(target=worker, daemon=True).start()
    _stream_q = q

    def gen():
        try:
            yield _sse({"type": "start"})
            while True:
                try:
                    kind, payload = q.get(timeout=600)
                except queue.Empty:
                    yield _sse({"type": "error", "text": "stream timed out"})
                    break
                if kind == "delta":
                    yield _sse({"type": "delta", "text": payload})
                elif kind == "reasoning":
                    yield _sse({"type": "reasoning", "text": payload})
                elif kind == "event":
                    yield _sse({"type": "event", "kind": payload.get("kind"),
                                "text": payload.get("text", "")})
                elif kind == "done":
                    _maybe_reflect(sid)
                    yield _sse({"type": "done", "answer": payload})
                    break
                else:
                    yield _sse({"type": "error", "text": payload})
                    break
        finally:
            _stream_q = None
            _stream_lock.release()

    return Response(gen(), mimetype="text/event-stream",
                    headers={"Cache-Control": "no-cache",
                             "X-Accel-Buffering": "no"})


if __name__ == "__main__":
    sessions.rebuild_index()
    print("web UI on http://127.0.0.1:5000")
    app.run(host="127.0.0.1", port=5000, threaded=True)
