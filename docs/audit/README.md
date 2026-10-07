# SunStack — UI/UX, product, functionality and usability audit

Six reviewers, one application, one evidence directory. This file is the index
and the reconciliation. (A seventh agent was spawned for the adversarial pass and
cancelled; the one whose output is recorded here is `critic.md`.)

## How this audit was produced

| Role | Reviewer | Output |
|---|---|---|
| Lead (product, dashboard, workflow, colour semantics) | primary agent, driving a real browser | `findings.md`, `inventory.md`, `experience_audit.md` |
| A — Product & UX / IA | independent sub-agent | `product_ux_ia.md` |
| B — Visual & interaction system | independent sub-agent | `visual_system.md` |
| C — Functional QA (API contract) | independent sub-agent | `functional_qa.md` |
| D — UX writing / copy | independent sub-agent | `copy_audit.md` |
| E — Adversarial critic | independent sub-agent | `critic.md` |

**Method.** The live server (`sunstack ui`) was run and driven in real Chromium at
1440×900 and 320–414 px; every control was exercised and its *effect* verified
rather than its click acknowledged; `fetch` was instrumented to capture every
request; the DOM was measured (computed styles, contrast, rects, tab order,
class lists); and the two published artifacts were read directly. Evidence
screenshots are in `screenshots/`.

**No implementation code was modified.** The only additions are files under
`docs/audit/`.

## Coverage

30 of 34 inventoried interactions verified live (**88%**). Not testable in this
environment, recorded as such in `inventory.md` §5: a `POST /api/refresh` run to
completion (multi-minute upstream CAMS queue — the button was exercised and
observed fetching), permission-restricted states (none exist in the product), and
a genuinely empty deployment (the client's own empty path was forced instead).

---

## Reconciliation

### What the specialist reviewers added that the lead missed

These are findings I did not have, each independently verified before being
promoted into `findings.md`:

1. **`time_utc` is local wall clock stamped `Z`** (→ F-29). The *hourly* frame is
   correct and the *half-hour* frame is wrong, so one published artifact carries
   the same key with two meanings, and the half-hour value contradicts its own
   `interval_end_utc` by exactly the site's UTC offset. Found by the QA reviewer;
   I re-derived it from the artifact and located the line
   (`opportunity.py:787`).
2. **"Purple rows = in class" is structurally impossible inside the window**
   (→ F-30). The row-class ternary lets `inwindow` shadow `inclass`. Found by the
   IA reviewer; I reproduced it on Wednesday 2026-10-07, where the 1 PM row is
   inside both and renders amber.
3. **The hero's "best usable" window can fall inside the user's class** (→ F-31).
   `best_usable_30m` never receives the schedule predicate, so the headline
   recommendation ignores the schedule the product already knows about.
4. **Seven simultaneous "when" answers, three different intervals** (→ F-32),
   including `best_comfortable_usable_30m_*` which is computed, shipped, and
   rendered nowhere.
5. **The `Overall` cell duplicates a hidden column and costs 31% of the hourly
   table's height** (`visual_system.md` D2): the `<br>` adds 16 px × 12 rows =
   192 px inside a 621 px table.
6. **`Int 34` and `Abs 34` are the same field rendered twice in one day cell**
   (D3), and the same triple is rendered in three different orders across the
   page (D4).
7. **The authored glossary text never reaches the screen** (D8): a runtime
   override replaces it with different copy, so the authored `UV∘`/`ΔUV`/`Export
   CSV` sentences are dead code.
8. **The 30-minute `Source` column leaks a raw enum with inverted logic** (D7):
   the human label `hourly split` is only used when the field is *empty*; the
   populated case renders `interpolated_hourly`.
9. **The type scale is not a ramp** (D9/§2.1): 10 sizes, seven of them within 1 px
   of each other, the 16 px base never declared, and six sizes inside one 118 px
   day cell.

I verified items 1, 2, 3, 5 and the two copy claims below directly; the rest are
taken from the specialist with its own evidence attached.

### What the reviewers refuted (mine included)

An audit that only reports its hits is not auditable. Confirmed non-defects:

| Claim | Verdict | Who checked |
|---|---|---|
| `Source data` renders nothing | **wrong** — `<details>` content has no `innerText` while closed; `textContent` is 17 106 chars | lead, self-corrected |
| Personal MMD is a dead control | **wrong** — it renders `Your MMD: 1.31× (30-min, client-side · …)` | lead, self-corrected |
| The `<select>` surface slugs do not match the registry | **wrong** — they match; I had misread the option *text* | lead, self-corrected |
| Azimuth is a broken control | **refuted as a standalone control** — at the default Tilt 0 the plane is horizontal and azimuth is physically irrelevant; it works in combination (`tilt=60&az=0` → factor 0.2475, `az=180` → 3.4708) | QA reviewer |
| The 400 for an unknown surface is misleading about `custom` | **confirmed, but as an unreachable-advertised-option defect**, not a wrong message | QA reviewer |

### Contradictions between reviewers, resolved

1. **F-00 vs `functional_qa.md` §1.** The QA reviewer found that azimuth alone and
   surface-at-Tilt-0 change *nothing* in the payload; F-00 says four controls
   change nothing *visible*. **Both are right and they compose:** the payload does
   change (metadata, and physics once tilted), and the UI still shows the user no
   numeric change because the only affected fields live inside a collapsed
   disclosure. The resolution is F-00's fix — surface the user-dependent number —
   not a code change to the controls.
2. **F-09/F-15 vs `visual_system.md` §4.** No contradiction: the visual reviewer
   quantified what I had described qualitatively (the `Overall`/`Loc` duplication
   costs 192 px; `UV∘`/`UV` are 81 px vs 115 px columns). The visual file is the
   better evidence; `findings.md` now cites it.
3. **`product_ux_ia.md` §4 vs `experience_audit.md` §3.2.** The IA reviewer
   identified seven distinct "when" answers; my dashboard audit had counted the
   metrics without noticing that three of them are *competing answers to one
   question*. **The IA reviewer is right and more useful** — F-32 adopts its
   framing and its fix.

### The lead's own recommendations that I would now change

Challenging my own work, as required:

- **Alternative A is no longer my first choice.** `experience_audit.md` §5
  recommends the "answer first" single column. The IA reviewer's evidence (seven
  answers, three intervals) shows the primary problem is not *ordering* but
  *multiplicity*. A one-column layout does not fix multiplicity. **The first move
  should be to collapse the seven answers to one** — a content change — and only
  then reorder. Alternative A remains the right *layout*, but it is step two.
- **F-26's proposed palette is a sketch, not a spec.** The measured defect (three
  shared hex values between the quality and hazard scales) is solid; the specific
  replacement colours I proposed are unreviewed. They should be validated for
  contrast and for colour-vision deficiency before use.
- **F-27's fix has a real cost.** Loosening the drizzle hard-block means some
  users will see a "good" window during light drizzle. I stand by the soft-penalty
  recommendation because a 0.024 mm forecast should not delete a day, but the
  threshold is a product judgement, not a correctness proof, and I have labelled
  it as such.

### Consolidated severity

Counts are derived from `findings.md`: 38 IDs, F-00 … F-38, with gaps in the
sequence because findings were added as they were verified and several were
re-graded by the adversarial review. Counting IDs is not evidence of coverage.

| Severity | Items |
|---|---|
| **P0** | none — no finding is a release-blocking failure of a core workflow |
| **P1** | F-36 (unknown weather reads as perfect), F-37 (non-finite `min_temp` disables the cold floor), F-30 (class highlight unreachable inside the window), F-31 (headline window ignores the schedule), F-32 (seven competing "when" answers), F-29 (half-hour `time_utc` is not UTC), F-01 (personal schedule published), F-02 (stale data unmarked), F-03 (`[object Object]`), F-04 (hero), F-05 (MMD basis enums), F-26 (score/hazard palette collision), F-27 (drizzle policy), F-28 (composite not cross-site comparable) |
| **P2** | F-06 (narrowed), F-07, F-08, F-09, F-10, F-11, F-12, F-13, F-14, F-15, F-16 (narrowed), F-33, F-34 |
| **P3** | F-17 (raised to P2 by the reviewer), F-18 … F-25, F-35 |

Copy findings are catalogued separately in `copy_audit.md` (77 findings over 118
strings, 16 concept rows, with exact replacement text — **apply selectively**:
the adversarial review found the terminology map conflates the deprecated
composite with the ranked objective and merges two deliberately separate
pigment channels). Visual-system findings are in `visual_system.md` (17
inconsistencies, 13 hard-coded colours bypassing the token set).

### What the adversarial review changed

`critic.md` is the reason this audit is worth reading. It produced:

- **Two findings none of the six reviewers had**, both live-reproduced and both
  now independently confirmed by the lead: **F-36** (336 rows on a shipped
  location report `feasibility 100` and `comfort "perfect"` while simultaneously
  reporting that the weather is missing) and **F-37** (`min_temp=nan` silently
  disables the cold floor and the summary still reports the old threshold).
- **Eleven corrections to existing findings**, including two outright errors of
  mine (day cells *do* inherit `button:hover`; the 30-minute table has seven
  columns, not six) and one wrong technical characterisation (the UVI sub-range
  is a **source range**, not a prediction interval). All are recorded in
  `findings.md` under "Corrections applied after adversarial review".
- **A different priority order.** Its case for shipping F-36 first — an observed
  violation of the product's own stated invariant, on a shipped location, versus
  a policy preference with a real comfort trade-off — is stronger than my
  original ordering. The roadmap has been reordered to match.
- **A quantified objection to my own palette proposal**: the yellow I suggested
  for the UVI 3–5 band has 1.42:1 contrast on white, which would make the 9 px
  dots harder to see. The measured defect (shared hex values) stands; my proposed
  replacement does not, and is now marked as a sketch requiring validation.

---

## The three questions the product owner asked during the audit

### "This is a mess and doesn't update with the top things"

**Confirmed, and it is the single most consequential finding (F-00).** Measured:
changing Surface to Fresh snow and Tilt to 45° leaves the headline dose at
**1136.1** unchanged; Skin changes only a sentence; Min °F changes the headline
only when it is restrictive enough to exclude the previously-best window. The
invariance is *correct physics* — the headline is the horizontal environmental
reference — but the page never says so, and the user-dependent number exists only
inside a collapsed disclosure. The hero is also 236 characters / 44 words
carrying 11 facts, and renders the same window and the same number twice.

### "How are South Bend and Pacific Palisades almost the same?"

**On the good days, because the composite blends an absolute with a
self-referential percentile.** Over the 14 common days the two sites *do* separate
(mean `Overall` 24.2 vs 41.5; mean `Abs` 23.7 vs 42.2). But on 10-06/07/10 the gap
collapses to 3 and 0 points while `Abs` differs by 13, because `Local` is measured
against each site's *own* history and South Bend scores *higher* (95 vs 86 on
10-10) for having weaker weather. The percentile cancels the absolute inside a
geometric mean. **Plus a separate, worse defect:** Palisades reads exactly **0** on
2026-10-12 with `Abs 37.5` and UVI 4.65, because `weather_code=53` (moderate
drizzle), `rain=0.0 mm`, `precipitation=0.024 mm` hard-blocks all 24 daylight
half-hours, and the composite is `components × 0`. South Bend, with `Abs 23`,
reads **29** that day. A trace of drizzle inverted the ranking. (F-28, F-27)

### "The colours don't make sense"

**Confirmed and measured.** `--mid` (score 40–64, "mediocre quality") and
`uvColor()` for UVI 3–5 ("moderate burn risk") are the **same hex value**,
`#8a6200`, rendered four columns apart in the same table. `--ok` is likewise
shared with UVI 0–2, and `--low` with UVI 6–7. There is **no yellow anywhere**, so
the conventional 3–5 "moderate" UV band renders as brown. Not a contrast failure —
every pairing passes AA (4.79–15.36) — a *meaning* failure, which is why automated
checks never flagged it. (F-26)

---

## Read in this order

1. `findings.md` — 34 prioritized findings with evidence, root cause, exact fix and
   acceptance criteria.
2. `inventory.md` — what exists, and the coverage matrix.
3. `experience_audit.md` — executive assessment, page and dashboard audit,
   workflows, three structural alternatives, remediation roadmap.
4. `product_ux_ia.md`, `visual_system.md`, `functional_qa.md`, `copy_audit.md` —
   the specialists' full evidence.
5. `critic.md` — the adversary's attack on all of the above.
6. `screenshots/` — rendered evidence at desktop and mobile.
