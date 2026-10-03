# my-agent — Phase 1: The Loop & Reasoning (ReAct)

Minimal ReAct agent built from scratch, modeled on NousResearch/hermes-agent architecture.

Papers behind this phase:
- ReAct — arxiv.org/abs/2210.03629 (reason → act → observe interleave)
- Toolformer — arxiv.org/abs/2302.04761 (tools learned from schema quality)

## Setup

```bash
source .venv/Scripts/activate   # Windows Git Bash (Linux/macOS: source .venv/bin/activate)
cp .env.example .env            # then fill in BASE_URL, API_KEY, MODEL
```

## Structure

```
agent/loop.py      # the ReAct loop (the heart)
agent/llm.py       # provider wrapper: chat(messages, tools)
agent/prompt.py    # system prompt
tools/registry.py  # schemas + handlers, incl. `finish`
tools/files.py     # read_file / write_file
main.py            # CLI REPL
```

## Acceptance tests (definition of done)

1. "What is 17×23? Show your work." → must call a tool, not answer from memory
2. "Read notes.txt, write a summary to summary.txt" → multi-step read → write → finish
3. "Read /nonexistent/file.txt" → reads error observation, reports failure honestly
4. Impossible task → budget respected, explains what blocked it

## Rules the loop must enforce

- Always append the assistant message BEFORE tool results (role alternation)
- Tool errors are observations ("ERROR: ..."), never exceptions
- Truncate tool outputs (~2000 chars)
- Hard max_turns budget (start with 25)
