# SunStack single-page UI — product design & information architecture audit

**Scope.** Information architecture, task fit, and product design of the one-page client. No implementation
file was modified.

**Evidence base.**

| Ref | Artifact |
|---|---|
| `S:L###` | `src/sunstack/serving.py` — line numbers are source lines of the file; the client is the single `HTML` constant on lines **519–698** (inline `<style>` 521–589, body 590–604, `<script>` 605–697) |
| `O:L###` | `src/sunstack/opportunity.py` |
| `U:L###` | `src/sunstack/ui.py` |
| `X:L###` | `src/sunstack/output.py` |
| `C:L###` | `docs/SUNSTACK_V5_FINAL_IMPLEMENTATION_CONTRACT.md` |
| Live | `uv run sunstack ui --port 8903 --no-browser`, current run `20261006_215615_215394_86352`, 14 daily / 163 hourly / 326 half-hourly rows |
| Published | `docs/index.html` served read-only over `python3 -m http.server` |
| Measured | Chromium, headless, viewports 1440×900 and 390×844 |

Every number below is a DOM measurement from those two viewports unless labelled as arithmetic.
Claims marked **[INFERENCE]** are reasoning, not observed UI text.

---

## 1. Section inventory in rendered order

Single scrolling document. `.wrap` (`S:L590`) has 12 direct children; the first (`.top`) holds the header
*and* both control groups. Heights are live-page, 1440×900.

| # | Region | Source | Top→Bottom (px) | Height | Interactive controls (visible) | Contents |
|---|---|---|---|---|---|---|
| 1 | `.top` — header | `S:L591` | 28–248 | 220 | **13** | `<h1>Sunlight hours</h1>`; `#runline` provenance line |
| 1a | `.controls.settings` | `S:L592–593` | (inside 1) | — | **9** | `#locsel` Location · `#skin` Skin (7 options: None + I–VI) · `details.mmd` disclosure (`<summary>I have my MMD</summary>`) · `#mmd` My MMD · `#mmdbasis` basis (5 options) · `#mintemp` Min °F · `#surface` Surface (14 options) · `#skintilt` Tilt · `#skinaz` Azimuth |
| 1b | `.controls.actions` | `S:L594` | (inside 1) | — | **4** | `Apply` button (lives at the end of 1a) · `Refresh forecast` (`class="primary livereq"`) · `Calendar` anchor (`#cal`) · `Export CSV` |
| 2 | `#msg.status` | `S:L595` | 0–0 | 0 (empty) | 0 | Transient status/error text; `display:block` always, hidden by being empty |
| 3 | `#hero` | `S:L596` | 274–414 | 140 | 0 | One serif sentence: the page's headline answer |
| 4 | `.legend` | `S:L597` | 418–450 | 32 | 0 | "Ranking is maximum expected 30-minute delayed-pigmentation dose (fixed-duration-dose-v2). Overall is a LEGACY composite (deprecated product heuristic); UV∘ is headline UVI fusion, while TanDose comes from the UVA/UVB model." |
| 5 | `#skinctx` | `S:L598` | 456–471 | 15 | 0 | Fitzpatrick context; renders "not specified — Environmental scores are skin-type independent." when Skin is unset |
| 6 | `#strip` | `S:L599`, cell template `S:L642` | 479–831 | 352 | **14** | 14 `<button class="daycell" role="option">`, one per forecast day, each carrying ~13 data items: day/date, `day_status`, best-window time range, `🎓 …` class spans, big `Overall` number, `Int`, `Fit`, `Conf`, `UV lo–hi`, `Feels lo–hi`, `Gust`, `Abs · Loc`, `bar`. Horizontally scrollable (`.strip{overflow-x:auto}`, `S:L539`): scrollWidth **1786 px** vs clientWidth **1076 px** at 1440 → **~8.4 of 14 cells visible**, the rest need a horizontal scroll |
| 7 | `#doses` | `S:L600` | 853–959 | 106 | **1** | `<h2 class="sec">Doses — intensity vs accumulated exposure</h2>`, `#doserow`, and `details#advphoto` ("Advanced / Photobiology") containing `#advrow` + `#provenance` |
| 8 | `#charts` | `S:L601` | 981–1332 | 351 | **2** | `<h2 class="sec">Day charts (separate panels — SED is exposure, never “good”)</h2>`; `.chartnav` with `‹`/`›` and `#chartName`; three `<canvas>` (`chartScore` 150 h, `chartDose` 120 h, `chartSed` 120 h) of which **exactly one is displayed at a time** (`chartToggle` sets the others to `none` — measured: `chartScore=inline, chartDose=none, chartSed=none`) |
| 9 | `#sunfigwrap` | `S:L602` | 1332–1552 | 220 | **1** | `svg#sunfig` (sun position + torso-recline figure), `#suncap`, `#sunsel` Time select |
| 10 | `details.glossbox` | `S:L602` | 1566–1594 | 28 (closed) | **1** | "Column glossary" — 15 headwords (`UV∘`, `OM/CAMS/EPA`, `Clear`, `ΔUV`, `UVA/UVB`, `Temp`, `Wind`, `Cloud`, `Rain`, `DNI`, `Overall`, `Abs`, `Local`, `Atm`, `Conf`) |
| 11 | `#detail` | `S:L602` container, filled by `renderDay()` `S:L683–697` | 1616–3390 | **1774** | **2** (+36 click-only rows) | `h2` date header · `.bestline` · `.classrow` (`#classTgl` + note) · `h3` "Every hour — Headline UVI first" + `#nerdBtn` · `.gloss` · hourly table (12 rows × 20 cols, **12 cols hidden**) · `h3` "Every 30 minutes" · 30-min table (24 rows × 7 cols) |
| 12 | `details.debug` | `S:L603` | 3416–3441 | 25 (closed) | **1** | "Source data" → `<pre id="debugtext">` containing the whole `summary.json` pretty-printed |

**Totals.** 3501 px of document at 1440×900 (**3.89 screens**); 4066 px at 390×844 (**4.82 screens**).
**35** natively interactive elements (buttons, selects, inputs, anchors, `summary` disclosures) — 13 in the
header, 14 day cells, 2 chart arrows, 1 time select, 3 disclosure summaries, 2 table toggles. Plus **36**
`#detail tr[data-time]` rows with `click` handlers and **no** `tabindex`, `role`, or key handler
(measured: `rows: 36, focusable: 0, role: 0`) — mouse-only affordances.

Published page (`docs/index.html`) is the same structure minus three controls and minus two CSS rules, per
`X:L63–92`: `Min °F` becomes `<input id="mintemp" type="hidden" value="50">`, the `Apply` button and the
`Refresh forecast` button are removed, and `<span class="note">Static export · min 50°F · reruns publish
fresh data</span>` replaces them. Measured published heights: **3449 px** desktop, **3972 px** mobile.
A `#skinnote` paragraph is injected by `X:L88–92`.

---

## 2. Task analysis

### Who this is for (verified vs inferred)

**VERIFIED** — read off the UI itself:

- The product's own headline is **"Sunlight hours"**, not TanScore: `<h1>Sunlight hours</h1>` (`S:L591`) and
  `<title>Sunlight hours — SunStack</title>` (`S:L521`). `README.md` calls the project "SunStack TanScore".
- The UI addresses exactly one person and assumes they already know their own skin photobiology:
  `<summary title="Only if you have a measured or estimated personal MMD">I have my MMD</summary>` (`S:L592`),
  `<label>My MMD <input id="mmd" … placeholder="J/m²" title="Measured/estimated personal MMD in
  melanogenic-effective J/m² — leave blank unless you know yours">`, and the basis select's options
  `SUNSTACK_EFFECTIVE`, `SOURCE_SPECTRUM`, `OBJECTIVE_ESTIMATE`, `COARSE_ESTIMATE` (all `S:L592`).
- The page renders one person's university lecture timetable: `const CLASSES={1:[[660,735],[770,820],[840,950]],…}`
  (`S:L676`), `<input type="checkbox" id="classTgl" checked> Show my classes (ET, Mon–Fri)` (`S:L690`), and
  `free for you:` (`S:L678`, `S:L689`).
- The secondary surfaces are developer surfaces: `#provenance` prints `fusion calibrated-uvi-fusion-v2 ·
  confidence calibrated-error-v1 · rank fixed-duration-dose-v2 · Model action-spectrum-v2 · spectrum tier
  provisional · spectral tierC-broadband-proxy-v2 (C) · global ref global-mel-ref-v2 (1.793 W/m²) · CAMS
  2026-10-06T12:00Z · UVI agree 6.2% · calib nasa_power_ml_plus_cams_spectral · UVA model: same-domain MAE
  0.33 W/m², live NWP-fed MAE ~5.8 (train/serve shift, see Research notes)` (`S:L627`), and `#debugtext` dumps
  the raw summary JSON (`S:L603`, `S:L646`).
- `README.md:179`: "TanScore is an environmental/pigmentation-potential model, **not a safe exposure-time
  recommendation**."

**INFERENCE (stated as such).** The UI is built for **one technical operator** — the repository owner — who
(a) wants a personal "should I, and when should I, get sun today" answer that respects a class timetable,
and (b) wants model-transparency instrumentation to check the pipeline. Both jobs are served by the same
undifferentiated scroll. `README.md` states no audience, no user story, and no task list anywhere; the
"Getting started" section is entirely about `cdsapi` credentials and `uv sync`. **[INFERENCE]**

The discrepancy the task anticipated is real and specific: **`README.md` documents the product as a public,
source-transparent forecast stack with a dashboard, while the rendered UI contains one individual's weekly
class schedule rendered as public page copy.** See §5.

### Tasks

Interaction counts are counted from a cold load of the live page in its default state (SEL = today, all
disclosures closed, `.nerd` hidden, `show-nerd` off). "Scrolls" are 900 px viewport-heights at 1440×900.

| # | Task (job to be done) | Entry point | Interactions to complete | Scrolls | Answered? | Carrying text / control |
|---|---|---|---|---|---|---|
| **T1** | *Should I bother going out at all today?* | `#strip` cell 1 | **0** | 0.53 (cell at y 479) | **Directly, but by a key the product deprecated.** `day_status` is derived from `overall_tan_opportunity_0_100` — `"day_status": _day_status(float(best["overall_tan_opportunity_0_100"]))` (`O:L1239`), `_day_status` thresholds at `O:L1245–1258` | cell text `Tue, 10/6 / FAIR` and `NO OUTDOOR WINDOW` (`S:L642`, `d.day_status`) |
| **T2** | *When exactly should I go out today?* | `#hero` (`S:L596`) | **0** for today's headline; **1** click + **1.8 scrolls** to reach the day's own answer at `#detail` | 1.8 | **Not directly.** The hero is about the *best day in the run*, not today, and it prints two windows. Measured on the live page at first paint: hero = `Wednesday, October 7 Strongest 30 min 1:30 PM – 2 PM … best usable 30 min 1:30 PM – 2 PM …` while `#detail` (SEL = today) = `Tuesday, October 6 … Good window (longest near-peak) 12 PM – 4 PM … free for you: 12:30 PM–4 PM` (`S:L644`, `S:L689`) | hero `S:L644`; `.bestline` `S:L689` |
| **T3** | *Is there a better day this week?* | `#hero`, then `#strip` | **0–1** (horizontal scroll on the strip) | 0.5 | **Directly** — the hero is exactly this answer (`bestDay()` sorts by `best_usable_30m_dose_j_m2` → `strongest_30m_dose_j_m2` → `best_30m_tan_dose_j_m2`, `S:L634`) — but the strip's own comparison number is the legacy composite | `.daycell .pk` = `day_overall_peak_0_100` (`S:L642`) |
| **T4** | *Plan tomorrow / a specific future day.* | `#strip` cells 2–14 | **1** click on the cell | 0 + 1.8 | **Directly** — click sets `SEL=el.dataset.date;render()` (`S:L645`) and every panel re-renders. But 5 of 14 cells (Fri 10/9 onward) are multi-day-out rows and still render the identical layout with no confidence decay cue beyond a small `Conf` figure | `.daycell` click `S:L645` |
| **T5** | *Is it worth going out at all — how usable is it outdoors?* | `#strip` `Fit`/`Gust` lines; `#doses` | **0** | 0.95 (doses at y 853, half-cut by the fold) | **Directly** | `Fit 88%` (`S:L642`, `title="Outdoor fit: share of daylight half-hours not hard-blocked"`); `#doserow` = `TanDose peak 30 min 1045.3 J/m² mel (2 PM) · best hour 2156.4 J/m² (1:30 PM) · best window 7756.1 J/m² · today 11956.8 J/m² (Normalized reference exposure: 1.9 ref-hours (model normalization, not a recommended exposure duration)) (partial) | SED peak 30m 2.10 · window 15.95 · today 27.38 (partial)` (`S:L625`) |
| **T6** | *Put the windows on my calendar.* | `#cal` anchor in `.controls.actions` | **1** | 0 | **Directly** — but the subscribed event is time-typed to a *different* window than the page's headline. `build_calendar_ics` starts from `best_usable_30m_start/end/dose` (`S:L363–365`) and labels it `basis, dose = "Best usable sun", usable_dose` (`S:L376`). Verified `curl /api/calendar.ics`: `SUMMARY:Best usable sun 1:30 PM-2:00 PM (dose 1136.1 J/m2 E_mel)`, `DTSTART:20261007T173000Z` — the same 30 min the page calls "best usable", while `.bestline` says `Good window … 12 PM – 4 PM · free for you: 12:30 PM–1 PM` | `S:L363–365`, `S:L376`; anchor title `Subscribe to the best-window calendar` (`S:L594`) |
| **T7** | *Take the numbers away for my own analysis.* | `Export CSV` button | **1** | 0 | **Directly** | `exportVisibleCsv()` — `const hHead=['time','uv_index','uv_index_clear_sky',…]` (`S:L623`); the on-page gloss says "**All columns stay in the page** — hidden ones are one tap away and always in Export CSV." (`S:L690`) |
| **T8** | *Verify the model is trustworthy / see where a number came from.* | `details#advphoto` ("Advanced / Photobiology") for tier/fusion/confidence; `details.debug` ("Source data") for the raw summary | **1** click + scroll; **2** for the raw JSON (3.6 scrolls) | 0.9 / 3.6 | **Directly** | `#advrow` = `UVA day 922544.3 J/m² · UVB day 16712.60 J/m² | Visible-Darkening Potential (peak 30m) 46613.6 J/m² existing-pigment (not new melanin) | spectral tier C (tierC-broadband-proxy-v2) · action spectrum parrish_fda_3630 checksum ✓ · global ref global-mel-ref-v2 (1.793 W/m²) · UVI disagreement 8.5% (moves confidence, not physics)`; `#provenance` as quoted above; `#debugtext` (`S:L603`, `S:L646`) |

**Interaction-cost note.** No task in the list requires typing or multi-step commitment, but **seven of
eight are answered without the user touching anything** — the page is a broadcast, not a query surface. The
only write interaction is `#cal` (subscribe). Consequently the failure mode of this page is not
"too many clicks to the answer"; it is **the answer given at the wrong scope** (T2).

---

## 3. Hierarchy critique

### What is visually and structurally prioritized

Measured emphasis, in order of weight:

1. **A 26 px serif headline sentence** — `.hero{font-family:Georgia,serif;font-size:26px;line-height:1.35;margin:26px 0 4px;max-width:34em}` (`S:L536`) — the single largest text on the page, occupying the first scroll.
2. **A 14-cell, 352 px-tall, horizontally-scrolling strip of 14 cards with ~13 data items each** — `.strip{display:flex;gap:10px;overflow-x:auto;padding:14px 2px;margin:8px 0 4px}` (`S:L539`) on a 220 px header. It occupies the entire second half of the first screen and visually dominates everything below.
3. **The `Overall` number**: `.daycell .pk{font-family:Georgia,serif;font-size:24px;margin-top:6px}` (`S:L543`) — the second-largest type on the page — plus the cell's `bar` width and the cell's `border-color` when wet, plus the `day_status` word, plus `#detail h2`'s inline colour via `scoreColor(d.day_overall_peak_0_100)` (`S:L688`, thresholds at `S:L612`).
4. **A 32 px legend paragraph explaining what the ranking is** (`S:L597`).

### What the user most needs

For the primary job (T1/T2) the user needs, in order: **today**, **a single window**, **why that window and
not the other one**, **whether the outdoors is tolerable**. The page delivers: a *different day's* window
first, two windows at once, no reason, and the outdoor verdict split across two `uv` sub-lines inside a
scrolling card.

### Specific elements competing for attention

| Competition | Evidence |
|---|---|
| **Hero day vs selected day.** The largest text answers for `bestDay()` while everything below answers for `SEL`. On first paint they are different days. | hero `S:L641` (`const b=bestDay()`) vs `S:L640` (`SEL` = today) and `S:L644`/`S:L689` |
| **Two rankings in one sentence.** "Strongest 30 min X; best usable 30 min Y" is structurally two answers to one question, in the most prominent element. | `S:L644` |
| **Legacy composite vs v5 dose, in the same viewport.** The strip's big number + bar + status derive from `overall_tan_opportunity_0_100` while the legend 32 px below says it "is a LEGACY composite (deprecated product heuristic)". | `S:L642`, `S:L543`, `O:L1239` vs `S:L597` |
| **Three "best time" answers, none labelled with its key.** `.win` = `winStr(d.best_window_start,…)` (legacy sustained window, `O:L878` ranks it by Overall); `.bestline` adds `best hour`; `free for you` = `best_available_window`. | `S:L642`, `S:L689` |
| **The 30-minute table outranks the hourly table** while showing less: 924 px vs 623 px, 7 columns vs 20, and 2 of its 7 columns are the deprecated composite and its percentile. | measured `#detail` children: `tablewrap` #1 h=623 (12 rows × 20 cols), #2 h=923 (24 rows × 7 cols) |
| **`Int` and `Abs` are the same field printed twice in one cell** — `day_absolute_peak_0_100`. Measured text: `Int 34 … Abs 34 · Loc 93`. | `S:L642` (two `<div class="uv">` from one variable) |
| **Three canvases, one visible.** The `<h2>` says "separate panels" and all three are in the DOM stacked at 150/120/120 px, but only one has `display` ≠ `none`; the other two need the `‹`/`›` arrows. Measured `chartName`: `1 of 3 — TanScore 0–100 (instantaneous intensity)`. | `S:L601`, `S:L630` |
| **Two identical legend paragraphs** — one as `.legend` at y 418, one as `p.gloss` inside `#detail` at y 1782. | `S:L597` vs `S:L690` |
| **Hero ends on model plumbing.** The headline sentence's final clause is `Surface Unknown; backend tierC-broadband-proxy-v2 (tier C).` — the operator's provenance appears in the user's answer. | `S:L644` |

**Structural read.** The page is a *verification instrument with a headline bolted on*. 1774 px (50.7 % of
the document) is `#detail`; 1687 px of that is raw tables. The answer — one window for one day — is a
36 px `.bestline` buried at y 1645, below two information-dense sections the user did not ask for.
The hierarchy says "here is everything the model produced, in day order"; the job says "tell me when to go".

---

## 4. The three-ranking question

### What actually exists

`build_daily_summary` computes **three** fixed-duration rankings plus a legacy sustained window plus a
legacy peak row:

| Field | Where computed | Where rendered |
|---|---|---|
| `strongest_30m_start/end/dose_j_m2` | `O:L1070`, emitted `O:L1169–1171` | `#hero` only (`S:L644`) |
| `best_usable_30m_start/end/dose_j_m2` | `O:L1071`, emitted `O:L1172–1174` | `#hero` (`S:L644`); **and the ICS event time** `S:L363–365`, `S:L376` |
| `best_comfortable_usable_30m_start/end/dose_j_m2` | `O:L1072–1074`, emitted `O:L1175–1177` | **Nowhere.** `grep -c 'best_comfortable_usable_30m' src/sunstack/serving.py` → **0**. Shipped in the payload, unused by the client |
| `best_window_start/end` + `best_window_rank_formula` = `window-rank-v1 (mean overall opportunity over contiguous eligible half-hours; dose reported, not ranked)` | `_best_contiguous_window`, `O:L871–918`, emitted `O:L1162–1164`, `O:L1168` | `#strip .win` (`S:L642`) and `.bestline` "Good window (longest near-peak)" (`S:L689`) |
| `best_available_window_start/end` | same function with `skip_class=True` (`O:L1066`), emitted `O:L1165–1167` | `.bestline` "free for you:" (`S:L689`), `availWin()` (`S:L678`) |
| `best_hour_start/score_0_100` | `O:L1046–1062`, emitted `O:L1150–1157` | `.bestline` "best hour" (`S:L689`) |
| `best_30m_start` = the row where `overall_tan_opportunity_0_100` is maximal | `O:L1041–1045` | `.bestline` "peak 30-min dose" via `peak_30m_tan_dose_j_m2` (`S:L689`, `O:L1216`) |
| `overall_tan_opportunity_0_100` | `O:L224` | `#strip` big number + bar + border (`S:L642`), `#detail h2` (`S:L688`), hourly `Overall` column (`S:L686`), 30-min `Overall` column (`S:L687`), `.bestline` "best hour (43)" score, `pickSunRow` default frame (`S:L672`), sun caption `(UV 4.8, overall 43)` (`S:L671`), ICS description `Overall 43/100` (`S:L386`, `S:L406`) |

### Is this coherent? No — and it is measurable, not aesthetic

On the live run, for **2026-10-07** (the day the hero promotes), all of the following render simultaneously
on one page:

| Answer rendered | Window | Source | Rendered in |
|---|---|---|---|
| "Strongest 30 min" | 1:30–2:00 PM | `strongest_30m_*` | `#hero` |
| "best usable 30 min" | 1:30–2:00 PM | `best_usable_30m_*` | `#hero` |
| "Good window (longest near-peak)" | **12:00–4:00 PM** | `best_window_*` | `.bestline` + strip `.win` |
| "free for you:" | **12:30–1:00 PM** (30 min) | `best_available_window_*` | `.bestline` |
| "best hour" | 1:30 PM | `best_hour_start` | `.bestline` |
| "peak 30-min dose" | 2:00 PM stamp | `best_30m_start` (legacy Overall argmax) | `.bestline` |
| Sun-figure default frame | 2:00 PM | `pickSunRow` by `overall_tan_opportunity_0_100` | `#sunsel` + `#suncap` |
| Calendar event | **1:30–2:00 PM** | `best_usable_30m_*` | `.ics` DTSTART |

**Seven "when" answers for one day, three genuinely different intervals** (12:00–16:00, 12:30–13:00,
13:30–14:00), with no on-page statement of which one the product stands behind. The only disambiguation is
the `title` attribute on `#cal` — `Subscribe to the best-window calendar` (`S:L594`) — which names a
*window* concept the calendar does not use.

### Three concrete defects behind the incoherence

1. **"Best usable" is not usable.** Contract §2.5 defines it as "maximum expected 30-minute dose among
   windows that pass hard outdoor constraints **and user schedule constraints**" (`C:L186`). The
   implementation passes only `usable_only=True`: `usable_30m = best_fixed_dose_window(daylight, 30,
   usable_only=True)` (`O:L1071`), and `best_fixed_dose_window`'s docstring enumerates
   completeness/hard-usability/comfort but **not schedule** (`O:L922–933`). Schedule filtering exists only
   in the *separate* `best_available_window`, which feeds a different label. Verified consequence: on Wed
   2026-10-07 the hero's "best usable 30 min **1:30 PM – 2 PM**" falls inside the Wednesday class block
   `[770,820]` = 12:50–13:40 (`S:L676`, `O:L854`), while the page simultaneously prints
   `free for you: 12:30 PM–1 PM`. **The page's headline recommendation is itself in class.**
2. **The class signal is structurally unreachable inside the window.** Both table builders use
   `${w?' class="inwindow"':(cl?' class="inclass"':'')}` (`S:L686`, `S:L687`) — `inwindow` shadows `inclass`.
   Measured: `#detail tr.inclass` = exactly `11:00` ×2 and `11:30`; the rows at 12:50–13:40 render as
   `inwindow` (`★`, `--sunwash`) and never purple. The instruction `Purple rows = in class — plan around
   them` (`S:L690`) is therefore false for every class row that matters.
3. **`Overall` is still the default ranking key**, which contract §2.5 forbids: "The old
   `overall_tan_opportunity_0_100` may remain for one migration version as a **deprecated product
   heuristic**, clearly labeled 'legacy composite,' and **must not be the default ranking key**" (`C:L191`).
   It is the key for: the strip's largest glyph and bar, the strip's status word, the detail header colour,
   the detailed-table primary column, the sun figure's default time, and the calendar description.

### Proposed exact resolution

Small, mechanical, and it deletes more than it adds:

1. **`#hero` names one window, one key.** Replace `S:L644`'s two-clause sentence with a single emphasised
   window and an explicit basis label, e.g. `Best usable 30 min 12:30–1:00 PM — 1,136 E_mel J/m² (objective:
   maximum expected 30-min delayed-pigmentation dose among windows passing hard outdoor blocks and your
   schedule)`. Move `Surface …/backend … tier …` out of the hero into `#provenance` (it is already there
   verbatim). One sentence, one answer, one stated key.
2. **Make "best usable" mean what the contract says.** Add `skip_class`/`exclude` to
   `best_fixed_dose_window` (`O:L921+`) and pass the schedule from `best_usable_30m` at `O:L1071`, so
   `strongest_30m` stays schedule-blind and `best_usable_30m` becomes schedule-aware. This makes hero and
   ICS agree with `free for you` by construction and removes the need for `best_available_window_*`.
3. **Demote, don't hide, the other rankings.** Put `strongest_30m_*` and `best_comfortable_usable_30m_*` in
   one secondary compare line under the hero — `strongest 1:30–2:00 PM (in class) · comfortable 12:30–1:00 PM`
   — so the near-miss is visible without being a competing headline. This is the only place
   `best_comfortable_usable_30m_*` gets used, and it makes the field non-dead.
4. **Delete `Overall` as a ranking key in the UI, keep it as a labelled column** (§2.5): strip `.pk`, the bar
   width, `scoreColor` and `day_status` switch to the same dose-based key as the hero. `day_status` is
   server-side (`O:L1239`) so it moves with it; the `title="Overall tanning opportunity 0–100 — LEGACY
   composite (deprecated product heuristic)"` header (`S:L690`) stays as the deprecation label.
5. **`pickSunRow` must not use the composite.** `S:L672` selects the default frame by
   `overall_tan_opportunity_0_100`; it should default to the hero window start, and the caption
   `(UV 4.8, overall 43)` (`S:L671`) should print the dose, not the composite.
6. **Calendar = page.** `build_calendar_ics` (`S:L363–365`, `S:L376`) must emit the same window the hero
   headlines, and its `Overall {peak}/100` (`S:L398–399`) should become the dose.

Net effect: one ranking decision, stated once, reused by every surface; the other two rankings become
labelled alternatives rather than competitors; `overall_tan_opportunity_0_100` survives as a labelled legacy
column.

---

## 5. Personalization contamination

### What is shipped

The client hardcodes one person's weekly timetable:

- `S:L676`: `const CLASSES={1:[[660,735],[770,820],[840,950]],2:[[570,620],[660,735]],3:[[660,735],[770,820],[840,950]],4:[[660,735]],5:[[770,820]]};`
- `S:L677`: `function classAt(time,loc){if((loc||"")!==""&&loc!=="south-bend")return "";try{…}`
- `S:L679`: `function classSpans(date,loc){if((loc||"")!==""&&loc!=="south-bend")return "";…}`
- `S:L678`: `function availWin(date,a,b){…return `<span class="note cls">free for you: ${hhmm(f0s)}–${hhmm(f1s)}</span>`;}`

The server does the same, with the ET schedule reinterpreted in the *site's* wall clock:

- `O:L851`: `_CLASS_BLOCKS = {0: [(660, 735), (770, 820), (840, 950)], 1: [(570, 620), (660, 735)], …}` with the
  comment `# Weekly class blocks, minutes since midnight ET, Mon=0..Fri=4 (mirrors UI CLASSES).`
- `O:L1066`: `avail = _best_contiguous_window(daylight, skip_class=True)` — **no site gate**.

Copy that reaches a stranger: `Show my classes (ET, Mon–Fri)` and `Purple rows = in class — plan around
them` (`S:L690`), `free for you:` (`S:L689`, `S:L678`), `🎓 9:30–10:20, 11:00–12:15 ET` per strip cell
(`S:L642`).

### It is published, and it is wrong on the second site

**Published page** (`http://127.0.0.1:8904/index.html`, served from the committed `docs/`): `#locsel` value
`"south-bend"`; `classTgl: true` with label `Show my classes (ET, Mon–Fri)`; **10** of 14 strip cells carry
a `.cls` span; `.bestline` reads `… free for you: 12:30 PM–4 PM`; the string `south-bend` appears 3×,
`Show my classes` 1×, `free for you` 2×, `CLASSES=` 1× in the committed HTML. `LOC` is set from the select
(`LOC=dd.value`, `S:L618`), so the class branch is live for the default site.

**Pacific Palisades page** (`docs/sites/pacific-palisades/index.html`, Pacific time): `#locsel` value
`"pacific-palisades"`. There, `classAt`/`classSpans` correctly return empty (0 `.cls` cells), **but the
server-side field is not gated** and the page still prints
`… free for you: 12:30 PM–3 PM`, and `data.json` carries `best_available_window_start =
2026-10-06T12:30:00` for every day. The Eastern lecture blocks are being subtracted from a California
afternoon in Pacific wall-clock time via `_in_class`'s `dt.dayofweek` / `dt.hour` (`O:L861–868`). A
South-Bend course schedule is silently shaping the published forecast window for a different city.

### Product implications

1. **Privacy/context leak.** An identifiable weekly university timetable is public page copy on the default
   site. `README.md` never mentions it; no config, env var, or site file controls it.
2. **The contamination is unfixable by the reader.** A visitor cannot clear `CLASSES` — the checkbox hides
   `.cls` divs and toggles `body.hide-class` (`S:L692`, `S:L571–572`), but `#detail`'s `free for you` is
   server-supplied and takes priority over `availWin` in the template ternary (`S:L689`), so it survives the
   toggle.
3. **It silently redefines "usable" for everyone.** Because `best_available_window` is published as
   `free for you:` and the calendar/hero do not use it, a public subscriber receives *two* answers and no
   way to know one of them was filtered by someone else's lectures.
4. **It blocks the ranking fix.** §4's fix makes `best_usable_30m` schedule-aware. Doing that against a
   global constant would spread the contamination into the calendar and the hero.

### Concrete, shippable resolution — keep the capability, remove the contamination

The capability is legitimate: a user-supplied schedule is in the contract (`C:L186`, `C:L1088`) and is the
only personal constraint the product has. Make it **config, not code, and per site**:

1. **Move the timetable into `locations.yaml`.** Add an optional per-site block, e.g.
   `schedule: [{days: [mon,tue,wed,thu,fri], start: "09:30", end: "10:20"}, …]` plus `schedule_label: "my
   classes"`. Both committed sites ship `schedule: []`. `config.Site` gains the field; `_CLASS_BLOCKS`
   (`O:L851`) is deleted and `_in_class` (`O:L861`) reads the active site's blocks, so the timezone question
   disappears (times are site-local, not "ET").
2. **Gate every class surface on the payload, never on the slug.** Add the schedule to the served payload
   (`/api/data` and the static `data.json`). Delete `const CLASSES` (`S:L676`) and make
   `classAt`/`classSpans`/`availWin` (`S:L677–679`) and the `classrow` block (`S:L690`) render only when
   `DATA.summary.schedule` is non-empty. Gate on **data**, not `LOC==="south-bend"`.
3. **Fix the label.** `Show my classes (ET, Mon–Fri)` → `Show your schedule` with the site timezone
   abbreviation interpolated from the payload; the strip's `🎓 … ET` (`S:L642`) takes the same abbreviation.
   No hardcoded `ET`.
4. **Let the operator keep the personal build without publishing it.** Because the schedule is now config,
   the owner's own copy is either an untracked `locations.local.yaml` overlay or an env var
   (`SUNSTACK_SCHEDULE`), read by `sunstack ui`/`sunstack run` and **never** written into `docs/data.json`.
   The published page then has no `classrow`, no `.cls` spans, no `free for you:`, no `🎓`, and no class
   branch in `classAt`.
5. **Keep the `#classTgl` semantics but make it honest.** Once (1)–(4) land, `inwindow` shadowing `inclass`
   (`S:L686–687`) must be fixed regardless — render `inclass` as an additional badge on `inwindow` rows, so
   "plan around them" cannot be defeated by the best window.

Acceptance for this resolution: `grep -c 'ET' docs/index.html` for class copy → 0; `docs/index.html` and
`docs/sites/pacific-palisades/index.html` contain no `CLASSES=`, `Show my classes`, `free for you`, or
`🎓`; `uv run sunstack ui` on the operator's machine still produces a schedule-filtered recommendation when
the local overlay is present.

---

## 6. Page length and density

### Measurements

| Viewport | Document height | Screens | Notes |
|---|---|---|---|
| 1440×900 (live) | **3501 px** | **3.89** | Below-the-fold content: 2601 px = **2.89 screens** |
| 390×844 (live) | **4066 px** | **4.82** | No horizontal overflow (`scrollWidth` 390 = viewport) |
| 1440×900 (published `docs/index.html`) | **3449 px** | 3.83 | 52 px shorter: no Min °F / Apply / Refresh |
| 390×844 (published) | **3972 px** | 4.71 | |

**What is above the fold at 1440×900** (fold = y 900): `.top` (28–248, 13 controls), `#hero` (274–414),
`.legend` (418–450), `#skinctx` (456–471), `#strip` (479–831, 14 cells, itself 63 % scrolled), and the first
47 px of `#doses` (853–959).

**What is below the fold at 1440×900:** `#charts` (981–1332), `#sunfigwrap` (1332–1552), the glossary
(1566–1594), **all of `#detail`** (1616–3390), and `Source data` (3416–3441).

**At 390×844** the fold lands at the strip: header 18–443, `#hero` 469–667, `.legend` 671–751, `#strip`
795–1147. Everything from the day strip down is below the fold.

**Section weight** (`#detail` dissected, 1440×900):

| Element | Height |
|---|---|
| `#detail` total | **1774** (50.7 % of the page) |
| `h2` date header | 27 |
| `.bestline` (the day's actual answer) | **36** |
| `.classrow` (contamination) | 22 |
| `h3` "Every hour — Headline UVI first" + `Show all columns` | 35 |
| `p.gloss` (duplicate of `.legend`) | 15 |
| hourly table (12 rows × 20 cols, 12 hidden) | 623 |
| `h3` "Every 30 minutes" | 17 |
| 30-min table (24 rows × 7 cols) | **923** |

Density: 35 native controls + 36 mouse-only clickable rows; 20 table columns of which 12 are hidden behind
`Show all columns` (`body.show-nerd .nerd{display:table-cell}th.nerd,td.nerd{display:none}`, `S:L568`);
3 canvases of which 1 renders; 4 disclosures all closed by default.

### Recommended changes, each justified

**Consolidate**

| Change | Justification |
|---|---|
| Delete `.legend` (`S:L597`) and keep the identical `p.gloss` inside `#detail` (`S:L690`) — or vice-versa, moving the survivor next to the `Overall` column it explains | Two renderings of the same sentence, 1364 px apart (y 418 and y 1782), both measured on the live page. −32 px, one fewer thing to keep in sync |
| Move `details.glossbox` (the 15-headword glossary) from y 1566 to immediately above the hourly table at y 1797 | It currently sits 231 px *before* the first table and 700 px before the columns it defines (`UV∘`, `OM`, `CAMS`, `EPA`, `Clear`, `ΔUV`, …) |
| Merge the 30-min table into the hourly table's disclosure as a toggle | 923 px for 7 columns, 2 of which are the deprecated composite (`Overall`, `Local`) already present in the hourly table. It is the single largest element in `#detail` and outranks the 20-column table it summarises |
| Move `#sunfigwrap` (220 px desktop / **389 px mobile**) inside the hourly disclosure | Its own note says `Guidance is geometry context, not a score` (`S:L602`); it answers no task in §2 directly, and its default frame is chosen by the deprecated composite (`S:L672`) |

**Move into disclosures**

| Change | Justification |
|---|---|
| `#charts`: either show all three panels stacked, or put the whole section behind one disclosure | Currently 2 controls, a 351 px region, and `chartName` = `1 of 3 — …`; 2 of 3 charts are hidden by `chartToggle` (`S:L630`) with no persistent affordance other than a 12 px `‹ ›` row |
| `#advphoto` and `#provenance` already disclose correctly — but `#provenance` is also the only static-page feedback for Surface changes (see below), so it must not stay closed-caption-only | Verified on the published page: selecting `Fresh snow` writes `<span id="surfacecontext">Surface Fresh snow (client-side) · proxy 88.00% · reflected context 0.00 W/m² broadband proxy · …</span>` into the *closed* `#provenance` at y 853 inside `Advanced / Photobiology` — invisible |

**Remove from the user surface**

| Change | Justification |
|---|---|
| `details.debug` "Source data" (`#debugtext`, the entire `summary.json`) → a separate route or a download link | 25 px closed, thousands of px open, at y 3416 (3.6 screens down). It is operator instrumentation; `Export CSV` already covers the data job. `S:L646` sets it unconditionally on every render |
| The `Int` line inside every day cell | `Int ${f0(d.day_absolute_peak_0_100)}` is byte-identical to the later `Abs ${f0(d.day_absolute_peak_0_100)}` in the same cell (`S:L642`); measured `Int 34 … Abs 34 · Loc 93` |
| The `#mintemp` control on the live page **only when it is not the constraint in play** | It is one of 13 header controls, yet the static export deletes it (`X:L63–66`) precisely because it is fixed at 50. Either expose it as the real constraint (label it, show what it excludes) or default-hide it as the static build does |

**Keep above the fold, unchanged:** `.top`, `#hero`, `#strip`. They are the only three regions that answer
T1–T4, and they already fit in one 900 px screen.

**Projected effect (arithmetic from measured heights, 1440×900):** −32 (legend) − 220 (sunfig moved into a
closed disclosure) − 923 (30-min table behind a toggle) − 25 (debug) ≈ **2300 px, 2.6 screens**, with the
answer surface — header, hero, strip, doses — unchanged at 0–959 px.

**Assessed at 390×844:** the mobile page is 4.82 screens with the strip at 352 px and `#detail` at 1908 px.
The same consolidations return ~2.4 screens. Note the mobile layout has **no** mobile-specific restructuring
beyond `@media(max-width:640px){h1{font-size:26px}.hero{font-size:21px}.wrap{padding:18px 12px 50px}}`
(`S:L589`) — every dense desktop table is simply narrower and vertically taller.

---

## 7. Three structural alternatives for the primary answer surface

Three genuinely different structures, not skins. Each is scoped to *the primary answer surface* — the
region that currently holds `#hero` + `.legend` + `#skinctx` + `#strip` (y 274–831, 557 px desktop).

### Alt A — Answer-first single column (narrative)

One dominant answer object for one selected day; everything else is a list row or a disclosure.

```
┌──────────────────────────────────────────────────────────────┐
│ Sunlight hours — South Bend, IN            [skin][surface][▾]│
│                                                              │
│  ┌────────────────────────────────────────────────────────┐  │
│  │  TODAY, WED 7 OCT                                      │  │
│  │  GO OUT  12:30 – 1:00 PM                               │  │
│  │  1,136 E_mel J/m² · UV 4.8 · 73°F · 0 blocked half-hrs │  │
│  │                                                        │  │
│  │  why this window                                       │  │
│  │   · strongest 30 min   1:30–2:00 PM  (in class)        │  │
│  │   · comfortable 30 min 12:30–1:00 PM                   │  │
│  │   · today's ceiling    1,136 J/m² over 30 min          │  │
│  └────────────────────────────────────────────────────────┘  │
│                                                              │
│  7-day outlook                                               │
│   Wed 7  FAIR  12:30–1:00 PM   1,136    fit 100%   conf 46   │
│   Thu 8  FAIR  12:30–1:00 PM   1,051    fit 100%   conf 49   │
│   Fri 9  POOR   2:00–5:30 PM     620    fit  88%   conf 29   │
│   Sat 10 FAIR  12:00–4:00 PM     ?      fit 100%   conf 42   │
│   ⋯ 14 rows, no horizontal scroll                            │
│                                                              │
│  ▸ Sunburn (SED)                                         1   │
│  ▸ Sun position & pose                                   2   │
│  ▸ Hourly / 30-min tables                                3   │
│  ▸ Model, provenance, export                             4   │
└──────────────────────────────────────────────────────────────┘
```

### Alt B — Week × hour matrix (schedule-first)

The answer is a cell's position. Time is the axis; there is no prose headline.

```
┌────────────────────────────────────────────────────────────────────┐
│ South Bend · 7 days · each cell = 30 min, fill = expected dose      │
│            [skin IV][grass][min 50°F][key: dose ▾][Apply]           │
│                                                                     │
│        6a 7a 8a 9a 10a 11a 12p 1p 2p 3p 4p 5p 6p 7p                 │
│  Wed ▏  ·  ·  ·  ░  ░  ▒  ██ ██ ██ ▒  ▒  ░  ·  ·   ← schedule ticks │
│  Thu ▏  ·  ·  ·  ░  ░  ▒  ██ ██ ██ ▒  ▒  ░  ·  ·                  │
│  Fri ▏  ·  ·  ·  ░  ░  ░  ▒  ▒  ██ ██ ██ ▒  ░  ·                  │
│  Sat ▏  ·  ·  ·  ░  ░  ░  ░  ░  ░  ░  ░  ·  ·  ·                  │
│  Sun ▏  ·  ·  ·  ·  ·  ░  ░  ░  ░  ░  ·  ·  ·  ·                  │
│                                                                    │
│  ██ recommended   ▒ usable   ░ marginal   · hard-blocked           │
│  ▞▞ your schedule (toggle)                                         │
│  ┌──────────────────────────────────────────────────────────────┐  │
│  │ Wed 1:30 PM · 1,136 J/m² · UV 4.8 · 73°F · conf 46 · in class│  │
│  └──────────────────────────────────────────────────────────────┘  │
│  (click a cell → inspector; the inspector is the read-out)         │
└────────────────────────────────────────────────────────────────────┘
```

### Alt C — Ranked candidate list (evidence-first)

The answer is row 1 of an ordered list of 15/30/60-minute windows; the ranking key is a visible control.

```
┌───────────────────────────────────────────────────────────────────────────┐
│ Wed 7 Oct · best usable 30 min today: 12:30–1:00 PM (1,136 E_mel J/m²)      │
│ Ranked by  [max expected 30-min delayed-pigmentation dose ▾]              │
│ Filters   [comfort ≥ any ▾] [hide my schedule ☑] [min 50°F] [surface ▾]  │
├───────────────────────────────────────────────────────────────────────────┤
│ #   window               dose      UV  feels  conf  status                │
│ 1   Wed 12:30–1:00 PM    1,136     4.8  72°F   46   ✓ recommended         │
│ 2   Wed  1:30–2:00 PM    1,136     4.8  73°F   46   ✗ in class            │
│ 3   Thu 12:30–1:00 PM    1,051     4.5  59°F   49   ✓ recommended         │
│ 4   Wed 12:00–12:30 PM     980     4.6  72°F   45   ✗ in class            │
│ 5   Fri  2:00–5:30 PM      620     3.3  56°F   29   ✓ usable              │
│ 6   Sat 12:00–4:00 PM      —       —    —      —    ✗ all blocked         │
│ ⋯  next 72 h, one row per candidate window                                │
│ [15 min] [30 min] [60 min]                                                │
├───────────────────────────────────────────────────────────────────────────┤
│ ▸ why is #2 ranked but not recommended?                                   │
│ ▸ sunburn (SED) and dose detail                                           │
│ ▸ sun position & pose                                                     │
│ ▸ model, provenance, versions, export CSV/ICS                             │
└───────────────────────────────────────────────────────────────────────────┘
```

### Comparison on the six criteria

| Criterion | **A — Answer-first single column** | **B — Week × hour matrix** | **C — Ranked candidate list** |
|---|---|---|---|
| **Clarity** | **Best.** One window, one sentence, one reason block. The only structure that can state a single ranking key without competing answers. | Medium. Powerful for pattern-seeing, but with no prose the user must infer that a filled cell *is* the recommendation, and must infer the key from a legend. Colour-and-fill encoding raises the "SED is never good" confusion the current heading already fights (`S:L601`). | High. The ranking key is the section header, and every alternative window carries its own disqualifier (`✗ in class`, `✗ all blocked`). Least capable of being misread as three answers, because there is literally one ordered list. |
| **Task efficiency** | T1 **0**, T2 **0**, T3 **0**, T4 **1**. Best raw speed. | T1 **0** (today's row is visible), T2 **1** (must click the cell), T3 **0** (whole week on one screen), T4 **1**. Best at T3/T4 but T2 becomes a click. | T1 **0**, T2 **0** (row 1), T3 **0**, T4 **0** (future days interleaved by window, not by day). Best across all four because ranking is orthogonal to date — a Thu window can outrank a Wed one and appear first. |
| **Implementation cost** | **Lowest.** Deletes `.legend`, `#skinctx`, the 14-cell strip template (`S:L642`), and the hero's two-clause sentence (`S:L644`); adds one summary object rendered from `strongest/best_usable/best_comfortable` — all three already in the payload (`O:L1169–1177`). No new data. | **Highest.** Needs a new grid renderer, a new fill scale, a cell-inspector state, and a new interaction model (click-a-cell, not click-a-day). The current data is per-row and would need bucketing into 7 × 28 cells at both 30-min and hourly resolution, plus a text fallback for the whole grid. | **Low.** Reuses `#detail`'s table machinery (`tablewrap`, `tbody` row builder `S:L686`) and the existing per-row fields; the list is a projection over `DATA.half_hour` sorted by `best_*` dose, which the payload already carries per row plus per day. One new sort/filter state. |
| **Discoverability** | High. Everything important is in the first 400 px; the `7-day outlook` rows are plain text, no horizontal scroll, no hidden columns. | Medium. A first-time visitor may not read a heat grid as "when to go", and the inspector is discoverable only after a cell click. | High. Row 1 is the answer; the sort control is labelled; the disqualifier column teaches the model. Downside: 72 h of rows pushes "today" below "tomorrow" for a user who only wants today — mitigated by the summary line above the list. |
| **Scalability** | Medium. Scales well in *rows per day* (add Sat/Sun, add a third site) but has one answer slot; adding 15/60-min variants means more cards. Handles two sites naturally (one page each, as today). | Medium–low. Adding 15/60-min windows changes the grid resolution and doubles/quadruples cells; adding a site changes the page. DST transitions produce duplicate/missing cells; timezone is the x-axis, so it must be labelled explicitly per site (the Pacific Palisades case already proves this is a live risk, §5). | **Best.** Widening to 15/60-min is a control, not a redesign; extending to 7 days is a scroll; adding a site is a filter. Mirrors contract §2.5's "Repeat for 15/60 minutes where useful" (`C:L189`) without restructuring. |
| **Accessibility** | **Best.** A heading, a paragraph and a two-column list; the only interactive elements are the day rows (native `<button>`) and `<details>` disclosures. No colour-only encoding. | **Worst.** The primary information is a filled grid: ~196 non-text cells relying on hue/opacity, with no natural screen-reader reading order. Requires a parallel table plus per-cell accessible names — substantial extra work — and fails at 390 px without a redesign (7 columns × 14 h cannot fit; the mobile page is already 4.82 screens). | Good. Text table with real `<th>`s; the disqualifier is a text column, not a colour. The 36 mouse-only clickable rows the current page has (§1) must become real controls, which this structure forces anyway. |

### Choice: **Alt C — Ranked candidate list**

Justification, tied to the defects found:

1. **It resolves §4 structurally instead of by relabelling.** The failure is not that three rankings exist —
   the contract mandates three (`C:L183–191`). The failure is that they are presented as three *headlines*.
   Alt C makes one of them the sort key and the other two *row attributes*: `strongest` becomes "row 2, in
   class", `comfortable` becomes a filter, `overall_tan_opportunity_0_100` becomes one more column. A
   headline cannot do that; a list can.
2. **It makes the schedule visible rather than hidden.** In Alt C, `✗ in class` is a cell in the status
   column on the same row as the contender. Today the app hides exactly that fact — measured:
   `inwindow` shadows `inclass` (`S:L686–687`), and the hero promotes a window the class filter excludes.
   Alt A can also show the line, but only for the one window it chose; the list shows it for every candidate.
3. **It is the cheapest of the three against real data.** `DATA.half_hour` already carries one row per
   30 minutes with `predicted_uva_wm2`, `uvi_consensus`, `overall_tan_opportunity_0_100`,
   `local_tan_score_0_100`, `subhour_source`, and the day summary already carries `strongest_30m_*` /
   `best_usable_30m_*` / `best_comfortable_usable_30m_*` (`O:L1169–1177`). This is a sort plus a
   row template — the row template being `S:L686`'s, already written.
4. **It removes work rather than adding it.** Adopting Alt C retires the 14-cell strip template
   (`S:L642`, 2189 chars of JS), the `Int`/`Abs` duplication, the second legend, and the day-cell horizontal
   scroll (1786 px content in a 1076 px box). Combined with §6's consolidations the answer surface shrinks
   from 557 px + 1774 px of detail to roughly one screen.
5. **Accessibility is a constraint, not a nice-to-have.** The measured `rows: 36, focusable: 0, role: 0`
   (§1) means the existing table rows are already mouse-only; Alt B would extend that failure mode to the
   primary surface, Alt C forces it to be fixed on the rows that matter most.
6. **It scales the way the contract wants.** §2.5 asks for 15/60-minute repetition and §16.3 defines
   candidate windows as explicit intervals (`C:L1082–1089`) — literally a list of candidates ranked by dose.
   Alt C is that structure rendered.

Cost accepted: the user must scan a list rather than read one sentence. Mitigated by the mandatory summary
line above the list (row 1 restated in prose with its ranking key), which also becomes the only place the
product states *one* answer — the thing the current hero fails to do.

**Sequencing.** Alt C depends on §4's resolution landing first (one ranking key, `best_usable_30m` made
schedule-aware) and on §5's resolution (schedule from config, not constants); otherwise the list would
faithfully present the same contradictions in a new shape.

---

## Appendix — raw measurements

```
LIVE  http://127.0.0.1:8903/   1440×900   scrollHeight 3501   screens 3.89   interactive 35
LIVE                          390×844    scrollHeight 4066   screens 4.82   scrollWidth 390
PUB   docs/index.html         1440×900   scrollHeight 3449
PUB   docs/index.html         390×844    scrollHeight 3972

#strip        scrollWidth 1786  clientWidth 1076   → 8.4/14 cells visible at 1440
#charts       chartScore=inline chartDose=none chartSed=none   chartName "1 of 3 — TanScore 0–100 (instantaneous intensity)"
#detail       36 tr[data-time]   focusable 0   role 0
#detail.hourly-table 12 rows × 20 cols, 12 cols .nerd, 156 .nerd cells hidden
#detail.half-table   24 rows ×  7 cols
details       mmd(closed) advphoto(closed) glossbox(closed) debug(closed)

#default state first paint
#hero    "Wednesday, October 7 Strongest 30 min 1:30 PM – 2 PM — 1136.1 E_mel J/m²; best usable 30 min
          1:30 PM – 2 PM — 1136.1 E_mel J/m² (confidence 46). Local 95 · Overall 44 · Abs 35.
          Surface Unknown; backend tierC-broadband-proxy-v2 (tier C)."
#detail  "Tuesday, October 6 · Overall 43 Local 93 · Abs 34 opportunity: FAIR"
.bestline"Good window (longest near-peak) 12 PM – 4 PM · best hour 1:30 PM (43) · peak 30-min dose
          1111 J/m² · peak UV 4.8 · 72.2°F · 3 blocked half-hours. … free for you: 12:30 PM–4 PM"

#2026-10-07 daily row (live API)
  best_window           2026-10-07T12:00 → 16:00
  best_available_window 2026-10-07T12:30 → 13:00
  best_hour_start       2026-10-07T13:30
  strongest_30m         2026-10-07T13:30 → 14:00   1136.1
  best_usable_30m       2026-10-07T13:30 → 14:00   1136.1
  best_comfortable_…    2026-10-07T13:30 → 14:00   1136.1   (rendered nowhere)
  best_30m_start        2026-10-07T14:00                    (legacy Overall argmax)
  ICS DTSTART/DTEND     20261007T173000Z → 1730+30      SUMMARY "Best usable sun 1:30 PM-2:00 PM"
```