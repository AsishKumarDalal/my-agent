# LLM provider wrapper.
# chat(messages, tools, on_text=None) -> assistant message dict.
#
# Streaming (added Phase 8): while the response arrives token by token,
#   - text deltas are handed to `on_text` as they arrive (rendering is the
#     CALLER's job — this module knows nothing about terminals), and
#   - tool-call deltas are ACCUMULATED BY INDEX: the provider sends the id and
#     name on the first chunk for a call and the JSON `arguments` as fragments
#     split across later chunks, so nothing is usable until concatenated.
#
# The return shape is byte-identical to the old non-streaming chat(), so
# loop.py / resilience.py / context.py / memory.py need no other changes.
import os
from openai import OpenAI
from dotenv import load_dotenv

load_dotenv()

# Lazy client: a missing/invalid API_KEY must not crash at import time (the
# web server imports this module on boot). It raises on first actual call,
# where resilience/UI error handling can surface it cleanly.
_client = None


def _get_client() -> OpenAI:
    global _client
    if _client is None:
        _client = OpenAI(
            base_url=os.getenv("BASE_URL", "https://api.openai.com/v1"),
            api_key=os.getenv("API_KEY"),
        )
    return _client

# Set False the first time a provider rejects streaming, so we stop trying
# for the rest of the process (a capability fact, not a per-call error).
_stream_supported = True


def _assemble(messages: list, tools: list, on_text, on_reasoning) -> dict:
    """Streaming path: render text live, accumulate tool calls by index.
    Reasoning deltas (provider-dependent field) go to on_reasoning and are
    deliberately NOT stored — they are scratch work, not protocol."""
    stream = _get_client().chat.completions.create(
        model=os.getenv("MODEL", "openai/gpt-4o-mini"),
        messages=messages,
        tools=tools,
        stream=True,
    )

    text_parts = []
    tool_acc: dict[int, dict] = {}   # index -> {id, name, arguments}

    for chunk in stream:
        if not chunk.choices:        # some providers append a usage-only chunk
            continue
        delta = chunk.choices[0].delta
        if delta is None:            # some providers send a null final delta
            continue

        # reasoning models expose their thinking either as `reasoning_content`
        # (DeepSeek-style) or `reasoning` (OpenRouter-style)
        reasoning = getattr(delta, "reasoning_content", None) \
            or getattr(delta, "reasoning", None)
        if reasoning and isinstance(reasoning, str) and on_reasoning:
            on_reasoning(reasoning)

        if delta.content:
            text_parts.append(delta.content)
            if on_text:
                on_text(delta.content)

        for pos, tc in enumerate(delta.tool_calls or []):
            idx = getattr(tc, "index", None)
            if idx is None:          # defensive: fall back to list position
                idx = pos
            slot = tool_acc.setdefault(idx, {"id": None, "name": None,
                                             "arguments": ""})
            if getattr(tc, "id", None):
                slot["id"] = tc.id
            fn = getattr(tc, "function", None)
            if fn is not None:
                if getattr(fn, "name", None):
                    slot["name"] = fn.name
                if getattr(fn, "arguments", None):
                    slot["arguments"] += fn.arguments   # fragments concatenate

    msg = {"role": "assistant", "content": "".join(text_parts) or ""}
    if tool_acc:
        msg["tool_calls"] = [
            {
                # synthetic id when a provider omits it: the loop pairs tool
                # results by tool_call_id, so the protocol needs one either way
                "id": slot["id"] or f"call_{i}",
                "type": "function",
                "function": {
                    "name": slot["name"] or "",
                    "arguments": slot["arguments"] or "{}",
                },
            }
            for i, slot in sorted(tool_acc.items())   # original call order
        ]
    return msg


def _blocking(messages: list, tools: list, on_text, on_reasoning) -> dict:
    """Original non-streaming path — the fallback when streaming is off or the
    provider rejects it. If the caller asked for rendering, hand over the whole
    text at once rather than not showing it at all."""
    resp = _get_client().chat.completions.create(
        model=os.getenv("MODEL", "openai/gpt-4o-mini"),
        messages=messages,
        tools=tools,
    )
    msg = resp.choices[0].message

    reasoning = getattr(msg, "reasoning_content", None) \
        or getattr(msg, "reasoning", None)
    if reasoning and isinstance(reasoning, str) and on_reasoning:
        on_reasoning(reasoning)

    assistant_msg = {"role": "assistant", "content": msg.content or ""}
    if msg.tool_calls:
        assistant_msg["tool_calls"] = [
            {
                "id": tc.id,
                "type": "function",
                "function": {"name": tc.function.name, "arguments": tc.function.arguments},
            }
            for tc in msg.tool_calls
        ]
    if on_text and assistant_msg["content"]:
        on_text(assistant_msg["content"])
    return assistant_msg


def _looks_like_no_stream(e: Exception) -> bool:
    """True only for a CAPABILITY failure — the provider refused streaming
    itself. Deliberately narrow: a context-overflow 400 must NOT match, or we
    would wrongly disable streaming and swallow an error that resilience needs
    to see for emergency compression."""
    if isinstance(e, TypeError):
        return True
    status = getattr(e, "status_code", None)
    return status == 400 and "stream" in str(e).lower()


def chat(messages: list, tools: list, on_text=None, on_reasoning=None) -> dict:
    """One model call. `on_text` receives text deltas; `on_reasoning` receives
    the model's reasoning deltas (when the provider emits them)."""
    global _stream_supported

    emitted = {"any": False}

    def _spy(token: str):
        # track what the user has already seen: once text is on screen it
        # cannot be un-emitted, so a later failure must not silently fall back
        if on_text:
            emitted["any"] = True
            on_text(token)

    if _stream_supported and os.getenv("AGENT_STREAM", "1") == "1":
        try:
            return _assemble(messages, tools, _spy, on_reasoning)
        except Exception as e:
            if not emitted["any"] and _looks_like_no_stream(e):
                _stream_supported = False
                print("\n[stream] provider rejected streaming — "
                      "falling back to blocking calls")
            else:
                raise

    return _blocking(messages, tools, on_text, on_reasoning)
