# CLI REPL entry point.
# while True: input() -> agent.run(msg) -> print. /new resets history, /exit quits.
from agent.loop import run
 
 
def main():
    history = []
    print("Agent ready. /new = reset context, /exit = quit.")
    while True:
        try:
            user_input = input("\nyou > ").strip()
        except (EOFError, KeyboardInterrupt):
            break
        if not user_input:
            continue
        if user_input == "/exit":
            break
        if user_input == "/new":
            history = []
            print("(context cleared)")
            continue
        answer, history = run(user_input, history)
        print(f"\nagent > {answer}")
 
 
if __name__ == "__main__":
    main()
