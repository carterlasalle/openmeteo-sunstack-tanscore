# SunStack — experience, dashboard and workflow audit

Companion to `inventory.md` (what exists + coverage), `findings.md` (prioritized
defects) and the specialist files written by the independent reviewers
(`copy_audit.md`, `product_ux_ia.md`, `functional_qa.md`, `visual_system.md`).

---

## 1. Executive assessment

### What this product is, judged as a product

A single-location solar/UV decision aid. Its real job is narrow and valuable:
**tell me the best window to be outside today, and tell me honestly how much to
trust it.** Everything else — two sites, a calendar, CSV export, a photobiology
disclosure — is secondary to that one answer.

### Strengths (these are unusual and worth protecting)

1. **Intellectual honesty is visible in the product.** `spectral tier C`,
   `tierC-broadband-proxy-v2`, "not a recommendation", "SED is exposure, never
   good", the train/serve MAE gap, `validation_issues`, and a per-source UVI
   cross-check with `—` for genuinely missing values. Most consumer forecast
   products show none of this.
2. **The ranking objective is physically correct and documented** in the UI's
   own legend: maximum expected fixed-duration delayed-pigmentation dose, with
   the deprecated composite explicitly named as deprecated.
3. **Progressive disclosure exists and works** — four `<details>`, a 12↔20
   column toggle with correct `aria-pressed`, and a class-row toggle.
4. **Baseline accessibility is genuinely good**: contrast 5.36–17.61, 2 px focus
   rings, `lang`, ordered headings, no images missing `alt`, no motion to
   reduce, and disclosure targets at 28 px.
5. **Failure discipline is real.** During this audit an upstream
   Open-Meteo timeout caused the strict gate to *refuse to publish* rather than
   emit a plausible number.

### Major weaknesses

1. **The answer is buried in prose.** The hero is 236 characters / 44 words
   carrying 11 distinct facts (F-04), and the two rankings it names render the
   same window and the same number, so the reader learns nothing from half of it.
2. **The controls barely connect to the answer** (F-00). Five of seven staged
   controls cannot change any number on screen; nothing says so.
3. **The headline number cannot be compared across sites and is used as if it
   can** (F-28) — and it can be annihilated to exactly `0` by a drizzle code
   (F-27), which inverts the ranking between the two locations.
4. **The page never admits when it is showing stale data** (F-02), in a product
   where acting on stale data is the whole risk.
5. **Colour carries no stable meaning** (F-26): the UV hazard scale and the
   quality score are literally the same hex values.
6. **82% of the computed model is unreachable** (below). The product knows 298
   fields per hour and shows about 31.

### Recommended product direction

Stop treating this as a dashboard and treat it as an **answer with evidence
attached**. Concretely: one headline sentence that is a *time and a dose*; one
invariant statement explaining what the controls do and do not change; the
user-dependent number shown next to the control that changes it; the evidence
(per-source UV, feasibility, confidence) one deliberate step away; and every
number carrying its own scope (this location / all locations) so it cannot be
misread.

The material to do this already exists in the payload. Almost nothing here needs
new science — it needs the existing numbers to be *placed* correctly.

---

## 2. Page audit — the single page

Purpose: answer "when should I go outside today, and how much should I trust
it?" and let a user act (apply their own context, subscribe, export).

Measured at 1440×900: **3 501 px ≈ 3.9 screens**.

| # | Section (rendered order) | Purpose | Verdict |
|---|---|---|---|
| 1 | Title + run line | provenance | **Keep, shorten.** `Updated Tue, Oct 6, 9:56 PM · 163 hourly rows · forecast 83b9724 · absolute is provisional global scale, local is this location's percentile` — the last clause is a 14-word caveat welded onto a timestamp. |
| 2 | Controls row (8 controls) | user context | **Restructure.** Staged controls with no indication that Apply is required for 7 of 8, and no indication that 4 of them cannot affect the numbers. |
| 3 | Explanatory sentence | tells you ground reflection is zero when flat | **Move.** It currently explains *why a control does nothing*, placed before the control has been used, and only covers tilt/azimuth — not surface, not skin. |
| 4 | Action row (Refresh / Calendar / Export) | act | **Split.** "Refresh forecast" is a 1–15 minute operation sitting beside two instant actions with identical styling weight; it has no progress, no ETA, no cancel. |
| 5 | Hero | **the answer** | **Rewrite.** 236 chars / 44 words / 11 facts. See F-04, F-00. |
| 6 | Legend | ranking semantics | **Move into a disclosure.** Two sentences of methodology above the fold, including a deprecation notice, competing with the answer. |
| 7 | Skin context line | Fitzpatrick context | **Keep**, but it is the only visible effect of the Skin control, which is why that control reads as dead. |
| 8 | Day strip (14 cells) | pick a day | **Keep, reduce.** Each cell carries day, status, window, class spans, peak score, Int/Fit/Conf, UV range, feels range, gust, `Abs · Loc`, and a bar — 13 values in a ~118×150 px card. |
| 9 | Doses line | exposure accounting | **Keep, restructure.** One run-on line mixing TanDose and SED with `(partial)` and `(model normalization, not a recommended exposure duration)`. |
| 10 | Advanced / Photobiology | technical detail | **Keep the capability, fix the content** (F-14). |
| 11 | Charts (3 panels) | shape of the day | **Keep.** Genuinely good: separate panels, correct framing ("SED is exposure, never good"), best-window band, hover readout. |
| 12 | Sun figure | comprehension aid | **Keep.** Best element on the page — turns a number into "sun 43° up in the south; lie flat or lift your torso". |
| 13 | Column glossary | decode the table | **Keep.** |
| 14 | Day header + class toggle | selected-day summary | **Fix** (F-01: personal class data; F-10: `Overall` leads). |
| 15 | Hourly table (20 cols) | evidence | **Keep, fix cells** (F-15, F-16). |
| 16 | 30-min table (7 cols) | the ranked unit | **Fix** (F-16: missing dose and confidence). |
| 17 | Source data | provenance | **Fix** (F-13: 17 KB of summary JSON, mislabelled). |

**Length verdict:** 3.9 screens is not excessive for the amount of evidence
offered — the problem is *ordering*, not length. The three things a user needs
(answer, when, how sure) are interleaved with methodology, tooling and
provenance above the fold; the evidence they might want is further down.

---

## 3. Dashboard and data-presentation audit

### 3.1 The scale of the omission

| Frame | Fields computed | Fields rendered | Share |
|---|---|---|---|
| hourly row | **298** | ~31 distinct values across 20 columns | **~10%** |
| half-hour row | **266** | ~7 columns | **~3%** |
| daily row | **83** | ~13 in the day cell | **~16%** |
| run summary | 62 | 0 directly (17 KB raw JSON in a disclosure) | 0% |

**Correction (from the adversarial review):** this is *not* an argument that 82 %
of the model deserves to be rendered. Those counts include aliases, version
strings, provenance and completeness flags — not independent user questions — and
the complete JSON *is* reachable through the read API. The defensible claim is the
narrow one: the **dose** (the ranking objective) and **confidence** (the
trust cue) are absent from the 30-minute table, and the calibrated prediction
interval is not surfaced anywhere, while 17 KB of run metadata is. Hiding detail
is correct; hiding the two fields that answer "how much" and "how sure" is not.

### 3.2 Metric-by-metric

| Metric (as rendered) | Question it answers | Verdict |
|---|---|---|
| `Strongest 30 min` (window + J/m²) | when is the most exposure available | **Keep — promote.** Currently duplicated with the next row. |
| `best usable 30 min` | when is it actually achievable | **Keep** — but only render when it differs, and say why. |
| `confidence NN` | how much to trust this | **Keep, re-frame.** A bare 1–100 with no scale, no band and no anchor (F-25). |
| `Local NN` | how this compares to this location's history | **Keep — label it.** It is a within-location percentile rendered beside an absolute; the pair invites cross-site comparison (F-28). |
| `Overall NN` | — | **Remove or relabel.** Deprecated by the product's own legend, still leading the hero, the strip, the tables and the ICS (F-10). |
| `Abs NN` | worldwide strength | **Keep.** This is the cross-site-comparable number and it is currently the *least* prominent of the three. |
| `Int / Fit / Conf` in day cells | intensity, usability share, forecast agreement | **Keep** — good trio, but `Fit 100%` needs its denominator stated. |
| `UV∘ NN` + range | UV index and its **source range** | **Keep.** The unlabelled sub-range (`3.0–6.2`) is the min/max of the available per-source UVIs (`serving.py:680`), **not** a prediction interval — `uvi_prediction_interval_low/high` is a different field and is not rendered there. It needs a label (`source range`), and the calibrated interval, which is the trust-relevant number, is currently not surfaced at all. |
| `ΔUV` | source disagreement | **Keep.** Genuinely distinctive. |
| `OM / CAMS / EPA / Clear` | per-source evidence | **Keep.** Best part of the table. |
| `Rain %`, `Cloud %`, `windy` | go/no-go | **Keep.** |
| `blocked_half_hours` (as `Fit`) | how much of the day is excluded | **Keep — expose the reason.** The reason exists (`outdoor_feasibility_reason_codes`) and is rendered only as a note in the row. |
| `Source: interpolated_hourly` | provenance of the row | **Keep**, but it is jargon; `interpolated from hourly` is the same length. |

### 3.3 Visualization-by-visualization

| Visualization | Type fit | Verdict |
|---|---|---|
| Day-strip bar (`<div class="bar"><i width%>`) | good — a magnitude glyph in a scan row | **Keep.** Best density decision on the page. |
| Chart 1 — TanScore vs time (area) | correct | **Keep.** Best window shaded, hover readout works. |
| Chart 2 — cumulative TanDose | correct for an odometer | **Keep.** Framing is honest. |
| Chart 3 — cumulative SED | correct | **Keep.** |
| All three charts | — | **Gap:** no axes labels beyond bare numbers, no units on the y-axis, and no data-table alternative. The `title` attribute is the only machine-readable description (F-17). |
| Sun figure (SVG) | ideal | **Keep.** Unambiguous, labelled (`ground`, `face S · torso ~47°`). |
| UVI dot | correct idea, wrong palette | **Fix** (F-26). |
| In-row `★` marker | good | **Keep.** |

### 3.4 Composition problems

- **No cross-site view.** The product holds two sites and offers no comparison;
  the location control is a modal swap that loses the other site's context (F-08).
  A user asking "Palisades or South Bend this weekend" has to remember one while
  looking at the other.
- **The strip is the only navigation**, and it costs 14 tab stops (F-07).
- **No "now" affordance.** Nothing indicates the current time on the charts or
  in the tables, so "should I go out *now*" requires scanning for today's date
  and then reading a table.
- **Confidence is not attached to the window it qualifies.** The hero quotes one
  confidence for a window; the day cell quotes another at peak; the table quotes a
  third per hour. Three confidences, no key to which qualifies what.

---

## 4. Workflow audit

### W1 — "When should I go outside today?" (the core task)

| | |
|---|---|
| **Current journey** | Load → read 236-character hero → find the window inside it → check `confidence 46` (no scale) → scan the day strip for the same day → scroll to the table → find the starred rows → read `Note` for block reasons. **7 steps, 4 of them re-reading the same fact in a different place.** |
| **Friction** | The window is stated twice identically; confidence is bare; the day's blocked hours are in the limiter text of the day header; "is it *now*" is not answerable from the charts; the hero does not say whether the window already passed. |
| **Failure points** | If the window has passed, nothing says so — the hero still presents it as "Strongest 30 min". |
| **Improved journey** | Load → one sentence: `Now 2:10 PM — best window today was 1:30–2:00 PM (1136 J/m², moderate confidence). Next good window: tomorrow 1:30 PM.` → the strip marks today and the past. **1 step.** |
| **UI changes** | Hero becomes a state machine: *upcoming* / *in progress* / *passed* / *none today*. Mark `now` on all three charts. Attach the confidence to the window it belongs to. |
| **Acceptance** | The hero states whether the window is past, current or upcoming; a `now` marker is visible on every chart; the reader never has to reconcile two confidences for one window. |

### W2 — "Make it match my situation" (surface, posture, skin, MMD)

| | |
|---|---|
| **Current journey** | Change Surface → change Tilt → change Azimuth → press Apply → *nothing numeric changes* → open Advanced/Photobiology → read `reflected E_mel 0.13 W/m²` → conclude either it worked or the app is broken. **5 steps ending in doubt.** |
| **Friction** | F-00 in full. Four controls with no visible numeric effect; the one number that changes is inside a collapsed disclosure and has no unit continuity with the headline. |
| **Failure points** | A user cannot tell success from failure. The already-verified-correct pipeline behaviour is indistinguishable from the bug that made it inert earlier in this project. |
| **Improved journey** | Change Surface → the control shows the profile's reflectance inline → press Apply → the headline gains a second figure: `on fresh snow, tilted 45°: 1 339 J/m² (+18%)`. **3 steps, immediately legible.** |
| **UI changes** | Second headline figure (already in the payload as `skin_plane_delayed_pigmentation_effective_irradiance_wm2`); an invariant line under the controls; per-control "no effect unless …" hints; Apply disabled until something changed. |
| **Acceptance** | A change to any of the four controls produces a visible numeric change within one Apply, and the invariant statement is present in the default state. |

### W3 — "Take it with me" (subscribe / export)

| | |
|---|---|
| **Current journey** | Calendar link → OS subscribes to `webcal://…`. Or Export CSV → three files land in Downloads with no naming context in the UI. |
| **Friction** | The ICS title is `Best usable sun 1:30 PM-2:00 PM (dose 1111.1 J/m2 E_mel)`; the description is 9 lines of `Overall/Local/Local@best/Abs/Peak UV/UVA/UVB/TanDose/SED/Confidence`; `J/m2` and `E_mel` leak internal names (F-18). The exported CSVs are named `sunstack-all-hourly.csv` etc. with no site or date, so two sites' exports collide. |
| **Failure points** | A subscribed calendar shows the deprecated composite as the headline fact for the day. |
| **Improved journey** | Subscribe → events titled `Sun: 1:30–2:00 PM, 1136 J/m²` with a two-line description. Export → `sunstack-south-bend-2026-10-07-hourly.csv`. |
| **UI changes** | ICS `SUMMARY`: `Best window 1:30–2:00 PM · 1136 J/m²`. `DESCRIPTION`: dose, confidence, one caveat. Filenames include site slug + selected date. Add one line of UI copy stating that subscribed times refresh with each run. |
| **Acceptance** | No internal identifier or `J/m2` form appears in the ICS; exported filenames are unique per site and date. |

---

## 5. Three structural alternatives for the primary answer surface

Each is a genuinely different structure, not a restyle.

### Alternative A — "Answer first, evidence behind" (single column, strict priority)

```
┌──────────────────────────────────────────────────────────┐
│ SunStack · South Bend            Updated 9:56 PM · tier C│
├──────────────────────────────────────────────────────────┤
│                                                          │
│   Best window today                                      │
│   1:30 – 2:00 PM                                         │
│   1136 J/m²  ·  moderate confidence                      │
│                                                          │
│   Now 2:10 PM — this window has passed.                  │
│   Next: tomorrow 1:30 – 2:00 PM                          │
│                                                          │
│   [ Show me why ▾ ]                                      │
├──────────────────────────────────────────────────────────┤
│ Your context: Surface [Unknown ▾] Tilt [0] Skin [None ▾] │
│ Your surface does not change the reference above.        │
│ On fresh snow, tilted 45° it would be 1339 J/m² (+18%).  │
├──────────────────────────────────────────────────────────┤
│ [14-day strip]                                           │
└──────────────────────────────────────────────────────────┘
```

- **Clarity** highest — one decision, one number, one caveat.
- **Task efficiency** best for W1; W2 handled by putting the user-dependent
  number directly under the controls that change it.
- **Implementation** low — every value already exists; this is template work.
- **Discoverability** good — the evidence is one labelled disclosure away.
- **Scalability** weak — a second location needs a second surface.
- **Accessibility** best — shortest tab path to the answer, one landmark.

### Alternative B — "Split answer / evidence panes" (two columns ≥ 1024 px)

```
┌───────────────────────────────┬──────────────────────────┐
│ ANSWER                        │ EVIDENCE                 │
│ Best window 1:30–2:00 PM      │ per-source UVI + ΔUV     │
│ 1136 J/m² · confidence 46     │ 30-min table (sortable)  │
│                               │ charts w/ now marker     │
│ [Now] [Today] [Tomorrow] tabs │ feasibility + reasons    │
│                               │ run metadata (collapsed) │
├───────────────────────────────┴──────────────────────────┤
│ 14-day strip                                             │
└──────────────────────────────────────────────────────────┘
```

- **Clarity** high for desktop, but two competing focal columns.
- **Task efficiency** best for W1 *and* for "why is it 1136" — no scrolling.
- **Implementation** medium — needs a real layout pass and a scroll strategy.
- **Discoverability** best — evidence is permanently visible.
- **Scalability** best — the right pane is exactly where a second location, a
  comparison, or a history view would go.
- **Accessibility** medium — reading order must be forced so the answer is first
  in the DOM even though it is visually left.

### Alternative C — "Ranked list first" (the answer as a queue)

```
┌──────────────────────────────────────────────────────────┐
│ SunStack · South Bend · now 2:10 PM                      │
├──────────────────────────────────────────────────────────┤
│ ▸ TODAY  1:30–2:00 PM   1136 J/m²   moderate     ♨ best  │
│   TODAY  2:00–2:30 PM    980 J/m²   moderate             │
│   TODAY  3:00–3:30 PM    610 J/m²   low                  │
│   TOMORROW 1:30–2:00 PM 1240 J/m²   high         ♨ best  │
├──────────────────────────────────────────────────────────┤
│ [14-day strip] [why this order ▾] [your context ▾]       │
└──────────────────────────────────────────────────────────┘
```

- **Clarity** high — answers "what are my options" rather than "what is the one
  number", which matches how people actually plan.
- **Task efficiency** best for planning across days; slightly worse for "today
  only" than A.
- **Implementation** medium — needs a cross-day window ranking (today the strip
  and tables are day-scoped).
- **Discoverability** high — skips the strip for the primary task.
- **Scalability** good — naturally extends to a second location as a second
  queue.
- **Accessibility** good — a list of four rows, one landmark.

### Recommendation

**A as the immediate structure, evolving toward C.** A is the smallest change
that fixes the highest-severity findings (F-00, F-04, F-02, F-25) because it only
reorders and re-words existing values — no new computation. C is the better
long-term product (planning is the real job) but it requires cross-day window
ranking, which is a science change and should not gate the interface fix.

B is rejected as the *first* move: it doubles the visual complexity on a page
whose problem is that the primary answer is already hard to find, and it needs a
layout pass that would mask whether the copy fix worked.

**Challenging my own recommendation:** A's risk is that it hides the honesty
material (tier, sources, caveats) that is currently a genuine strength. That is
why the disclosure is labelled `Show me why` rather than `Details`, and why the
tier badge stays in the header — the honesty stays visible, only its *volume*
moves.

---

## 6. Remediation roadmap

Ordered by user impact ÷ effort, with dependencies.

### Phase 1 — Critical correctness (do first; each is independently shippable)

**Revised after adversarial review.** The first item is now F-36, not the drizzle
policy: it is an *observed contradiction of the product's own stated invariant on
a shipped location*, whereas the drizzle threshold is a policy preference with a
real comfort trade-off. The drizzle change moves to Phase 3 as a policy decision.

| # | Item | Depends on | Done when |
|---|---|---|---|
| 1.0 | **F-36: unknown weather must not read as perfect.** Make missing essential weather an explicit unknown state; require completeness for usable/comfortable eligibility; render the unknown verdict instead of a fit/comfort score. Leave the environmental dose untouched. | — | the live Palisades missing-temperature rows stop reporting `feasibility 100` / `comfort "perfect"`; a candidate with missing weather is excluded from usable ranking but keeps its dose |
| 1.1 | **F-37: reject non-finite `min_temp`** (NaN, ±inf) on both endpoints; assert finiteness in the artifact validator | — | non-finite input returns 4xx; `summary.min_tan_temperature_f` always equals the applied value |
| 1.2 | F-02: stale-data marker + disable Apply in flight | — | a failed load visibly marks the retained run |
| 1.3 | F-03: normalise structured `detail`; treat blank numeric fields as unset | — | `[object Object]` is unreachable |
| 1.4 | F-12: re-raise `HTTPException`; 4xx for user errors; drop "check the server log" | — | invalid input returns 4xx; the phrase is gone |
| 1.5 | F-29: fix the half-hour `time_utc` conversion (leave the correct hourly frame alone) | — | every `*_utc` field equals its row's `interval_end_utc` |
| 1.6 | F-01: remove the hardcoded class schedule; reimplement as per-visitor input | — | published HTML contains no schedule |

### Phase 2 — Core answer surface (the redesign)

| # | Item | Depends on | Done when |
|---|---|---|---|
| 2.1 | F-04: rewrite the hero; one sentence; no `E_mel`; `J/m²` everywhere | — | hero ≤ 20 words, carries window + dose + confidence + past/now/upcoming |
| 2.2 | F-00: invariant statement + second headline figure for the user-dependent dose | 2.1 | changing surface/tilt changes a figure above the fold |
| 2.3 | F-10: resolve the deprecated composite — remove or rename on every surface incl. ICS | 2.1 | no deprecated metric renders unqualified |
| 2.4 | F-25/F-28: label `Local` as within-location; make the cross-site-comparable number absolute | 2.1 | no cross-site comparison is implied by a self-referential number |
| 2.5 | Adopt Alternative A's ordering (answer → context → strip → evidence) | 2.1–2.4 | a first-time user can answer W1 without scrolling |

### Phase 3 — Information architecture

| # | Item | Depends on | Done when |
|---|---|---|---|
| 3.1 | F-08: URL state for location + day; persist location | — | reload preserves the site; URL is shareable |
| 3.2 | F-16: 30-min table gains dose + confidence; both tables sortable | 2.5 | dose visible at 30-min resolution; header click sorts |
| 3.3 | Compare view for two locations | 3.1 | both sites' headline doses visible simultaneously |
| 3.4 | `now` marker on charts and tables; `now`-aware hero | 2.1 | W1 answerable at a glance |

### Phase 4 — Copy and terminology

| # | Item | Depends on | Done when |
|---|---|---|---|
| 4.1 | Apply the copy audit table wholesale | — | no raw enum, no parameter name, no `E_mel`, no `J/m2` in rendered text |
| 4.2 | F-05: human labels for the MMD basis + explain the consequence | — | each option is an English phrase |
| 4.3 | F-13/F-14: restructure Source data and the provenance line | — | no 17 KB blob; the accuracy caveat is visible |
| 4.4 | F-15: split packed cells; state units in headers | 3.2 | no cell mixes reason + measurement |

### Phase 5 — Visual system

| # | Item | Depends on | Done when |
|---|---|---|---|
| 5.1 | F-26: standard UV ramp; move the score ramp off it; reserve amber for selection | — | no shared hex between the two scales |
| 5.2 | F-06: hover states for every interactive element | — | every clickable element responds to the pointer |
| 5.3 | Tokenise the remaining hard-coded colours | 5.1 | no inline `style="color:#…"` in generated rows |
| 5.4 | Typographic and spacing scale | 2.5 | one coherent ramp, documented |

### Phase 6 — Accessibility and performance

| # | Item | Depends on | Done when |
|---|---|---|---|
| 6.1 | F-07: real listbox semantics or plain buttons for the strip | 3.4 | one tab stop; arrow keys work |
| 6.2 | F-17: charts get `role="img"` + `aria-label` + a data table | — | every chart has a text alternative |
| 6.3 | F-22: fix CLS 0.16; reserve layout for strip/tables | 2.5 | CLS < 0.1 |
| 6.4 | Keyboard shortcut layer (nothing exists today) | 3.4 | `j/k` day navigation, `/` focus search, `?` help |

### Dependencies and sequencing notes

- Phase 1 is independent of everything and fixes user-visible wrongness; ship it
  first.
- Phase 2 is the highest-leverage work and must precede Phase 3.2/3.3, because
  restructuring tables before the headline is settled produces churn.
- Phase 4 (copy) should be applied *with* Phase 2, not after — the hero rewrite
  is a copy change.
- Phase 6.1 depends on 3.4 because the strip's interaction model changes once
  `now` is a first-class concept.
- **Two items I deliberately do not recommend:** adding more metrics, and adding
  animation. The product's problem is that it already computes 298 fields and
  shows 31, and its motion budget (zero transitions) is fine.

---

## 7. Self-critique of this audit

Where I could be wrong, stated plainly:

1. **F-28's severity depends on intent.** If `Overall` is *meant* as a
   within-location interpretation, converging across sites is expected and the
   defect is only that it is presented without a scope label. I have kept it P1
   because the strip, the hero and the ICS all present it as the day's headline
   fact, not as a within-location statistic.
2. **F-27's fix has a real trade-off.** Loosening the drizzle block means some
   users will be shown a "good" window during light drizzle. The product's own
   stated principle is "missing weather is never perfect"; the honest compromise
   is a *soft* penalty plus a visible reason, not silence — which is what I
   recommend, but it is a judgement call about a physical comfort threshold, not
   a correctness proof.
3. **My coverage is 88%, not 100%.** Not tested: a live `POST /api/refresh` to
   completion (multi-minute upstream CAMS queue — the button was exercised and
   observed fetching, but I did not watch it finish), permission-restricted states
   (none exist), and a genuinely empty deployment (I forced the client's empty
   path instead). All three are recorded as such in `inventory.md`.
4. **Three of my initial suspicions were wrong** and are corrected in
   `findings.md`: `Source data` is not empty, personal MMD is not inert, and the
   surface slugs do match. I include this because an audit that reports only its
   hits is not auditable.
5. **Alternative A is the safest, not the best.** C is the better product for
   real planning behaviour. I recommend A first only because it needs no new
   computation, and I say so explicitly rather than presenting A as optimal.