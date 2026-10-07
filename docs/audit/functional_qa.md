# Functional QA — SunStack API contract & control effects

Auditor: `FunctionalQA` (sub-agent). Date: 2026-10-06/07 (machine local, America/Indiana/Indianapolis).
Server: **already running** at `http://127.0.0.1:8901`, used READ-ONLY. No `POST /api/refresh`, nothing written under `data/`.
Method: HTTP GETs (`urllib`/`curl`), recursive JSON diff of whole payloads, `pandas` reads of the run parquet (read-only), and one live Chromium tab against `http://127.0.0.1:8901/` for client-side claims.

Run identity of the data used throughout (from `GET /api/data?location=south-bend`):

| field | value |
|---|---|
| `run` | `data/latest` |
| `summary.created_at` | `2026-10-06T21:56:35.850472-04:00` |
| `summary.forecast_code_sha` (client "runline") | `83b9724` |
| `build_sha` | `511c611` |
| rows | `daily` 14, `hourly` 163 (daylight only), `half_hour` 326 (daylight only) |

`GET /api/data?location=pacific-palisades` returns run `data/sites/pacific-palisades/latest`, `summary.created_at` `2026-09-23T04:32:19.662663+00:00`, stamp `20260923_043056` — a **two-week-stale frame with an older schema** (see §1.8, §6.4).

Baseline request used as the diff control everywhere below:

```
GET http://127.0.0.1:8901/api/data?location=south-bend      -> 200, 4 389 090 bytes
```

---

## 1. Control-effect matrix

Each row is a pair of requests that differ **only** in the named parameter; the "changed fields" column lists every distinct response path that changed (with the exact values of one representative row). Underscored path segments are loops: `half_hour[]` = all 326 daylight half-hour rows, `hourly[]` = all 163 daylight hours, `daily[]` = 14 days.

| Control (UI label) | Request A → Request B | Changed fields (exact before → after) | Verdict |
|---|---|---|---|
| **Skin** (`Skin` select I–VI) | `?location=south-bend` → `?location=south-bend&skin_type=3` | `half_hour[].fitzpatrick_type` `null`→`3`; `half_hour[].fitzpatrick_label` `"not specified"`→`"Type III — intermediate response; may burn, tans gradually"`; `half_hour[].personal_uv_risk_context` `"not personalized"`→`"intermediate erythema susceptibility; individual response varies substantially"`; `half_hour[].skin_response_note` `"Environmental scores are skin-type independent."`→`"Fitzpatrick type changes risk/response interpretation, not environmental TanScore. …"` (same 4 paths on `hourly`, ×326 / ×163). **Zero numeric fields changed.** | CONFIRMED, limited: the label implies risk personalization; the response changes interpretation text only, which the response itself states |
| **Min °F** (`Min °F` input, default 50) | `?location=south-bend` → `?…&min_temp=40` | `hourly[].minimum_tan_temperature_f` `50.0`→`40.0`; `hourly[].outdoor_feasibility_0_100` `0.0`→`67.8`; `hourly[].outdoor_blocked` `true`→`false`; `hourly[].outdoor_block_reason` `"temperature < 50F"`→`""`; `hourly[].outdoor_feasibility_reason_codes` `"too_cold"`→`"ok"`; `hourly[].outdoor_flags` `""`→`"cold"`; `hourly[].comfort_band` `"too cold"`→`"cool"`; `daily[].blocked_half_hours` `3`→`0`; `daily[].day_status` `"NO OUTDOOR WINDOW"`→`"POOR"`; `daily[].best_comfortable_usable_30m_*` `376.3`/`"2026-10-16T10:30:00"`→`null`. | CONFIRMED as a **feasibility threshold**, not a filter: rows below the threshold stay in the payload. `?location=south-bend&min_temp=50` is byte-identical to the no-param baseline (0 differing paths), so 50 is the run default |
| **Surface** (`Surface` select) | `?location=south-bend` → `?…&surface=dry_beach_sand` (Tilt stays 0) | only 7 metadata fields per row: `surface_display_name` `"Unknown surface"`→`"Dry beach sand"`, `surface_material_slug` `"unknown"`→`"dry_beach_sand"`, `surface_model_quality` `"none"`→`"broadband_uv_proxy"`, `surface_reflectance_source` `"no assertion"`→`"IARC table: dry light beach sand 15-18% UVB"`, `surface_reflection_uncertainty` `0.0`→`0.03`, `surface_uva_reflectance` `0.0`→`0.165`, `surface_uvb_reflectance` `0.0`→`0.165`. | CONFIRMED, limited: at the UI default Tilt 0 the response changes **no physics at all** (the UI carries the same caveat — see below) |
| **Surface + Tilt** | `?…&surface=unknown&skin_tilt_deg=60` → `?…&surface=dry_beach_sand&skin_tilt_deg=60` | the 7 metadata fields **plus** `skin_plane_ground_reflected_uva_wm2` `0.0`→`0.0742`, `skin_plane_ground_reflected_uvb_wm2` `0.0`→`0.0742`, `skin_plane_ground_reflected_delayed_pigmentation_wm2` `0.0`→`0.04196`. `skin_plane_e_mel_wm2` unchanged. | CONFIRMED: reflection is emitted as separate fields; it is **not** added to `skin_plane_e_mel_wm2` (by design — `spectral.py:284-296` "kept separate from the horizontal environmental fields") |
| **Surface extent** (no UI control exists) | `?…&surface=dry_beach_sand&skin_tilt_deg=60` → `?…&surface_extent=broad` | exactly one field: `half_hour[].surface_extent_mode` `"local"`→`"broad"` (+1 on `hourly`). **489 paths = 326 + 163 echoes, nothing else.** | CONFIRMED **no functional effect**; no client ever sends it (the live page's request omits `surface_extent` entirely, see §1.9) |
| **Tilt (°)** (`Tilt` input, default 0) | `?location=south-bend` → `?…&skin_tilt_deg=60` | `skin_plane_standard` `"horizontal environmental reference"`→`"tilt 60deg az 180deg (horizontal reference preserved)"`; `skin_plane_factor` `1.0`→`3.4708`; `skin_plane_e_mel_wm2` `0.00295`→`0.01024`; `skin_plane_delayed_pigmentation_effective_irradiance_wm2` `0.00295`→`0.01024` | CONFIRMED |
| **Azimuth (°)** (`Azimuth` input, default 180) | `?location=south-bend` → `?…&skin_azimuth_deg=180` | **0 differing paths.** | REFUTED as a standalone control: at the UI's default Tilt 0 the plane is horizontal, so azimuth is physically irrelevant (matched by `spectral.py:254-263` early return). CONFIRMED only in combination: `tilt=60&az=0`→`tilt=60&az=180` gives `skin_plane_factor` `0.2475`→`3.4708`, `skin_plane_e_mel_wm2` `0.00073`→`0.01024`; `tilt=60&az=90`→`az=270` gives `20.0383`→`0.2475` |
| **My MMD** (`My MMD` input) | `?location=south-bend` → `?…&personal_mmd=300&personal_mmd_basis=OBJECTIVE_ESTIMATE` | `personal_mmd_equivalent_dose_j_m2` `null`→`300.0`; `personal_mmd_fraction` `null`→`0.018`; `personalization_basis` `"not personalized"`→`"OBJECTIVE_ESTIMATE"`. **No dose/score/ranking field changes.** | CONFIRMED, context-only (documented in `opportunity.attach_personalization`: "The fraction is context only, never safe-exposure allowance"). `personal_mmd_fraction = dose / personal_mmd` (`5.31 / 300 = 0.0177 → 0.018`) |
| **MMD basis** (`I have my MMD` basis select) | `?…&personal_mmd=300&personal_mmd_basis=OBJECTIVE_ESTIMATE` → `…=COARSE_ESTIMATE` | exactly one field: `personalization_basis` `"OBJECTIVE_ESTIMATE"`→`"COARSE_ESTIMATE"` (×326 + ×163). | CONFIRMED **provenance-only**: the label ("Where the MMD number came from … SOURCE_SPECTRUM (convertible lamp spectrum)") implies a conversion; the response performs none |

### 1.8 Stale-schema site (observed, not a control)
The palisades payload carries **no** v5 fields at all. `half_hour[0]` (verified key-by-key) is missing `uvi_consensus`, `erythemal_irradiance_wm2`, `melanogenic_effective_irradiance_wm2`, `tan_dose_*` and the `delayed_pigmentation_dose_*` twins, all `skin_plane_*`, `time_utc`, `interval_*` and `comfort_band`; it does still carry `fitzpatrick_type: null`, `surface_display_name: "Unknown surface"`, `outdoor_blocked: false`, `overall_tan_opportunity_0_100: 1.2`. `summary.schema_version` is absent. Diffing it against south-bend produced ~1853 `MISSING_IN_B` paths. Live consequence: on `http://127.0.0.1:8901/` selecting the LA site renders the hero as `"— — E_mel J/m²"`.

### 1.9 Control → request wiring (live browser, Chrome, tab `qa-func`)
- Changing a control does **not** auto-refetch; the panel has an explicit `Apply` button (`<button onclick="loadData()">Apply</button>`). The location `<select id="locsel">` *does* refetch on `change`.
- Recorded outgoing request after setting Surface = Dry sand, Tilt = 60, Azimuth = 180 and clicking Apply:
  `/api/data?skin_type=&min_temp=50&personal_mmd=&personal_mmd_basis=&surface=dry_beach_sand&skin_tilt_deg=60&skin_azimuth_deg=180&location=south-bend` → 200, 4 430 135 bytes.
- The provenance panel then read: `Surface Dry beach sand · proxy 16.50% · reflected E_mel 0.04 W/m² · tilt 60° azimuth 180°` — i.e. the surface effect is visible in the UI once tilted, and invisible (panel still `Surface Unknown surface · proxy 0.00% · reflected E_mel 0.00 W/m² · tilt 0°`) when not.
- The live page's own note next to the Surface control states the geometry: *"ground reflection is geometrically zero; recline or stand the plane to see the surface effect."*

---

## 2. Contradictory response state — `summary.skin_type` null while rows say 3

**CONFIRMED.**

```
GET http://127.0.0.1:8901/api/data?location=south-bend&skin_type=3   -> 200
  summary.skin_type                      = null
  half_hour[0].fitzpatrick_type          = 3
  half_hour[0].fitzpatrick_label         = "Type III — intermediate response; may burn, tans gradually"
```

Provenance of each value:

- **Rows** are computed **per request**: `ui.py::data()` → `_filtered_payload(...)` → `attach_fitzpatrick(hourly, skin_type)` / `attach_fitzpatrick(half, skin_type)` (`serving.py:86-141`, lines 99-100). Hence `fitzpatrick_type: 3` on every row.
- **`summary`** is *not* computed per request. `_filtered_payload` does `summary = json.loads(summary_path.read_text())` where `summary_path = run / "summary.json"` (`serving.py:137-138`), and `ui.py` returns it verbatim. That file is written once per run at `cli.py:717` with `"skin_type": skin_type` (`cli.py:637`) — the **run's CLI parameter**, not the request's.
- The on-disk value confirms it: `data/latest/summary.json` → `"skin_type": null` (the serving/CLI runs are launched without `--skin-type`). The `GET /api/data?…&skin_type=3` diff shows **no `summary.*` path changed at all**.
- Latent consequence (from code, not exercised — `POST /api/refresh` was out of scope): `ui.py::refresh()` forwards `skin_type=st` into `run_live_fn(...)`, so a single refresh with `skin_type=3` would write `"skin_type": 3` into `summary.json` and **every** later `/api/data` request would report `summary.skin_type: 3` regardless of its own `skin_type` param, while `rows` keep following the request. `[INFERENCE]`

---

## 3. Unreachable advertised surface (`custom`)

**CONFIRMED — no request through the HTTP API can use `surface=custom`.**

1. The 400 for an unknown surface lists it as allowed:
   `GET /api/data?location=south-bend&surface=kittens` → **400**, `detail`:
   `"ERROR surface: unknown surface 'kittens'; allowed: ['aged_asphalt', 'aged_concrete', 'aged_snow', 'custom', 'dry_beach_sand', …]"` (source: `surface.py:PRESETS`).
2. Every `custom` request fails identically:
   - `GET /api/data?location=south-bend&surface=custom` → **400**, `detail` = `"ERROR surface: custom surface requires both --surface-uva-reflectance and --surface-uvb-reflectance in [0,1]"`
   - `GET /api/data?location=south-bend&surface=custom&surface_uva_reflectance=0.5&surface_uvb_reflectance=0.5` → **400**, same `detail` (FastAPI ignores undeclared query params).
   - `GET /api/calendar.ics?location=south-bend&surface=custom` → **400**, same `detail`.
   - `POST /api/refresh` also reaches `_parse_surface` before doing anything (not exercised: forbidden).
3. Code evidence that the values can never be supplied over HTTP: `surface.py:resolve_surface(slug, uva_reflectance, uvb_reflectance)` raises unless both floats are passed. The HTTP routes call `_parse_surface(surface, extent)` (`ui.py:33-45`), which calls `resolve_surface(slug)` with **no** reflectances; `spectral.apply_skin_plane` likewise calls `_resolve_surface(surface_slug, uva_reflectance, uvb_reflectance)` with `None` from the serving path (`spectral.py:227`). Reflectances exist only as CLI arguments: `cli.py:1311 "--surface-uvb-reflectance"`, validated at `cli.py:1381-1393`.
4. The client cannot even ask for it: the Surface `<select>` offers exactly `unknown, grass_summer, grass_winter, dry_beach_sand, wet_beach_sand, light_concrete, aged_concrete, fresh_asphalt, aged_asphalt, weathered_wood_deck, open_water, sea_foam, fresh_snow, aged_snow` — `custom` (one of the 15 `PRESETS`) is not in the list.

Net: the error message advertises a slug that every read route rejects, with a message naming CLI flags that an HTTP client cannot send.

---

## 4. Validation taxonomy

All requests below are on `/api/data` except where marked. Shape is `typeof detail` in the JSON body.

| case | request | status | `detail` shape | message (verbatim) |
|---|---|---|---|---|
| unknown location | `?location=atlantis` | **500** | str | `"404: unknown location: atlantis"` |
| unknown surface | `?location=south-bend&surface=kittens` | 400 | str | `"ERROR surface: unknown surface 'kittens'; allowed: ['aged_asphalt', 'aged_concrete', 'aged_snow', 'custom', 'dry_beach_sand', …]"` |
| bad surface_extent | `?location=south-bend&surface=dry_beach_sand&surface_extent=galaxy` | 400 | str | `"surface_extent must be one of ['local', 'broad'], got 'galaxy'"` |
| skin_type=99 | `?location=south-bend&skin_type=99` | **500** | str | `"Fitzpatrick skin type must be an integer from 1 to 6"` |
| skin_type=abc | `?location=south-bend&skin_type=abc` | **500** | str | `"400: invalid skin_type: 'abc'"` |
| min_temp=abc | `?location=south-bend&min_temp=abc` | 422 | **list** | `[{"type": "float_parsing", "loc": ["query", "min_temp"], "msg": "Input should be a valid number, unable to parse string as a number", "input": "abc"}]` |
| min_temp= (empty) | `?location=south-bend&min_temp=` | 422 | **list** | `[{"type": "float_parsing", "loc": ["query", "min_temp"], "msg": "Input should be a valid number, unable to parse string as a number", "input": ""}]` |
| skin_tilt_deg=200 | `?location=south-bend&skin_tilt_deg=200` | 400 | str | `"skin_tilt_deg must be a finite number in [0, 180], got '200'"` |
| skin_azimuth_deg=999 | `?location=south-bend&skin_azimuth_deg=999` | 400 | str | `"skin_azimuth_deg must be a finite number in [0, 360], got '999'"` |
| personal_mmd=abc | `?location=south-bend&personal_mmd=abc` | 400 | str | `"personal_mmd must be a number in melanogenic-effective J/m^2, got 'abc'"` |
| personal_mmd_basis=NOPE | `?location=south-bend&personal_mmd=300&personal_mmd_basis=NOPE` | 400 | str | `"personal_mmd_basis must be one of ['SUNSTACK_EFFECTIVE_DOSE_MEASURED', 'SOURCE_SPECTRUM_MEASURED', 'OBJECTIVE_ESTIMATE', 'COARSE_ESTIMATE'] when personal_mmd is given, got 'NOPE'"` |
| (extra) skin_tilt_deg=abc | `?location=south-bend&skin_tilt_deg=abc` | 400 | str | `"skin_tilt_deg must be a finite number in [0, 180], got 'abc'"` |
| (extra) surface=custom | `?location=south-bend&surface=custom` | 400 | str | see §3 |
| (extra) surface_extent alone | `?location=south-bend&surface_extent=galaxy` | 400 | str | `"surface_extent must be one of ['local', 'broad'], got 'galaxy'"` |

**Client errors reported as 5xx (3 cases, all on both `/api/data` and `/api/calendar.ics`):**

- `location=atlantis` → **500** `"404: unknown location: atlantis"`. Mechanically: `ui.py` raises `HTTPException(404, …)` *inside* the outer `try`, and the outer `except Exception as exc: raise HTTPException(500, detail=str(exc))` re-wraps it — the `"404: "` prefix in the message is the stringified inner exception.
- `skin_type=abc` → **500** `"400: invalid skin_type: 'abc'"` (same swallow of an inner 400).
- `skin_type=99` → **500** `"Fitzpatrick skin type must be an integer from 1 to 6"` (a `ValueError` from `attach_fitzpatrick`, so unvalidated input values are 5xx).

The parameters parsed *before* the outer `try` (`personal_mmd`, `personal_mmd_basis`, `surface`, `surface_extent`, `skin_tilt_deg`, `skin_azimuth_deg`) correctly return 400.

**Structured (`list`) `detail`:** the two `min_temp` cases (FastAPI/pydantic request validation, 422). The client does `const j = await r.json(); if(!r.ok) throw new Error(j.detail || 'Request failed'); … show('Could not load forecast: ' + e.message + '…')`, so a one-element array of objects stringifies to `[object Object]`.

- Live confirmation (Chrome tab, field cleared then Apply): outgoing request `/api/data?skin_type=&min_temp=&…&location=south-bend` → **422**, body `{"detail":[{"type":"float_parsing","loc":["query","min_temp"],"msg":"Input should be a valid number, unable to parse string as a number","input":""}]}`, and the page showed:
  `Could not load forecast: [object Object]. Check the server log, then Refresh.`
  The client always sends `min_temp=<fields value>` (default `50`), so clearing the Min °F box breaks the whole load.
- Same taxonomy on `/api/calendar.ics` (verified: `location=atlantis` 500 / `skin_type=abc` 500 / `skin_type=99` 500 / `surface=kittens` 400 / `surface_extent=galaxy` 400 / `surface=custom` 400 / `min_temp=` 422 list).

---

## 5. Invariant spot-checks (south-bend daylight half-hour rows)

Row chosen: `half_hour[0]` of `GET /api/data?location=south-bend` → `2026-10-06T08:00` (and the frame maximum `2026-10-06T14:00`).

| check | values | verdict |
|---|---|---|
| `erythemal_irradiance_wm2 == uvi_consensus / 40` | 08:00 → `erythemal 0.00108`, `uvi_consensus 0.043`, `0.043/40 = 0.001075` (Δ 5.0e-06, the 5-decimal rounding of the published column). 14:00 → `erythemal 0.12`, `uvi_consensus 4.8`, `4.8/40 = 0.12` exactly. Max \|Δ\| over all 326 half-hour rows and all 163 hourly rows = **5.000e-06** | **CONFIRMED** (equality up to 5e-06 rounding) |
| `uvi_consensus` inside `[min,max]` of finite per-source UVIs | 08:00 → `uvi_source_values [0.0, 0.043, null]`, `uvi_consensus 0.043`, `uvi_consensus_sources 2`, `uvi_source_spread 0.043` → `0.0 ≤ 0.043 ≤ 0.043`. 14:00 → values `[4.8, 4.5, null]`, consensus `4.8`, min/max finite `4.5 / 4.8` → inside. **0 violations across all 326 rows with a consensus.** (Per-source columns: `uvi_openmeteo 0.0`, `uvi_cams 0.0425483845`, `uvi_epa null`, `uvi_sunny 0.043` at 08:00) | **CONFIRMED** |
| `delayed_pigmentation_dose_*` twins == `tan_dose_*` namesakes | 08:00 → `tan_dose_30m_j_m2 = 5.31` / `delayed_pigmentation_dose_30m_j_m2 = 5.31`; `…_15m… 2.655 = 2.655`; `…_1h… 5.31 = 5.31`; also the `_complete`, `_coverage_fraction`, `_reference_minutes`, `_model_version` twins all equal. **0 mismatches** scanning every `*tan_dose*` key on `hourly`, `half_hour` and `daily` | **CONFIRMED** |

Note: these invariants hold for the **south-bend** frame. The palisades frame carries none of these columns (`uvi_consensus`, `erythemal_irradiance_wm2` and `tan_dose_*`/`delayed_pigmentation_dose_*` are all absent — see §1.8), so the checks are **UNVERIFIED** there — not failed, simply not computable on the stale run.

---

## 6. Calendar output (`/api/calendar.ics`)

Fetched: `GET http://127.0.0.1:8901/api/calendar.ics?location=south-bend` → 200, 9 430 bytes, and `?location=pacific-palisades` → 200, 7 433 bytes. Both are built by `serving.build_calendar_ics(daily, run, hourly, site_slug=…, tz_name=site.timezone)` (`ui.py::calendar`).

| check | south-bend | pacific-palisades |
|---|---|---|
| VEVENT count | **14** (= 14 `daily` rows) | **14** |
| UID count / unique | 14 / 14 unique; first `UID:sunstack-best-south-bend-2026-10-06@south-bend` | 14 / 14 unique; first `UID:sunstack-best-pacific-palisades-2026-09-22@pacific-palisades` |
| DTSTART/DTEND shape | 14 + 14, all matching `(DTSTART\|DTEND):\d{8}T\d{6}Z`; all `DTSTART < DTEND` | same, all valid |
| unescaped `,` / `;` / newline in structured props | **0** (values use `\,` — e.g. pacific SUMMARY `Best sun 11:30 AM-4:00 PM (UV 6.8\, overall 54)`) | 0 |
| folding / bytes | 71 continuation lines, longest line exactly **75 octets**, no non-ASCII bytes, no lone CR, no bare LF | 42 continuation lines, max 75 octets, no non-ASCII, no lone CR |

First event, verbatim (south-bend):

```
BEGIN:VEVENT
UID:sunstack-best-south-bend-2026-10-06@south-bend
DTSTAMP:20261007T025757Z
SEQUENCE:0
DTSTART:20261006T173000Z
DTEND:20261006T180000Z
SUMMARY:Best usable sun 1:30 PM-2:00 PM (dose 1111.1 J/m2 E_mel)
DESCRIPTION:Best usable sun 1:30 PM-2:00 PM (dose 1111.1 J/m2 E_mel). Overa
 ll 43/100. Local 93/100. Local@best 93/100. Abs 34/100. Peak UV 4.8 at 2:0
 0 PM. UVA 39.578 W/m2. UVB 0.9025 W/m2. TanDose window 7756.1 J/m2 mel. Ta
 nDose day 11956.8 J/m2 mel (partial). SED window 15.951. SED day 27.381 (p
 artial). UVA day 922544 J/m2. UVB day 16712.6 J/m2. Confidence 50. FAIR. T
 imes refresh with each SunStack run.
END:VEVENT
```

(the `Overa`/`ll` split is RFC 5545 line folding at 75 octets — unfolding joins it back to `Overall`)

First event, verbatim (pacific-palisades):

```
BEGIN:VEVENT
UID:sunstack-best-pacific-palisades-2026-09-22@pacific-palisades
DTSTAMP:20261007T025757Z
SEQUENCE:0
DTSTART:20260922T183000Z
DTEND:20260922T230000Z
SUMMARY:Best sun 11:30 AM-4:00 PM (UV 6.8\, overall 54)
DESCRIPTION:Overall 54/100. Local 82/100. Local@best 78/100. Abs 49/100. Pe
 ak UV 6.8 at 1:00 PM. UVA 44.921 W/m2. UVB 1.2934 W/m2. SED window 24.372.
  SED day 38.937. UVA day 1.05616e+06 J/m2. UVB day 24777.3 J/m2. Confidenc
 e 92. GOOD. Times refresh with each SunStack run.
END:VEVENT
```

**6.4 Staleness (observed, not a format defect):** the pacific-palisades events cover `2026-09-22 … 2026-10-05`; its `DTSTART`s (`20260922T183000Z` …) are all in the past relative to the audit date, because the site's `latest` run is from `2026-09-23`. A subscriber to that feed gets 14 past events and no future ones. Also note `DTSTAMP` is regenerated per request (`datetime.now(UTC)`), so the same UID yields a newer `DTSTAMP` on every fetch (valid per RFC 5545, but the payload is not byte-stable).

---

## 7. Timezone consistency

**Displayed row times are the selected site's local wall clock.** Evidence chain:

1. The published `time` column is a **naive local string**: `data/latest/tables/tan_forecast_30min.parquet` row 16 → `time = "2026-10-06T08:00"` (dtype `str`), `time_utc = 2026-10-06 08:00:00+00:00`, `interval_start_utc = 11:30Z`, `interval_end_utc = 12:00Z`, `interval_midpoint_utc = 11:45Z`, `solar_elevation_deg = 1.52`. It is produced by `out["dt"].dt.strftime("%Y-%m-%dT%H:%M")` from a site-local tz-aware `dt` (`opportunity.py:530`; the site tz is set per site by `config.use_site`).
2. `interval_end_utc == localize(time, site_tz)` for **all 326** south-bend half-hour rows (0 mismatches), offset exactly `4:00:00` = `America/Indiana/Indianapolis` EDT. `summary.timezone` is `America/Indiana/Indianapolis` for south-bend and `America/Los_Angeles` for palisades.
3. Independent physical anchor: `solar_elevation_deg` is 1.52° at `"08:00"` (South Bend sunrise ≈ 07:50 EDT) and 3.05° at `"07:00"` for palisades (LA sunrise ≈ 06:45 PDT). Reading those labels as UTC would put both rows at local midnight (elevation ≈ −25°).
4. The ICS conversion agrees: `_ics_stamp("2026-10-06T13:30", "America/Indiana/Indianapolis") = 20261006T173000Z` with `SUMMARY … 1:30 PM`, and for palisades `11:30 AM` local ↔ `20260922T183000Z` (−7).
5. The client renders the string **verbatim**: `hhmm(s)` extracts `m[1]:m[2]` from `/T(\d\d):(\d\d)/` with no `Date` parsing (`serving.py` HTML), and `loadData()` fetches `time` rows that always include `…T08:00`-style local stamps. Live page: south-bend table showed `8 AM, 9 AM, 10 AM, …` matching the API strings.

**Class overlay label ("Show my classes (ET, Mon–Fri)")** — accurate for south-bend, inert elsewhere:

- `classAt`/`classSpans`/`availWin` all start with `if((loc||"")!==""&&loc!=="south-bend") return "";` — the schedule is applied **only** to the south-bend site, whose displayed times are Eastern (points 1–5 above), so the `ET` label is correct where it is used. Live: `classSpans("2026-10-06","south-bend")` = `"9:30–10:20, 11:00–12:15"`, and the rendered hourly rows for that (Tuesday) day carried `in class` on exactly the 10 AM / 11 AM / 12 PM rows.
- The JS windows and the server-side `opportunity._CLASS_BLOCKS` (used for class-aware window scoring) agree **per weekday** — JS indexes by `Date.getDay()` (Sun=0) and Python by `Timestamp.dayofweek` (Mon=0), and the two tables are shifted accordingly (verified day-by-day for 2026-10-06…2026-10-19: identical spans, none on Sat/Sun, `12:50–13:40` only on Fridays).
- Caveat to flag: for a non-south-bend site the overlay silently does nothing — live, the LA page rendered `TIME 7 AM…` with **no** `in class` notes while the checkbox `Show my classes (ET, Mon–Fri)` stayed checked and visible. The label is not *wrong* for the site it applies to; it is misleading for the other site it is displayed on.
- Robustness note: `classAt` parses the naive local string with `new Date(time)` and reads `getHours()/getDay()`; because the string is naive the hour numbers are preserved in any browser zone (verified in Chrome, `GMT-0400`), so the match is not browser-tz dependent in practice.

**Defect found while checking this (also touches §6): `time_utc` is not UTC.**

```
GET /api/data?location=south-bend
  half_hour[0]  time = "2026-10-06T08:00"
                time_utc = "2026-10-06T08:00:00.000Z"      <- local wall clock relabelled Z
                interval_start_utc = "2026-10-06T11:30:00.000Z"
                interval_end_utc   = "2026-10-06T12:00:00.000Z"   <- the true UTC instant of that label
                solar_elevation_deg = 1.52                        <- dawn, only true for 12:00Z / 08:00 EDT
```

Across the frame: `time_utc == time + "Z"` on **163/163** hourly and **326/326** half-hour rows, i.e. every `time_utc` is exactly the site's UTC offset (4 h) early. Source: `opportunity.py:786-787` — `if "time_utc" not in out.columns and "dt" in out.columns: out["time_utc"] = pd.to_datetime(out["dt"], utc=True)`, where the 30-min frame's `dt` is the **naive local** stamp (`opportunity.py:421-422`), so `utc=True` labels local as UTC. The correctly-UTC companions (`interval_start_utc`/`interval_end_utc`/`interval_midpoint_utc`) are inconsistent with it by 4 h. No client code reads `time_utc` (0 occurrences in the served HTML), so this is an API-consumer hazard only — but any consumer converting `time_utc` to local time gets a 4-hour error.

---

## Summary of findings

**CONFIRMED defects**
1. `summary.skin_type` is `null` while requested rows carry `fitzpatrick_type` (§2); the field is run-time metadata, and a future refresh with a skin type would contaminate it for all later requests.
2. Three client-error cases return **500** instead of 4xx (§4): unknown location, `skin_type=abc`, `skin_type=99`.
3. `min_temp=` (empty) → **422 with a structured `detail` array**, which the client renders as `Could not load forecast: [object Object]. …`; leaving the Min °F box empty breaks the page load (§4).
4. `surface=custom` is advertised in the 400 message but is unreachable over HTTP, with a message about CLI flags (§3).
5. `surface_extent` has no effect beyond echoing `surface_extent_mode`, and no client sends it (§1).
6. `skin_azimuth_deg` has **zero** effect at the UI's default Tilt 0 (§1); `surface` has zero physical effect at Tilt 0 too (metadata only).
7. `personal_mmd_basis` changes only the echoed `personalization_basis` string — no conversion, despite a label promising one (§1).
8. `time_utc` is local wall clock stamped `Z`, 4 h off from the row's true UTC instant carried in `interval_end_utc` (§7).
9. `GET /api/data?location=pacific-palisades` serves a two-week-stale, pre-v5 frame (no `uvi_consensus`, `erythemal_irradiance_wm2`, `tan_dose_*`/`delayed_pigmentation_dose_*`, `skin_plane_*`, `interval_*`, `time_utc`; hero renders `— — E_mel J/m²`; the calendar feed contains only past events) (§1.8, §6.4).

**REFUTED**
- "every control produces the effect its label promises": refuted for azimuth-only, surface-without-tilt, `surface_extent`, and `personal_mmd_basis` (§1).
- "the client string-concatenation of `detail` always yields a readable message": the string cases are readable in the 400s, but 422s and the 3 swallowed-`HTTPException` cases produce `[object Object]` or a `"404: …"` prefix (§4).

**UNVERIFIED / not exercised**
- §5 invariants on the palisades frame (columns absent there).
- `POST /api/refresh` (forbidden in this audit): the `summary.json` skin-type contamination and the `skin_type=…` refresh path are read from code only.
- Whether any other consumer reads `time_utc` (outside this repo: unknown).