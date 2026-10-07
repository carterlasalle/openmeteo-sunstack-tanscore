# Visual & interaction system audit — SunStack client

Target: the design system actually implemented in `src/sunstack/serving.py` (single `HTML = r"""…"""`
constant, `src/sunstack/serving.py:519-698`) and the rendered result at `http://127.0.0.1:8901/`.

## Method & evidence base

* Client source of record: `src/sunstack/serving.py`. `HTML` occupies lines 519–698:
  CSS `L523-589`, document body `L590-604`, script `L604-698`. `src/sunstack/ui.py:72` imports this
  constant (`HTML = _serving_template_mod.HTML`) and `ui.py:82-84` returns it verbatim for `GET /`.
* Served-HTML identity check: `GET /` returned 52 709 bytes; byte-identical to the `HTML` constant in
  `serving.py` (verified by direct comparison — no server drift, so source line references and DOM
  measurements describe the same code).
* Live measurements: headless Chromium, viewport 1440×900, DPR 1, page fully rendered
  (14 day cells, 2 tables, 12 hourly rows + 24 half-hour rows for the selected day 2026-10-06).
* Every number below is a measured computed style, `getBoundingClientRect()` value, or a source
  line reference. Items not reproduced live are marked **HYPOTHESIS**.

---

## 1. Token extraction

### 1.1 `:root` custom properties (`src/sunstack/serving.py:524`)

15 tokens, all colour values, all declared on one line:

| Token | Value | Referenced from CSS | Referenced from JS |
|---|---|---|---|
| `--paper` | `#eef1ee` | 1 | 0 |
| `--surface` | `#ffffff` | 6 | 0 |
| `--surface2` | `#f7f9f7` | 1 | 0 |
| `--head` | `#e4e9e4` | 2 | 0 |
| `--headtxt` | `#4e5754` | 1 | 0 |
| `--track` | `#dfe4df` | 1 | 0 |
| `--ink` | `#151a18` | 6 | 0 |
| `--muted` | `#5b6461` | 13 | 0 |
| `--line` | `#d2d8d3` | 7 | 0 |
| `--sun` | `#a85500` | 9 | 0 |
| `--sunwash` | `#fdeed0` | 3 | 0 |
| `--ok` | `#2c7a45` | 0 | 1 |
| `--mid` | `#8a6200` | 0 | 1 |
| `--low` | `#b3450f` | 0 | 1 |
| `--poor` | `#646c69` | 0 | 1 |

* 50 `var()` call sites in CSS; 11 of 15 tokens used there. The remaining 4 (`--ok`, `--mid`, `--low`,
  `--poor`) are referenced **only** from JavaScript inline styles — all four inside `scoreColor`,
  `src/sunstack/serving.py:612`: `scoreColor=v=>+v>=65?'var(--ok)':+v>=40?'var(--mid)':+v>=20?'var(--low)':'var(--poor)'`.
* No token is unreferenced, but no token is referenced from both surfaces: the palette is split into
  a CSS half (11) and a JS-only half (4).
* `--paper` has exactly one consumer (`body{background:var(--paper)}`, L525).

### 1.2 Colour literal accounting

Total colour literals in the client source: **54 occurrences / 28 distinct spellings** (15 of the
occurrences are the `:root` definitions themselves). Distinct colour *values* in use: **28** = 15 token
values + 13 values that exist only as literals.

**Literals outside `:root`: 39 occurrences** (8 in CSS, 31 in JS).

**A. CSS literals that bypass the token system (8 occurrences, 6 values):**

| Value | Line | Usage site |
|---|---|---|
| `#fff` | L535 | `button.primary{… color:#fff}` — same value as `--surface`, different spelling |
| `#f7dfe0` | L564 | `.error{background:#f7dfe0}` |
| `#7c2327` | L564 | `.error{color:#7c2327}` |
| `#eef0e4` | L564 | `.info{background:#eef0e4}` |
| `#4c5540` | L564 | `.info{color:#4c5540}` |
| `#ece4f4` | L569 | `tr.inclass td{background:#ece4f4}` |
| `#5b4a8a` | L573 | `.daycell .cls{color:#5b4a8a}` |
| `#5b4a8a` | L575 | `.note.cls{color:#5b4a8a}` |

**B. JavaScript/SVG literals that bypass the token system (31 occurrences, 16 values):**

| Value | Occurrences | Lines | Usage sites |
|---|---|---|---|
| `#c0392b` | 7 | L642 ×5, L686 ×2 | wet day-cell border; `<b>` rain %; wet `.pk` colour; `windy` `<b>`; wet `.bar i` background; hourly `Rain` cell; hourly `Wind` cell |
| `#5b6461` | 6 | L628 ×2, L671 ×4 | canvas tick/gridline labels; SVG text `ground`, `sun below horizon`, `no direct-sun posture`, `face … torso …` — re-spelling of `--muted` |
| `#a85500` | 3 | L628, L671 ×2 | `chartScore` series stroke; sun-disc stroke; reflected-ray dash — re-spelling of `--sun` |
| `#2c7a45` | 2 | L611, L628 | `uvColor` (<3 UVI dot); `chartDose` series line — re-spelling of `--ok` |
| `#c3cac5` | 2 | L611, L671 | "unknown UVI" dot fill **and** the sun-figure ground line — one grey, two jobs; no token |
| `#d2d8d3` | 1 | L628 | canvas gridline stroke — re-spelling of `--line` |
| `#f7f9f7` | 1 | L669 | `stickFigure` head fill — re-spelling of `--surface2` |
| `#151a18` | 1 | L671 | SVG `color` for the figure group — re-spelling of `--ink` |
| `#646c69` | 1 | L671 | SVG `color` of the guide figure — re-spelling of `--poor` |
| `#8a6200`, `#b3450f` | 1 each | L611 | `uvColor` bands 3–5 and 6–7 — re-spellings of `--mid` / `--low` |
| `#a12a1f` | 1 | L611 | `uvColor` band 8–10 — **no token**; visually adjacent to `--low #b3450f` |
| `#6a3fbf` | 1 | L611 | `uvColor` band ≥11 — **no token** |
| `#7b4bd6` | 1 | L628 | `chartSed` series line — **no token**; a second purple |
| `#e8a100` | 1 | L671 | sun-disc fill — **no token**; a second amber |
| `rgba(178,94,0,0.10)` | 1 | L628 | chart best-window band fill — **no token**; neither `--sun` nor `--sunwash` |

**C. Values with no token at all (13):** `#c0392b`, `#5b4a8a`, `#c3cac5`, `#f7dfe0`, `#7c2327`,
`#eef0e4`, `#4c5540`, `#ece4f4`, `#a12a1f`, `#6a3fbf`, `#7b4bd6`, `#e8a100`, `rgba(178,94,0,0.10)`.

**D. Token values re-spelled as literals (9 values, 17 JS + 1 CSS occurrences):** `--muted`×6,
`--sun`×3, `--ok`×2, `--surface2`, `--ink`, `--line`, `--mid`, `--low`, `--poor`.

---

## 2. Type scale

### 2.1 `font-size` — 10 distinct values, 1076 elements

| Size | Elements | Declared at | Owners (measured) |
|---|---|---|---|
| 34px | 1 | L529 | `h1` |
| 26px | 2 | L536 | `.hero` + its `<b>` |
| 24px | 16 | L543, L549 | `.daycell .pk` ×14, `.daydetail h2` ×2 |
| 16px | 71 | — | **never declared**; inherited UA default (`body`, `.wrap`, `.top`, `.daycell`, `.bar`, `div`) |
| 15px | 2 | L551 | `.bestline` + its `<b>` — the only 15px text in the app |
| 14px | 20 | L541, L550, L553, L563 | `.daycell .dow`, `h2.sec`, `h3`, `.status`, `#nerdBtn` |
| 13px | 655 | L530, L531, L532, L538, L555, L583, L585 | `.sub`, `.controls`, all form controls, `.legend`, `table` (⇒ `th`/`td`), `.sunfig .cap`, `summary` |
| 12px | 299 | L542, L544, L562, L565, L576, L577, L578, L579 | `.note`, `.daycell .dt`, `.daycell .uv`, `.daycell .win`, `.daycell .txt`, `.chartnav`, `details.debug`, `.gloss`, `#skinctx` |
| 11px | 10 | L573, L578 | `.daycell .cls` ×10 (one per class day), `.daycell .txt` (only on wet days — not present in this render) |
| 10px | 2 | L671 | SVG `<text>` in `#sunfig`: `ground`, `face S · torso ~47°` |

Plus a non-DOM font size: the chart axis labels use `x.font='9px sans-serif'` (`L628`).

**Verdict: not a coherent ramp.** Seven of the ten sizes sit in a 1px progression (10, 11, 12, 13, 14,
15, 16) with no ratio; the base size (16px) is the one value that is never declared. There is no
modular step between 16 and 24, and the two largest sizes (26, 34) are 34px = `h1`, 26px = `.hero`
only. `.daycell` uses 6 different sizes inside a 118px-wide card (14/12/12/11/24/12).

### 2.2 `font-weight` — 4 computed values

| Weight | Elements | Where it comes from |
|---|---|---|
| 400 | 715 | UA default (never declared as a base) |
| 600 | 211 | L529 `h1`, L533 `.controls a.btn`, L533 `button`, L549 `h2`, L550 `h2.sec`, L553 `h3`, L558 `thead th`, + inherited by day-cell children |
| 700 | 151 | L537 `.hero b`, L541 `.daycell .dow`, L560 `tr.inwindow td:first-child`, L570 `tr.inclass td:first-child`, L573 `.daycell .cls`, L577 `.daycell .win`, blank `<b>` in table cells (UA `bolder`) |
| 900 | 1 | `<b>windy</b>` inside `.daycell` — UA `bolder` resolved against the inherited 600 from `button` (L533) |

*The same `<b>` element therefore renders at 700 in table cells and 900 in day cells for the same
markup pattern (L642 vs L686).* No declaration produces 900 intentionally.

### 2.3 `line-height`

Declared exactly **once** in the whole client: `.hero{line-height:1.35}` (`L536`) ⇒ measured 35.1px.
Every other measured element (1076 of 1078) computes `normal`. Line rhythm is therefore fully implicit
and changes with font size — e.g. `.note` 12px ≈ 14.4px, `td` 13px ≈ 15.6px.

### 2.4 `font-family`

Three declarations: `body` system stack `-apple-system,BlinkMacSystemFont,"Segoe UI",Helvetica,Arial,sans-serif`
(L525); Georgia serif on `h1` (L529), `.hero` (L536), `.daycell .pk` (L543), `.daydetail h2` (L549);
`'9px sans-serif'` in canvas (L628), plus `h2.sec{font-family:inherit}` (L550) which is the single
override back to the system stack.

---

## 3. Spacing / geometry

### 3.1 `border-radius` — 6 distinct values

| Radius | Elements | Declared at |
|---|---|---|
| 0 | 975 | default (nothing sets it) |
| 3px | 28 | L545/L546 `.daycell .bar`, `.daycell .bar i` (bar is 5px tall) |
| 8px | 21 | L532 form controls, L566 `details.debug pre`, L582 `.sunfig svg`, L601 inline `canvas` style |
| **9px** | **1** | L563 `.status` — single outlier, no other element in the app uses 9px |
| 12px | 17 | L540 `.daycell`, L554 `.tablewrap`, L581 `.sunfig` |
| 50% | 36 | L561 `.uvdot` |

### 3.2 `padding` — 9 distinct values (source-declared)

| Value | Declared at | Applied to |
|---|---|---|
| `28px 22px 60px` | L527 | `.wrap` → `18px 12px 50px` under the ≤640px media query (L589) |
| `0 0 16px` | L528 | `.top` |
| `8px 10px` | L532, L556 | forms controls (451 elements) + every `th`/`td` |
| `10px 12px` | L540, L563 | `.daycell`, `.status` |
| `12px` | L566 | `#debugtext` |
| `14px 2px` | L539 | `.strip` |
| `14px 16px` | L581 | `.sunfig` |
| `5px 0` | L585 | `details>summary` |
| `0` | — | default |

Two families are visible — **8px 10px** (controls and table cells) and **10–16px** (cards) — but the
card family has four different values (10/12, 12, 14/2, 14/16, 28/22/60) with no shared step.

### 3.3 `margin` — 12 distinct values; vertical steps are 2, 4, 6, 8, 12, 14, 22, 26

| Value | Declared at |
|---|---|
| `0 0 2px` | L549 `.daydetail h2` |
| `4px 0 0` / `0 0 4px` | L530 `.sub` / L536 `.hero` |
| `6px 0 0` / `0 0 6px` | L579 `.gloss`, L576 `.chartnav`, L538 `.legend` |
| `8px 0 4px` / `8px 0 0` | L539 `.strip` / L574 `.classrow`, L545 `.daycell .bar`, L588 `.sunfig select`, L601 inline canvas |
| `12px 0` | L563 `.status`, L566 `details.debug pre` |
| `0 0 14px` | L551 `.bestline`, L581 `.sunfig` |
| `22px 0 0` | L548 `.daydetail` |
| `22px 0 8px` | L550 `h2.sec`, L553 `h3` |
| `26px 0 4px` / `26px 0 0` | L536 `.hero` / L565 `details.debug` |

**Verdict: not systematic.** Eight vertical steps with no 4/8 scale (12 and 22/26 are off-grid), and
two components that should share a rhythm (`h2.sec` and `h3`) share the value `22px 0 8px` while
section containers use `22px 0 0`.

---

## 4. Consistency defects

### D1 — Same quantity, two headers: `UV∘` vs `UV`  (CONFIRMED)

* Hourly table header, `src/sunstack/serving.py:690`: `<th title="Headline UVI (bias-corrected inverse-error fusion) — drives the SED channel">UV∘</th>` → rendered text **`UV∘`**.
* 30-minute table header, `src/sunstack/serving.py:691`: `<th>UV</th>` → rendered text **`UV`**, and no `title` at all.
* Both cells render the same expression: `uvColor(x.uvi_consensus ?? x.uv_index)` + `f1(x.uvi_consensus ?? x.uv_index)` (L686, L687). Column widths 81px vs 115px.
* **Resolution:** use `UV∘` with the L690 `title` in both tables.

### D2 — Hourly `Overall` cell duplicates the hidden `Local` column (CONFIRMED)

* Hourly row, L686: `<td><b>${f0(x.overall_tan_opportunity_0_100)}</b><br><span class="note">Loc ${f0(x.local_tan_score_0_100)}</span></td>` → rendered **`9` / `Loc 40`** (two lines).
* The same row also emits `<td class="nerd">${f0(x.local_tan_score_0_100)}</td>` and the header emits `<th class="nerd" …>Local</th>` (L690), hidden by `th.nerd,td.nerd{display:none}` (L568).
* Cost measured: **every** hourly row is 49px tall (12/12 rows); the equivalent single-line row in the 30-min table is 33px. The `<br>` = 16px × 12 rows = **192px**, 31% of the hourly table (621px table inside a 623px `.tablewrap`), spent duplicating a hidden column.
* **Resolution:** drop `<br><span class="note">Loc N</span>`, make `Overall` and `Local` two always-visible columns in both tables.

### D3 — Day cell shows the same value twice under two names (CONFIRMED)

* L642 emits `<div class="uv" title="Intensity: absolute melanogenic strength (provisional global scale)">Int ${f0(d.day_absolute_peak_0_100)}</div>` **and later in the same cell** `<div class="uv">Abs ${f0(d.day_absolute_peak_0_100)} · Loc ${f0(d.day_local_peak_0_100)}</div>`.
* Rendered day cell (2026-10-06): `43 | Int 34 | Fit 88% | Conf 50 | UV 4.8 · 43.1–72.2° | Feels 39.2–66.8° | Gust 18 | Abs 34 · Loc 93`.
* `Int 34` and `Abs 34` are the same field; `Abs` is also a table column header (L690).
* **Resolution:** delete the `Int` line.

### D4 — Day cell `Abs · Loc` vs table columns `Overall`/`Abs`/`Local` (CONFIRMED)

* Day cell (L642): the big unlabelled `.pk` number = `day_overall_peak_0_100` (43), then `Int`/`Abs`/`Loc` lines.
* Table headers (L690): three separate columns `Overall`, `Abs`, `Local`.
* Hero (L644): `Local 95 · Overall 44 · Abs 35` — order `Local, Overall, Abs`.
* Day heading (L688): `<span style="color:${scoreColor(...)}">· Overall 43</span> <span class="note">Local 93 · Abs 34</span>` — order `Overall, Local, Abs`.
* Four renderings of one triple, three orders, two abbreviations (`Loc`/`Local`), and the day cell's primary number has no label at all.
* **Resolution:** one vocabulary and one order everywhere — `Overall`, `Abs`, `Local`.

### D5 — `Note` column mixes block reason, sun bearing and class (CONFIRMED)

* Hourly (L686): `const note=[disagreeNote(x),cl].filter(Boolean).join(' · ')` and then `${esc(note)}${sun}` where `sun = ' ☀︎ N° <compass>'` — up to three semantic types in one cell. Rendered: `temperature < 50F ☀︎ 2° E`, `in class ☀︎ 23° ESE`, `UVI sources disagree ☀︎ 32° SW`, and a bare `☀︎ 42° S` when only geometry applies.
* 30-minute (L687): `${esc([disagreeNote(x),cl].filter(Boolean).join(' · '))}` — no bearing. Rendered: `temperature < 50F`, `in class`, `UVI sources disagree`.
* Related: the header `Note` also carries the class marker, and `.note` (12px/`--muted`) is the same class used for subcaptions inside other cells.
* **Resolution:** a dedicated `Sun` column for the bearing (in both tables); `Note` keeps block reason + class only.

### D6 — Source-spread rendered two different ways (CONFIRMED)

* Hourly: a dedicated column `ΔUV` (L690, `title="Max UVI spread across sources — disagree flag at ≥1.0, strong at ≥2.0"`) rendered as `(spread).toFixed(2)` → rendered `1.3`.
* 30-minute: `uviRange(x)` (L680) emits `<b>${max}</b><br><span class="note">${min}–${max}</span>` inside the UV cell → rendered `4.2` / `3.0–4.2`, with title "Source range 4.2 vs 3.0 across UVI sources…".
* Same concept, different columns, different formats (spread vs min–max), different titles, and only the 30-min form costs a second line (6 of 24 rows = 49px).
* **Resolution:** one representation — keep the `ΔUV` column in both, drop `uviRange`.

### D7 — 30-minute `Source` column leaks a raw enum (CONFIRMED)

* L687: `${esc(x.subhour_source==='native_HRRR_radiation_weather_plus_interpolated_UV'?'30-min · HRRR wx/rad + interp UV':(x.subhour_source||'').slice(0,24)||'hourly split')}`.
* Rendered for every one of the 24 rows: **`interpolated_hourly`** — the human label `'hourly split'` only appears when the field is empty, and the non-HRRR branch truncates to 24 chars with no mapping.
* **Resolution:** map enum → label (`interpolated_hourly` ⇒ `hourly split`), and render `HRRR wx/rad + interp UV` without the redundant `30-min ·` prefix (the column already sits under "Every 30 minutes").

### D8 — Authored glossary text is replaced at runtime by different copy (CONFIRMED)

* Authored (`L690`): `UV∘ Headline UVI (…) · ΔUV source-range spread flags disagreement · Ranking is maximum expected 30-minute delayed-pigmentation dose (fixed-duration-dose-v2); Overall is a LEGACY composite (deprecated product heuristic) · <b>All columns stay in the page</b> — hidden ones are one tap away and always in Export CSV.`
* Runtime override (`L696`): `renderDay=function(){renderDayBase();const gloss=document.querySelector('#detail .gloss');if(gloss)gloss.textContent='Ranking is maximum expected 30-minute delayed-pigmentation dose (fixed-duration-dose-v2). Overall is a LEGACY composite (deprecated product heuristic).';};`
* Measured live: rendered text is the 151-char override — the UV∘/ΔUV clause, the `Export CSV` sentence and the `<b>` emphasis in the authored version never reach the screen. `.gloss` measured height 15px (one line) vs the authored 3-clause paragraph.
* The same two sentences also appear in `.legend` (`L597`) with a `;` where the override uses `.`.
* **Resolution:** delete the L696 override and keep one paragraph; if the legend is meant to differ, give it different content rather than a copy of the gloss.

### D9 — `h2.sec` and `h3` are visually identical (CONFIRMED)

* `.daydetail h2.sec` (`L550`): `font-family:inherit; font-size:14px; font-weight:600; color:var(--muted); margin:22px 0 8px`.
* `h3` (`L553`): `font-size:14px; margin:22px 0 8px; color:var(--muted); font-weight:600`.
* Measured: both `14px / 600 / rgb(91,100,97)` with margin `22px 0 8px`. Rendered section headings (`Doses —…`, `Day charts…`) are indistinguishable from sub-headings (`Every hour —…`, `Every 30 minutes`).
* **Resolution:** give `h2.sec` a distinct step (e.g. 16px/700 or `--ink` colour) and keep `h3` at 14px/600.

### D10 — Interactive-looking `Show all columns` button inflates its heading (CONFIRMED)

* L690: `<h3>Every hour — Headline UVI first <button id="nerdBtn" …>Show all columns</button></h3>`.
* Measured: this `h3` is 35px tall; the sibling `h3` (`Every 30 minutes`, `L691`) is 17px — the inline button's `8px 10px` padding (L532) sets the line box.
* **Resolution:** move the toggle out of the heading, next to the table (the `.chartnav` pattern at L601 already does this).

### D11 — `<b>` renders at two different weights (CONFIRMED)

* Day cell `<b style="color:#c0392b">windy</b>` (L642) computes **font-weight 900**, because the inherited weight is `button`'s 600 (L533) and UA `bolder` rounds up.
* Table `<b>${f0(…)}</b>` (L686) computes **font-weight 700**, because `td` is 400.
* **Resolution:** declare `b,strong{font-weight:700}` explicitly.

### D12 — Empty-state colspan disagrees with the column count (CONFIRMED in source)

* L690 renders `<td colspan="19">No hourly rows for this day.</td>`; the same table's header emits **20** `<th>` (measured count = 20: Time, UV∘, OM, CAMS, EPA, Clear, ΔUV, UVA, UVB, Temp, Wind, Cloud, Rain, DNI, Overall, Abs, Local, Atm, Conf, Note).
* The 30-minute table's `colspan="7"` (L691) matches its 7 columns.
* **HYPOTHESIS** that it renders misaligned — the branch was not reproduced (the selected day always has rows).
* **Resolution:** `colspan="20"`.

### D13 — Best-window is signalled four ways; class tint can be masked (CONFIRMED)

* In-table: `★ ` prefix (L686/L687), `tr.inwindow td{background:var(--sunwash)}` (L559), `tr.inwindow td:first-child{font-weight:700}` (L560) — three treatments for one condition.
* Day cell: a `.win` chip in `--sun`/700 (L577) — same condition, different visual language (no `★`, no tint).
* Rows are mutually exclusive: `${w?' class="inwindow"':(cl?' class="inclass"':'')}` (L686, L687). Measured 30-min row classes: `12:00–15:30 = inwindow`, `09:30, 10:00, 11:00, 11:30 = inclass` (no overlap in this run). Source-derived consequence, not reproduced: a class block inside the good window would be rendered as `inwindow` only and lose its purple.
* **Resolution:** keep the amber background for the window and mark class rows with an orthogonal channel (left border/inset rule) so the two states can co-exist.

### D14 — Purple means "in class" and "free for you" (CONFIRMED)

* `.note.cls{color:#5b4a8a}` (L575) is applied by `L689` to both `<span class="note cls">all of it in class</span>` and `<span class="note cls">free for you: ${…}</span>`.
* Rendered live: `<span class="note cls">free for you: 12:30 PM–4 PM</span>` — measured colour `rgb(91,74,138)`.
* The same purple family also marks class rows (`.inclass` background `#ece4f4`, L569) and class chips (`.daycell .cls`, L573) — those two agree; the `free for you` usage is the contradiction.
* **Resolution:** reserve purple for class; render the availability span with `.note` (muted) or a success token.

### D15 — No `:disabled` treatment while the primary button is disabled for minutes (CONFIRMED)

* `refreshData()` (`L622`) sets `_b.disabled = true` for the duration of `POST /api/refresh` (the copy itself says "takes minutes"), resetting in both the success and catch paths.
* The stylesheet contains **no** `:disabled` / `[disabled]` rule anywhere in L523-589; `button{cursor:pointer}` (L533) and `button.primary{background:var(--sun);color:#fff}` (L535) keep applying. Measured computed style of the button at rest: `cursor:pointer`, `background:rgb(168,85,0)`, `border:1px solid rgb(168,85,0)`.
* A disabled control therefore looks and points exactly like an enabled one; the only feedback is the `.status` message above the hero.
* **Resolution:** add `button:disabled{opacity:.55;cursor:not-allowed}` and keep the status line.

### D16 — Clickable rows have no cursor or hover affordance (CONFIRMED)

* Copy asserts interactivity: `.sunfig .cap` "Click any table row to inspect that time" (L602). The handler exists (`L692`, `#detail tr[data-time]` → `FIG.sel` → `renderSunFig`) and works: clicking row `2026-10-06T08:00` changed `#suncap` from `2 PM — sun 43° up (S) …` to `8 AM — sun low 2° (E) …` (measured).
* But `tr`/`td` compute `cursor:auto` and hovering a row leaves `td` background unchanged (`rgb(236,228,244)` → `rgb(236,228,244)`).
* **Resolution:** `#detail tbody tr[data-time]{cursor:pointer}` plus a hover tint.

### D17 — Same cell type, two `font-size` treatments for the note text (CONFIRMED)

* Hourly `Note` cell: `<td class="note">` (L686) → 12px; the *same* row's `Rain`/`Cloud`/`DNI` cells are `<td class="nerd">` → 13px; and the `Conf` cell is `<td>` 13px while the `Overall` cell's subcaption is `.note` 12px.
* In the 30-min table, `Source` and `Note` are `.note` (12px) while every numeric column is 13px (L687).
* Measured `td.note` font-size = 12px, `td` = 13px in the same row.
* **Resolution:** keep the numeric/annotation split but apply it consistently (both tables, both text columns).

---

## 5. Component inventory

States are those with **explicit styling** (source) plus what was **measured** live. "No rule" = the
state has no CSS rule in L523-589.

| Component | Base | Hover | Focus | Selected / checked | Disabled | Other missing states |
|---|---|---|---|---|---|---|
| `button` (Apply, Export CSV, ‹, ›, Show all columns) | ✔ L532/533 | ✔ L534 `border-color:var(--sun)` | ✔ L567 | ✖ | **no rule** | active/pressed, `aria-pressed` styling (`#nerdBtn` toggles `aria-pressed` but styles nothing) |
| `button.primary` (Refresh forecast) | ✔ L535 amber bg + `#fff` | rule matches but border is already `--sun` ⇒ **measured no visible change** (`rgb(168,85,0)` → `rgb(168,85,0)`) | ✔ | — | **no rule** (D15) | busy/progress, error |
| `.daycell` (14 buttons, `role="option"`) | ✔ L540 | ✔ via `button:hover` — only when unselected | ✔ | ✔ L547 (`2px solid var(--sun)` + `--sunwash`) | **no rule** | pressed; selected cells have no hover delta (border already `--sun`) |
| `a.btn` (Calendar) | ✔ L533 | **no rule** | ✔ L567 | visited **not distinguished** (`color:var(--ink)` at L533 overrides UA visited) | ✖ | — |
| `select` (#locsel, #skin, #surface, #mmdbasis, #sunsel) | ✔ L532 | **no rule** (measured `rgb(210,216,211)` unchanged) | ✔ | — | **no rule** | `:open`, `option` styling |
| `input[type=number]` (#mintemp, #skintilt, #skinaz, #mmd) | ✔ L532 | **no rule** | ✔ | — | **no rule** | `:invalid` (despite `min`/`max` attributes), `::placeholder` |
| `input[type=checkbox]` (#classTgl) | ✔ L587 (16px, `vertical-align:-3px`) | **no rule** | ✔ (outline, offset 2px, outside the box) | **no rule** — UA default `accent-color`, `--sun` never applied | **no rule** | indeterminate |
| `details/summary` (mmd, advphoto, glossbox, source-data) | ✔ L585 | **no rule** | ✔ L586 | **no rule** — open and closed render identically (no `::marker` control) | ✖ | open-state affordance |
| `tr[data-time]` (clickable rows) | — | **no rule** | ✖ not focusable | ✔ L559/560 `inwindow`, L569/570 `inclass`; **masked when both** (D13) | ✖ | `cursor:pointer` (D16) |
| `table` / `th` / `td` | ✔ L555-558 | ✖ | ✖ | sticky first column L557 | — | row hover |
| `.tablewrap` | ✔ L554 (`overflow:auto`, radius 12) | ✖ | ✖ | — | — | scroll affordance when content overflows (measured 1436px content in 1074px box in "all columns" mode) |
| `canvas` charts | ✔ inline `style` (L601: 1px border, radius 8, surface bg) | ✖ | ✖ | visibility via `CHART` selector only | ✖ | no DPR scaling (bitmap 640×150 drawn into 1074×252 CSS px) |
| `.uvdot` badge | ✔ L561 (9px circle) | — | — | colour set inline per value (no class variants) | — | no legend for the dot colours anywhere in the UI |
| `.note` text | ✔ L562 12px `--muted` | — | — | ✔ `.note.cls` purple L575 | — | — |
| `.status` message | ✔ L563 + `.show` L564 | ✖ | ✖ | ✔ `.error` / `.info` L564 | — | **no `role="status"`/`aria-live`** on `#msg` (`<div id="msg" class="status">`), no dismiss, no icon |
| `#msg` at rest | measured `display:none` with text `Loading…` still inside | | | | | stale text retained while hidden |
| `.strip` day carousel | ✔ L539 `overflow-x:auto` | ✖ | ✖ | — | — | no scroll affordance (1786px content in 1076px, 6 of 14 cells clipped) |

**Interactive elements with NO hover style** (measured by dispatching a real hover and re-reading
computed style; "no change" = identical computed `border-color`/`background`):

1. `a#cal.btn` — `Calendar` (`rgb(210,216,211)` before and after).
2. `select#skin`, `select#locsel`, `select#surface`, `select#mmdbasis`, `select#sunsel`.
3. `input#mintemp`, `input#skintilt`, `input#skinaz`, `input#mmd` (all `type=number`).
4. `input#classTgl` (checkbox).
5. All four `details > summary` elements.
6. `tr[data-time]` — the table rows are clickable and documented as clickable (D16).
7. `button.primary.livereq` and `.daycell[aria-selected="true"]` — a rule matches, but the computed
   border colour is identical before/after because it is already `--sun`; the hover state is a no-op.

**Focus** is the one state that is uniform: all 12 controls reachable by `Tab` measured
`outline: solid 2px rgb(168,85,0); outline-offset: 2px` from the single `:focus-visible` rule (L567).

**Disabled / hidden-but-not-disabled, measured:**

* No element in the rendered DOM carried `[disabled]` or `aria-disabled="true"` at rest, and the
  stylesheet has no rule for either state (D15) — so a disabled control is unrepresentable in CSS.
* `button.livereq` ("Refresh forecast") is set `disabled=true` by `L622` for a multi-minute request
  while keeping `cursor:pointer` and the same amber fill: **enabled-looking while disabled**.
* `#msg` is `display:none` at rest yet still holds `Loading…` — hidden but neither `hidden` nor
  `aria-hidden`, and not a live region.
* `details.mmd` (closed) measures 26px tall while its content `<span id="mmdwrap">` still has a layout
  box (185×92 at y=133, `display:inline`) that is not painted. The field is not disabled, not
  `hidden`, and not removed from layout — its state is expressed purely by the UA `details` behaviour.

---

## 6. Colour semantics

Measured computed colours (live DOM) and their consumers:

| Colour | Where it appears | Meaning asserted by the UI |
|---|---|---|
| `--sun #a85500` | `button:hover` border (L534), `button.primary` fill (L535), `.daycell .win` (L577), `.bestline b` (L552), `.sunfig .cap b` (L584), `:focus-visible` outline (L567), `::selection` uses `--sunwash` (L526), sun-disc stroke (L671) | interaction/affordance **and** "best window" data emphasis **and** sun geometry |
| `--sunwash #fdeed0` | `.daycell[aria-selected]` background (L547), `tr.inwindow td` (L559), `::selection` (L526) | selection highlight **and** in-window data highlight |
| `--mid #8a6200` | `scoreColor` 40–64 (L612) | "mid score"; also the `uvColor` band 3–5 as a literal (L611) |
| `--low #b3450f` | `scoreColor` 20–39 (L612) | "low score"; also `uvColor` band 6–7 as the *same hex* (L611) |
| `--ok #2c7a45` | `scoreColor` ≥65 (L612) | "good score"; also `uvColor` UVI<3 and the `chartDose` line (L611/L628) |
| `--poor #646c69` | `scoreColor` <20 (L612), guide-figure stroke (L671) | "poor score" **and** a neutral geometry colour |
| `#c0392b` | wet day border/`.pk`/bar (L642), rain & wind `<b>` (L642, L686) | rain and wind warnings **and** an override of the score colour |
| `#a12a1f` | `uvColor` UVI 8–10 (L611) | "very high UV" — untokenised red |
| `#6a3fbf`, `#7b4bd6` | `uvColor` UVI≥11 (L611); `chartSed` line (L628) | two unrelated purples |
| `#e8a100` | sun-disc fill (L671) | sun glyph — untokenised amber, 4th amber in the system |
| `rgba(178,94,0,.10)` | chart best-window band (L628) | best window — untokenised, not `--sun` (`#a85500`) nor `--sunwash` |
| `#5b4a8a` | class chip (L573), `.note.cls` (L575) | "in class" **and** "free for you" (D14) |
| `#ece4f4` | `tr.inclass td` (L569) | "in class" |
| `#c3cac5` | unknown-UVI dot (L611), sun-figure ground line (L671) | "no data" **and** a geometry reference line |
| `#f7dfe0` / `#7c2327`, `#eef0e4` / `#4c5540` | `.error` / `.info` (L564) | error / info |

**One colour, two meanings:**

1. `#2c7a45` — (a) score ≥65 ("excellent"), (b) UVI <3 dot on the same row, (c) the `chartDose`
   line, whose own caption says *"exposure odometer, higher is more dose not better"* (L601). Green
   simultaneously means "best", "low UV" and "most dose".
2. `#5b4a8a` — "in class" (blocked) and "free for you" (available) (D14).
3. `#c0392b` — rain warning, wind warning, and the day cell's *score* colour: on a wet day the big
   `.pk` number and the `.bar i` fill switch to red (`style="color:${wet?'#c0392b':scoreColor(pk)}"`,
   L642), so the score colour stops encoding score.
4. `--sun #a85500` — interactive affordance (hover/focus/primary fill) and data emphasis (best
   window, sun) with no visual distinction between the two roles.
5. `--sunwash #fdeed0` — selection state and data state.
6. `#c3cac5` — "no UVI data" and "ground plane".
7. `--poor #646c69` — worst score band and a neutral figure colour.

**Two (or more) colours, one meaning:**

1. `--low #b3450f` and `#a12a1f` — two near-identical reds for "elevated" (score band vs UVI band).
2. `--ok #2c7a45` and `#2c7a45`-as-literal: three spellings of the same green for three roles
   (leaf token, JS literal, chart series).
3. Four ambers for one lamp: `--sun #a85500`, `--mid #8a6200` (also in the day-cell `.pk`), `#e8a100`
   (sun disc), `rgba(178,94,0,.10)` (chart band).
4. Greys for different jobs: `--muted #5b6461`, `--poor #646c69`, `#c3cac5`, `--line #d2d8d3`,
   `--track #dfe4df`, `--headtxt #4e5754`.
5. `#6a3fbf` (UVI≥11 dot) and `#7b4bd6` (SED chart line) — two purples with no shared meaning.
6. `#ece4f4` (class row) and `#f7dfe0`/`#eef0e4` (status tints) are three single-use pale tints.

**Consistent meanings (verified):** `--sunwash` + `★` + bold first cell all consistently mark the
best window; the UVI dot scale is monotone (green → brown → orange → red → red → purple) and matches
the standard UVI bands, with `#c3cac5` for missing data — but the dot has no legend in the UI (the
glossary at L602 documents columns, not dot colours).

Measured WCAG contrast (sRGB, computed from the declared values):

| Pair | Ratio | Note |
|---|---|---|
| `--muted` on `--surface` | 6.10 | `.note`, `.dt`, `.uv` 12px text |
| `--muted` on `--paper` | 5.36 | `.legend`, `.gloss` |
| `--sun` on `--surface` | 5.30 | `.win`, `.bestline b` |
| `--sun` on `--sunwash` | 4.62 | `.win` inside a selected day cell |
| `--headtxt` on `--head` | 6.07 | table headers |
| `--ok`/`--mid`/`--low`/`--poor` on `--surface` | 5.28 / 5.49 / 5.56 / 5.40 | score numbers |
| `#c3cac5` on `--surface` | 1.67 | unknown-UVI dot (non-text, informational only) |
| `#5b4a8a` on `#ece4f4` | 6.08 | class text on class row |
| `#e8a100` vs `#a85500` | 2.40 | sun disc fill against its stroke (decorative) |

---

## 7. Density and rhythm (measured at 1440×900, DPR 1)

**Content max-width:** `.wrap{max-width:1120px;margin:0 auto;padding:28px 22px 60px}` (L527).
Measured at a 1440px viewport: wrap box 1120px wide, inner content **1076px**, document
`scrollWidth == clientWidth == 1440` (no horizontal page scroll). One responsive rule exists in the
whole client — `@media(max-width:640px)` (L589) — and it changes exactly three values: `h1` 34→26px,
`.hero` 26→21px, `.wrap` padding 28/22/60 → 18/12/50.

**Total page height: 3501px.** Section heights and inter-section gaps:

| # | Section | Height | Gap above | % of page |
|---|---|---|---|---|
| — | `.wrap` top padding | 28 | — | 0.8% |
| 1 | `.top` (h1 + runline + 9 form controls + a `<span class="note">` + Apply, then the 3-button actions row) | 220 | 0 | 6.3% |
| 2 | `#msg` (`.status`, `display:none` — occupies no space, contributes no gap) | 0 | n/a | 0% |
| 3 | `.hero` (26px serif, 4 lines × 35.1px) | 140 | 26 | 4.0% |
| 4 | `.legend` | 32 | 4 | 0.9% |
| 5 | `#skinctx.gloss` | 15 | 6 | 0.4% |
| 6 | `.strip` (14 day cells) | 352 | 8 | 10.1% |
| 7 | `#doses` | 106 | 22 | 3.0% |
| 8 | `#charts` | 351 | 22 | 10.0% |
| 9 | `.sunfig` (SVG 300×190 + caption) | 220 | 0 | 6.3% |
| 10 | `details.glossbox` (closed) | 28 | 14 | 0.8% |
| 11 | `#detail` (day heading + hours table + half-hour table) | **1774** | 22 | **50.7%** |
| 12 | `details.debug` (closed, source data) | 25 | 26 | 0.7% |
| — | `.wrap` bottom padding | 60 | — | 1.7% |

Sums: heights 3263 + gaps 150 + padding 88 = 3501 ✔. Gaps: `26 / 4 / 6 / 8 / 22 / 22 / 0 / 14 / 22 / 26`
— six distinct values, of which 22px (section rhythm) dominates while the header block uses 4/6/8.

**Where vertical space is used disproportionately:**

1. **`#detail` = 50.7% of the page.** Inside it (measured): `h2` 27, `.bestline` 36, `.classrow` 22,
   `h3` 35, `.gloss` 15, hourly `.tablewrap` 623 (table 621), `h3` 17, half-hour `.tablewrap` 923 (table 921).
2. **Every hourly row is 49px instead of 33px** because of the `<b>N</b><br><span class="note">Loc N</span>`
   cell (D2). 12/12 rows × 16px = **192px** (31% of that table's 623px wrapper / 621px table) spent
   duplicating a column that is hidden by default; the 30-min table proves the 33px baseline
   (18 of its 24 rows).
3. **6 of the 24 half-hour rows are 49px** (measured distribution 18×33px + 6×49px = 888px) because
   `uviRange` inserts a second line in the UV cell (D6) — 96px.
4. **Charts: 351px section, of which the visible canvas is 253.7px tall and 1076px wide for a
   640×150 bitmap** (inline `width`/`height` at L601, `style="width:100%"`), i.e. a measured 1.68×
   upscale — axis labels are drawn at `9px` (L628) and are then stretched.
5. **`.strip` 352px tall / 1786px wide inside 1076px**: 8 of 14 cells fully visible, 6 clipped
   (cell 9 `2026-10-14` occupies x 1208→1326 vs the visible box 182→1258), with no scroll affordance.
6. **`.top` 220px** for a title, one status line and 10 controls — the `Apply` button overflows onto
   its own row after the description span (`L592-593` places a `<span class="note">` inside the flex
   row), measured `.controls.settings` height 78px with the actions row separate.
7. **Heading block above the tables:** `h3` (35px, inflated by the inline button, D10) + `.gloss`
   (15px, runtime-replaced, D8) + `.classrow` (22px) + margins (22+8+8) ≈ 110px of chrome before the
   first table row.
8. **Nine vertical margin steps (2–26px)** with no shared scale; `h2.sec` and `h3` both consume
   `22px 0 8px` (D9) while section containers use `22px 0 0` (L548) and the hero uses `26px 0 4px` (L536).

---

## Open items (not reproduced)

* **HYPOTHESIS** — D12 (hourly empty-state `colspan="19"` vs 20 columns) was read from source only; the
  branch requires a day with zero hourly rows, which the current run does not contain.
* **HYPOTHESIS** — the wet-day visuals (`#c0392b` border, `.pk`, `.bar`, `<b>N% rain</b>`, and the
  `.txt` "· wet" span at 11px) were not exercised: no day in the current run has
  `peak_precip_probability_pct ≥ 40`, so `.daycell .txt` (L578) has zero instances in the DOM.
* **HYPOTHESIS** — the `.error` / `.info` status treatments (L564) were not captured in a visible
  state: `show('Loading…','info')` (L621) runs before the first paint and `hide()` (L624) removes
  `.show` after load; the element measured `display:none` with the text still present.
* Not measured: print/PDF output, ≤640px behaviour beyond the three overridden values, and the
  `.status` overflow behaviour at narrow widths.