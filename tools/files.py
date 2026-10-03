# File tool implementations here: read_file, write_file.
# Handlers receive a dict of args, return a STRING result (the observation).
# Wrap filesystem errors as "ERROR: ..." strings — never raise.
import os
import subprocess
 
 
def read_file(args: dict) -> str:
    path = args.get("path", "")
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            content = f.read()
        return content if content else "(empty file)"
    except FileNotFoundError:
        return f"ERROR: file not found: {path}"
    except PermissionError:
        return f"ERROR: permission denied: {path}"
    except IsADirectoryError:
        return f"ERROR: is a directory, not a file: {path}"
    except OSError as e:
        return f"ERROR: {e}"
 
 
def write_file(args: dict) -> str:
    path = args.get("path", "")
    content = args.get("content", "")
    try:
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            f.write(content)
        return f"OK: wrote {len(content)} chars to {path}"
    except OSError as e:
        return f"ERROR: {e}"
 
 
def run_command(args: dict) -> str:
    cmd = args.get("command", "")
    try:
        r = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=30)
        out = (r.stdout or "") + (("\n[stderr]\n" + r.stderr) if r.stderr else "")
        return f"exit_code={r.returncode}\n{out or '(no output)'}"
    except subprocess.TimeoutExpired:
        return "ERROR: command timed out after 30s"
    except Exception as e:
        return f"ERROR: {type(e).__name__}: {e}"
