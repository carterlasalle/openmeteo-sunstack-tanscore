# SunStack — prioritized findings

Audit basis: source read of `src/sunstack/{ui,serving,output,opportunity}.py`,
plus live driving of `http://127.0.0.1:8901/` in real Chromium at 1440×900 and
320–414 px. Every finding below was reproduced; the reproduction is in
`Evidence`. Confidence reflects how directly the evidence establishes the claim.

Full disclosure of my own corrections: three things I first suspected turned out
**not** to be defects and are recorded here so they are not reintroduced —
`Source data` is not empty (it renders 17 106 chars; `<details>` content has no
`innerText` while closed), personal MMD is not a dead control (it renders
`Your MMD: 1.31×`), and the surface slugs in the `<select>` do match the
registry.

Severity: **P0** core-workflow failure / data integrity · **P1** major usability
or broken important feature · **P2** meaningful clarity/interaction/efficiency ·
**P3** polish.

---

## Corrections applied after adversarial review

`critic.md` attacked every finding. Where it was right, the finding is corrected
below rather than left standing. These corrections are part of the audit record.

| Finding | Original claim | Correction |
|---|---|---|
| F-00 | "Surface, Tilt, Azimuth and Skin **change nothing visible**"; "nothing on the page states" the invariant | **Overstated.** Skin visibly changes `#skinctx`; Surface visibly changes the hero's `Surface X;` noun; the sun card already names the *horizontal environmental reference* and the Surface tooltip says it is never the horizontal environment. The real defect is that the **numeric** effect is buried in a collapsed disclosure and the explanation is remote — a clarity defect (P2), not an absent explanation. The invariance itself is correct physics. |
| F-00 fix | "Your surface, tilt **and skin type** change your skin-plane exposure" | **Wrong for Skin.** Fitzpatrick changes response/risk interpretation, not incident radiation. The control explanation must say so. |
| F-06 | day cells "have no hover feedback" | **Wrong.** `.daycell` is a `<button>` and inherits `button:hover`. Only the *selected* day and the primary button are no-op states. Narrowed to those. |
| F-16 | the 30-minute table has "6 columns" | **Wrong count — it is 7** (Time, UV, UVA, Overall, Local, Source, Note). Sorting is an *absent capability*, not a broken advertised interaction; it is no longer bundled with the missing-columns fix. |
| F-19 | accepting −100/120 °F proves invalid bounds | **Unproven.** A comfort preference is not an angle with a fixed domain. The real hole is **non-finiteness** — see F-37, which is the defect that matters. |
| F-29 | escalates to P0 "the moment anything consumes it" | **Deflated.** A consumer increases exposure; P0 requires an identified consumer and consequence. Stays P1. |
| F-31 fix | use `free for you: 12:30–1 PM` as the corrected window | **Wrong example.** Wednesday's class starts 12:50, so that interval also overlaps class, and its end-row dose is 1098.81 J/m², not 1136.1. Eligibility must be recomputed over full intervals, not substituted from the legacy availability label. |
| F-28 | the percentile "rewards the weaker location" and "cancels" the absolute gap | **Causal attribution unproven.** The convergence is observed; isolating one component of a geometric mean with four weighted inputs needs a same-row counterfactual. The *conclusion* (a self-referential percentile must not lead a cross-site comparison) stands on the invariant alone. |
| F-34 | the handler name "promises the visible view" | **Overreach.** `exportVisibleCsv` is an implementation name; the visible label is just `Export CSV`. Global scope and colliding filenames are verified; a second day-scoped action is optional, not required. |
| experience §3.1 | "82% of the computed model is unreachable" | **Wrong as a coverage claim.** The 298/266 field counts include aliases, version strings, provenance and completeness flags, not independent user questions. The complete JSON *is* reachable through the read API. The narrower claim — that dose and confidence are missing from the 30-minute table — is the real finding. |
| experience §3.2 | the UVI sub-range "is the prediction interval" | **Wrong.** It is the min/max of the available per-source UVIs (`serving.py:680`). `uvi_prediction_interval_low/high` is a different field and is not rendered there. Corrected to "source range". |
| copy_audit terminology map | consolidates "Overall" as the ranked headline and merges pigment-darkening with delayed pigmentation | **Must not be applied wholesale.** `Overall` is the deprecated composite, not the fixed-duration objective; delayed pigmentation and existing-pigment darkening are deliberately separate channels. |

---

## P1 findings

### F-36 — Unknown weather reads as perfect usability, on a shipped location

| | |
|---|---|
| **Severity** | **P1 — the single strongest finding in the audit, and it violates the product's own stated invariant** |
| **Location** | `opportunity.py:119-161, 200-213` (missingness recorded but not applied) and `best_fixed_dose_window` (reads `outdoor_blocked`, not `outdoor_feasibility_complete`) |
| **Problem** | When essential weather is missing, the row records that fact in three places — `outdoor_feasibility_complete = false`, `outdoor_block_reason = "unknown (missing weather)"`, `outdoor_feasibility_reason_codes = "missing_weather"` — and **still reports `outdoor_feasibility_0_100 = 100.0`, `outdoor_blocked = false` and `comfort_band = "perfect"`**. The day's blocked-half-hour count is zero. So "unknown" is presented to the user as "perfect", and unknown rows are eligible for the usable/comfortable rankings. |
| **Why it matters** | This is the invariant the product states about itself — missing weather must never read as perfect. A user shown 100 % fit and "perfect" comfort for a day whose temperature the system never received will plan around a verdict the system cannot support. It is the one finding where the product is confidently wrong rather than merely unclear, and it is live on a shipped location. |
| **Evidence** | `GET /api/data?location=pacific-palisades&min_temp=50` → **336** half-hour rows with `temperature_2m = null`, every one reporting `outdoor_feasibility_0_100: 100.0`, `outdoor_blocked: false`, `comfort_band: "perfect"`, `outdoor_feasibility_complete: false`, `outdoor_block_reason: "unknown (missing weather)"`, `outdoor_feasibility_reason_codes: "missing_weather"`. First rows: `2026-09-22T07:00`, `07:30`, `08:00`. |
| **Reproduction** | `curl 'http://127.0.0.1:8901/api/data?location=pacific-palisades&min_temp=50'` and inspect any row whose `temperature_2m` is null. |
| **Expected** | An unknown-weather row is excluded from the usable and comfortable rankings and presents an explicit unknown verdict; its physical dose is still reported. |
| **Actual** | 100 % feasibility, not blocked, comfort "perfect", eligible for ranking. |
| **Root cause** | Missingness is recorded as metadata (`complete`, `reason_codes`) but never propagated into the feasibility value or the eligibility predicate that the rankings read. |
| **Recommended fix** | Make missing essential weather an explicit third state in the shared feasibility result, require `outdoor_feasibility_complete` for usable/comfortable eligibility, and render that state instead of a fit/comfort verdict. Leave environmental irradiance and the strongest physical dose untouched — the two axes must stay separate. |
| **Acceptance** | The live Palisades missing-temperature row no longer reports 100 %/perfect; a physically complete candidate with a missing temperature or weather code is excluded from usable ranking while retaining its dose; a row with missing weather never displays `comfort_band: "perfect"`. |
| **Confidence** | High (336 rows read from the live API; three independent fields contradict the verdict) |

### F-37 — A non-finite `min_temp` silently disables the cold floor

| | |
|---|---|
| **Severity** | P1 |
| **Location** | `ui.py` `min_temp: float \| None` query parameter; `opportunity.apply_outdoor_feasibility` |
| **Problem** | `min_temp=nan` is accepted (HTTP 200) and the comparison `temp < min_temp` becomes false for every row, so the cold floor disappears. A 43.1 °F hour that is blocked as "too cold" under the default 50 °F becomes 100 % feasible and unblocked. The summary still reports `min_tan_temperature_f: 50.0`, so the published metadata disagrees with the rows it describes. |
| **Why it matters** | A non-finite input silently removes a safety floor and produces a reassuring verdict, and the artifact then misreports the threshold it used. This is the concrete validation hole — finiteness — that the "temperature needs a plausible range" framing missed. |
| **Evidence** | Same row, two requests: `min_temp=50` → `feas=0.0, blocked=true, reason="temperature < 50F", codes="too_cold"`; `min_temp=nan` → `feas=100.0, blocked=false, reason="", codes="ok"` — with `temp=43.1` in both. `summary.min_tan_temperature_f` is `50.0` in both. |
| **Reproduction** | `curl 'http://127.0.0.1:8901/api/data?location=south-bend&min_temp=nan'` and compare the first half-hour row with the `min_temp=50` response. |
| **Expected** | 4xx for NaN and ±inf on `/api/data` and `/api/calendar.ics`; the previously accepted view is left intact. |
| **Actual** | 200 with the floor disabled. |
| **Root cause** | No finiteness check on the parsed float. |
| **Recommended fix** | Reject non-finite values explicitly (the existing `_value`-style guards already do this for tilt/azimuth — apply the same to `min_temp`), and add the finiteness assertion to the artifact validator so a non-finite threshold can never be published. |
| **Acceptance** | `min_temp=nan`, `inf`, `-inf` return 4xx on both endpoints; `summary.min_tan_temperature_f` always equals the value actually applied to the rows. |
| **Confidence** | High (two live requests diffed on one row) |

### F-00 — The control row and the answer are almost disconnected, and the page never says so

| | |
|---|---|
| **Severity** | P1 — this is the single most consequential product-design defect |
| **Location** | the `.controls.settings` row (Location, Skin, MMD, Min °F, Surface, Tilt, Azimuth, Apply) versus `#hero`, the day strip and both tables |
| **Problem** | Five of the seven staged controls cannot change any number the user is looking at. Only **Min °F** moves the headline, and only when it is restrictive enough to exclude the previously-best window. **Surface**, **Tilt**, **Azimuth** and **Skin** change nothing visible in the main view — their entire effect is a `skin_plane_*` value rendered inside a collapsed disclosure and one noun in the hero's `Surface X;` clause. Nothing on the page states that the headline is a *horizontal environmental reference* that is invariant to surface and posture by design. |
| **Why it matters** | A user's mental model is "the controls at the top configure the answer below". Here they do not, and the product does not say so. A user who sets their surface to Fresh snow and a 45° tilt sees the same headline and concludes either that the controls are broken or that the feature is fake — the same conclusion the *pipeline* bug produced for a different reason earlier in this session. The correct behaviour (an invariant environmental reference) is defensible science but an indefensible *interface* without an explicit statement and an obvious readout of what did change. |
| **Evidence** | Controlled experiment — change exactly one control, press Apply, capture the headline: |

| Change applied | headline dose | headline window | `Surface` clause | skin context | plane factor | reflected W/m² |
|---|---|---|---|---|---|---|
| baseline | 1136.1 | 1:30–2 PM | Unknown | not specified | — | — |
| Surface → Fresh snow, Tilt → 45° | **1136.1** | 1:30–2 PM | Fresh snow | not specified | 1.179 | 36.13 |
| Skin → III | **1136.1** | 1:30–2 PM | Fresh snow | Type III — intermediate response | 1.179 | 36.13 |
| Min °F → 20 | **1136.1** | 1:30–2 PM | Fresh snow | Type III | 1.179 | 36.13 |
| Min °F → 90 | **1111.1** | 1:30–2 PM | Fresh snow | Type III | 1.179 | 36.13 |

The headline also renders **the same window and the same number twice** (`Strongest 30 min 1:30 PM – 2 PM — 1136.1 …; best usable 30 min 1:30 PM – 2 PM — 1136.1 …`), so the reader cannot learn what distinguishes the two rankings, and the day strip, the doses line and the tables are the only places the distinction appears — inconsistently.

| | |
|---|---|
| **Reproduction** | Load the page → set Surface to `Fresh snow` and Tilt to `45` → Apply → observe the headline is unchanged; open Advanced/Photobiology to find `reflected E_mel` changed. Then set Skin to `III` → Apply → only the context line changes. |
| **Expected** | Either the controls change the answer, or the page says plainly which numbers are user-invariant and shows what the control *did* change, next to the control. |
| **Actual** | Four controls with no visible numeric effect and no explanation; one control (Min °F) with a conditional effect; the two headline rankings rendered identically. |
| **Root cause** | The science is right and the interface was never designed around it. `delayed_pigmentation_effective_irradiance_horizontal_wm2` is deliberately user-invariant (contract §2.1.A); the skin-plane variant is the user-dependent quantity, but it is surfaced only as `skin_plane_*` inside a disclosure. The control row was added after the model, without a place for the user-dependent output. |
| **Recommended fix** | Three changes, all structural, none cosmetic. **(1) State the invariant.** Put one line directly under the control row: *"Your surface, tilt and skin type change your skin-plane exposure, not the environmental reference — the headline is the horizontal reference for this location."* **(2) Give the user-dependent number a home.** When surface ≠ Unknown or tilt ≠ 0, promote a second headline figure: `On fresh snow, tilted 45°: 1339 J/m² (+18% vs horizontal)` — the value already exists as `skin_plane_delayed_pigmentation_effective_irradiance_wm2`. When surface = Unknown and tilt = 0, show only the reference and say why the control has no effect yet (which the existing sentence under the controls half-does, in the wrong place and only for tilt). **(3) Collapse the two identical rankings.** When `strongest_30m` and `best_usable_30m` resolve to the same window, print one sentence: `Best window today: 1:30–2 PM · 1136 J/m² · confidence 46.` Print two only when they differ, and then name the reason (`best usable avoids your blocked hours`). |
| **Acceptance** | With surface = Unknown and tilt = 0, the page states that surface/posture do not affect the reference. With surface = Fresh snow and tilt = 45, a user-dependent dose figure is visible above the fold without opening a disclosure, and it differs from the reference by the same ratio as `skin_plane_*` in the payload. The hero prints one window sentence when the two rankings agree and two labelled sentences when they differ. |
| **Confidence** | High (controlled experiment, exact values, reproducible) |

### F-26 — The score palette and the UV-index palette are the same colours (product-owner report, reproduced)

| | |
|---|---|
| **Severity** | P1 |
| **Location** | `serving.py` `:root` tokens, `uvColor()`, `scoreColor()`, `.uvdot`, `.daycell .pk`, `tr.inwindow` wash |
| **Problem** | The 0–100 quality score and the UV index hazard scale share **three identical hex values** for different meanings, and they are rendered a few columns apart in the same table. The UV 3–5 band also has no yellow, so "moderate UV" renders brown — the same brown as the app's brand accent. |
| **Why it matters** | In a UV-safety product a hue must not mean "quality" in one column and "hazard" in the next. Here `#8a6200` means *score 40–64 (mediocre)* **and** *UVI 3–5 (moderate burn risk)*; `#2c7a45` means *score ≥65 (good)* **and** *UVI 0–2 (safe)* — those two happen to agree, which makes the collision worse, because the 3–5 collision then reads as "brown = mediocre" rather than "brown = caution". The amber family (`--sun` `#a85500`, `--sunwash` `#fdeed0`, `--mid` `#8a6200`) additionally carries "primary button", "best-window row", "selected day" and "mid score", so four meanings share one hue. |
| **Evidence** | Measured live, in one table: UVI 3.8 / 4.6 / 4.8 dots → `rgb(138, 98, 0)` = `#8a6200`; day peaks 43 / 44 → `color: var(--mid)` = `#8a6200`. UVI 0–2.6 dots → `rgb(44, 122, 69)` = `#2c7a45` = `var(--ok)`. Day peaks 40 / 26 / 29 → `var(--low)` = `#b3450f`, which is also `uvColor()`'s UVI 6–7 colour. Tokens: `--sun:#a85500 --sunwash:#fdeed0 --ok:#2c7a45 --mid:#8a6200 --low:#b3450f --poor:#646c69`. Scale: `uvColor = v<3?'#2c7a45':v<6?'#8a6200':v<8?'#b3450f':v<11?'#a12a1f':'#6a3fbf'`. |
| **Important correction** | This is **not** a contrast failure. Every one of these pairings passes WCAG AA (4.79 / 5.49 / 5.56 / 15.36 / 5.30). It is a *meaning* defect, not an accessibility one — which is why automated checks did not catch it. |
| **Reproduction** | Open the hourly table on a day with UVI ≈ 4; compare the dot to the left of `UV∘` with the `Overall` number in the same row. |
| **Expected** | Two independent, conventional scales: a UV index ramp matching the universal WHO/WMO/EPA convention (0–2 green, 3–5 **yellow**, 6–7 **orange**, 8–10 **red**, 11+ **violet**), and a separate quality ramp that does not reuse those hues. |
| **Actual** | One hue ramp used twice. No yellow anywhere in the product, so the "moderate UV" band has no identity of its own. |
| **Root cause** | The score ramp (`--ok/--mid/--low/--poor`) predates the UV dot; `uvColor()` was written alongside the table using the same tokens. The brand accent was chosen from the same amber family. |
| **Recommended fix** | Adopt the standard UV ramp verbatim for UVI only, and move the score ramp off it. Concrete proposal: keep `uvColor = <3 #1a9641, <6 #ffd500, <8 #f57c00, <11 #d7191c, else #7b2fbe` (the conventional five bands, with the 3–5 band as yellow); change the score ramp to a **neutrally-graded** one that shares no hex with the UV ramp — e.g. `--score-high:#1a7f4b`, `--score-mid:#6b6f6d`, `--score-low:#8a5a2b`, `--score-poor:#646c69` — so "quality" reads as a lightness ramp and "hazard" keeps the traffic-light convention. Reserve `--sun`/`--sunwash` (amber) exclusively for *selection* (best window, selected day, active control), never for a data value. |
| **Acceptance** | No hex value is returned by both `uvColor()` and `scoreColor()`; the UVI dot for a value in [3,6) is yellow; the best-window wash hue appears on no data value; a screenshot shows a UVI dot and a score in the same row that are unambiguously different colours. |
| **Confidence** | High (measured in the DOM; tokens and functions quoted verbatim) |

### F-29 — `time_utc` is local wall clock stamped `Z`, and contradicts the interval fields in the same row

| | |
|---|---|
| **Severity** | **P1 today, P0 the moment anything consumes it.** No rendered surface reads this field, so it has no current user-visible effect — but it is a published-artifact integrity defect: a field named `*_utc` is not UTC, and it disagrees with its own row. |
| **Location** | `src/sunstack/opportunity.py:787` — `out["time_utc"] = _pd.to_datetime(out["dt"], utc=True)` |
| **Problem** | `out["dt"]` is a **naive local wall-clock** timestamp. `pd.to_datetime(..., utc=True)` on a naive series *localises* it as UTC rather than converting it, so `08:00` local (EDT, UTC−4) becomes `08:00Z` instead of `12:00Z`. The hourly frame takes a different path (`tanscore.build_live_feature_frame` → `_to_utc_from_openmeteo`) and is **correct**. The result is one published payload where the same key means two different things. |
| **Why it matters** | Anyone joining on `time_utc` — a notebook, a validation script, a future consumer — is silently 4 hours off, and the artifact ships a field that contradicts the interval fields sitting next to it. The project's own temporal contract (§5) exists precisely to make support provable; this defeats it. |
| **Evidence** | Published `docs/data.json`, first daylight rows: |

| frame | `time` | `time_utc` | `interval_start_utc` | `interval_end_utc` |
|---|---|---|---|---|
| `hourly` | `2026-10-06T08:00` | **`2026-10-06T12:00:00.000Z`** ✓ | — | — |
| `half_hour` | `2026-10-06T08:00` | **`2026-10-06T08:00:00.000Z`** ✗ | `2026-10-06T11:30:00.000Z` | `2026-10-06T12:00:00.000Z` |

  `summary.timezone = America/Indiana/Indianapolis` (UTC−4 in October). The correct instant for local 08:00 is 12:00Z — which is exactly what `interval_end_utc` says and what the *hourly* frame says. Parsed delta between the half-hour row's `time_utc` and its own `interval_end_utc` = **−4 h**. |

| | |
|---|---|
| **Reproduction** | `git show origin/main:docs/data.json`, compare `half_hour[0].time_utc` with `half_hour[0].interval_end_utc` and with `hourly[0].time_utc`. |
| **Expected** | Every `*_utc` field is a true UTC instant, and equals the interval bound it corresponds to. |
| **Actual** | The half-hour `time_utc` is the local clock value with a `Z` appended. |
| **Root cause** | Localise-vs-convert confusion on a naive timestamp; the hourly path avoided it by using an Open-Meteo-aware converter. |
| **Recommended fix** | In `opportunity.py`, localise before converting: `_pd.to_datetime(out["dt"]).dt.tz_localize(config.TIMEZONE).dt.tz_convert("UTC")`, or simply alias the already-correct interval bound — `out["time_utc"] = out["interval_end_utc"]` for the backward-mean grid. Add an invariant to the artifact validator: for every row, `time_utc` must equal `interval_end_utc` (within the sampling convention) and must round-trip through the run's timezone. |
| **Acceptance** | For every published row in both frames, `time_utc` equals the row's `interval_end_utc`; a validator check fails the build if any `*_utc` field differs from its local `time` by anything other than the site's UTC offset. |
| **Confidence** | High (values read from the published artifact; both frames compared; root cause located by line) |

### F-27 — A drizzle code deletes a whole day and drives the headline score to exactly 0 (product-owner report, reproduced)

| | |
|---|---|
| **Severity** | P1 — arguably P0: it silently removes days from the product and inverts the ranking between sites |
| **Location** | `src/sunstack/opportunity.py` `RAIN_CODES`/`rain_now`/`hard_block`; `overall_tan_opportunity_0_100 = components × multiplier`; `config.ACTIVE_PRECIP_IN_THRESHOLD` |
| **Problem** | `RAIN_CODES = set(range(51, 68)) \| {80,81,82}` includes **51/53/55 = drizzle (light/moderate/dense)** and 56/57 freezing drizzle. Any of those codes hard-blocks the half-hour. Because the published composite is `weighted_geometric(components) × feasibility_multiplier`, a hard block sets the multiplier to 0 and the day's `Overall` becomes **exactly 0** — discarding the fact that the sun was strong. |
| **Why it matters** | On 2026-10-12 Pacific Palisades has `weather_code=53` (moderate drizzle), `rain=0.0 mm`, `precipitation=0.024 mm` and `peak_precip_probability=28%` — and every one of its 24 daylight half-hours is blocked, so the day renders **`Overall 0`**, status `NO OUTDOOR WINDOW`, `best_window = null`. In the *same row* the day cell also renders `Abs 38 · Loc 81`, so the cell contradicts itself. On that date the weaker-sun site reads **29**: South Bend (`Abs 23`, UVI 3.5, no rain) outranks Palisades (`Abs 38`, UVI 4.65, 0.024 mm drizzle). A trace of drizzle inverted the comparison. |
| **Evidence** | `getComputedStyle`/payload for PP 10-12: `blocked_half_hours: 24`, `day_overall_peak_0_100: 0.0`, `day_absolute_peak_0_100: 37.5`, `day_local_peak_0_100: 81.3`, `peak_uv_index: 4.65`; a half-hour row: `weather_code 53`, `rain 0.0`, `precipitation 0.024`, `outdoor_block_reason "precipitation in interval/code"`, `outdoor_feasibility_reason_codes "rain_interval"`, `overall_tan_opportunity_0_100 0.0`, `tan_score_absolute_0_100 37.5`. All 24 rows carry `rain_interval`. Code: `RAIN_CODES = set(range(51, 68)) \| {80, 81, 82}`; `ACTIVE_PRECIP_IN_THRESHOLD = 0.001` in (= 0.025 mm); `hard_block = rain_now \| snow_now \| thunder \| too_hot \| too_cold \| ground_snow`. |
| **Reproduction** | Compare the two published artifacts for `2026-10-12`: `docs/data.json` (South Bend, `day_overall_peak_0_100 = 29.4`) and `docs/sites/pacific-palisades/data.json` (`0.0`). |
| **Expected** | Trace precipitation and "drizzle" advisories degrade the score smoothly rather than annihilating it; a day with `Abs 38` never renders `0`; and a hard block removes a *window*, not the *day's information*. |
| **Actual** | A drizzle code wipes 24 of 24 windows and zeroes the score. |
| **Root cause** | Two decisions compounded. (1) The interval threshold (0.001 in) and the code list were set to be conservative — "any precipitation means don't lie down outside" — but the code list starts at 51 (drizzle), so *light* drizzle is treated identically to heavy rain. (2) The composite multiplies by the feasibility multiplier instead of reporting the two facts separately, so `blocked` destroys `strong`. |
| **Recommended fix** | Split the two axes that are currently multiplied. Publish `radiation_score` (feasibility-independent) and `usability` separately, and let `Overall` be a *labelled* combination that never falls below the radiation floor: e.g. `Overall = max(radiation_score × 0.15, components × multiplier)`. For precipitation, gate the hard block on intensity, not on the code alone: hard-block only when `precipitation ≥ 0.5 mm/h` (≈ 0.01 in per hour) or `weather_code ∈ {55, 65, 82, 95, 96, 97}`; treat `51/53, 56, 61, 80` as a soft penalty (`multiplier × 0.5`) and surface the reason as "light precipitation — usable, expect damp". Keep the honest block for thunder and heavy rain. |
| **Acceptance** | A half-hour with `weather_code = 51/53` and `rain = 0` yields a non-zero feasibility and a non-zero score; a day with `Abs ≥ 35` never renders `Overall 0` while its sub-scores are shown; and the day cell cannot display `0` beside `Abs 38 · Loc 81` without an explicit "blocked: drizzle" label explaining the conflict. |
| **Confidence** | High (payload values, all 24 rows, and the exact constants quoted) |

### F-28 — `Overall` compresses and can invert the difference between two clearly different sites (product-owner report, reproduced)

| | |
|---|---|
| **Severity** | P1 |
| **Location** | `overall_tan_opportunity_0_100` = weighted **geometric** mean of `abs`, `local`, `atmosphere`, `confidence`, then × feasibility. `local_tan_score_0_100` is a percentile against **each site's own** climatology. |
| **Problem** | On the days with good weather the two sites' `Overall` converge (43 vs 46; 44 vs 47; and 43 vs 43 on 10-10) while `Abs` differs by 13 points (34 vs 47) and the peak temperature by 15 °F (72 vs 87). The reason is structural: `Local` is self-referential, so on 10-10 South Bend scores `Local 95` against Palisades' `86` — the percentile *rewards* the weaker location for having weaker weather — and that term cancels the absolute gap inside the geometric mean. |
| **Why it matters** | The user's question ("how are they almost the same when Palisades clearly has better weather") is answerable only by reading the raw fields. The headline number is the one surface that does **not** show the difference, and it is the surface the strip, the hero and the calendar all use. A percentile rendered beside an absolute invites exactly this misreading. |
| **Evidence** | 14 common days from the two published artifacts: |

| date | SB Overall | PP Overall | SB Abs | PP Abs | SB Local | PP Local | SB UVI | PP UVI | SB hi°F | PP hi°F |
|---|---|---|---|---|---|---|---|---|---|---|
| 10-06 | 43 | 46 | 34 | **47** | 93 | 91 | 5 | 6 | 72 | 87 |
| 10-07 | 44 | 47 | 35 | **48** | **95** | 93 | 5 | 6 | 75 | 80 |
| 10-08 | 40 | 43 | 34 | 45 | **94** | 90 | 4 | 6 | 65 | 84 |
| 10-10 | **43** | **43** | 34 | **42** | **95** | 86 | 5 | 6 | 82 | 79 |
| 10-11 | 3 | 32 | 4 | 32 | 30 | 71 | 1 | 4 | 63 | 78 |

   Over the full 14 days the composite *does* separate them — mean `Overall` SB 24.2 vs PP 41.5 (+17.2) against mean `Abs` 23.7 vs 42.2 (+18.5), i.e. only 1.1× compressed overall. **The convergence is specific to the good days**, which is precisely when a user is comparing them. `Local` inverts (SB higher than PP on 10-07, 10-08, 10-10) because each is normalised to its own history.

| | |
|---|---|
| **Reproduction** | Diff `day_local_peak_0_100` and `day_absolute_peak_0_100` for the two sites on 2026-10-10. |
| **Expected** | Either the headline separates locations on absolute grounds, or it is explicitly labelled as a within-location interpretation and never used to compare sites. |
| **Actual** | A single `Overall` is presented as a cross-site comparable number in the day strip, the hero and the ICS, and it converges exactly when the comparison matters. |
| **Root cause** | The composite mixes an absolute (`Abs`) with a self-referential percentile (`Local`) as if both were comparable across sites; a geometric mean then further compresses. The project's own invariant already states that the local percentile is interpretation, not physics — the composite violates it by construction. |
| **Recommended fix** | Stop publishing one number that means both. Give the hero and the strip an explicitly absolute headline (the dose in J/m², which already exists and already separates the sites: 1136 SB vs 1178+ PP) and keep `Local` as a clearly-labelled *within-location* percent ("stronger than 95% of this location's daylight hours"). If a single 0–100 is still wanted, make it purely absolute and state that it is not location-relative. |
| **Acceptance** | No single number is presented as comparable across sites unless all of its inputs are absolute; `Local` is always rendered with a within-location qualifier; the day strip conveys a visible difference between the two sites on the 10-06/07/10 dates. |
| **Confidence** | High (both published payloads, 14 days, arithmetic shown) |

### F-30 — "Purple rows = in class" is structurally impossible inside the best window

| | |
|---|---|
| **Severity** | P1 |
| **Location** | `serving.py` both table builders: `${w?' class="inwindow"':(cl?' class="inclass"':'')}`; legend at `.classrow .note` |
| **Problem** | The row-class expression is a ternary chain, so `inwindow` **shadows** `inclass`: a row that is both inside the best window and inside a class block renders as `inwindow` and can never be purple. The page states `Purple rows = in class — plan around them`, but the rows that matter most — the ones inside the recommended window — are exactly the ones that never turn purple. |
| **Why it matters** | The whole point of the class feature is to warn the user that the recommended window collides with their schedule. The implementation can only warn about class time *outside* the window, which is the one case where it does not matter. A user following the legend will conclude they are free during a class. |
| **Evidence** | Selected **Wednesday 2026-10-07** (day header `Wednesday, October 7 · Overall 44 Local 95 · Abs 35`). Window = 12 PM–4 PM (`inwindow` rows: 12 PM, 1 PM, 2 PM, 3 PM hourly; 12 PM–3:30 PM half-hourly). Wednesday's class blocks per `CLASSES[3] = [[660,735],[770,820],[840,950]]` = 11:00–12:15, **12:50–13:40**, **14:00–15:50**. The **1 PM** row (13:00) is inside 12:50–13:40 *and* inside the window. Measured: `document.querySelectorAll('tr.inclass').length` = 6 (all outside the window: 9:30, 10, 11 AM); `inwindow && inclass` = **0**; the 1 PM row's first cell background is `rgb(253, 238, 208)` (the amber `--sunwash`), never `rgb(236, 228, 244)` (the purple `#ece4f4`). |
| **Reproduction** | Open the page, click the Wednesday day cell, inspect the 1 PM row in the hourly table: it is starred amber, not purple, despite falling in a class block. |
| **Expected** | A row inside both the window and a class block is visibly marked as in-class (e.g. a purple left border or a `🎓` marker on top of the amber wash), or the legend is corrected to say class marking applies only outside the window. |
| **Actual** | The purple state is unreachable for in-window rows; the legend is false. |
| **Root cause** | A single ternary was used to express two independent booleans. |
| **Recommended fix** | Make the classes independent: `class="… ${w?'inwindow':''} ${cl?'inclass':''}"`, and give `.inclass` a treatment that composes with `.inwindow` (e.g. a 3 px purple left border + the `🎓` glyph, keeping the amber wash for the window). Then correct the legend to match, or delete the legend if the composition is self-evident. |
| **Acceptance** | Selecting Wednesday 10/7 marks the 1 PM and 1:30 PM rows as in-class *and* in-window with both signals visible; `tr.inclass` includes at least one `inwindow` row; the legend describes what is actually rendered. |
| **Confidence** | High (DOM measured, class blocks read from source, both signals compared) |

### F-31 — The hero's "best usable" window can fall inside the user's class, because schedule filtering is not applied

| | |
|---|---|
| **Severity** | P1 — a stated contract violation with a user-visible wrong answer |
| **Location** | `opportunity.py` `best_fixed_dose_window(daylight, 30, usable_only=True)` and `best_usable_30m_*`; `best_available_window_*` (the schedule-aware variant) feeds a different label |
| **Problem** | The product defines "best usable 30 min" as the maximum expected dose among windows passing hard outdoor constraints **and the user's schedule constraints**. The implementation passes only `usable_only=True`; the schedule filter lives in a *separate* `best_available_window_*` that feeds the `free for you:` line instead. So the headline recommendation and the schedule-aware window are computed independently and can disagree. |
| **Why it matters** | The hero is the recommendation. On Wednesday 2026-10-07 it promotes 1:30–2:00 PM while the same page prints `free for you: 12:30 PM–1 PM`, and 1:30 PM lies inside the 12:50–13:40 class block. The product recommends a time the user has told it they are busy. |
| **Evidence** | Hero (Wednesday): `best usable 30 min 1:30 PM – 2 PM — 1136.1 E_mel J/m²`. Wednesday class block `[770,820]` = 12:50–13:40 contains 13:30. `best_usable_30m_start/end` is emitted from `best_fixed_dose_window(..., usable_only=True)` with no schedule argument, while `best_available_window_*` is the only schedule-aware value. |
| **Reproduction** | Select Wednesday; compare the hero window with the `free for you:` line and with the class blocks. |
| **Expected** | `best_usable_30m` excludes class-blocked windows, so hero, `free for you:` and the ICS agree by construction. |
| **Actual** | Three independent answers; the headline one ignores the schedule. |
| **Root cause** | Schedule filtering was added as a separate ranking rather than as a predicate on the existing one. |
| **Recommended fix** | Thread the schedule predicate into `best_fixed_dose_window` (a `skip_class`/`exclude` argument), pass it from `best_usable_30m`, and let `strongest_30m` stay schedule-blind. Then `best_available_window_*` becomes redundant and can be deleted. |
| **Acceptance** | On any day with a class block inside the candidate window, the hero's `best usable` window does not overlap a class block; hero, `free for you:` and the ICS event name the same window. |
| **Confidence** | High (rendered contradiction + code path identified) |

### F-32 — Seven simultaneous "when" answers, three different intervals, no stated basis

| | |
|---|---|
| **Severity** | P1 |
| **Location** | `#hero`, `.bestline`, `#strip .win`, `#sunsel`, ICS — seven distinct fields all answering "when" |
| **Problem** | For one selected day the page renders: `strongest_30m` (hero), `best_usable_30m` (hero + ICS), `best_window_*` "Good window (longest near-peak)" (strip + bestline), `best_available_window_*` "free for you:" (bestline), `best_hour_start` (bestline), `best_30m_start` = argmax of the **deprecated** `overall_tan_opportunity_0_100` ("peak 30-min dose"), and the sun figure's default frame (also picked by the deprecated composite). Nothing on the page says which one the product stands behind. |
| **Why it matters** | Three genuinely different intervals are presented as equally authoritative. A user cannot tell whether the answer is 12–4, 12:30–1, or 1:30–2. This is the "fundamentally confusing information architecture" case: the page has no single recommendation. |
| **Evidence** | Wednesday 2026-10-07, all rendered on one page: `Strongest 30 min 1:30–2 PM` · `best usable 30 min 1:30–2 PM` · `Good window (longest near-peak) 12 PM – 4 PM` · `free for you: 12:30 PM–1 PM` · `best hour 1:30 PM` · `peak 30-min dose` at the 2 PM stamp · sun figure defaulting to 2 PM. Intervals: 12:00–16:00, 12:30–13:00, 13:30–14:00. |
| **Reproduction** | Load the page and read the hero, the day header line, the strip window, and the sun caption in one pass. |
| **Expected** | One headline window with a stated objective; the others labelled as alternatives with their basis. |
| **Actual** | Seven answers, no basis statement. |
| **Root cause** | Rankings were added over time; each new one got its own render site; none retired the previous. |
| **Recommended fix** | Adopt the IA reviewer's proposal: the hero names **one** window and its objective; `strongest_30m` and `best_comfortable_usable_30m_*` move to a single secondary compare line (which also makes the currently-unused `best_comfortable_usable_30m_*` field live); the strip's bar/score, `day_status`, the detail header colour and `pickSunRow` all switch to the same dose-based key as the hero; `best_available_window_*` is deleted once F-31 lands. |
| **Acceptance** | Exactly one window is presented as the recommendation; every other time shown carries a visible label naming what it is; no surface uses the deprecated composite as its ranking key. |
| **Confidence** | High (all seven render sites read from source and observed) |

### F-33 — The hero promotes a different day than the one selected

| | |
|---|---|
| **Severity** | P2 |
| **Location** | `#hero` vs `#detail h2` (day header) |
| **Problem** | With Tuesday 6 October selected, the hero reads `Wednesday, October 7 Strongest 30 min …` while the day header immediately below reads `Tuesday, October 6 · Overall 43 …`. The hero is about the best upcoming day; the rest of the page is about the selected day; nothing labels the difference. |
| **Why it matters** | The two most prominent headings on the page name different days. A user reading the hero and then the table is comparing two different forecasts. |
| **Evidence** | Measured simultaneously: hero `Wednesday, October 7 Strongest 30 min 1:30 PM – 2 PM — 1136.1 E_mel J/m²`; `#detail h2` `Tuesday, October 6 · Overall 43 Local 93 · Abs 34 opportunity: FAIR`. |
| **Reproduction** | Load the page with the default (first) day selected and read the hero and the day header. |
| **Expected** | Either the hero is scoped to the selected day, or it is explicitly labelled `Best day this fortnight` and visually separated from the selected-day detail. |
| **Actual** | Unlabelled mismatch. |
| **Root cause** | The hero was designed as a global "best day" summary; the day strip and detail were added as a per-day inspector; the two were never reconciled. |
| **Recommended fix** | Label the hero's scope (`Best day in the next 14`), and make the selected day's own summary the day header, which it already is. Alternatively scope the hero to the selected day and add a separate `Best day this fortnight` line. |
| **Acceptance** | No two headings on the page name different days without one of them stating its scope. |
| **Confidence** | High (measured) |

### F-01 — A personal weekly class schedule is shipped in the public product

| | |
|---|---|
| **Severity** | P1 |
| **Location** | `src/sunstack/serving.py` (`const CLASSES={1:[[660,735],…]}` and three render functions); `src/sunstack/opportunity.py:851` `_CLASS_BLOCKS`; rendered in the day strip, the day header, the hourly table and the 30-min table |
| **Problem** | The public page renders first-person, owner-specific copy — `Show my classes (ET, Mon–Fri)`, `Purple rows = in class — plan around them`, `free for you: 12:30 PM–4 PM`, and `🎓 9:30–10:20, 11:00–12:15 ET` inside day cells. It is a hardcoded personal timetable, duplicated in two languages, gated by `loc === "south-bend"`. |
| **Why it matters** | Any visitor to the South Bend site is shown someone else's university timetable as if it were theirs. It is also a duplicated source of truth (`CLASSES` in JS, `_CLASS_BLOCKS` in Python) that can silently drift, and it is gated by a literal site slug, so it breaks the moment the default site changes. In a product that already accepts third-party location proposals via a public PR flow, personal data baked into the artifact is a trust problem, not a polish issue. |
| **Evidence** | Rendered: `docs/index.html` contains `Show my classes (ET, Mon–Fri)`; screenshot `02-day-strip.webp` shows `🎓 9:30–10:20, 11:00–12:15 ET` on the Tue 10/6 cell; the day header line reads `free for you: 12:30 PM–4 PM`. Source: `grep -n "CLASSES" src/sunstack/serving.py` → `const CLASSES={1:[[660,735],[770,820],[840,950]],2:[[570,620],[660,735]],…}`; `opportunity.py:849-868`. |
| **Reproduction** | Load the live page at South Bend with the default settings; read the day cells and the line under the selected date. |
| **Expected** | A shared product shows no personal schedule; if the capability is kept it is user-supplied at runtime and never published. |
| **Actual** | A hardcoded personal timetable is rendered to every visitor. |
| **Root cause** | The feature was built for the author's own use and shipped in the shared template; the Python copy was needed for window selection, so the schedule exists twice. |
| **Recommended fix** | Remove `CLASSES` from the client and `_CLASS_BLOCKS` from `opportunity.py`. Reimplement as an optional, per-visitor `classes` input (a small array of `{dow,start,end,tz}` in `localStorage`, parsed client-side), rendered only when it is non-empty. The server-side window selection must not depend on it — a personal schedule can *filter* candidate windows client-side without changing the served artifact. If server-side support is wanted, it belongs in a query parameter, never in the shipped default. |
| **Acceptance** | `docs/index.html` and the live page contain no `class`, `🎓`, or `free for you` text when no schedule has been supplied; no schedule constant exists in `serving.py` or `opportunity.py`; supplying a schedule client-side still highlights those rows; the published artifact is byte-identical for two different visitors. |
| **Confidence** | High (rendered + source) |

### F-02 — A failed load leaves the previous forecast on screen with no staleness marker

| | |
|---|---|
| **Severity** | P1 |
| **Location** | `src/sunstack/serving.py` `loadData()` catch branch; `#msg` status bar; hero, day strip and tables |
| **Problem** | When a load fails, the status bar shows an error but **every number stays on screen unchanged** — hero headline, day strip, doses, tables and charts all keep rendering the previous payload. Nothing marks them as stale. |
| **Why it matters** | This is a forecast product. Showing a confidently-rendered "Strongest 30 min 1:30 PM – 2 PM" next to "Could not load forecast" invites the user to act on numbers that are not the ones they asked for. The failure is silent to anyone who does not read the status line, and the status line is the only cue. |
| **Evidence** | Screenshot `01-hero-and-controls.webp`: red status bar reads `Could not load forecast: [object Object]. Check the server log, then Refresh.` while the hero simultaneously reads `Wednesday, October 7 Strongest 30 min 1:30 PM – 2 PM — 1136.1 E_mel J/m²`. Reproduced live by clearing Min °F and pressing Apply. |
| **Reproduction** | Open the page → clear `Min °F` → click **Apply**. |
| **Expected** | Either the view is replaced by an error state, or the retained data is visibly marked stale (dimmed + "showing the previous run from <time>"). |
| **Actual** | Old data rendered at full confidence, one line of error text above it. |
| **Root cause** | `loadData()` catches, calls `show(...,'error')` and returns without touching `DATA` or re-rendering. |
| **Recommended fix** | In the catch branch, set a `body.data-stale` class and render a conspicuous banner (keep `#msg` for transient notes). The banner must name the run time of the data actually on screen, which is already available as `summary.created_at` / `#runline`. Additionally, disable **Apply** while a load is in flight so a user cannot queue requests against stale state. |
| **Acceptance** | After a failed load the page shows a persistent, non-dismissable-until-success marker naming the displayed run's timestamp; all numeric surfaces are visually de-emphasised; a later successful load clears it. |
| **Confidence** | High (screenshot + live repro) |

### F-03 — A cleared numeric field produces `[object Object]`

| | |
|---|---|
| **Severity** | P1 |
| **Location** | `serving.py` `loadData()` error path; `ui.py:86` `/api/data` (`min_temp: float \| None`); `#mintemp` |
| **Problem** | Emptying **Min °F** submits `min_temp=`, FastAPI rejects it with **422** and a *structured* `detail` array. The client does `throw new Error(j.detail \|\| 'Request failed')`, so an array is string-concatenated into `[object Object]`. |
| **Why it matters** | The message is meaningless, and the instruction attached to it (`Check the server log, then Refresh.`) is unactionable for a user. There is no inline validation, no field highlight, and the field is allowed to be empty by the UI while the API rejects empty. |
| **Evidence** | Live status bar: `Could not load forecast: [object Object]. Check the server log, then Refresh.` (screenshot `01-hero-and-controls.webp`). API: `GET /api/data?min_temp=` → `422 {"detail":[{"type":"float_parsing","loc":["query","min_temp"],"msg":"Input should be a valid number, unable to parse string as a number","input":""}]}`. |
| **Reproduction** | Clear `Min °F`, click **Apply**. |
| **Expected** | `Min °F: enter a number, or leave blank` next to the field, or the blank treated as "no threshold". |
| **Actual** | `[object Object]` in the status bar. |
| **Root cause** | Two error channels: FastAPI's framework 422 (structured) versus the app's own `HTTPException` (string). The client assumes the string shape. |
| **Recommended fix** | Normalise in the client: if `j.detail` is not a string, use `j.detail[0].msg` or a generic fallback. Then prevent the state: treat an empty `#mintemp` as "omit the parameter" rather than sending `min_temp=`, and mirror the same rule for `#skinaz`/`#skintilt`. Add `aria-invalid` + a field-level message on the offending input. |
| **Acceptance** | Clearing any numeric field and pressing Apply yields either a successful load (blank = unset) or a field-level message naming the field's visible label; the strings `[object Object]` and `Check the server log` never appear in the status bar. |
| **Confidence** | High (live repro + raw 422 body) |

### F-04 — The headline sentence uses an internal variable name as its unit

| | |
|---|---|
| **Severity** | P1 |
| **Location** | Hero (`#hero`) and the ICS `SUMMARY` |
| **Problem** | The most prominent sentence in the product reads `Strongest 30 min 1:30 PM – 2 PM — 1136.1 E_mel J/m²; best usable 30 min …`. `E_mel` is the source-code identifier for melanogenic-effective irradiance; `m²` is U+00B2 in some places and `m2` in others. |
| **Why it matters** | The hero is the answer. A first-time user cannot decode `E_mel`, and the units are inconsistent with the ICS and the tables. It also directly violates the project's own published rule that user-facing text must name the endpoint rather than the internal quantity. |
| **Evidence** | Rendered hero: `Strongest 30 min 1:30 PM – 2 PM — 1136.1 E_mel J/m²; best usable 30 min 1:30 PM – 2 PM — 1136.1 E_mel J/m² (confidence 46).` ICS `SUMMARY`: `Best usable sun 1:30 PM-2:00 PM (dose 1111.1 J/m2 E_mel)`. |
| **Reproduction** | Load the page; read the hero. |
| **Expected** | `Best 30 min: 1:30–2:00 PM · dose 1136 J/m² (pigment-weighted)` — a named physical quantity with one consistent unit form. |
| **Actual** | `1136.1 E_mel J/m²`, and the same window reported twice with the same number, so the reader cannot tell what distinguishes "strongest" from "best usable". |
| **Root cause** | The hero template was written against the data field name. |
| **Recommended fix** | Replace with: `Strongest 30 min 1:30–2:00 PM · 1136 J/m² pigment-weighted dose; best usable 1:30–2:00 PM · 1136 J/m².` When the two windows are identical, collapse to one sentence (`Strongest and best usable are the same window today`). Standardise on `J/m²` everywhere (hero, tables, ICS, glossary). |
| **Acceptance** | The strings `E_mel` and `J/m2` appear nowhere in the rendered page or the ICS; the hero states in one clause whether the two ranked windows differ. |
| **Confidence** | High (rendered) |

### F-05 — Personal-MMD basis is offered as four raw enum constants

| | |
|---|---|
| **Severity** | P1 |
| **Location** | `#mmdbasis` `<select>` in the MMD disclosure |
| **Problem** | The options render as `SUNSTACK_EFFECTIVE_DOSE_MEASURED`, `SOURCE_SPECTRUM_MEASURED`, `OBJECTIVE_ESTIMATE`, `COARSE_ESTIMATE` — internal enum identifiers, in a control whose entire purpose is to tell the system *how much to trust the user's number*. |
| **Why it matters** | This is the one control that asks the user to make a scientific provenance judgement. Untranslated constants make that impossible; the user must guess. It also leaks implementation detail into a public UI. |
| **Evidence** | Live: `JSON.stringify([...document.getElementById('mmdbasis').options].map(o=>o.value+'|'+o.text))` → `["|—","SUNSTACK_EFFECTIVE_DOSE_MEASURED|SUNSTACK_EFFECTIVE_DOSE_MEASURED","SOURCE_SPECTRUM_MEASURED|SOURCE_SPECTRUM_MEASURED","OBJECTIVE_ESTIMATE|OBJECTIVE_ESTIMATE","COARSE_ESTIMATE|COARSE_ESTIMATE"]`. The value is echoed back verbatim in the doses line: `Your MMD: 1.31× (30-min, client-side · COARSE_ESTIMATE)`. |
| **Reproduction** | Open the page → open **I have my MMD** → inspect the basis dropdown. |
| **Expected** | Human labels with the code kept as the value, e.g. `value="SUNSTACK_EFFECTIVE_DOSE_MEASURED">Measured with SunStack's dose basis`, and a one-line explanation of why the basis matters and what happens if it is wrong. |
| **Actual** | Raw constants, both in the list and echoed back in the result text. |
| **Root cause** | The option list was generated from the API's accepted values without a display layer. |
| **Recommended fix** | Add a display map (`{value: label}`) used by both the `<option>` text and the result sentence. Recommended labels: `Measured with SunStack's dose basis`, `Measured from the source spectrum`, `Rough estimate from another app`, `Guessed`. Show the basis as plain words in the doses line, not the enum. |
| **Acceptance** | No `[A-Z_]{8,}` token appears in the rendered page; each option reads as an English phrase; the doses line echoes the label, not the value. |
| **Confidence** | High (live) |

### F-38 — A slow response can overwrite a newer one (no request generation check)

| | |
|---|---|
| **Severity** | P1 — source-supported; the latency test was not exercised |
| **Location** | `serving.py` `loadData()` — the fetch result is committed to the global `DATA` with no generation counter, no `AbortController`, and no comparison against the current selection |
| **Problem** | Every successful response is written to `DATA` unconditionally and then rendered. The location selector refetches on `change`, so switching South Bend → Pacific Palisades issues two requests; if the first resolves last it renders its payload **under the second site's controls**, and the Calendar link is rebuilt from the current (newer) controls while the data is older. |
| **Why it matters** | The page would show one location's forecast under another location's name, with a subscription URL that points at the wrong site. The stale-data marker proposed in F-02 covers *failed* loads; it does not cover a successful-but-superseded response, which is the harder case because everything looks healthy. |
| **Evidence** | Source: `loadData()` has the shape `const r = await fetch(url); const j = await r.json(); if (!r.ok) throw …; DATA = j; hide(); render();` with no guard. The location control's handler issues a new request on every `change` (observed in the fetch log during this audit: two `/api/data` calls 3 s apart on one selector interaction). |
| **Reproduction** | Throttle the network, select South Bend then immediately Pacific Palisades; if the first response is slower, the page renders South Bend's rows with `#locsel` on Pacific Palisades. |
| **Expected** | Only the response matching the current selection is committed; superseded responses are discarded or aborted. |
| **Actual** | Last-to-resolve wins. |
| **Root cause** | No request identity in the client's state model. |
| **Recommended fix** | Tag each request with a monotonically increasing generation, capture it before `await`, and drop the result if the generation has advanced; additionally `AbortController` the previous request. The same guard must cover the location-dependent Calendar URL rebuild. |
| **Acceptance** | Under an artificially delayed first response, the rendered location, the payload's `location` field and the Calendar URL always agree, and always match the selector. |
| **Confidence** | Medium-high — the code path is unambiguous, but I did not force the interleaving with network shaping |

---

## P2 findings

### F-06 — No hover feedback on most interactive elements

**Location** `serving.py` stylesheet. **Problem** the only hover rule in the whole
stylesheet is `button:hover`; `.daycell`, `a#cal` (`.btn`), `<summary>` and
`<select>` have none — verified by enumerating `:hover`/`:focus` rules in every
stylesheet (`["button:hover", ":focus-visible", "details > summary:focus-visible"]`).
**Why it matters** the day strip is the primary navigation control and the
Calendar link is the primary conversion action; neither responds to the pointer,
while a `cursor:pointer` affords a click. **Fix** add a shared
`.interactive:hover { … }` treatment and apply it to `.daycell`, `.btn`,
`summary` and the selects; keep the existing amber token. **Acceptance** every
clickable element changes a visible property on hover. **Confidence** High.

### F-07 — The day strip claims a listbox contract it does not implement

**Location** `#strip[role=listbox]` + 14 `.daycell[role=option]`.
**Problem** all 14 options are in the tab order (`tabindex="0"`), there is no
roving tabindex, no `aria-activedescendant`, and **no `keydown` handler exists
anywhere in the client** (`grep keydown` → none). Arrow keys do nothing;
`ArrowRight` leaves the selection unchanged. **Why it matters** a screen-reader
or keyboard user is told this is a listbox, then cannot operate it as one, and
must Tab through 14 cells. **Evidence** tab walk (positions 12–25 are all day
cells); `ArrowRight` on a focused `.daycell` left `#sunsel` at
`2026-10-06T14:00`; `Enter` does work. **Fix** implement the standard pattern —
`tabindex="0"` on the selected option only, `-1` on the rest, Arrow/Home/End move
selection and focus, `aria-activedescendant` on the listbox — or drop the
listbox roles and present them as plain buttons. **Acceptance** one tab stop for
the strip; arrows move the selection; a screen reader announces position and
name. **Confidence** High.

### F-08 — No URL state: nothing is shareable and the browser Back button is inert

**Location** client bootstrap (`restorePlane()`), no router.
**Problem** the page has no query string at any point. Location is not persisted
(`localStorage` holds only `sunstack_surface`, `sunstack_skin_tilt_deg`,
`sunstack_skin_azimuth_deg` — verified before/after reload: Pacific Palisades →
South Bend, surface/tilt retained). **Why it matters** the product's output is a
forecast you would naturally send to someone ("look at Thursday afternoon"), and
the most expensive choice a user makes — their site — is the one thrown away on
reload. Inconsistent persistence within the same control group is also confusing.
**Evidence** `location.search` → `'(no query string)'`; reload resets
`#locsel` to `south-bend` while keeping surface/tilt/azimuth. **Fix** encode
`location`, `date` and the staged controls in the query string via
`history.replaceState`; restore on load; make Back/Forward work. At minimum
persist `location` alongside the other three. **Acceptance** reloading
preserves the site; a copied URL reproduces the same view; Back returns to the
previous selection. **Confidence** High.

### F-09 — The same quantity is named and shown three different ways

**Location** hourly table header `UV∘`; 30-minute table header `UV`; glossary
`UV∘`; day cells `Int`/`Fit`/`Conf`; hourly table `Overall` cell renders a bold
number **plus a `Loc N` subcaption**, while a separate `Local` column exists and
the day cell shows `Abs 34 · Loc 93`. **Problem** one concept, three labels
(`UV∘` / `UV` / "Headline UVI"), and `Local` duplicated inside the `Overall`
cell and again as its own column. **Why it matters** duplication inside a cell
reads as a composite value and makes the column impossible to sort or scan;
inconsistent headers make the two tables look like different data. **Evidence**
`document.querySelectorAll('table')[0]` headers vs `[1]` headers; screenshot
`07-hourly-table.webp` (`Overall` 0 over `Loc 4`, and a `Local` column reading 4).
**Fix** one name per concept (`UV index`), drop the `Loc N` subcaption from the
`Overall` cell (the column exists), and keep `Abs`/`Local`/`Atm` as sibling
columns only. **Acceptance** no concept is rendered under two labels; no value
appears twice in the same row. **Confidence** High.

### F-10 — The deprecated composite still leads in four places

**Location** hero (`Overall 44`), day cells (`day_overall_peak`), both tables
(`Overall` column), the ICS `DESCRIPTION` (`Overall 43/100`), the day header
`· Overall 43`.
**Problem** `overall_tan_opportunity_0_100` is documented in the UI's own legend
as `LEGACY composite (deprecated product heuristic)` and is no longer the
ranking key, yet it is the number rendered most prominently and the one carried
into subscribed calendar events. **Why it matters** a user reading the hero, the
strip or their calendar sees the deprecated metric as the headline; the
deprecation exists only in prose. **Evidence** legend text; ICS
`DESCRIPTION: Best usable sun 1:30 PM-2:00 PM (dose 1111.1 J/m2 E_mel). Overall
43/100. Local 93/100. …`. **Fix** decide the product question — either the
legacy composite is removed from all display surfaces and the ICS, or it is
renamed honestly everywhere (e.g. `Legacy blend`). Keeping it prominent while
calling it deprecated is the worst of both. **Acceptance** no deprecated metric
is rendered without its qualifier adjacent to the number, and the ICS carries
the current ranking objective. **Confidence** High.

### F-11 — Errors name parameters, not fields, and one bad field wedges every later attempt

**Location** `ui.py` validation messages surfaced through `#msg`.
**Problem** messages read `skin_azimuth_deg must be a finite number in [0, 360],
got '720'` — the parameter identifier, not the label the user sees (`Azimuth`).
Because the client sends all fields on every Apply, an unfixed bad value keeps
producing the same error while the user edits *other* fields: setting
`Azimuth=720` then trying `Min °F = 0`, `120`, `-40` returned the identical
azimuth error four times. **Why it matters** the user is told about a field they
are not looking at, with a name that does not appear in the UI. **Evidence**
the four consecutive identical messages; the field label is `Azimuth`
(`document.querySelectorAll('.controls label')` → `Azimuth`). **Fix** map
parameter → label in the client (`skin_azimuth_deg` → `Azimuth`), mark the
offending input with `aria-invalid` and focus it, and validate per-field before
sending so other edits are not blocked. **Acceptance** the message names the
visible label and the field is highlighted; fixing it clears the error without
resubmitting unrelated fields. **Confidence** High.

### F-12 — Client errors are reported as 500 and the advice is to read the server log

**Location** `ui.py:86-149` `/api/data` and `/api/calendar.ics` catch-alls.
**Problem** `location=atlantis` → **500** `{"detail":"404: unknown location:
atlantis"}`; `skin_type=99` → **500** with a 400-style message;
`skin_type=abc` → **500** `"400: invalid skin_type: 'abc'"` — the status code is
literal text inside the message because the inner `HTTPException` was swallowed
by the outer `except Exception`. The client's advice in every failure is
`Check the server log, then Refresh.` **Why it matters** a 500 tells an operator
the server is broken when the request was simply invalid; folding a 400 into a
500 destroys the distinction that monitoring depends on. Telling a *user* to
read a server log is advice they cannot follow. **Evidence** the status/body
table in `functional_qa.md`; status bar text. **Fix** re-raise
`HTTPException` untouched (or restructure so only unexpected exceptions become
500) and keep 4xx for user errors. Change the user-facing fallback to
`Couldn't load that view. Try again, or pick another location.` **Acceptance**
invalid input returns 4xx with the true code; the string `server log` never
appears in a user-facing message. **Confidence** High.

### F-13 — "Source data" shows internal run metadata, not source data

**Location** `<details class="debug"><summary>Source data</summary><pre id="debugtext">`.
**Problem** the panel renders `JSON.stringify(DATA.summary, null, 2)` — **17 106
characters** of the run summary: versions, hashes, calibration metadata,
coordinates. **Why it matters** the label promises the underlying data (the
observations the forecast came from). What is delivered is provenance metadata,
unusable at that size, and the real source data is not reachable at all. A user
who opens it to check "where did this number come from" gets a debug blob.
**Evidence** `document.getElementById('debugtext').textContent.length` → `17106`.
**Fix** either rename it (`Run metadata (JSON)`) and collapse the default to a
summary block of the ~8 keys a user can interpret, or deliver what the label
says: a downloadable/copyable view of the per-source observations for the shown
run. **Acceptance** the label matches the content; the default rendering is
readable without scrolling past one screen. **Confidence** High.

### F-14 — The provenance line is an unpunctuated dump of thirteen identifiers, including a dead reference

**Location** `#provenance` inside Advanced/Photobiology.
**Problem** one rendered line: `Surface Fresh snow · proxy 88.00% · reflected
E_mel 0.13 W/m² · tilt 45° azimuth 200° · spectral tierC-broadband-proxy-v2 /
tier C · fusion calibrated-uvi-fusion-v2 · confidence calibrated-error-v1 ·
rank fixed-duration-dose-v2 · Model action-spectrum-v2 · spectrum tier provisional
· spectral tierC-broadband-proxy-v2 (C) · global ref global-mel-ref-v2
(1.793 W/m²) · CAMS 2026-10-06T12:00Z · UVI agree 6.2% · calib
nasa_power_ml_plus_cams_spectral · UVA model: same-domain MAE 0.33 W/m², live
NWP-fed MAE ~5.8 (train/serve shift, see Research notes)`.
**Why it matters** it is honest and valuable, but unstructured: the same fact is
stated twice (`spectral tierC…` and `spectral tierC… (C)`), `spectrum tier
provisional` competes with `spectral tierC…`, and `see Research notes` points at
a repository file the user has no access to. The final clause is the single most
important caveat on the page (a live-vs-training error gap) and is buried at the
end of a run-on. **Evidence** the rendered string above. **Fix** render as a
labelled definition list (`Data quality`, `Model`, `Reference`, `Caveat`) and
promote the `MAE` caveat to a visible note near the score, not inside a
disclosure. Replace `see Research notes` with a link or drop the clause.
**Acceptance** no fact appears twice; each line has a label; the accuracy caveat
is visible without opening a disclosure. **Confidence** High.

### F-15 — Cell content packs several meanings into one column

**Location** hourly table `Temp`, `Wind`, `Note` cells.
**Problem** `Temp` renders `43.1° fl 39.2° sun-feels 42.2° too cold` (four
facts); `Wind` renders `3 g8` (speed and gust, **no unit**); `Note` renders
`temperature < 50F ☀︎ 2° E` (a blocking reason and a sun bearing) or
`UVI sources disagree · 32° SW`. **Why it matters** units live only in the
glossary, so a scanned table cannot be read without a lookup; and a column named
`Note` carrying both a reason code and a compass bearing is not scannable.
**Evidence** header/cell dump in `inventory.md` §5; screenshot
`07-hourly-table.webp`. **Fix** split into `Temp` / `Feels` / status, add units to
the header (`Wind mph`), and separate the bearing into a `Sun` column or into
the existing sun-figure readout. **Acceptance** every numeric cell carries or
inherits a unit visible in the header; no cell mixes a reason code with a
measurement. **Confidence** High.

### F-16 — The two tables are not comparable

**Location** hourly table (20 columns) vs 30-minute table (6 columns).
**Problem** the 30-minute table — the table whose rows are the actual ranked
unit of the product — shows `Time, UV, UVA, Overall, Local, Source, Note`. It has
**no Confidence**, no dose column, no temperature, and it names the UV column
differently. Neither table is sortable or filterable; neither offers a jump to
the ranked best window. **Why it matters** the ranking objective is a
fixed-duration *dose*, and the dose is not a column in either table; confidence —
which the hero quotes — is absent from the finer table. **Evidence** header
lists; `th` elements have no `role`, `tabindex`, or inner control.
**Fix** give the 30-minute table the columns the product is actually about
(dose, confidence, temperature, block reason), and make both tables sortable by
clicking a header. **Acceptance** dose and confidence are visible at 30-minute
resolution; clicking a header sorts and announces the sort state. **Confidence**
High.

### F-34 — `Export CSV` exports everything, not what you are looking at

| | |
|---|---|
| **Severity** | P2 |
| **Location** | `serving.py` `exportVisibleCsv()` and the only CSV control on the page |
| **Problem** | The handler is named `exportVisibleCsv` and the control sits beside the day-scoped views, but it writes **three global files** — all days, all hourly rows, all 30-minute rows — regardless of the selected day, the visible columns, or the active filters. Nothing in the UI says the export is global. |
| **Why it matters** | A user who has selected a day and toggled the columns reasonably expects the export to match what they are looking at. They get 165 hourly rows and 14 days with no indication, and the filenames (`sunstack-all-hourly.csv`) do not carry the site either, so two sites' exports collide in Downloads. |
| **Evidence** | `onclick="exportVisibleCsv()"`; the handler body calls `dl('sunstack-all-hourly.csv', …)`, `dl('sunstack-all-30min.csv', …)`, `dl('sunstack-all-days.csv', …)` with no reference to the selected date; the success message reads `Exported all ${dall.length} days (…)`. No other CSV control exists on the page. |
| **Reproduction** | Select Wednesday, press Export CSV, inspect the files: they contain all 14 days. |
| **Expected** | Either the export is labelled as global (`Download all data (CSV)`), or it exports the selected day with the visible columns. |
| **Actual** | Global export behind a name that promises the visible view. |
| **Recommended fix** | Rename to `Download all (CSV)` and add a second, day-scoped action (`Download this day (CSV)`) that respects the selected date and the `nerd` column state. Include the site slug and the date in both filenames. |
| **Acceptance** | The control's label states its scope; a day-scoped export produces exactly the rows currently rendered; filenames are unique per site and date. |
| **Confidence** | High (handler read and executed; downloaded file inspected) |

### F-35 — The column-toggle tooltip never updates, so it contradicts the button

| | |
|---|---|
| **Severity** | P3 |
| **Location** | `#nerdBtn` — `title` attribute vs `textContent` |
| **Problem** | Toggling updates the label and `aria-pressed` but not the `title`, so after one click the button reads **"Hide extra columns"** while its tooltip still reads **"Show all 20 columns"**. |
| **Why it matters** | The tooltip is the only place that states the column count; a screen-reader or hover user is told the opposite of the current state. |
| **Evidence** | Before: `{text: "Show all columns", title: "Show all 20 columns", pressed: "false"}`. After one click: `{text: "Hide extra columns", title: "Show all 20 columns", pressed: "true"}`. |
| **Reproduction** | Click "Show all columns"; hover it. |
| **Expected** | The tooltip describes the current action, matching the label. |
| **Actual** | Tooltip frozen at the initial state. |
| **Recommended fix** | Set `title` in the same branch that sets `textContent` and `aria-pressed`. |
| **Acceptance** | After toggling, `title` and `textContent` describe the same action. |
| **Confidence** | High (measured) |

---

## P3 findings

| ID | Location | Problem | Fix | Confidence |
|---|---|---|---|---|
| F-17 | charts | 3 `<canvas>` carry only `title`; no `role="img"`, no `aria-label`, no text alternative or data table | add `role="img"` + `aria-label`, and an off-screen data table | High |
| F-18 | ICS `SUMMARY`/`DESCRIPTION` | `J/m2` (not `J/m²`), `E_mel`, unexpanded `SED`, 9-line description | standardise units; shorten to the answer + one caveat | High |
| F-19 | `api/data` | `min_temp` accepts `-100` and `120` with no bounds while tilt/azimuth are bounded — inconsistent validation | define and enforce a plausible range, or state that it is unbounded | High |
| F-20 | `surface` error message | advertises `custom` among allowed slugs, but `surface=custom` always fails and `/api/data` exposes no reflectance parameter — the option is unreachable | either expose the two reflectance parameters on `/api/data` or stop listing `custom` | High |
| F-21 | `summary.skin_type` | stays `null` when `skin_type=3` is requested while every row carries `fitzpatrick_type: 3` | populate it from the request, or drop the key | High |
| F-22 | performance | CLS **0.16** (above the 0.1 "good" threshold) and `/api/data` takes ~1 170 ms; the page shows `Loading…` for over a second before content settles | reserve space for the strip/tables, and consider a summary-first payload | High (measured) |
| F-23 | consistency | `UV∘` / `UV`; `E_mel` / `TanDose` / `SED` inconsistently expanded; `spectrum tier provisional` vs `spectral tier C` | one name per concept (see `copy_audit.md`) | High |
| F-24 | day header | renders `Overall 43` and elsewhere `day_overall_peak_0_100`; the "opportunity: FAIR" word is unexplained | define the vocabulary in one place, or remove the word | High |
| F-25 | hero | `(confidence 46)` with no scale, no anchor and no explanation; ranges from 1–100 across the dataset | state the scale once, or express as a band (`moderate confidence`) | High |

---

## What is genuinely good, and should not be lost

1. **The failure discipline is real.** When the upstream source returned
   `Unexpected error while streaming data: timeoutReached`, the pipeline refused
   to publish rather than emit a plausible number. That the same product does not
   surface *stale* data honestly once the client already holds it (F-02) is the
   gap, not the principle.
2. **Progressive disclosure exists and works** — four `<details>`, a 12↔20 column
   toggle with correct `aria-pressed`, and a class-row toggle. The **placement**
   of some disclosures is wrong (F-14, F-13), not the idea.
3. **The physics caveats are stated in the product.** `spectral tier C`, the
   Tier-C proxy warning, "not a recommendation", "SED is exposure, never good",
   and the train/serve MAE gap are all rendered. Very few products admit this
   much. They need structure, not removal.
4. **Unit and cross-check discipline in the tables.** `OM`/`CAMS`/`EPA`/`Clear`
   shown side by side with `ΔUV` disagreement, and `—` used for genuinely
   missing values rather than `0`, is exactly right.
5. **The sun figure is a genuine comprehension aid** — it turns an abstract
   score into "the sun is 43° up in the south; lie flat or lift your torso".
6. **Accessibility is close.** Focus rings at 2 px, contrast 5.36–17.61, `lang`,
   headings in order, no images missing `alt`, no motion to reduce, and the
   disclosures already have proper targets after this session's fix.