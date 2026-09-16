---
name: Bug report
description: Something scores, renders, or runs wrong
labels: [bug]
---

## What is wrong

## Expected

## Evidence

Run stamp (`data/latest/summary.json` → `run`), affected timestamps, and the
numbers you saw versus the numbers you expected. Paste the relevant
`data/logs/sunstack.log` excerpt.

## Reproduction

Commands run, starting from `main`. For scoring bugs, include the failing
case as a candidate test in `tests/test_core.py` if you can.

## Environment

- Commit:
- `uv run sunstack doctor --probe` output (redact credentials):

> Do not paste API keys, tokens, `~/.cdsapirc` contents, or full provider
> payloads containing credentials.
