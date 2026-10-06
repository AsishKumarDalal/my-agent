# Phase 2: the path sandbox.
# Every path-touching tool call passes through validate_path() BEFORE the handler runs.
# Model-proposed paths are untrusted input: resolve them absolutely, then check
# they stay inside the workspace. Fail-safe default = deny.
import os
from pathlib import Path

WORKSPACE = Path(os.getenv("AGENT_WORKSPACE", ".")).resolve()

# Never readable/writable even by accident. Checked on the FINAL resolved path.
FORBIDDEN_NAMES = {".env", ".git", ".venv", "node_modules", ".ssh", "id_rsa"}


def validate_path(path_str: str) -> str:
    """Returns 'OK' if safe, otherwise an ERROR string (a denial observation)."""
    if not path_str:
        return "ERROR: empty path"

    p = Path(path_str)

    # 1) Make it absolute relative to the workspace, then resolve().
    #    resolve() collapses ../ sequences and symlinks BEFORE we judge it —
    #    this is what defeats "notes/../../.env" traversal tricks.
    if not p.is_absolute():
        p = WORKSPACE / p
    try:
        p = p.resolve()
    except OSError as e:
        return f"ERROR: cannot resolve path: {e}"

    # 2) Allowlist rule: everything the agent touches lives in the workspace.
    if not str(p).startswith(str(WORKSPACE)):
        return ("ERROR: path resolves outside the workspace "
                f"({p}). The agent may only access files inside {WORKSPACE}. "
                "Do not retry silently — ask the user.")

    # 3) Forbidden names, checked on EVERY component (so notes/../.env still hits).
    for part in p.parts:
        if part in FORBIDDEN_NAMES:
            return (f"ERROR: access to '{part}' is forbidden by policy. "
                    "Do not retry — ask the user.")

    return "OK"


def is_safe(path_str: str) -> bool:
    return validate_path(path_str) == "OK"
