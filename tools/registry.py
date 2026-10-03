# Tool registry here.
# Each tool = JSON schema (name, description, params) + python handler.
# Registry = dict: name -> {"schema": ..., "handler": ...}.
# Include a `finish` tool: agent must declare done WITH evidence.
from tools.files import read_file, write_file, run_command
 
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
 
REGISTRY = {
    "read_file": read_file,
    "write_file": write_file,
    "run_command": run_command,
    # `finish` has NO handler — the loop intercepts it (like Hermes's agent-level tools)
}
 
 
def schemas() -> list:
    return SCHEMAS
 
 
def dispatch(name: str, args: dict) -> str:
    if name not in REGISTRY:
        return f"ERROR: unknown tool '{name}'. Available: {sorted(REGISTRY)}"
    try:
        return str(REGISTRY[name](args))
    except Exception as e:
        return f"ERROR: {type(e).__name__}: {e}"