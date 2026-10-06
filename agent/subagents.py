# Phase 5: sub-agents. A child = one fresh run() call with a self-contained
# brief, a smaller budget, and NO parent context (context isolation is the
# product). Depth guard via threading.local — parallel-safe by construction.
# Children inherit all Phase 2 security for free: their calls go through the
# same dispatch() chokepoint (sandbox, blocklist, approval).
import threading

_tls = threading.local()

CHILD_MAX_TURNS = 15
BRIEF_SUFFIX = (
    "You are a sub-agent spawned by a parent agent. You receive no other "
    "context — the task below is self-contained. Work autonomously and "
    "FINISH with a concise report: findings, files touched, next steps. "
    "Do not ask questions; decide and act."
)


def depth() -> int:
    return getattr(_tls, "depth", 0)


class DepthGuard:
    """Context manager: increments THIS thread's depth; a child runs at >=1.
    Thread-local because with parallel tools a global counter is racy."""

    def __enter__(self):
        _tls.depth = depth() + 1
        return self

    def __exit__(self, *exc):
        _tls.depth = depth() - 1


def spawn_child(task: str) -> str:
    """Runs a child agent. Returns ONLY its final report string — never a
    transcript (summaries, not transcripts: the parent pays ~200 tokens for
    the child's ~20k of exploration). Children are ephemeral: no session."""
    from agent.loop import run
    with DepthGuard():
        answer, _history = run(
            f"{BRIEF_SUFFIX}\n\nTASK:\n{task}",
            history=None,
            session_id=None,
            max_turns=CHILD_MAX_TURNS,
            allow_delegate=False,   # depth limit by construction
        )
    return answer
