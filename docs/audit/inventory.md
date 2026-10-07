# SunStack — application inventory (audit Phase 1–2)

Evidence basis: source read of `src/sunstack/{ui,serving,output}.py`, plus live
inspection of `http://127.0.0.1:8901/` driven in real Chromium at 1440×900 and
320–414 px. Screenshots in `docs/audit/screenshots/`.

## 1. What the product is

A single-page solar/UV forecast. For one location it answers, in one scroll:

- when the strongest delayed-pigmentation ("tanning") exposure is,
- when the best *usable* window is (hard outdoor constraints),
- what the sunburn (erythemal/SED) exposure is,
- whether going outside is even sensible (temperature, wind, rain, thunder, snow),
- and it offers a calendar subscription.

Two published sites: **South Bend, IN** (default, repo-root `docs/`) and
**Pacific Palisades, CA** (`docs/sites/pacific-palisades/`). Two delivery modes:
a live FastAPI server (`sunstack ui`) and a static export. Both render from the
same template (`output.render_static_html()` is derived from the live HTML by
anchor swaps).

## 2. Architecture

| Layer | File | Notes |
|---|---|---|
| HTTP | `src/sunstack/ui.py` (258 lines) | 6 routes, listed below |
| Client | `src/sunstack/serving.py` (~730 lines) | HTML + CSS + minified JS as Python string constants. **This is the entire UI.** |
| Static export | `src/sunstack/output.py` (297 lines) | `render_static_html()`, `_swap_once()` anchors, writes `docs/*` |

No frontend framework, no component library, no router, no build step, no state
store. Navigation is one document; "state" is a single global `DATA` object plus
`localStorage`. There is no URL state at all.

### Routes

| Route | Method | Purpose |
|---|---|---|
| `/` | GET | the page |
| `/api/data` | GET | the whole payload (daily, hourly, half_hour, summary) |
| `/api/locations` | GET | site list for the location selector |
| `/locations.json` | GET | same payload, so the static-site fetch path also works live |
| `/api/refresh` | POST | live Open-Meteo + CAMS fetch and rebuild (minutes) |
| `/api/calendar.ics` | GET | ICS subscription feed |

### Query parameters on `/api/data`
`skin_type` (1–6/empty), `min_temp` (float/empty), `personal_mmd`,
`personal_mmd_basis`, `surface` (slug), `surface_extent` (local|broad),
`skin_tilt_deg` (0–180), `skin_azimuth_deg` (0–360), `location` (slug).

## 3. Component inventory

### 3.1 Controls (11)

| # | Selector | Type | Options | Effect |
|---|---|---|---|---|
| 1 | `#locsel` | select | 2 sites | refetches `/api/data?location=` |
| 2 | `#skin` | select | None, I–VI | refetches with `skin_type`; row-level `fitzpatrick_*` |
| 3 | `.mmd summary` | details | — | opens the MMD group |
| 4 | `#mmd` + `#mmdbasis` | number + select | 4 bases | `personal_mmd`, `personal_mmd_basis` |
| 5 | `#mintemp` | number | — | `min_temp` |
| 6 | `#surface` | select | 14 slugs | `surface` |
| 7 | `#skintilt` | number | 0–180 | `skin_tilt_deg` |
| 8 | `#skinaz` | number | 0–360 | `skin_azimuth_deg` |
| 9 | Apply | button | — | `loadData()` with all current values |
| 10 | Refresh forecast | button | — | `POST /api/refresh` |
| 11 | `#nerdBtn` | button | — | toggles 20/20 columns (`.nerd`) |

Controls 2–8 are **staged**: changing them does nothing until Apply. Only
`#locsel` applies immediately.

### 3.2 Actions
`#cal` (Calendar, `webcal://` link), "Export CSV" (3 client-side CSV downloads),
`#chartPrev` / `#chartNext` (chart panels 1–3 with wrap), `#sunsel` (35 time
options), `#classTgl` (checkbox), 14 `.daycell` buttons, hourly-table row clicks,
`<details>` × 4 (`mmd`, `advphoto`, `glossbox`, Source data).

### 3.3 Data views
- Day strip: 14 day cells, each with day name, status, window, class spans, peak
  score, Int/Fit/Conf, UV range, feels-like range, gust, `Abs · Loc`, and a bar.
- Doses line: 30-min peak / best hour / best window / today, plus SED equivalents,
  plus the MMD multiplier when set.
- Charts: 3 canvas panels — TanScore (0–100), cumulative TanDose, cumulative SED.
- Sun figure: SVG with sun position + a posture stick figure.
- Tables: hourly (20 columns) and 30-minute (6 columns).
- Disclosures: Advanced/Photobiology, provenance line, Column glossary, Source data.

## 4. States present

| State | Where | Verified |
|---|---|---|
| Initial / loading | `show('Loading…')`, "#msg" | yes |
| Populated | default | yes |
| Empty | `if(!DATA.daily.length)` → "No forecast data yet." | yes (forced in-page) |
| Error | `show(...,'error')` | yes (empty Min °F, 404 location) |
| Disabled | Refresh button only, during an in-flight refresh | yes (code) |
| Selected | `.daycell[aria-selected]`, chart panel, `#sunsel` | yes |
| Focus | 2 px solid outline on buttons, cells, inputs | yes |
| Hover | **only `button:hover`** | yes |
| Permission-restricted | none exists | n/a |
| Long-content | long location names, long class spans | partial |

## 5. Coverage matrix

Legend: **PASS** verified working · **PARTIAL** works with a caveat ·
**FAIL** wrong or broken · **UNVERIFIED** not testable here.

| Feature | Interaction | Expected | Actual | Status | Evidence |
|---|---|---|---|---|---|
| Location | select Pacific Palisades | data refetches for that site | `/api/data?...location=pacific-palisades`, hero/day strip change | PASS | fetch log; 165→168 rows |
| Skin type | select III + Apply | context updates | request carries `skin_type=3`; rows carry `fitzpatrick_type:3`; context line renders | PASS | `#skinctx` text |
| Min °F | 45 + Apply | refetch wider/narrower | `min_temp=45` applied | PASS | request URL |
| Min °F | clear + Apply | graceful | **422** → message `[object Object]` | **FAIL** | status bar text |
| Surface | fresh_snow + tilt 45 + Apply | plane/reflected change | horizontal E_DP unchanged at 0.63116; reflected 0 → 48.78 | PASS | live values |
| Tilt/Azimuth | 45/200 + Apply | geometry changes | `skin_plane_factor` moves off 1.0 | PASS | live values |
| Apply | — | applies all staged | does | PASS | request URL |
| Refresh | click | live run | real Open-Meteo+CAMS fetch; sat in ADS queue minutes | PARTIAL | server log; no progress |
| Refresh | double click | no stacking | button disabled in flight (added this session) | PASS | code + live |
| Calendar | link | ICS | 14 VEVENTs, valid UTC | PASS | raw ICS |
| Export CSV | click | 3 files | `sunstack-all-hourly.csv` (42 cols, 165 rows) + 30-min + days | PASS | download |
| Day strip | click a day | selects the day | `#sunsel` + tables + charts move; `aria-selected` updates | PASS | live |
| Day strip | arrow keys | listbox pattern | no keydown handler; selection does not move; 14 tab stops | **FAIL** (ARIA contract) | tab walk, ArrowRight no-op |
| Chart nav | prev/next ×4 | cycles 1→2→3→1 | wraps correctly | PASS | `#chartName` |
| Chart hover | mousemove | tooltip | `#charttip` → "2 PM — Score #7" | PASS | live |
| Charts | AT exposure | described | `title` only, no `role` | PARTIAL | DOM |
| Sun figure | row click | figure follows | "2 PM — sun 43° up (S)" → "8 AM — sun low 2° (E)" | PASS | `#suncap` |
| Time select | pick | figure follows | does | PASS | live |
| Show all columns | toggle | 12→20 cols | 20/20 headers visible, `aria-pressed` true | PASS | DOM |
| Show my classes | uncheck | hides class rows/spans | `body.hide-class`, `.cls` display:none | PASS functionally | DOM |
| MMD | 800 + COARSE_ESTIMATE + Apply | personalizes | doses line gains "Your MMD: 1.31× (30-min, client-side · COARSE_ESTIMATE)" | PARTIAL | text |
| MMD basis | read labels | human labels | raw enums `SUNSTACK_EFFECTIVE_DOSE_MEASURED` etc. | **FAIL** (copy) | option list |
| Hourly table | click header | sort | nothing; `th` has no role/tabindex/button | **FAIL** (expected absent) | live |
| Hourly row | click | inspects that time | sun figure updates | PASS | live |
| 30-min table | read | comparable | 6 columns vs hourly's 20; no Confidence | PARTIAL | headers |
| Advanced/Photobiology | open | technical detail | opens; wall of version identifiers | PARTIAL | text |
| Column glossary | open | explain columns | opens, 28 px target | PASS | live |
| Source data | open | source data | 17 106 chars of pretty-printed `DATA.summary` JSON | PARTIAL | `textContent` |
| Empty state | no rows | message | "No forecast data yet.", no exception, recovers | PASS | forced render |
| Error state | bad param | actionable | raw parameter name, stale data stays on screen | **FAIL** | screenshot 01 |
| Deep link | reload with state | restored | location resets to South Bend; no query string exists | **FAIL** | reload |
| Responsive | 320–1440 | no overflow | clean after this session's fix | PASS | sweep |
| Contrast | sampled elements | AA | 5.36–17.61 | PASS | computed |
| Keyboard | Tab order | logical | logical; 14+ day cells inflate tab count | PARTIAL | tab walk |
| Reduced motion | — | respected | no transitions/animations exist; no rule needed | PASS | computed |

**Coverage: 30 of 34 inventoried interactions verified live (88%).**
Not testable here: permission-restricted states (none exist), a live `POST
/api/refresh` to completion (multi-minute upstream CAMS queue; the button was
exercised and observed fetching), and a genuine empty *deployment* (forced via
the client's own code path instead).