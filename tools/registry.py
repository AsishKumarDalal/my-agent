# Tool registry here.
# Each tool = JSON schema (name, description, params) + python handler.
# Registry = dict: name -> {"schema": ..., "handler": ...}.
# Include a `finish` tool: agent must declare done WITH evidence.
from tools.files import read_file, write_file, run_command
from tools.todo import handle_todo
from tools.memory_search import handle_session_search
from tools.sandbox import validate_path
from tools.approval import is_dangerous, request_approval
from agent.subagents import spawn_child, depth

SCHEMAS = [
    {
        "type": "function",
        "function": {
            "name": "read_file",
            "description": "Read the full contents of a text file. Use it to inspect existing files before modifying them, and to verify a write succeeded.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Relative or absolute file path"}
                },
                "required": ["path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "write_file",
            "description": "Create or overwrite a text file with the given content. Overwrites without asking. Verify important writes afterwards with read_file.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Destination file path"},
                    "content": {"type": "string", "description": "Full file contents to write"},
                },
                "required": ["path", "content"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "run_command",
            "description": "Run a shell command and return stdout, stderr, and exit code. Use for calculations, listing files, checking system state. Commands time out after 30 seconds.",
            "parameters": {
                "type": "object",
                "properties": {
                    "command": {"type": "string", "description": "The shell command to execute"}
                },
                "required": ["command"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "todo",
            "description": "Write or update your plan list. The plan lives in a file, so rewrite the FULL list each time and mark progress with [x] — it survives context compression. Re-read it (read_file) every few turns to stay on plan.",
            "parameters": {
                "type": "object",
                "properties": {
                    "items": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Full plan lines, e.g. ['[x] read config', '[ ] write tests']"
                    }
                },
                "required": ["items"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "delegate_task",
            "description": "Spawn a sub-agent for an INDEPENDENT subtask (research a topic, explore files, draft a section). The brief MUST be self-contained: goal, constraints, relevant paths, and what done means — the sub-agent sees nothing else. Returns only its concise report. Use for parallelizable or context-heavy exploration.",
            "parameters": {
                "type": "object",
                "properties": {
                    "task": {"type": "string", "description": "Self-contained mission brief"}
                },
                "required": ["task"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "session_search",
            "description": "Search ALL your past conversations (full-text, BM25-ranked). Use when you need something remembered from a previous session: a fix you applied, a decision made, a command that worked, a user preference mentioned. Returns short snippets with session ids.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Keywords to search for, e.g. 'auth token fix'"},
                    "limit": {"type": "integer", "description": "Max results (default 5, max 10)"}
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "finish",
            "description": "Declare the task complete. MUST be called when done, with concrete evidence — never claim success without verification. Also call it when the task is impossible, explaining what blocked you.",
            "parameters": {
                "type": "object",
                "properties": {
                    "summary": {"type": "string", "description": "What you did"},
                    "evidence": {"type": "string", "description": "How you know it worked (tool outputs you observed)"},
                },
                "required": ["summary", "evidence"],
            },
        },
    },
]

# Tools whose args may contain a filesystem path -> sandboxed.
PATH_KEYS = {"read_file": ("path",), "write_file": ("path",)}

REGISTRY = {
    "read_file": read_file,
    "write_file": write_file,
    "run_command": run_command,
    "todo": handle_todo,
    "session_search": handle_session_search,
}

def dispatch(name: str, args: dict) -> str:
    # 0) Agent-level tools intercepted BEFORE the registry (Hermes pattern).
    #    delegate_task needs the depth guard, so it's handled here —
    #    complete mediation: no code path can spawn a child except through
    #    this chokepoint.
    if name == "delegate_task":
        if depth() > 0:
            return ("DENIED: sub-agents cannot delegate. Do the work yourself "
                    "and report findings to the parent agent.")
        task = str(args.get("task", "")).strip()
        if not task:
            return ("ERROR: 'task' is required and must be a self-contained "
                    "brief (goal, constraints, paths, what done means).")
        return spawn_child(task)

    # 1) Complete mediation starts with the cheapest check: existence.
    if name not in REGISTRY:
        return (f"ERROR: unknown tool '{name}'. "
                f"Available: {sorted(REGISTRY)} — do not invent tool names.")

    # 2) Dangerous shell commands need a human. Denial states the rule
    #    so the model generalizes instead of retry-storming.
    if name == "run_command":
        cmd = str(args.get("command", ""))
        if is_dangerous(cmd) and not request_approval(cmd, name):
            return ("DENIED: command requires human approval and was refused. "
                    "Do not retry silently — ask the user or propose a safer alternative.")

    # 3) Path tools: the model's path string is untrusted. Validate BEFORE
    #    the handler sees it. Handlers no longer trust their inputs.
    for key in PATH_KEYS.get(name, ()):
        verdict = validate_path(str(args.get(key, "")))
        if verdict != "OK":
            return verdict   # the ERROR/teaching string, straight to the model

    # 4) All checks passed — execute.
    try:
        return str(REGISTRY[name](args))
    except Exception as e:
        return f"ERROR: {type(e).__name__}: {e}"

 
def schemas() -> list:
    return SCHEMAS
 
 
