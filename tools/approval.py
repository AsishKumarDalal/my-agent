# Phase 2: the approval gate.
# Model proposes, human decides. Danger detection is a cheap blocklist;
# the callback is a SEAM — swap the CLI impl for Telegram in Phase 4
# without touching any tool or the registry.
import os

# Blocklist catches obvious disasters cheaply. It is NOT a security boundary —
# it's a tripwire backed by the approval gate. Allowlist thinking belongs on
# irreversible actions only.
DANGEROUS_PATTERNS = [
    "rm -rf", "rm -r ", "rmdir /s", "del /s", "del /f", "rd /s",
    "format ", "mkfs", "shutdown", "reboot",
    "> /dev/sda", "dd if=",
    "curl ", "wget ", "Invoke-WebRequest", "iwr ",
    "| sh", "| bash", "| powershell", "| iex",
    "chmod 777", "sudo ",
]


def is_dangerous(command: str) -> bool:
    cmd = command.lower()
    return any(pat.lower() in cmd for pat in DANGEROUS_PATTERNS)


# THE SEAM: a function (command, tool_name) -> bool (True = allowed).
# Default: ask in the terminal. Headless runs (no TTY) fail CLOSED — deny.
APPROVAL_CALLBACK = None  # set from main.py; None = use default


def _default_callback(command: str, tool_name: str) -> bool:
    if not os.isatty(0):  # fail-safe default: no human available -> deny
        print(f"[approval] no TTY; DENIED by default: {command}")
        return False
    print(f"\n⚠ APPROVAL NEEDED ({tool_name}):")
    print(f"   {command}")
    answer = input("   Allow? [y/N] ").strip().lower()
    return answer == "y"


def request_approval(command: str, tool_name: str) -> bool:
    cb = APPROVAL_CALLBACK or _default_callback
    try:
        return bool(cb(command, tool_name))
    except Exception as e:
        print(f"[approval] callback failed ({e}); denying by default")
        return False
