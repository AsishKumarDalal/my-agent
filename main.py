# CLI REPL entry point (updated for Phase 3 sessions, Phase 7 memory).
# /new starts a persisted session, /sessions lists them, /resume <id> reloads,
# /title names the current session, /memory shows MEMORY.md, /reflect forces
# memory extraction, /exit quits (and reflects). History is session-backed:
# storage (SQLite) is truth; `history` here is just the live view.
from agent.loop import run
from agent.memory import load_memory, reflect_and_save
from agent import sessions

REFLECT_EVERY = 5   # messages between automatic reflections


def main():
    history = []
    session_id = None
    titled = False
    exchanges = 0
    sessions.rebuild_index()   # index anything written pre-Phase 7
    print("Agent ready. /new /sessions /resume <id> /title <name> /memory "
          "/reflect /exit.")
    while True:
        try:
            user_input = input("\nyou > ").strip()
        except (EOFError, KeyboardInterrupt):
            reflect_and_save(history)
            break
        if not user_input:
            continue
        if user_input == "/exit":
            reflect_and_save(history)   # forgetting into a summary = the moment
            break                       # of remembering into memory

        if user_input == "/new":
            session_id = sessions.new_session()
            titled = False
            history = []
            print(f"(new session: {session_id})")
            continue

        if user_input == "/sessions":
            for sid, title, parent, count, created in sessions.list_sessions():
                lineage = f" (child of {parent})" if parent else ""
                print(f"{sid} | {title or '(untitled)'} | {count} msgs | "
                      f"{created}{lineage}")
            continue

        if user_input.startswith("/resume"):
            sid = user_input.split(maxsplit=1)[1].strip() \
                if len(user_input.split(maxsplit=1)) > 1 else ""
            loaded = sessions.load(sid)
            if not loaded:
                print(f"(no messages found for '{sid or '<id?>'}')")
                continue
            session_id, history, titled = sid, loaded, True
            print(f"(resumed {sid}: {len(history)} messages)")
            continue

        if user_input == "/memory":
            mem = load_memory()
            print(f"--- MEMORY.md {'(empty)' if not mem else ''}---")
            print(mem or "(nothing remembered yet)")
            continue

        if user_input == "/reflect":
            if not history:
                print("(nothing to reflect on yet)")
                continue
            new = reflect_and_save(history)
            print(f"(memory updated: {len(new)} chars)")
            continue

        if user_input.startswith("/title"):
            if not session_id:
                print("(no active session — /new first)")
                continue
            name = user_input.split(maxsplit=1)[1].strip() \
                if len(user_input.split(maxsplit=1)) > 1 else ""
            sessions.set_title(session_id, name)
            print(f"(session titled: {name})")
            continue

        # auto-title a fresh session from its first real message
        if session_id and not titled:
            sessions.set_title(session_id, user_input[:40])
            titled = True

        answer, history = run(user_input, history=history,
                              session_id=session_id)
        print(f"\nagent > {answer}")

        # periodic reflection on long conversations (session-end /exit and
        # /reflect are the other two triggers)
        exchanges += 1
        if exchanges % REFLECT_EVERY == 0 and history:
            new = reflect_and_save(history)
            if new:
                print(f"(memory updated after {exchanges} exchanges)")


if __name__ == "__main__":
    main()
