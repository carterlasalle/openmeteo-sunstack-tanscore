# ast-grep rules for this repo

Four rules, each derived from a defect that shipped. They are **searches**, not
gates: every one of them has legitimate hits, so a match is a candidate for a
human rather than a failure.

| Rule | Defect it comes from |
|---|---|
| `strptime-without-zone` | Naive parse, timezone patched on later (the DTZ007 shape) |
| `naive-tzinfo-replace` | The patch itself: `.replace(tzinfo=...)` asserting a zone the value never carried |
| `interval-bound-from-offset` | `_best_end = _best_dt + Timedelta(minutes=30)` followed by a trailing-column read — published the next slot's dose (1000.854 instead of 1104.66) |
| `neighbouring-row-index` | The same off-by-one as a primitive: `iloc[i+1]`, `shift(1)` |

## Run

```bash
uv run ast-grep scan            # the whole tree
uv run ast-grep scan path.py    # one file
```

## Validate a rule before trusting it

A rule that never fires is worse than no rule: it reports "clean" forever. Every
rule here was checked against the revision that *had* the defect, and the check
is repeatable:

```bash
# the off-by-one rule, against the code before the fix
git show d581a28^:src/sunstack/opportunity.py > /tmp/old_opportunity.py
uv run ast-grep scan --json /tmp/old_opportunity.py | python3 -m json.tool | grep ruleId
```

That run reports `L1370 interval-bound-from-offset  _best_end = _best_dt +
pd.Timedelta(minutes=30)` — the line the bug lived on. The first version of that
rule matched nothing anywhere, because it looked for the `Timedelta` in the same
call as the column read while the two live on different lines; the control run is
what caught it.
