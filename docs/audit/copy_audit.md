# SunStack web-UI copy audit

Observation-only. No implementation file was modified by this audit.

**Line-reference convention.** `serving.py:N` = `src/sunstack/serving.py:N`, `output.py:N` = `src/sunstack/output.py:N`,
`ui.py:N` = `src/sunstack/ui.py:N`. Where copy that the UI renders lives in a data layer (`tanscore.py`, `opportunity.py`,
`surface.py`) the finding says so and quotes it.

**Verified facts used below** (quoted with references):

- The whole client is one Python string: `serving.py:519` — `HTML = r"""<!doctype html>`.
- The static export swaps copy in place: `output.py:12` — `raise RuntimeError(f"static export anchor drifted ({found}x): {old[:70]!r}")`.
- `/api/calendar.ics` ignores three of the parameters the live UI sends: `ui.py:228` — `# Calendar ranking is
  environmental-horizontal; validated UI context is ignored.` and the call it makes is `_, hourly, _, daily, summary =
  _filtered_payload(root, st, min_temp, site)` (`ui.py:229`), i.e. `surface`, `surface_extent`, `skin_tilt_deg`,
  `skin_azimuth_deg` fall back to defaults.
- The http error detail strings that can reach a user's screen are `ui.py:42` (`f"surface_extent must be one of
  {list(SURFACE_EXTENT_MODES)}, got {mode!r}"`), `ui.py:57`/`ui.py:61`
  (`f"{name} must be a finite number in [0, {high:g}], got {text!r}"`), `ui.py:114`/`ui.py:179`/`ui.py:223`
  (`f"invalid skin_type: {skin_type!r}"`), `ui.py:175` (`"live refresh unavailable: server started without a runner"`),
  `ui.py:201` (`f"LIVE REFRESH FAILED: {exc}"`), `serving.py:39` (`f"unknown location: {slug}"`), `serving.py:57`
  (`"No SunStack run found. Click Refresh or run \`uv run sunstack run\`."`), `serving.py:105`
  (`"Latest run is missing TanScore output tables; refresh the data."`), `surface.py:158`
  (`f"unknown surface {slug!r}; allowed: {sorted(PRESETS)}"`), `serving.py:507-508`
  (`f"personal_mmd must be a number in melanogenic-effective J/m^2, "` / `f"got {mmd_text!r}"`), `serving.py:511`
  (`f"personal_mmd must be a positive finite dose, got {mmd_text!r}"`), `serving.py:514-515`
  (`f"personal_mmd_basis must be one of {list(_PERSONAL_MMD_BASES)} "` / `f"when personal_mmd is given, got {basis_text!r}"`).
- Static-export copy differs from live: `output.py:70` — `f'</div><div class="controls actions" role="group"
  aria-label="Actions"><span class="note">Static export · min {min_temp_f:g}°F · reruns publish fresh data</span>'`;
  `output.py:64` replaces `'<label>Min °F <input id="mintemp" type="number" min="32" max="80" step="1" value="50"
  style="width:64px"></label>'` with a hidden input; `output.py:86` appends `' Static page: local client-side reflection
  only; broad/homogeneous extent needs backend RT.'` to the Surface `title`. The committed published page confirms the
  swap: `docs/index.html` contains `Static export · min 50°F · reruns publish fresh data` and contains `Min °F` zero times.

---

## 1. Inventory

### 1.1 Page title and header

| Element | Exact text | Source |
|---|---|---|
| `<title>` | `Sunlight hours — SunStack` | serving.py:521 |
| `<h1>` | `Sunlight hours` | serving.py:591 |
| runline, initial | `Loading forecast…` | serving.py:591 |
| runline, runtime (assembled) | `'Updated '+fmtTime(s.created_at)+' · '+(DATA.hourly\|\|[]).length+' hourly rows · forecast '+fc` + `' (page '+rc+')'` + `' · absolute is provisional global scale, local is this location\u0027s percentile'` | serving.py:636 |
| time fallback | `'unknown time'` | serving.py:606 |

### 1.2 Control labels, options, aria-labels and tooltips

| Element | Exact text | Source |
|---|---|---|
| settings group `aria-label` | `Display settings` | serving.py:592 |
| actions group `aria-label` | `Actions` | serving.py:594 |
| `Location` label + placeholder option | `Location` / `Loading…` | serving.py:592 |
| `Skin` label + default option | `Skin` / `None` | serving.py:592 |
| Skin options | `I`, `II`, `III`, `IV`, `V`, `VI` | serving.py:592 |
| MMD `<summary>` + its tooltip | `I have my MMD` / `Only if you have a measured or estimated personal MMD` | serving.py:592 |
| `My MMD` input label, placeholder, tooltip | `My MMD` / `J/m²` / `Measured/estimated personal MMD in melanogenic-effective J/m² — leave blank unless you know yours` | serving.py:592 |
| `basis` label, empty option, option labels, tooltip | `basis` / `—` / `SUNSTACK_EFFECTIVE`, `SOURCE_SPECTRUM`, `OBJECTIVE_ESTIMATE`, `COARSE_ESTIMATE` / `Where the MMD number came from: SUNSTACK_EFFECTIVE (this exact action-spectrum basis), SOURCE_SPECTRUM (convertible lamp spectrum), OBJECTIVE_ESTIMATE (instrument data), COARSE_ESTIMATE (rough traits, wide uncertainty)` | serving.py:592 |
| `Min °F` label | `Min °F` | serving.py:593 |
| `Surface` label + tooltip | `Surface` / `Ground around you: changes reflected skin-plane exposure only, never horizontal environment` | serving.py:593 |
| Surface options (14) | `Unknown`, `Summer grass`, `Winter grass`, `Dry sand`, `Wet sand`, `Light concrete`, `Aged concrete`, `Fresh asphalt`, `Aged asphalt`, `Wood deck`, `Open water`, `Sea foam`, `Fresh snow`, `Aged snow` | serving.py:593 |
| `Tilt` / `Azimuth` labels | `Tilt` / `Azimuth` | serving.py:593 |
| pose note | `At the default flat, horizontal pose, ground reflection is geometrically zero; recline or stand the plane to see the surface effect.` | serving.py:593 |
| buttons | `Apply`, `Refresh forecast`, `Export CSV` | serving.py:594 |
| calendar link + tooltip | `Calendar` / `Subscribe to the best-window calendar` | serving.py:594 |
| chart nav `aria-label`s | `Chart panels`, `Previous chart`, `Next chart` | serving.py:601 |
| day strip `aria-label` | `Days` | serving.py:599 |
| sun figure `aria-label` | `Sun position and recline figure` | serving.py:602 |
| Sun-figure `Time` label | `Time` | serving.py:602 |
| columns button tooltip | `Show all 20 columns` | serving.py:690 |
| nerd toggle labels | `Show all columns` / `Hide extra columns` | serving.py:690, 646, 692 |
| class toggle | `Show my classes (ET, Mon–Fri)` | serving.py:690 |

### 1.3 The four `<details>` summaries

| Summary | Exact text | Source |
|---|---|---|
| personal MMD | `I have my MMD` | serving.py:592 |
| photobiology | `Advanced / Photobiology` | serving.py:600 |
| glossary | `Column glossary` | serving.py:602 |
| source data | `Source data` | serving.py:603 |

### 1.4 Legend, glossary, hero, day cells

| Element | Exact text | Source |
|---|---|---|
| legend paragraph | `Ranking is maximum expected 30-minute delayed-pigmentation dose (fixed-duration-dose-v2). Overall is a LEGACY composite (deprecated product heuristic); UV∘ is headline UVI fusion, while TanDose comes from the UVA/UVB model.` | serving.py:597 |
| hero, initial | `Finding the best light…` | serving.py:596 |
| hero, runtime | `<b>${dayName(b.date)}</b> Strongest 30 min ${winStr(strongStart,strongEnd)} — ${f1(...)} E_mel J/m²; best usable 30 min ${winStr(usableStart,usableEnd)} — ${f1(...)} E_mel J/m² (confidence ${f0(usableRow.tan_forecast_confidence_0_100)}). Local ${f0(...)} · Overall ${f0(...)} · Abs ${f0(...)}. Surface ${esc(surfaceName)}; backend ${esc(backend)} (tier ${esc(tier)}).` / `'No usable light in this run.'` | serving.py:644 |
| skin context line | `'<b>'+esc(r.fitzpatrick_label)+'</b> — '+esc(r.skin_response_note\|\|'')` (hidden until data loads) | serving.py:637 |
| glossary paragraph (in `<details>`) | `UV∘ consensus UVI (headline) · OM/CAMS/EPA per-source UVI · Clear cloud-free UVI · ΔUV max source spread (flag ≥1.0, strong ≥2.0) · UVA/UVB predicted W/m² · Temp °F + feels-like · Wind mph + gust · Cloud % · Rain % (≥40 wet) · DNI direct beam W/m² · Overall LEGACY composite 0–100 (deprecated product heuristic) · Abs worldwide strength · Local location percentile · Atm geometry-conditioned transmission percentile · Conf confidence (cut when sources disagree).` | serving.py:602 |
| in-page gloss paragraph (restates legend) | `UV∘ Headline UVI (bias-corrected inverse-error fusion of OM Best Match + CAMS + EPA) · ΔUV source-range spread flags disagreement · Ranking is maximum expected 30-minute delayed-pigmentation dose (fixed-duration-dose-v2); Overall is a LEGACY composite (deprecated product heuristic) · All columns stay in the page — hidden ones are one tap away and always in Export CSV.` | serving.py:690 |
| gloss override after render | `Ranking is maximum expected 30-minute delayed-pigmentation dose (fixed-duration-dose-v2). Overall is a LEGACY composite (deprecated product heuristic).` | serving.py:696 |
| day cell — day name / date | `esc(shortDay(d.date))` / `esc(d.day_status\|\|'')` | serving.py:642 |
| day cell — rain chip | `${f0(pp)}% rain` + `<span class="txt">· wet</span>` | serving.py:642 |
| day cell — window | `${winStr(d.best_window_start,d.best_window_end)}` | serving.py:642 |
| day cell — class chip | `🎓 ${cs} ET` | serving.py:642 |
| day cell — chips and tooltips | `Int ${f0(...)}` (`title="Intensity: absolute melanogenic strength (provisional global scale)"`), `Fit ${f0(...)}%` (`title="Outdoor fit: share of daylight half-hours not hard-blocked"`), `Conf ${f0(...)}` (`title="Forecast agreement at the peak hour"`), `UV ${f1(...)} · ${f1(...)}–${f1(...)}°`, `Feels ${f1(...)}–${f1(...)}°`, `Gust ${f0(...)}` + `windy`, `Abs ${f0(...)} · Loc ${f0(...)}` | serving.py:642 |
| day header | `· Overall ${f0(...)}`, `Local ${f0(...)} · Abs ${f0(...)}`, `opportunity: ${esc(d.day_status\|\|'')}` | serving.py:688 |
| best line | `Good window (longest near-peak) <b>…</b> · best hour ${hhmm(...)} (${f0(...)}) · peak 30-min dose ${f0(...)} J/m² · peak UV ${f1(...)} · ${f1(...)}°F · ${f0(...)} blocked half-hours. Rows tinted below fall inside the good window.` + `free for you: ${hhmm(...)}–${hhmm(...)}` | serving.py:689 |
| class row note | `Purple rows = in class — plan around them` | serving.py:690 |
| day status vocabulary (data layer, rendered by the UI) | `UNKNOWN`, `EXCELLENT`, `VERY GOOD`, `GOOD`, `FAIR`, `POOR`, `NO OUTDOOR WINDOW` | opportunity.py:1245-1258 |
| comfort bands (data layer, rendered in the Temp cell) | `perfect`, `too cold`, `cool`, `sun-warmed`, `warm`, `too hot` | opportunity.py:207-213 |
| outdoor block reasons / flags (data layer, rendered in the Note cell) | `precipitation in interval/code`, `snowfall in interval/code`, `thunderstorm`, `snow-covered ground`, `unknown (missing weather)`, `temperature >= {N}F`, `temperature < {N}F`; `cold`, `heat`, `{N}% precipitation risk`, `windy`, `humid/sweaty`, `high apparent temperature` | opportunity.py:167-196 |
| posture guidance (data layer, rendered in the sun caption) | `sun below horizon — no direct-sun posture`, `sun {N}° up ({C}) — lay flat on back, face up`, `sun {N}° up ({C}) — lay flat, or lift torso ~{N}° toward {C} to face it`, `sun low {N}° ({C}) — face {C}, lift torso ~{N}° toward the sun if comfortable` | tanscore.py:477-489 |

### 1.5 Doses panel

| Element | Exact text | Source |
|---|---|---|
| heading | `Doses — intensity vs accumulated exposure` | serving.py:600 |
| loading state | `Loading doses…` | serving.py:600 |
| doses row, runtime | `TanDose peak 30 min <b>${f1(d.best_30m_tan_dose_j_m2)} J/m² mel</b> (${hhmm}) · best hour <b>${f1(...)} J/m²</b> (${hhmm}) · best window <b>${f1(...)} J/m²</b> · today <b>${f1(...)} J/m²</b> (…)` | serving.py:625 |
| reference-exposure chip | `Normalized reference exposure: ${(d.tan_dose_day_reference_minutes/60).toFixed(1)} ref-hours (model normalization, not a recommended exposure duration)` with `title="Equivalent minutes at the fixed global-reference melanogenic irradiance. Not safe minutes, minutes-until-tan, minutes-until-burn, or exposure advice."` | serving.py:625 |
| SED segment | `SED peak 30m ${f2(...)} · window ${f2(...)} · today ${f2(...)}` | serving.py:625 |
| partial marker | `' (partial)'` | serving.py:625, serving.py:260 |
| personal-MMD segments | `Your MMD: <b>N×</b> (30-min, client-side · {basis}) · day: <b>N×</b>` and `Peak 30-min MMD fraction: <b>N×</b> ({basis}) · Daily TanDose / MMD: <b>N×</b>` | serving.py:625 |
| advanced row | `UVA day … J/m² · UVB day … J/m² \| Visible-Darkening Potential (peak 30m) … J/m² existing-pigment (not new melanin) \| spectral tier {tier} ({backend}) · action spectrum {name}` + `checksum ✓` + ` · global ref {v} ({N} W/m²) · UVI disagreement {N}% (moves confidence, not physics)` | serving.py:625 |
| provenance row | `Model {v} · spectrum tier {t} · spectral {b} ({tier}) · global ref {v} ({N} W/m²) · CAMS {cycle} · UVI agree {N}% · calib {tier} · UVA model: same-domain MAE 0.33 W/m², live NWP-fed MAE ~5.8 (train/serve shift, see Research notes)` | serving.py:625 |
| surface-context line (live override of provenance) | `Surface ${surfaceName} · proxy ${N}% · reflected E_mel ${N} W/m² · tilt ${T}° azimuth ${A}° · spectral ${b} / tier ${t} · fusion ${v} · confidence ${v} · rank ${v}` with fallback `'Unknown surface'` | serving.py:627 |
| surface-context (static export) | `' · spectral '+…+' (tier '+…+') · fusion '+…+' · confidence '+…+' · rank '+…`; `'Surface '+name+' · broad extent requires backend RT'+tail`; `'Surface '+name+' (client-side) · proxy '+N+'% · reflected context '+N+' W/m² broadband proxy · tilt '+T+'° azimuth '+A+'°'+tail` | output.py:96-101 |

### 1.6 Chart panel names and descriptions

| Element | Exact text | Source |
|---|---|---|
| charts heading | `Day charts (separate panels — SED is exposure, never “good”)` | serving.py:601 |
| panel selector text | `(CHARTI+1)+" of "+cs.length+" — "+CHARTS[CHARTI][1]` | serving.py:630 |
| panel names | `TanScore 0–100 (instantaneous intensity)`, `TanDose J/m² (cumulative exposure)`, `SED (cumulative sunburn load)` | serving.py:629 |
| canvas tooltips | `TanScore 0–100 — instantaneous intensity, best window shaded`; `Cumulative TanDose — exposure odometer, higher is more dose not better`; `Cumulative SED — sunburn load, never good` | serving.py:601 |
| hover tip (dynamic) | `hhmm(CHARTTIMES[n])+" — "+c.id.replace("chart","")+" #"+(n+1)` → renders `2:30 PM — Sed #8` | serving.py:632 |
| panel note | `TanScore fixed 0–100 (top, instantaneous intensity); cumulative TanDose melanogenic J/m² (middle, exposure odometer); cumulative SED (bottom, sunburn-weighted exposure, never “good”). Shaded band = best window. Pigment-darkening lives in tables under Advanced, never merged into TanScore.` | serving.py:601 |
| axis end-value units | `' J/m²'` (TanDose), `' SED'` (SED) | serving.py:628 |

### 1.7 Sun-position figure

| Element | Exact text | Source |
|---|---|---|
| caption, initial | `Pick a time to see the sun position and posture.` | serving.py:602 |
| caption, runtime | `<b>${hhmm(row.time)}</b> — ${esc(row.sun_posture_guidance\|\|'')} (UV ${f1(row.uv_index)}, overall ${f0(row.overall_tan_opportunity_0_100)})` | serving.py:671 |
| figure note | `Legs stay flat, parallel to the ground — only the torso lifts. Click any table row to inspect that time. Guidance is geometry context, not a score. Headline TanScore/TanDose is the horizontal environmental reference; facing the sun is not modeled.` | serving.py:602 |
| SVG labels | `ground`; `sun below horizon`; `no direct-sun posture` | serving.py:671 |
| SVG `<title>` | `sun ${elev.toFixed(0)}° up, ${row.sun_compass\|\|''}` | serving.py:671 |
| SVG footer label | `face ${row.sun_compass\|\|'—'} · torso ~${Math.round(lift)}°` | serving.py:671 |
| time selector options | `${hhmm(x.time)} — sun ${f0(x.solar_elevation_deg)}° ${esc(x.sun_compass\|\|'')}` | serving.py:673 |

### 1.8 Table column headers

| Table | Headers | Source |
|---|---|---|
| Every hour | `Time`, `UV∘`, `OM`, `CAMS`, `EPA`, `Clear`, `ΔUV`, `UVA`, `UVB`, `Temp`, `Wind`, `Cloud`, `Rain`, `DNI`, `Overall`, `Abs`, `Local`, `Atm`, `Conf`, `Note` (20) | serving.py:690 |
| header tooltips | `Local hour`; `Headline UVI (bias-corrected inverse-error fusion) — drives the SED channel`; `OM = Open-Meteo Best Match UVI (not GFS-only)`; `CAMS = Copernicus spectral UVI`; `EPA = NWS operational UVI by ZIP`; `Clear-sky UVI — cloud-free value, compare with UV∘ for cloud suppression`; `Max UVI spread across sources — disagree flag at ≥1.0, strong at ≥2.0`; `Predicted UVA irradiance W/m²`; `Predicted UVB irradiance W/m²`; `Total cloud cover %`; `Precipitation probability % — bold red at ≥40`; `Direct normal irradiance, instantaneous W/m²`; `Overall tanning opportunity 0–100 — LEGACY composite (deprecated product heuristic)`; `Absolute melanogenic strength — worldwide scale`; `Local percentile — how rare this is for this location`; `Atmospheric quality percentile — air clarity`; `Forecast confidence 0–100 — discounted when sources disagree` | serving.py:690 |
| section heading | `Every hour — Headline UVI first` | serving.py:690 |
| Every 30 minutes | heading `Every 30 minutes`; headers `Time`, `UV`, `UVA`, `Overall`, `Local`, `Source`, `Note` (7) | serving.py:691 |
| in-row source labels | `'30-min · HRRR wx/rad + interp UV'`, `'hourly split'`, or `(x.subhour_source\|\|'').slice(0,24)` | serving.py:687 |
| in-row sun chip | `☀ ${f0(x.solar_elevation_deg)}° ${esc(x.sun_compass\|\|'')}` | serving.py:686 |
| disagreement notes | `UV/broadband inputs disagree on cloud`, `UVI sources disagree`, plus raw `outdoor_block_reason` text | serving.py:681 |
| source-range tooltip | `Source range ${hi.toFixed(1)} vs ${lo.toFixed(1)} across UVI sources — min/max of visible sources, not a modeled sunny/cloudy scenario` | serving.py:680 |
| spread tooltip | `Disagree flag at spread ≥1.0 UVI, strong at ≥2.0` | serving.py:686 |

### 1.9 Status messages (`show()` calls)

| Message | Class | Source |
|---|---|---|
| `'Loading…'` | `info` | serving.py:621 |
| `'Could not load forecast: '+e.message+'. Check the server log, then Refresh.'` | `error` | serving.py:621 |
| `'Calling live Open-Meteo and CAMS, rebuilding scores (takes minutes)…'` | `info` | serving.py:622 |
| `'Refresh complete.'` | `info` | serving.py:622 |
| `'Refresh failed: '+e.message` | `error` | serving.py:622 |
| `'No forecast data yet.'` | `error` | serving.py:623, 635 |
| `` `Exported all ${dall.length} days (${hours.length} hourly + ${half.length} 30-min rows).` `` | `info` | serving.py:623 |
| `'Dose panel failed to render — see console.'` | `error` | serving.py:646 |
| `'Charts failed to render — see console.'` | `error` | serving.py:646 |

### 1.10 Error messages that can reach the user

| Message | Trigger | Source |
|---|---|---|
| `'Request failed'` / `'Refresh failed'` | `j.detail` absent on a non-OK response | serving.py:621, 622 |
| `Server error` style body from FastAPI | HTTPException details listed in the header of this document | ui.py:42, 57, 61, 114, 175, 179, 201, 223; serving.py:39, 57, 105, 507-515; surface.py:158 |
| `'unknown location: {slug}'` | 404 on `/api/data` | serving.py:39 |
| `'No SunStack run found. Click Refresh or run \`uv run sunstack run\`.'` | 500 on `/api/data` with no run dir | serving.py:57 |
| `'Latest run is missing TanScore output tables; refresh the data.'` | 500 on `/api/data` with empty tables | serving.py:105 |
| `'LIVE REFRESH FAILED: {exc}'` | 500 on `/api/refresh` | ui.py:201 |
| `'live refresh unavailable: server started without a runner'` | 503 on `/api/refresh` | ui.py:175 |
| `'static export anchor drifted (…)'` | build-time only, never rendered in the UI | output.py:12 |

### 1.11 Empty / unknown states

| State | Exact text | Source |
|---|---|---|
| location picker, pre-fetch | `Loading…` | serving.py:592 |
| runline, pre-fetch | `Loading forecast…` | serving.py:591 |
| doses, pre-fetch | `Loading doses…` | serving.py:600 |
| source data, pre-fetch | `Loading…` | serving.py:603 |
| no hourly rows | `No hourly rows for this day.` | serving.py:690 |
| no 30-minute rows | `No 30-minute rows for this day.` | serving.py:691 |
| no light at all | `No usable light in this run.` | serving.py:644 |
| no data loaded | `No forecast data yet.` | serving.py:623, 635 |
| missing numeric value | `'—'` (`const f0=n=>n==null\|\|Number.isNaN(+n)?'—':…`) | serving.py:607-609, 613, 616 |
| missing sun time | `'unknown time'` | serving.py:606 |
| night in the figure | `sun below horizon`, `no direct-sun posture` | serving.py:671 |
| surface unknown in provenance | `'Unknown surface'` | serving.py:627 |
| skin note when no context data | element hidden (`el.hidden=true`) | serving.py:637 |

### 1.12 Calendar (ICS) copy served by `/api/calendar.ics` and `calendar-30min.ics`

| Element | Exact text | Source |
|---|---|---|
| daily calendar name | `X-WR-CALNAME:SunStack best sun windows` | serving.py:482 |
| daily event summaries | `Best usable sun {s}-{e} (dose {n} J/m2 E_mel)`; `Strongest 30m {s}-{e} (dose {n} J/m2 E_mel)`; `Best sun {s}-{e} (UV {n}, overall {n})`; `Best sun {s}-{e} (overall {n})` | serving.py:376-462 |
| daily description parts | `Best usable 30m … (dose … J/m2 E_mel)`; `Strongest 30m … is blocked by hard outdoor constraints`; `Overall {n}/100`; `Local {n}`; `Local@best {n}`; `Abs {n}`; `Peak UV {n} at {t}`; `UVA {n} W/m2`; `UVB {n} W/m2`; `UV index {n}`; `TanDose window {n} J/m2 mel`; `TanDose day {n} J/m2 mel`; `SED window {n}`; `SED day {n}`; `UVA day {n} J/m2`; `UVB day {n} J/m2`; `Confidence {n}`; `Times refresh with each SunStack run.` | serving.py:387-449 |
| interval calendar name | `X-WR-CALNAME:SunStack 30-min doses` | serving.py:324 |
| interval summaries/descriptions | `Sun {HH:MM} (ABS 45/100)`; `Abs {n}/100`, `Overall {n}/100`, `Local {n}/100`, `TanDose30 {n} J/m2 mel`, `SED30 {n}`, `UVA30 {n} J/m2`, `UVB30 {n} J/m2`, `Conf {n}`, `native HRRR`, `interpolated hourly`, `tier {t}`, plus raw `outdoor_block_reason`/`outdoor_flags` | serving.py:286-318 |

---

## 2. Findings

| Location | Existing text | Problem | Exact replacement | Rationale |
|---|---|---|---|---|
| serving.py:521 (and its static copy) | `Sunlight hours — SunStack` | Nothing on the page reports sunlight hours. The page reports a 0–100 dose score, a UV index, a dose panel and outdoor usability. First-time users will read "hours" literally. | `SunStack — 30-minute UV and tanning forecast` | The title must name what the page measures. The page's own ranking concept is a 30-minute dose. |
| serving.py:591 | `Sunlight hours` | Same mismatch as the `<title>`, and it duplicates the brand instead of naming the place and time horizon. | `30-minute sun forecast` | `<h1>` should say the product and the horizon; "Sunlight hours" implies a sunrise/sunset table. |
| serving.py:594 | `Apply` | Vague. It is not stated what is applied, and it is the only way to re-run the query after changing six controls. | `Update forecast for these settings` | Names the effect (re-fetch `/api/data` with the current control values) and the scope of the settings. |
| serving.py:594 | `Refresh forecast` | "Refresh" reads as a cheap page reload, but the handler calls `POST /api/refresh`, and the status message admits it takes minutes (`serving.py:622`). | `Run live forecast now (takes minutes)` | Sets the expectation the code already knows: `'Calling live Open-Meteo and CAMS, rebuilding scores (takes minutes)…'`. |
| serving.py:594 | `Export CSV` | Ambiguous scope: it exports every day, every hour and every 30-minute row regardless of the selected day and the hidden columns, and the handler is even named `exportVisibleCsv`. | `Download CSV (all days, all rows)` | States the real scope; the success message already says `'Exported all ${dall.length} days …'`. |
| serving.py:594 | `Calendar` with `title="Subscribe to the best-window calendar"` | The label does not say it is a subscription, and the tooltip promises the user's settings reach the calendar, but `ui.py:228` says `# Calendar ranking is environmental-horizontal; validated UI context is ignored.` — `surface`, `surface_extent`, `Tilt` and `Azimuth` are dropped (`ui.py:229` passes only `st`, `min_temp`, `site`). | Label `Subscribe to calendar`; tooltip `Subscribe to a calendar of best sun windows for this location (your surface, tilt and azimuth are not applied)` | The copy must match `/api/calendar.ics`: skin type and minimum temperature are honoured; the surface and pose are not. |
| serving.py:690, 646, 692 | `Show all columns` / `Hide extra columns`, tooltip `Show all 20 columns` | The tooltip is only correct in the initial state: both toggles set `textContent` and `aria-pressed` and never update `title`, so after one click the button reads `Hide extra columns` while its tooltip still says `Show all 20 columns`. | Button text `Show 12 extra columns` / `Hide 12 extra columns`; tooltip in both states `Toggle the 12 hidden columns (all rows still export)` | The count is stable and verifiable (20 `<th>` in the header row, 12 of them `class="nerd"`), so the tooltip no longer lies after the toggle. |
| serving.py:690 | `Show all 20 columns` | Absolute count goes stale the moment a column is added, and it never states which rows are affected. | `Toggle the 12 hidden columns (all rows still export)` | Counts the hidden set instead of the total, so it survives column additions. |
| serving.py:594, 623 | `Export CSV` pressed on the 30-minute table | The button is global; pressing it while the "Every 30 minutes" table is on screen still downloads three files (hourly, 30-minute, daily). | `Download CSV (3 files: hourly, 30-minute, daily)` | Says exactly what lands in the Downloads folder. |
| serving.py:592 | `<summary …>I have my MMD</summary>` | First-person summary; "MMD" is an unexplained acronym at the point of first contact. | `Enter a personal MMD (optional)` | Second person, states the input, marks it optional. |
| serving.py:592 | `My MMD` / placeholder `J/m²` | "My MMD" is first-person and the placeholder states `J/m²` while the value must be melanogenic-effective joules (the tooltip says so). | Label `Personal MMD (J/m² E_mel)`; placeholder `e.g. 800 J/m² E_mel` | States the unit that the validator actually enforces (`serving.py:507`: `"personal_mmd must be a number in melanogenic-effective J/m^2, "`). |
| serving.py:592 | `Measured/estimated personal MMD in melanogenic-effective J/m² — leave blank unless you know yours` | Second-person clause adds nothing after the unit has been stated; "you know yours" is informal for a numeric input that rejects bad values loudly. | `Minimal melanogenic dose you measured or estimated, in J/m² E_mel. Leave blank if you do not have a value.` | Keeps the validation contract (`SUNSTACK_EFFECTIVE_DOSE_MEASURED` etc. require a real measured dose) in plain language. |
| serving.py:592 | `basis` label and options `SUNSTACK_EFFECTIVE`, `SOURCE_SPECTRUM`, `OBJECTIVE_ESTIMATE`, `COARSE_ESTIMATE` | Internal enum names are shown verbatim as UI options; a first-time user cannot choose. | Label `MMD source`; options `Measured with SunStack`, `Measured lamp/spectrum`, `Instrument estimate`, `Rough personal estimate` | The tooltip already translates each enum; the option text should carry that translation. |
| serving.py:592 | `Skin` / default option `None` | "None" reads as "no skin", and the Roman numerals `I`–`VI` are unexplained Fitzpatrick types. | Label `Skin (Fitzpatrick I–VI)`; default option `Not set` | Names the scale and makes the empty option an explicit "not chosen" state. |
| serving.py:593 | `Min °F` | Abbreviation only; static-export readers see the applied value in `Static export · min 50°F · reruns publish fresh data` (`output.py:70`) with no label explaining it. | `Minimum outdoor temperature °F` | Reads as a sentence, so the static note and the live label describe the same control. |
| serving.py:593 | `Tilt` / `Azimuth` | Units are implied by input attributes only (`min="0" max="180"`, `min="0" max="360"`); no `°`, and no convention for azimuth, even though the JS prints `tilt ${tilt}° azimuth ${azimuth}°` (`serving.py:627`). | `Tilt °` and `Azimuth ° (0 = north, 90 = east)` | The figure prints the same values with `°` and the compass ring uses north-zero (`serving.py:648`), so the label must match. |
| serving.py:593 | `At the default flat, horizontal pose, ground reflection is geometrically zero; recline or stand the plane to see the surface effect.` | 21 words of prose for a control hint; "recline or stand the plane" is body-posture instruction in a settings row. | `Flat pose = no ground reflection. Tilt the plane to see the surface effect.` | Same facts, 13 words, no posture advice. |
| serving.py:593 | `Unknown` (Surface option) | Reads as a statement about the ground, not about the data. | `Not set / not sure` | It is the "no surface chosen" state; the code treats it as a slug (`resolve_surface("unknown")`). |
| serving.py:627 | `'Unknown surface'` fallback text | Second name for the same state (`Unknown` in the picker). | `Surface not set` | One name per state. |
| serving.py:597 | `Ranking is maximum expected 30-minute delayed-pigmentation dose (fixed-duration-dose-v2). Overall is a LEGACY composite (deprecated product heuristic); UV∘ is headline UVI fusion, while TanDose comes from the UVA/UVB model.` | 28-word legend whose second sentence is repeated verbatim in two more places (`serving.py:690`, `serving.py:696`); `fixed-duration-dose-v2` is a version string, not language. | `Ranking = best 30-minute delayed-pigmentation dose. UV∘ is the headline UV index; TanDose comes from the UVA/UVB model. Column meanings: see Column glossary.` | Removes the version string and the duplicate LEGACY clause from the always-visible line while keeping the ranking definition. |
| serving.py:690 | `UV∘ Headline UVI (bias-corrected inverse-error fusion of OM Best Match + CAMS + EPA) · ΔUV source-range spread flags disagreement · Ranking is maximum expected 30-minute delayed-pigmentation dose (fixed-duration-dose-v2); Overall is a LEGACY composite (deprecated product heuristic) · All columns stay in the page — hidden ones are one tap away and always in Export CSV.` | 56 words above the first table, and its middle clause duplicates the legend paragraph that sits on the same screen. Two different explanations of the same scoring claim in one viewport. | `Rankings use the best 30-minute delayed-pigmentation dose. Column meanings: see Column glossary. All 20 columns stay in the page and in the CSV.` | Collapses to one sentence per idea and points at the disclosure that owns the long definitions. |
| serving.py:696 | `'Ranking is maximum expected 30-minute delayed-pigmentation dose (fixed-duration-dose-v2). Overall is a LEGACY composite (deprecated product heuristic).'` | A third copy of the legend sentence that overwrites any `.gloss` inside the day detail after render, so the paragraph at `serving.py:690` can be replaced without warning by a different wording. | `See Column glossary for column definitions.` | One owner per explanation; the glossary `<details>` is the place for definitions. |
| serving.py:601 | `Day charts (separate panels — SED is exposure, never “good”)` | The SED caveat is stated three times on the same screen (heading, note, canvas tooltip); a heading should name the section, not argue. | `Day charts (three panels)` | The caveat belongs once, on the SED canvas tooltip. |
| serving.py:601 | `Cumulative TanDose — exposure odometer, higher is more dose not better` | Missing comma (`more dose not better`), "exposure odometer" is a metaphor that has to be decoded, and the unit is absent. | `Cumulative TanDose (J/m² E_mel) — more dose, not better` | Names the unit the payload uses (`tan_dose_1h_j_m2`) and fixes the punctuation. |
| serving.py:601 | `Cumulative SED — sunburn load, never good` | "sunburn load" is jargon; the panel plots `sed_1h`, which is an erythemal dose, dimensionless but never stated. | `Cumulative SED — sunburn-weighted dose; never a target` | Says what is plotted and drops the two-word slogan. |
| serving.py:601 | `TanScore fixed 0–100 (top, instantaneous intensity); cumulative TanDose melanogenic J/m² (middle, exposure odometer); cumulative SED (bottom, sunburn-weighted exposure, never “good”). Shaded band = best window. Pigment-darkening lives in tables under Advanced, never merged into TanScore.` | 35-word paragraph above three canvases; repeats the "never good" caveat a third time; "lives in", "merged into" are informal. | `Top: TanScore 0–100 now. Middle: cumulative TanDose (J/m² E_mel). Bottom: cumulative SED — sunburn-weighted, never a target. Shaded band = best window.` | 24 words, one clause per panel, no duplicated caveat. |
| serving.py:632 | `hhmm(CHARTTIMES[n])+" — "+c.id.replace("chart","")+" #"+(n+1)` → renders `2:30 PM — Sed #8` | The hover tip synthesises a label from the DOM id, producing `Sed` and `Score`, while every other surface writes `SED` and `TanScore`. | `hhmm(${time}) + " — " + CHARTS[CHARTI][1] + ", point " + (n+1)` → `2:30 PM — SED (cumulative sunburn load), point 8` | Reuses the already-defined panel names (`serving.py:629`) instead of inventing a second vocabulary. |
| serving.py:602 | `Pick a time to see the sun position and posture.` | "Pick" is casual for a select control; the sentence does not say where the control is. | `Select a time to see sun position and posture.` | Matches the control (`<select id="sunsel">`, `serving.py:602`). |
| serving.py:602 | `Legs stay flat, parallel to the ground — only the torso lifts. Click any table row to inspect that time. Guidance is geometry context, not a score. Headline TanScore/TanDose is the horizontal environmental reference; facing the sun is not modeled.` | 40-word default-visible paragraph; "horizontal environmental reference" is unreadable for a first-time user and contradicts the posture advice the caption prints. | `Only the torso tilts; legs stay flat. Click a table row to inspect that time. This figure is geometry, not a score.` | 22 words; keeps the plot gesture and the "not a score" caveat and drops the unreadable clause. |
| serving.py:671 caption + tanscore.py:482 | `… — sun 62° up (NE) — lay flat on back, face up` next to `Guidance is geometry context, not a score.` | The caption commands a posture ("lay flat on back, face up") while the paragraph beside it says the content is context, not advice. Two instructions in one card. | Caption keeps the geometry only: `${hhmm} — sun ${elev}° up, ${compass}. Torso ~${lift}° to face it.` | Removes the medical-adjacent instruction and keeps the number the figure already draws. |
| serving.py:642 | `Int ${f0(d.day_absolute_peak_0_100)}` | Same datum is called `Abs` in the hero (`serving.py:644`), `Abs` in the day cell's own bottom line, `Abs` in the table, and `Absolute melanogenic strength` in the tooltip: four names for one number. | `Abs ${f0(d.day_absolute_peak_0_100)}/100` | One name per datum; the tooltip stays the long form. |
| serving.py:642 | `Fit ${f0(100*(1-(+d.blocked_half_hours\|\|0)/Math.max(1,rowsFor(DATA.half_hour,d.date).length)))}%` | "Fit" is not a noun a first-time user owns; the underlying value is the share of daylight half-hours that are not hard-blocked. | `Outdoor ${f0(...)}%` | Uses the same word the section header and tooltips use ("Outdoor fit", "outdoor_block_reason"). |
| serving.py:642 | `Conf ${f0(d.day_confidence_at_peak_0_100)}` and `>Abs ${f0(...)} · Loc ${f0(...)}<` | Abbreviations with no scale: `Conf 68`, `Abs 55`, `Loc 62`. The reader cannot tell these are 0–100. | `Confidence ${f0(...)}/100` and `Abs ${f0(...)}/100 · Local ${f0(...)}/100` | States the scale that the tooltips describe ("Forecast confidence 0–100", "Local percentile"). |
| serving.py:642 | `UV ${f1(d.peak_uv_index??…)} · ${f1(d.day_low_temperature_f??…)}–${f1(d.day_high_temperature_f??…)}°` | Two quantities share one line and one degree sign; the UV index has no unit and the temperature unit is implied by a trailing `°`. | `UV max ${f1(...)} · ${f1(...)}–${f1(...)} °F` | Separates the two readings and names the temperature unit, which the glossary also states as `Temp °F`. |
| serving.py:642 | `Gust ${f0(d.day_peak_gust_mph??…)}` | No unit printed, though the field is `day_peak_gust_mph` and the callout threshold is mph. | `Gust ${f0(...)} mph` | Unit is present in the payload and in the `windy` threshold logic; state it. |
| serving.py:642 | `windy` (red chip at ≥25) | The threshold is hidden in the render code (`wind_speed_10m>=25\|\|wind_gusts_10m>=25`) and appears nowhere in the UI text. | `windy (25+ mph)` | States the cutoff the code uses. |
| serving.py:642 | `· wet` (chip at ≥40% precipitation probability) | "wet" describes weather, not forecast probability; the threshold `pp>=40` is invisible. | `40%+ rain risk` | Names what the number is and the cutoff. |
| serving.py:644 | `<b>${dayName}</b> Strongest 30 min …; best usable 30 min … (confidence …). Local … · Overall … · Abs …. Surface …; backend … (tier …).` | 43-word hero that mixes three different score concepts, uses the unit spelling `E_mel J/m²` while the doses row on the same screen writes `J/m² mel` (`serving.py:625`), and ends with an infrastructure word (`backend`) and an unexplained `tier`. It is the first text a user reads. | `<b>${dayName(b.date)}</b>: strongest 30 min ${winStr(strongStart,strongEnd)}, ${f1(...)} J/m² E_mel. Best usable 30 min ${winStr(usableStart,usableEnd)}, ${f1(...)} J/m² E_mel (confidence ${f0(...)}/100). Overall ${f0(b.day_overall_peak_0_100)}/100.` | Keeps the decision-relevant facts, drops `Local`/`Abs` (already in the day header, `serving.py:688`) and the backend/tier strings. |
| serving.py:688 | `opportunity: ${esc(d.day_status\|\|'')}` | The rendered value is the `day_status` field (`serving.py:446` reads `row.get("day_status")`, produced by `opportunity.py:1239` from `_day_status`), whose values are `EXCELLENT`/`GOOD`/`NO OUTDOOR WINDOW` etc. Labelling them "opportunity:" renames the datum and reads as a fragment. | `status: ${esc(d.day_status\|\|'')}` | The label matches the field name and the vocabulary. |
| serving.py:689 | `Good window (longest near-peak) … Rows tinted below fall inside the good window.` | "Good" is used both as a status word (day status `GOOD`, `opportunity.py:1253`) and as the window qualifier, so the reader cannot tell whether "good window" is the free-text status or the ranked window. | `Best window (longest near-peak) … Tinted rows are inside the best window.` | Reserves "good" for the status vocabulary and reuses "best window", which is what the charts legend already calls it (`Shaded band = best window`). |
| serving.py:689 | `free for you: ${hhmm(...)}–${hhmm(...)}` | "free for you" is owner-specific: the window comes from a hardcoded personal schedule (`serving.py:676` `const CLASSES={1:[[660,735],…]}`, gated to one location at `serving.py:677`). | `free between classes: ${hhmm(...)}–${hhmm(...)}` | Describes the computation (free time between class blocks) rather than an unnamed person's calendar. |
| serving.py:690 | `Show my classes (ET, Mon–Fri)` | First-person and owner-specific: the schedule is a hardcoded constant for `south-bend` only; for every other location `classAt` returns `""` (`serving.py:677`) while the checkbox is still offered. | `Show class blocks (ET, Mon–Fri)` | Descopes the claim to class blocks and avoids implying the user's own timetable is loaded. |
| serving.py:690 | `Purple rows = in class — plan around them` | "in class" is ambiguous between the reader and the schedule, and "plan around them" is advice. | `Purple rows fall inside a class block.` | States the encoding only. |
| serving.py:690 | `<th>Temp</th><th>Wind</th>` (no `title`) | Of the 20 headers only these two carry no tooltip, and their units are stated nowhere in the table (only in the glossary `Temp °F + feels-like · Wind mph + gust`). | `Temp` with `title="Temperature °F; the note adds feels-like when it differs by ≥2°F"`; `Wind` with `title="Wind mph; gusts in bold red at ≥25"` | Brings the two unit-bearing headers in line with the other 18 tooltips and states the thresholds used in the render. |
| serving.py:691 | `<h3>Every 30 minutes</h3>` with headers `UV`, `UVA`, `Overall`, `Local`, `Source` | The same quantities are labelled `UV∘`, `UVA`, `Overall`, `Local` in the hourly table, and `Source` is a row-provenance column with no explanation. | Headers `UV (headline)`, `UVA W/m²`, `Overall /100`, `Local /100`, `Row source` | Aligns the two tables on one vocabulary and adds the missing unit on UVA. |
| serving.py:691 | `Time` | No timezone and no day qualifier, though times are naive site-local wall times formatted by `hhmm` (`serving.py:613`) which reads the `T HH:MM` substring. | `Time (local)` | The hourly table's tooltip already says `Local hour`; make it visible in the 30-minute table too. |
| serving.py:690 | `Every hour — Headline UVI first` | "Headline UVI first" describes column order, not the section, and "Headline" is jargon until the glossary is opened. | `Every hour` | The tooltip on the `UV∘` header already explains the headline concept. |
| serving.py:597, 601, 602, 690 | `UV∘` | The symbol appears four times, three of them outside the one place that explains it (`Column glossary`, `serving.py:602`), and it is read out as "UV" by screen readers with no accessible expansion. | Use `UV` in body copy and headers; keep `UV∘` only inside the Column glossary where it is defined | One symbol, defined once, referenced by a word everywhere else. |
| serving.py:625 | `TanDose peak 30 min … J/m² mel` / `best window … J/m²` / `today … J/m²` and `SED peak 30m 3.2 · window … · today …` | Two different unit conventions in one line (`J/m² mel` for the first three, bare `J/m²` for the rest), and `mel` is an abbreviation the page never defines. | `Peak TanDose (30 min) ${f1(...)} J/m² E_mel · best hour ${f1(...)} J/m² E_mel · best window ${f1(...)} J/m² E_mel · today ${f1(...)} J/m² E_mel`; SED segment `Peak SED (30 min) ${f2(...)} · window ${f2(...)} · today ${f2(...)} (unitless erythemal dose)` | One unit spelling across the panel, and the SED segment states that SED has no unit. |
| serving.py:625 | `Normalized reference exposure: ${(d.tan_dose_day_reference_minutes/60).toFixed(1)} ref-hours (model normalization, not a recommended exposure duration)` with tooltip `Equivalent minutes at the fixed global-reference melanogenic irradiance. Not safe minutes, minutes-until-tan, minutes-until-burn, or exposure advice.` | The label prints `ref-hours` while the tooltip defines the same quantity in minutes; `ref-hours` is an invented unit; the tooltip is a 24-word negation list. | `Reference exposure: 0.4 hours at the global reference irradiance (model normalization — not a recommended time in the sun)` with tooltip `Time at the fixed global-reference melanogenic irradiance. A normalization constant, not safe-exposure, tanning or burning time.` | Unifies the unit on the label the user reads and replaces the list of negations with one positive sentence plus one caveat. |
| serving.py:625 | `Visible-Darkening Potential (peak 30m) … J/m² existing-pigment (not new melanin)` | No such metric is named anywhere else; the underlying field is `pigment_darkening_dose_30m_j_m2`, and the chart note calls the concept `Pigment-darkening` (`serving.py:601`). | `Pigment-darkening dose, peak 30 min: ${f1(pkIp)} J/m² (acts on existing pigment, not new melanin)` | Uses the vocabulary already on the page instead of a third name. |
| serving.py:625 | `spectral tier ${tier} (${backend})` and `UVI disagreement 4.2% (moves confidence, not physics)` | `tier A (emulator)` reads as a grade; `backend`, `calib`, `fusion`, `rank` are implementation vocabulary; "moves confidence, not physics" is an argument, not a label. | `spectral tier ${tier} — backend ${backend}`; `source disagreement ${pct}% (lowers confidence only)` | Labels the value and states the effect without debating. |
| serving.py:625 | `global ref ${esc(sm.global_reference_version\|\|'—')} (${sm.global_reference_e_mel_wm2} W/m²)` | "global ref" is undefined and the quantity has no name; the same value appears as `global ref` here and as `global ref … (… W/m²)` in the provenance row. | `reference irradiance ${v} = ${N} W/m² E_mel` | Names the physical quantity and its unit. |
| serving.py:625 | `UVA model: same-domain MAE 0.33 W/m², live NWP-fed MAE ~5.8 (train/serve shift, see Research notes)` | Model-validation statistics inside the Advanced row; `MAE`, `NWP`, `train/serve shift` are three unexplained terms, and "see Research notes" points outside the page. | `UVA model error: 0.33 W/m² in-domain, ~5.8 W/m² with live weather data (documented in the repository's research notes)` | Expands the acronyms and makes the destination explicit. |
| serving.py:627 and output.py:96-101 | `Surface Dry sand · proxy 12.00% · reflected E_mel 3.42 W/m² · tilt 30° azimuth 180° · spectral emulator / tier A · fusion … · confidence … · rank …` vs static `Surface Dry sand (client-side) · proxy 12.00% · reflected context 1.24 W/m² broadband proxy · tilt 30° azimuth 180° · spectral … (tier …) · fusion … · confidence … · rank …` | Two different sentences for the same line depending on delivery mode, both with `proxy`, `E_mel`, `fusion`, `rank` unexplained; the static one calls a broadband proxy number "reflected context". | Live: `Surface: ${name} · reflectance proxy ${N}% · reflected pigment-darkening irradiance ${N} W/m² · tilt ${T}° · azimuth ${A}° (from north) · ${backend}, tier ${t}`. Static: `Surface: ${name} (computed in your browser) · reflectance proxy ${N}% · reflected broadband proxy ${N} W/m² · tilt ${T}° · azimuth ${A}° (from north) · ${backend}, tier ${t}` | Same sentence shape in both modes, units kept distinct ("pigment-darkening irradiance" vs "broadband proxy"), and the static-mode caveat is implied by "computed in your browser" instead of a second vocabulary. |
| output.py:86 | `' Static page: local client-side reflection only; broad/homogeneous extent needs backend RT.'` appended to the Surface tooltip | The live tooltip is already 14 words; this appends 15 more with two internal abbreviations (`backend RT`, `homogeneous extent`). | ` Static page: reflectance is computed in this browser, so only local surfaces are supported.` | One clause, no undefined acronym. |
| output.py:70 | `Static export · min 50°F · reruns publish fresh data` | "Static export" is a delivery detail; "reruns publish fresh data" does not say who reruns or what a rerun is, and the same sentence must carry the loss of the Min °F control (`output.py:64`) and of the Refresh button (`output.py:69`). | `Published page — no live refresh. Minimum outdoor temperature 50 °F. A new forecast appears when the site is republished.` | States what the reader cannot do here and what the frozen setting is. |
| serving.py:621 | `'Could not load forecast: '+e.message+'. Check the server log, then Refresh.'` | In the static export there is neither a server log nor a Refresh control; the committed page `docs/index.html` contains `Refresh forecast` zero times, so the instruction is unfollowable there. | Live: `Could not load forecast: ${message}. Check the server log, then use Run live forecast now.` Static (override in `output.py`): `Could not load forecast: ${message}. The page's data file (data.json) is missing or stale.` | The recovery step must exist in the mode that shows the message. |
| serving.py:623, 635 | `'No forecast data yet.'` | States the empty state but not the action; in the live UI the action exists one button away. | Live: `No forecast data yet. Use Run live forecast now to create one.` Static: `No forecast data in this page yet — the published data file is empty.` | Every empty state names the next step available in that mode. |
| serving.py:622 | `'Calling live Open-Meteo and CAMS, rebuilding scores (takes minutes)…'` | Gerund fragment, and it names two vendors before it names the effect (`CAMS` is explained nowhere on the page). | `Fetching live Open-Meteo and CAMS data and rebuilding the scores — this usually takes several minutes.` | Complete sentence, expanding the acronym only where it matters. |
| serving.py:646 | `'Dose panel failed to render — see console.'` / `'Charts failed to render — see console.'` | "see console" is developer shorthand as the only remedy, and neither message names the recovery the user can perform. | `The doses panel could not be drawn. Reload the page; if it happens again, open the browser console and report the error.` / `The charts could not be drawn. Reload the page; if it happens again, open the browser console and report the error.` | Gives the user an action before the diagnostic instruction. |
| serving.py:622 | `'Refresh complete.'` | "Refresh" no longer matches the button once the button is renamed, and the message does not say what changed. | `Live forecast updated.` | Consistent with the renamed control and states the outcome. |
| serving.py:636 | `' · absolute is provisional global scale, local is this location\u0027s percentile'` | Two clauses with no verb, using the abbreviations the chips also use, and "this location's percentile" needs the word "of what". | ` · Absolute = provisional worldwide scale; Local = percentile within this location's own history.` | Complete clauses that define both terms where they first appear. |
| serving.py:592 | `aria-label="Display settings"` / `aria-label="Actions"` | "Display settings" describes rendering, but the group changes the forecast inputs; "Actions" names no actions. | `Forecast inputs` / `Forecast actions` | Screen-reader users get the same mental model as sighted ones. |
| serving.py:599 | `aria-label="Days"` | The listbox holds one button per forecast day; "Days" does not say which days or that they are selectable. | `Forecast days — select one` | States the content and the affordance. |
| ui.py:175 | `live refresh unavailable: server started without a runner` | Lower-case, developer-only phrasing that reaches the user as the error text of a failed button press. | `Live refresh is not available in this session. Restart the server with the run command enabled.` | Written for the person who pressed the button. |
| ui.py:201 | `f"LIVE REFRESH FAILED: {exc}"` | Shouting prefix plus a raw exception; the exception text is developer output. | `f"Live refresh failed: {exc}. The previous forecast is still shown."` | Sentence case, no shouting, and it states what the user still has. |
| ui.py:42 | `f"surface_extent must be one of {list(SURFACE_EXTENT_MODES)}, got {mode!r}"` | Parameter names and a Python list repr in user-facing text. | `f"surface extent must be one of {', '.join(SURFACE_EXTENT_MODES)}; got {mode!r}"` | Prose instead of a code repr, and the offending value is still shown verbatim. |
| ui.py:57, 61 | `f"{name} must be a finite number in [0, {high:g}], got {text!r}"` | `{name}` is the raw query parameter (`skin_tilt_deg`, `skin_azimuth_deg`) and `[0, 180]` is interval notation. | `f"{name.replace('_', ' ')} must be a number between 0 and {high:g}; got {text!r}"` | Named in words, range in words. |
| ui.py:114, 179, 223 | `f"invalid skin_type: {skin_type!r}"` | Parameter name and repr. | `f"skin type must be 1–6; got {skin_type!r}"` | States the accepted domain, not the internal name. |
| serving.py:39 | `f"unknown location: {slug}"` | "location" in the UI is the picker labelled `Location`, but the picker sends a slug; the message never says what values work. | `f"unknown location '{slug}'. Choose one of: {', '.join(s.slug for s in config.active_sites())}"` | Tells the caller the accepted values, which the code already has. |
| serving.py:57 | `"No SunStack run found. Click Refresh or run \`uv run sunstack run\`."` | Names a button by a name the UI no longer uses for the failure path, and mixes a shell command into a browser message. | `"No SunStack run found. Use Run live forecast now, or run \`uv run sunstack run\` on the host."` | Matches the renamed control and marks the shell command as a host-side alternative. |
| serving.py:105 | `"Latest run is missing TanScore output tables; refresh the data."` | "refresh the data" is passive; the tables are named in internal vocabulary. | `"The latest run has no hourly/30-minute dose tables. Use Run live forecast now to rebuild them."` | Names the missing tables and the exact action. |
| serving.py:507-508, 511, 514-515 | `"personal_mmd must be a number in melanogenic-effective J/m^2, got …"` / `"personal_mmd must be a positive finite dose, got …"` / `"personal_mmd_basis must be one of […], got …"` | Parameter names, `J/m^2` ASCII caret, and a Python list of enum strings. | `"personal MMD must be a positive number of melanogenic-effective J/m²; got …"` / `"the MMD source is required when a personal MMD is given; choose one of: Measured with SunStack, Measured lamp/spectrum, Instrument estimate, Rough personal estimate"` | Same 400 status, human wording, one message instead of two near-duplicates. |
| surface.py:158 (rendered by the UI) | `f"unknown surface {slug!r}; allowed: {sorted(PRESETS)}"` | A sorted Python list of slugs is presented as the list of allowed values. | `f"unknown surface {slug!r}; allowed: {', '.join(sorted(PRESETS))}"` | Readable list in the same order. |
| serving.py:482 and 376-462 (ICS) | `X-WR-CALNAME:SunStack best sun windows`; `Best usable sun 1:00 PM-1:30 PM (dose 3.4 J/m2 E_mel)`; `Strongest 30m … is blocked by hard outdoor constraints`; `Times refresh with each SunStack run.` | The calendar name and event titles use a different vocabulary (`Best usable sun`, `Strongest 30m`, `hard outdoor constraints`) than the page (`best usable 30 min`, `strongest 30 min`, `blocked half-hours`), and the units are ASCII `J/m2 mel` while the page writes `J/m² E_mel`. | Calendar name `SunStack — best sun windows`; summaries `Best usable 30 min 1:00–1:30 PM — 3.4 J/m² E_mel`, `Strongest 30 min 1:00–1:30 PM — 3.4 J/m² E_mel (blocked by outdoor limits)`; trailing line `Times update with each SunStack run.` | The calendar is the same product read elsewhere; one vocabulary and one unit spelling. |
| serving.py:324 (ICS) | `X-WR-CALNAME:SunStack 30-min doses` | "doses" alone does not say which dose, while the events carry eight different metrics (`Abs`, `Overall`, `Local`, `TanDose30`, `SED30`, `UVA30`, `UVB30`, `Conf`). | `SunStack — 30-minute dose and weather detail` | Names the content of the events. |

---

## 3. Terminology map

| Concept | Every variant found | Canonical term |
|---|---|---|
| Delayed-pigmentation dose | `TanDose` (serving.py:601, 625, 629, 594-adjacent CSV), `delayed-pigmentation dose` (serving.py:597, 690, 696), `melanogenic J/m²` (serving.py:601), `J/m² mel` (serving.py:625, serving.py:290 ICS), `E_mel` (serving.py:627, 644), `melanogenic-effective J/m²` (serving.py:592, serving.py:507), `Pigment-darkening` (serving.py:601), `pigment_darkening_dose_30m_j_m2` (serving.py:623 CSV header), `Visible-Darkening Potential (peak 30m)` (serving.py:625), `J/m2 mel` (serving.py:376-462 ICS) | `TanDose`, unit `J/m² E_mel` |
| Delayed-pigmentation score (0–100, the ranked headline) | `Overall` (serving.py:597, 642, 688, 690), `Overall tanning opportunity 0–100` (serving.py:690 tooltip), `overall_tan_opportunity_0_100` (serving.py:623 CSV), `LEGACY composite` (serving.py:597, 690, 696), `Overall tanning opportunity 0-100 - LEGACY composite` (serving.py:690) | `Overall (0–100)` |
| Absolute melanogenic strength (0–100, worldwide scale) | `Abs` (serving.py:642, 644, 688, 690), `Int` (serving.py:642), `Absolute` (serving.py:690 tooltip "Absolute melanogenic strength"), `Absolute melanogenic strength — worldwide scale` (serving.py:690), `tan_score_absolute_0_100` (serving.py:628, 623 CSV) | `Absolute (0–100)` |
| Local rarity percentile | `Local` (serving.py:688, 690, 691), `Loc` (serving.py:642), `local` (serving.py:636), `Local percentile` (serving.py:690), `location percentile` (serving.py:602), `Local location percentile` (serving.py:602) | `Local percentile` |
| Sunburn dose | `SED` (serving.py:601, 629, 628), `Sed` (serving.py:632 derived label), `sed_1h` / `SED30` (serving.py:623, serving.py:292), `cumulative SED` (serving.py:601), `sunburn load` (serving.py:601), `sunburn-weighted exposure` (serving.py:601 tooltip), `SED peak 30m` (serving.py:625) | `SED` (unitless erythemal dose) |
| Headline UV index | `UV∘` (serving.py:597, 601 chart note, 690 headers, 602 glossary), `UV` (serving.py:642 day cell, 691 table), `UVI` (serving.py:602 glossary, 690 tooltips), `UV index` (serving.py:427 ICS), `Headline UVI` (serving.py:690), `uv_index` / `uvi_consensus` (serving.py:623 CSV) | `UV index` in body copy; `UV∘` only inside the Column glossary |
| Confidence | `Conf` (serving.py:642 day cell, 690 header, serving.py:295 ICS), `Confidence` (serving.py:441 ICS), `Confidence 0–100` (serving.py:690 tooltip), `confidence` (serving.py:644 hero), `Conf forecast agreement at the peak hour` (serving.py:642 tooltip) | `Confidence (0–100)` |
| Best window | `best window` (serving.py:597, 601, 625), `Good window (longest near-peak)` (serving.py:689), `best usable 30 min` (serving.py:644), `Strongest 30 min` (serving.py:644), `best hour` (serving.py:625, 689), `Best usable sun` / `Strongest 30m` / `Best sun` (serving.py:376-462 ICS), `window` (serving.py:625) | `best window`; the specific ranked ones as `best usable 30 min` and `strongest 30 min` |
| Outdoor usability | `Fit` (serving.py:642), `Outdoor fit` (serving.py:642 tooltip), `outdoor fit: share of daylight half-hours not hard-blocked` (serving.py:642), `blocked half-hours` (serving.py:689), `hard-blocked` (serving.py:642 tooltip), `hard outdoor constraints` (serving.py:401 ICS), `outdoor_block_reason` / `outdoor_flags` (serving.py:681), `NO OUTDOOR WINDOW` (opportunity.py:1258) | `outdoor fit`; blocked time as `blocked half-hours` |
| Personal minimal melanogenic dose | `MMD` (serving.py:592), `My MMD` (serving.py:592), `personal MMD` (serving.py:592 tooltip), `personal_mmd` (serving.py:507-515), `melanogenic-effective J/m²` (serving.py:592, 507), `MMD fraction` (serving.py:625) | `personal MMD`, unit `J/m² E_mel` |
| Pose / geometry inputs | `Tilt` (serving.py:593), `tilt` (serving.py:627), `Azimuth` (serving.py:593), `azimuth` (serving.py:627), `recline` (serving.py:593), `torso` (serving.py:671, 602), `posture` (serving.py:602, 671), `pose` (serving.py:593), `lift` (serving.py:671) | `Tilt °` and `Azimuth °`; the body state as `torso lift` |
| Surface reflection | `Surface` (serving.py:593, 627), `ground` (serving.py:671 SVG label), `Ground around you` (serving.py:593 tooltip), `proxy` (serving.py:627, output.py:101), `proxy_reflectance` (output.py:19), `broad extent` (output.py:97), `skin-plane` (serving.py:593 tooltip), `horizontal environment` (serving.py:593 tooltip), `reflected context` (output.py:101) | `Surface`; the number as `reflectance proxy` |
| Data freshness | `Refresh forecast` (serving.py:594), `Updated …` (serving.py:636), `refresh the data` (serving.py:105), `Times refresh with each SunStack run.` (serving.py:449), `reruns publish fresh data` (output.py:70), `LATEST` (serving.py:51) | `live forecast` / `published page`; the action `Run live forecast now` |
| Spectral model identification | `backend` (serving.py:627, 644, output.py:101), `spectral backend` (serving.py:625 provenance), `tier` (serving.py:627, 644), `spectral tier` (serving.py:625), `global ref` (serving.py:625), `fusion` / `confidence` / `rank` (serving.py:627, output.py:96) | `backend` + `tier`, and `reference irradiance` for `global ref` |
| Class blocks | `Show my classes (ET, Mon–Fri)` (serving.py:690), `Purple rows = in class` (serving.py:690), `free for you` (serving.py:689), `class block` (`classrow`, `serving.py:690`), `🎓 … ET` (serving.py:642) | `class blocks`; the free time as `free between classes` |
| Pigment darkening | `Pigment-darkening` (serving.py:601), `pigment_darkening_dose_30m_j_m2` (serving.py:623), `pigment_darkening_dose_1h_j_m2` (serving.py:623), `Visible-Darkening Potential (peak 30m)` (serving.py:625), `existing-pigment (not new melanin)` (serving.py:625) | `pigment-darkening dose` |

---

## 4. Density assessment

Threshold: paragraphs longer than ~25 words that are visible without opening a `<details>`. Word counts below are
computed on the literal strings quoted.

### 4.1 `serving.py:597` — legend, directly under the hero (28 words) — **shorten**

> `Ranking is maximum expected 30-minute delayed-pigmentation dose (fixed-duration-dose-v2). Overall is a LEGACY composite (deprecated product heuristic); UV∘ is headline UVI fusion, while TanDose comes from the UVA/UVB model.`

It is the first paragraph on the page and its second sentence is duplicated verbatim at `serving.py:690` and
`serving.py:696`. Not a disclosure candidate: the ranking definition is needed before the day strip.

**Replacement (23 words):** `Ranking = best 30-minute delayed-pigmentation dose. UV∘ is the headline UV index; TanDose comes from the UVA/UVB model. Column meanings: see Column glossary.`

### 4.2 `serving.py:601` — note under the three canvases (35 words) — **shorten**

> `TanScore fixed 0–100 (top, instantaneous intensity); cumulative TanDose melanogenic J/m² (middle, exposure odometer); cumulative SED (bottom, sunburn-weighted exposure, never “good”). Shaded band = best window. Pigment-darkening lives in tables under Advanced, never merged into TanScore.`

**Replacement (24 words):** `Top: TanScore 0–100 now. Middle: cumulative TanDose (J/m² E_mel). Bottom: cumulative SED — sunburn-weighted, never a target. Shaded band = best window.`

The dropped clause (`Pigment-darkening lives in tables under Advanced`) belongs in the `Advanced / Photobiology`
disclosure that already holds that table.

### 4.3 `serving.py:602` — note inside the sun-position card (40 words) — **shorten and move the caveat**

> `Legs stay flat, parallel to the ground — only the torso lifts. Click any table row to inspect that time. Guidance is geometry context, not a score. Headline TanScore/TanDose is the horizontal environmental reference; facing the sun is not modeled.`

**Replacement (22 words):** `Only the torso tilts; legs stay flat. Click a table row to inspect that time. This figure is geometry, not a score.`

The final clause is a modelling limitation, so it belongs in `Source data` or the `Column glossary`, not in the card.

### 4.4 `serving.py:690` — gloss paragraph above the hourly table (56 words) — **move into the disclosure, keep one line**

> `UV∘ Headline UVI (bias-corrected inverse-error fusion of OM Best Match + CAMS + EPA) · ΔUV source-range spread flags disagreement · Ranking is maximum expected 30-minute delayed-pigmentation dose (fixed-duration-dose-v2); Overall is a LEGACY composite (deprecated product heuristic) · All columns stay in the page — hidden ones are one tap away and always in Export CSV.`

This is the longest default-visible paragraph and the second of three copies of the ranking/LEGACY sentence. Every
definition in it already has a home: the `Column glossary` `<details>` (`serving.py:602`) and the per-header `title`
tooltips (`serving.py:690`).

**Replacement (12 words):** `Rankings use the best 30-minute delayed-pigmentation dose. Column meanings: see Column glossary.`

### 4.5 `serving.py:644` — hero sentence (43 words in a representative render) — **shorten**

> `<b>Monday</b> Strongest 30 min 1:00 PM – 1:30 PM — 3.4 E_mel J/m²; best usable 30 min 2:00 PM – 2:30 PM — 3.1 E_mel J/m² (confidence 68). Local 62 · Overall 71 · Abs 55. Surface Dry sand; backend emulator (tier A).`

It is the topmost line of the document, and the last sentence carries infrastructure vocabulary (`backend`, `tier`)
that no first-time user can use. `Local` and `Abs` are already rendered in the day header immediately below
(`serving.py:688`).

**Replacement (28 words):** `<b>Monday</b>: strongest 30 min 1:00 PM – 1:30 PM, 3.4 J/m² E_mel. Best usable 30 min 2:00 PM – 2:30 PM, 3.1 J/m² E_mel (confidence 68/100). Overall 71/100.`

### 4.6 `serving.py:689` — best-line under the day header (39 words, mostly fields) — **keep, tighten the trailing sentence**

> `Good window (longest near-peak) 11:00 AM – 3:30 PM · best hour 1:00 PM (78) · peak 30-min dose 3.4 J/m² · peak UV 7.9 · 71°F · 3 blocked half-hours. Rows tinted below fall inside the good window.`

The field list is the densest useful summary on the page and most of its words are numbers; only the trailing sentence
is prose. **Exact replacement for that sentence:** `Tinted rows are inside the best window.`

### 4.7 Below the threshold (no action required)

- `serving.py:593` — `At the default flat, horizontal pose, ground reflection is geometrically zero; recline or stand the plane to see the surface effect.` — 21 words; still listed as a finding above because it carries posture advice.
- `serving.py:636` — `Updated 3:12 PM · 72 hourly rows · forecast ed014cad (page 9f3b1a2) · absolute is provisional global scale, local is this location's percentile` — 23 words; the trailing clause is a finding for wording, not for length.