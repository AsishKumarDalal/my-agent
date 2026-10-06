# Phase 6: reliability & recovery. The harness layer the model never sees.
# Why this exists: tool errors become observations the model can react to,
# but API errors cannot — if chat() fails there IS no assistant message,
# so the model can't self-correct. The harness classifies failures and
# responds: transient -> backoff+jitter retry; self-inflicted overflow ->
# emergency compress + one retry; persistent -> honest abort. Retries wrap
# ONLY the network call, so nothing is ever double-appended (sessions stay
# truthful). Circuit breaker: repeated hard failures abort the run early.
import os
import time
import random

from agent.llm import chat

MAX_ATTEMPTS = int(os.getenv("AGENT_MAX_ATTEMPTS", "4"))
BREAKER_LIMIT = int(os.getenv("AGENT_BREAKER_LIMIT", "3"))  # consecutive aborts

RETRYABLE_STATUS = {408, 409, 429, 500, 502, 503, 504, 529}

# words that mark the SELF-INFLICTED failure class (our payload is too big)
_OVERFLOW_MARKERS = ("context length", "maximum context", "context_length",
                     "too many tokens", "reduce the length")

_consecutive_failures = 0   # circuit breaker state (process-wide is fine)


class RunAborted(RuntimeError):
    """Raised when the run must stop honestly (fatal error / breaker)."""


def _is_overflow(e: Exception) -> bool:
    text = str(e).lower()
    return any(marker in text for marker in _OVERFLOW_MARKERS)


def _retry_after(e: Exception) -> float | None:
    """Respect the server's Retry-After header when present (429s)."""
    resp = getattr(e, "response", None)
    if resp is not None:
        try:
            return float(resp.headers.get("retry-after"))
        except (TypeError, ValueError):
            pass
    return None


def _sleep_backoff(attempt: int, e: Exception | None = None):
    """Full jitter (AWS): wait = uniform(0, min(cap, base * 2^attempt)).
    Server-provided Retry-After overrides the dice."""
    if e is not None and _retry_after(e) is not None:
        time.sleep(min(_retry_after(e), 60))
        return
    base, cap = 1.0, 30.0
    time.sleep(random.uniform(0, min(cap, base * (2 ** attempt))))


def emergency_compress(messages: list) -> list:
    """The overflow path: preflight (maybe_compress) didn't prevent the
    rejection, so compress HARD — drop big tool outputs, force-summarize
    everything except system + last few turns. Used at most once."""
    from agent import context as ctx

    slim = []
    for m in messages:
        if m.get("role") == "tool" and len(m.get("content") or "") > 1000:
            slim.append({**m, "content":
                         "[tool output dropped to recover from context overflow]"})
        else:
            slim.append(m)

    cut = max(1, len(slim) - 4)          # keep only ~4 recent messages verbatim
    old, recent = slim[1:cut], slim[cut:]
    if not old:
        return slim
    return [slim[0], ctx._summarize(old)] + recent


def chat_with_retries(messages: list, tools: list, on_text=None,
                      on_reasoning=None) -> dict:
    """Drop-in replacement for chat() — the loop's only visible change.
    Raises RunAborted when the failure is fatal or the breaker trips.

    Streaming note: a retry re-renders from scratch. Text already on screen
    cannot be un-emitted, so on retry we say so instead of pretending the
    partial output was real. Storage is unaffected — the session only ever
    records the FINAL assembled message, after success."""
    global _consecutive_failures

    if _consecutive_failures >= BREAKER_LIMIT:
        raise RunAborted(
            f"API failed {_consecutive_failures} times in a row — circuit "
            f"breaker open. Session preserved; /resume when the provider "
            f"recovers.")

    emitted = {"any": False}

    def _spy(token: str):
        if on_text:
            emitted["any"] = True
            on_text(token)

    def _spy_reasoning(token: str):
        # reasoning on screen also cannot be un-emitted across a retry
        if on_reasoning:
            emitted["any"] = True
            on_reasoning(token)

    compressed = False                     # emergency compress: at most once
    attempt = 0
    last_err = None                        # `except ... as e` deletes e on
    while attempt < MAX_ATTEMPTS:          # block exit — keep our own ref
        try:
            msg = chat(messages, tools, _spy, _spy_reasoning)
            _consecutive_failures = 0      # success resets the breaker
            return msg
        except Exception as e:
            last_err = e
            status = getattr(e, "status_code", None)

            # 1) SELF-INFLICTED: our payload is too big. Fix it, retry ONCE.
            if status == 400 and _is_overflow(e) and not compressed:
                messages = emergency_compress(messages)
                compressed = True
                continue                   # the retry is free (no backoff)

            # 2) TRANSIENT: backoff with jitter and try again.
            if status in RETRYABLE_STATUS or isinstance(
                    e, (ConnectionError, TimeoutError)) or status is None:
                attempt += 1
                if attempt >= MAX_ATTEMPTS:
                    break
                if emitted["any"]:
                    print("\n[stream interrupted — the partial output above "
                          "(text and thinking) was discarded; retrying from "
                          "scratch]")
                    emitted["any"] = False   # next attempt renders fresh
                _sleep_backoff(attempt, e)
                continue

            # 3) PERSISTENT: bad key, bad model, malformed request.
            #    Retrying is denial — abort honestly, immediately.
            raise RunAborted(
                f"fatal API error ({type(e).__name__}"
                + (f", status {status}" if status else "")
                + f"): {e}") from e

    _consecutive_failures += 1
    raise RunAborted(
        f"API unavailable after {MAX_ATTEMPTS} attempts "
        f"({_consecutive_failures}/{BREAKER_LIMIT} toward circuit breaker): "
        f"{last_err}")
