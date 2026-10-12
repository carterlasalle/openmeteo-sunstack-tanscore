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
uv run ast-grep test            # do the rules still match what they claim?
```

## Validate a rule before trusting it

A rule that never fires is worse than no rule: it reports "clean" forever. Every
rule has a native test in `rule-tests/` covering what it must match **and what it
must not**, and `ast-grep test` runs them:

```bash
uv run ast-grep test
# test result: ok. 4 passed; 0 failed;
```

Each test's `valid:` cases are the rule's precision: `.shift(axis=1)` is a column
shift, `%z` in a format string means the parse produced an aware value, and
`out["interval_start_utc"] = end - Timedelta(...)` is the documented support
declaration rather than a slot lookup. Getting those wrong is how a scan turns
into noise nobody reads.

The first version of `interval-bound-from-offset` matched nothing anywhere: it
looked for the `Timedelta` in the same call as the column read while the two live
on different lines. The test cases are what caught it — an earlier attempt to
validate the rule against `git show <old revision>` failed in CI with exit 128,
because a shallow checkout has no history to show.
