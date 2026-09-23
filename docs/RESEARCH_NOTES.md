# Research notes behind TanScore 3.0

This file records the rationale so future changes do not quietly turn engineering convenience into biological claims.

## Fitzpatrick type

Fitzpatrick skin phototype is useful as a coarse description of sun-reactive phenotype, but it is not a precise dosimeter. Human studies measuring minimal erythema dose (MED) and minimal melanogenesis dose (MMD) show large within-type ranges, and objective skin color/pigmentation can correlate better with measured response.

Useful references:

- Westerhof et al., *The relation between constitutional skin color and photosensitivity estimated from UV-induced erythema and pigmentation dose-response curves*, PMID 2355184.
- Wulf et al., *Minimal erythema dose and minimal melanogenesis dose relate better to objectively measured skin type than to Fitzpatrick's skin type*, PMID 21091784.
- Ravnbak et al., *The minimal melanogenesis dose/minimal erythema dose ratio declines with increasing skin pigmentation...*, PMID 20584251.
- Diffey et al./related human-response work: *The physiological and phenotypic determinants of human tanning...*, PMID 20648713.

Therefore SunStack:

- accepts Fitzpatrick I-VI,
- displays qualitative personal-response/risk context,
- does **not** multiply environmental TanScore by a made-up skin-type coefficient,
- keeps open the option of future objective skin-color or measured MED/MMD inputs.

## UVA, UVB, and tanning

UVA contributes strongly to immediate and persistent pigment darkening; UVB is highly effective at inducing erythema and delayed tanning/new melanogenesis. Mixed solar-spectrum exposure therefore cannot be represented faithfully by UVI alone.

Reference review:

- Mahmoud et al., *Effects of ultraviolet radiation, visible light, and infrared radiation on erythema and pigmentation: a review*, PMID 23111621.

TanScore therefore predicts UVA separately, retains UVI/UVB information, and uses historical UVA/UVB targets rather than converting cloud cover directly into tanning points.

## NASA POWER

NASA POWER's Hourly API provides analysis-ready hourly data. SunStack uses POWER UVA/UVB as historical calibration targets and broadband solar/meteorological fields as model predictors.

Docs: https://power.larc.nasa.gov/docs/services/api/temporal/hourly/

## Open-Meteo archives

- Historical Forecast API: https://open-meteo.com/en/docs/historical-forecast-api
- Previous Runs API: https://open-meteo.com/en/docs/previous-runs-api

Historical Forecast supplies past operational forecasts in a live-API-compatible format. Previous Runs provides fixed lead-time versions (`previous_day1`, etc.), which is appropriate for model-skill analysis by forecast horizon.

## CAMS

CAMS global atmospheric composition forecasts provide ozone, aerosol optical properties and UV-related diagnostics. CAMS documentation lists UV biologically effective dose, clear-sky UV biologically effective dose, downward UV radiation, and numerous spectral aerosol fields.

Docs:

- https://confluence.ecmwf.int/pages/viewpage.action?pageId=347605172
- https://ads.atmosphere.copernicus.eu/

SunStack strict mode requires direct CAMS spectral AOD around the UVA band plus total-column ozone. AOD550 from Open-Meteo remains a fallback/context field, not a substitute for the full spectral tier.

## Outdoor feasibility is not biology

Temperature, rain, snow, thunderstorms, wind, and humidity should not be assigned fake melanogenesis weights simply because they are available.

SunStack therefore keeps two layers:

1. **Environmental TanScore**: radiation/pigmentation potential.
2. **Outdoor feasibility**: whether that predicted radiation is realistically usable outdoors.

The hard rain/snow/temperature rules are user/product rules, not claims that rain or 49°F changes melanocyte sensitivity. This separation is intentional.

## 2026-09-14 — Independent UVA validation (Payerne BSRN, Feb 2025)
Held-out R² 0.999 decomposes as: linear GHI-only OLS already scores R² 0.990
(MAE 0.76); HistGB adds the rest (MAE 0.32 UVA, 0.023 UVB with R² 0.990 — the
trees earn most on UVB, 4x MAE reduction over linear).
Against independent ground truth (Payerne SL-501A biometer, never in training,
with BSRN GHI/DNI/DHI + Brewer Dobson ozone + EAC4 aerosols as inputs): +42%
bias. Root-caused to INSTRUMENT SCALE, not the model: CERES clear-sky
UVA/GHI = 5.02% (n=2925, tight) vs station 3.5% at matched SZA 60-70. The SL-501
broadband response underweights band edges vs a true 315-400 integral.
Conclusion: the estimator faithfully reproduces its CERES-anchored training
distribution; absolute radiometric truth needs Brewer spectra (WOUDC), not
biometers. No model change made.

## 2026-09-15 — Train/serve clear-sky seam killed + end-to-end skill bounds
- `clear_ghi` was POWER MERRA clear-sky in training but pvlib Ineichen live
  (median abs diff 58 W/m2, p90 120). Moved one shared `solar_features()`
  (calibrate.py) used by both paths; retrained. Cost: UVA MAE 0.324->0.327,
  UVB 0.023->0.024 — negligible, and live consistency is unmeasurable in
  held-out metrics. Pinned by test_train_and_serve_share_clear_sky.
- Mapping skill (POWER inputs): UVA MAE ~0.30 daylight.
- NWP-fed skill (38k hrs archived-forecast inputs): UVA MAE ~5.8, bias +2.1,
  median 4.8. NOT estimator failure: inputs run ~20% brighter (median ghi
  307 vs 251 on agreement rows); model faithfully converts. BSRN Payerne
  cross-check: NWP-archive GHI +48 W/m2 (+29%) vs CMP22 truth, Feb 2025.
  kt verified TOA-based on both sides (corr 0.998); live kt unchanged.
- UVB shoulder audit: SZA<75 rel err fine (p90 8-22%); SZA 85-90 median
  -30% is noise-floor (UVB~0.005, erythemally nil). No change.
- Displayed confidence already sits 15-40% in exactly these low-trust
  regimes; architecture (separate confidence, not folded in) is the right
  mitigation. Direct UVA verification loop vs POWER is latency-blocked
  (radiation params null for Sep 10+ as of Sep 15; recipe: fetch_nasa_power_history
  start/end window + merge runs' tan_forecast_hourly predicted_uva_wm2 on
  time_utc, bin by tan_forecast_confidence_0_100 and lead_h).
- Brewer/WOUDC absolute probe deferred: scale is CERES-consistent,
  ratios inside literature QC band (0.02-0.08), no evidence justifying days
  of spectral integration. Revisit only if SMARTS offline check disagrees.

## 2026-09-15 — Sub-hourly interpolation grounded in HRRR truth
720 native HRRR 15-min rows (10 runs) vs time-interpolation: pure
interpolation error on daylight :15/:30/:45 slots (n=258) is linear-GHI
MAE 53.8 / median 16.0 / p90 143.8. Clear-sky-index (kt x exact-TOA)
wins: MAE 51.5, median 12.1 (-24%), low-sun MAE 23.3 -> 20.6. The big
errors are cloud-edge passages no interpolator can see (p90 ~140 both).
Shipped in build_30min_forecast for shortwave_radiation_instant only
(the measured quantity): exact pvlib TOA at :30 stamps, night-zero
instead of ghost light, bounded 0.7-1.3 propagation to UVA/UVB/UVI +
absolute recompute, native-HRRR override keeps precedence. Pinned by
pre-sunrise ghost test (6:30 slot exactly 0) and mocked-TOA kt-plumbing
test (312.5, not linear 250.0).

## 2026-09-16 — UV/broadband input-coherence flag
best_match is per-variable: only GFS provides UVI while GHI comes from the
hourly winner. On convective days the parts disagree (Sep-16 14:00: GHI 641
+ cloud 100% + UVI 0.65 in one row; GFS alone read 131/1.45/100%,
self-consistent). Response, truth-first: no values touched. New
uv_input_disagree flag (SZA<65, TOA>100, |clear-sky-index gap| with dead
band; twilight/night/NaN never flag) halves confidence and prints a visible
note in both tables. Thresholds are heuristic priors, not fitted.

## 2026-09-18 — Six straight publish failures (uv.lock drift, not science)
All Sep-17 runs (00:23 through 13:23 slots) computed fine — 36/36 feeds,
CAMS cycles resolved — then died at `git pull --rebase` with exit 128
("unstaged changes"). Root cause: the community-files commit dropped
`requires-python` from pyproject.toml, so setup-uv fell back to latest and
rewrote uv.lock mid-run; the dirty lock blocked the rebase. Fix: restored
`requires-python`, pinned `[tool.uv] required-version ==0.12.15` + explicit
setup-uv `version`, `uv sync --locked` (fail loudly instead of rewriting),
publish discards uv.lock churn and falls back to `-X theirs` on mid-run
local pushes. Workflow test now pins all of it.

## 2026-09-22 — Sun-position lay guidance (context, not scoring)
New columns sun_compass / torso_lift_deg / sun_posture_guidance from pvlib
geometry already in the feature frame: 16-point compass from azimuth,
torso lift = 90 - elevation (None below horizon), three-band guidance
(flat >= 55°, flat-or-lift 30-55°, face-and-lift < 30°). Half-hours
recompute from interpolated geometry rather than nearest-filling text.
UI gains a sun-arc SVG + stick figure (legs flat, torso lifts toward the
sun side) with click-any-row and a time dropdown. No score touched.

## 2026-09-22 — Multi-location support (registry + per-site runs + intake)
locations.yaml is the single registry (South Bend default; Palisades test
site appended). config.use_site scopes LAT/LON/TZ per block with restore;
_calibration_paths/run_live/bootstrap namespace to data/sites/<slug> while
the default keeps the legacy layout. UI/API/export/calendar carry location
(South Bend default; per-site UIDs; per-site ICS timezone). Public intake:
location_request template + location-intake workflow (pull_request_target
on BASE commit, no secrets) validates append-only proposals and comments a
plan; owner merge required before any calibration runs. Workflow exports
per-site dirs and publishes data/sites calibration.

## 2026-09-22 — Per-site alternating publish; cold sites skip (zero quality change)
Forecast job alternates run→export→publish per site (run_one_site) instead
of run-all→publish-all: South Bend publishes its own commit before Palisades
starts, so a slow/failing second site can never take down fresh SB data.
Cold sites raise _SiteSkipped (warning, not failure); location-calibrate owns
bootstrap. Identical code path per site, strict on, no fallback tiers —
quality cannot regress by construction. 502s in the Sep-22 log are ADS
queue saturation (Bad Gateway from the retrieve proxy, retried after 120s),
not request-shape errors; the 400s are the unpublished newest cycle.

## 2026-09-23 — Photobiology v4 (action-spectrum TanScore + TanDose)

Replaces the heuristic 55/30/15 Absolute (55% UVI + 30% UVA + 15%
sqrt(UVIxUVA)) with a wavelength/action-spectrum model:

- `E_mel = integral E_lambda S_mel dlambda` (Parrish-approximated provisional
  spectrum, log-space interpolation, 280-400 nm @1 nm); Absolute =
  100*E_mel/1.6 (global-mel-ref-v1-provisional, 99.9th percentile).
- Tier-C broadband runtime mapping derives band weights from the spectrum
  itself (w_uvb~0.57, w_uva~0.005); wavelength-additive by construction, no
  sqrt interaction (Keong 1990 photoaddition, PMID 2103131; Wolber 2008 kept
  as downstream-response evidence only).
- TanDose = trapezoidal integral of E_mel with gap splitting
  (SUNSTACK_TANDOSE_MAX_GAP_S); SED = integral(E_ery)/100 independent channel
  that never increases scores; UVA/UVB physical doses diagnostic only.
- Direct CAMS UVBED/clear-sky/downward UV plus all spectral aerosol optics
  (340/355/380/400) propagated; CAMS UVI = 40*UVBED; CAMS/OM disagreement
  reduces confidence only. Validation on the Palisades latest run shows a
  ~4-5 h CAMS-vs-OM diurnal phase offset (MAE ~3.2 UVI) under investigation;
  the disagreement penalty is the correct architectural response.
- Local reference rebuilt with v4 scores (legacy kept as diagnostic column
  `legacy_absolute_tan_score_55_30_15` for one migration version).
- Human-literature aggregates encoded in data/research/exposure_studies.json
  (no fabricated subject data); TanResponse stays interface-only until a
  fitted model beats cumulative dose on held-out studies.
- Primary references: Parrish 1982 (PMID 7122713), Keong 1990 (PMID 2103131),
  Ravnbak & Wulf 2007 (PMID 17256147), Miller 2008 (PMID 18616777), Ravnbak
  2009 (PMID 19688146), Ravnbak 2010 (PMID 20584251), Wolber 2008
  (PMID 18627527), MITF timer mechanistic prior (PMID 30401431).

## 2026-09-23 (follow-up) — v4 references rebuilt, stratified validation, literature gates

- Rebuilt `local_reference` (south-bend 108744 rows, pacific-palisades 111696
  rows) with v4 action-spectrum scores via `scripts/rebuild_v4_references.py`
  (legacy kept as diagnostic column only). Empirical grounding: pooled
  daylight Tier-C E_mel p99.9 = 1.522 W/m^2 across both sites' NASA POWER
  climatology; adopted reference 1.6 retains ~5% headroom for unsampled
  equatorial/high-altitude extremes (recorded in reference.json, value unchanged).
- `docs/validation/external_validation.md` now stratifies holdout UVA/UVB
  errors and CAMS-closure error by SZA/cloud/season/AOD340/ozone. Closure bias
  concentrates at high sun (SZA 30-50, bias -4.4) with near-zero CAMS values
  at Open-Meteo peak — consistent with a ~4-5 h decoded-valid-time phase
  offset, not a scale error; UVI-disagreement confidence penalty is the
  correct response pending a fix in CAMS time decoding.
- `scripts/check_literature.py` -> `docs/validation/literature_sanity.md`:
  all gates pass (Parrish UVB/UVA 1247x, Keong photoaddition exact,
  erythema/melanogenesis spectral crossing 1.44x at 300 nm vs 3.11x at
  340 nm, IPD UVA-dominant/UVB-silent, SED/TanDose divergence 5.40 vs 2706).
  Two provisional-shape bugs caught by the gates and fixed: IPD Gaussian was
  too broad shortward (added 312 nm logistic cutoff), and the assumed
  erythema>>melanogenesis ordering at 320 nm was backwards (spectra cross).
- Migration report gains UVA-rich vs UVB-rich divergence quintiles: most
  UVB-rich +9.8, most UVA-rich -0.7 under v4 — the intended reordering.
- Tier-B path scaffolded: `scripts/build_spectral_corpus.py` (stratified
  design over SZA/ozone/altitude/aerosol/albedo/cloud ranges, DRAFT uvspec
  template, manifest with checksums; runs uvspec only when installed) plus a
  strict `validate_tierB_manifest` contract in spectral.py.
- Remainders wired: per-30-minute `calendar-30min.ics` export, pigment-channel
  CSV columns, Visible-Darkening Potential in the UI dose row,
  personalization columns in live outputs (NaN until measured MMD supplied),
  broadband sqrt-correction rationale documented (sublinear broadband
  response, not a scoring weight).

## 2026-09-23 (follow-up 2) — CAMS time-decoder hardening + offline v4 re-score

- CAMS time-axis audit: the decoded `cams_direct_forecast` grid is correctly
  spaced (121 hourly rows) so the ~4-5 h CAMS-vs-OM diurnal offset is a phase
  anchoring question, not a collapse; raw netCDFs are not retained locally so
  the decode source cannot be re-examined here. Hardened
  `history._dataset_time_column` with `_cams_step_delta`: bare numeric steps
  are read as hours (CAMS leadtime_hour convention) instead of falling into
  `pd.to_timedelta`'s nanosecond default, which would collapse a forecast onto
  its reference time. Locked with `tests/test_cams_time_decode.py` (6 tests:
  valid_time passthrough, reference/timedelta, reference/numeric-hours,
  time/timedelta, time-only fallback, no-time empty, all through real .nc
  files via `normalize_cams_netcdf_zip`).
- Offline end-to-end v4 re-score (`scripts/rescore_latest_v4.py`) of the real
  Palisades latest run: 336 hourly -> 671 half-hours -> 14 days with ZERO
  photobiology/scoring validation errors; v4 max 68.9 at E_mel 1.10 (below
  the 1.6 global ref, correct for a temperate-September peak); daily TanDose
  15.6-22.5 kJ mel with complete coverage; 14 daily + 671 interval ICS
  events. Local scores 100% non-null against the rebuilt v4 reference.
  Report: `docs/validation/v4_rescore_verification.md` (artifacts in scratch).

## 2026-09-23 (follow-up 3) — audit-driven scoring tests

- New `tests/test_v4_scoring.py` (7 tests) pins previously untested
  production behavior offline: v4 Absolute equals 100*E_mel/E_ref with the
  legacy value present-but-unused; all 16 direct CAMS fields propagate with
  real sanitized column names (UVBED->erythemal, CAMS UVI = 40x,
  transmission, downward-UV differentiation to ~0.25 W/m^2); strong
  CAMS/Open-Meteo disagreement discounts confidence 80->52 while E_mel and
  Absolute stay bit-identical; window selection is dose-invariant (photon
  scaling x10 selects identical windows, doses x10); canonical dose columns
  exist at primitive/interval/window/day levels; SED gaps split with
  complete=false; TanResponse baseline returns cumulative dose only.
- Window-ranking semantics confirmed and documented: eligible groups (within
  12 of peak opportunity) prefer sustained length; TanDose never enters
  ranking. Fixed two of my own test expectations (hourly UVI-6 SED is 5.4,
  not 2.7; eligibility threshold is inclusive).

## 2026-09-23 (follow-up 4) — audit: honest unknown doses + row-level gap flags

- Found by audit: `_rolling_dose` returned 0.0 when NO timestamps fell in a
  trailing window (e.g. trailing-30m dose on an hourly grid) — 0 implies no
  exposure, but the truth is unknown. Now returns NaN with
  `tan_dose_{15m,30m,1h}_complete=false` and coverage 0; night rows with real
  coverage still integrate as true zero. Row-level
  `tan_dose_*/sed_*_complete` + `coverage_fraction` flags added per §1.3
  (timestamp-only, shared across dose families; SED carries its own pair).
- Pinned: sub-grid windows are NaN-not-zero, night-zero stays complete,
  Absolute is location-independent while Local percentiles move with the
  reference climatology (§21 invariant).

## 2026-09-23 (follow-up 5) — full §§1-27 completion audit

- Verified with evidence: spectrum metadata complete + checksums OK (all 4);
  global manifest carries all 10 required fields; summary writer emits all
  §20 keys; daily summaries carry every §18 field; snow still hard-blocks
  opportunity while albedo stays in physics.
- Fixed: Tier-B reserved-input contract (`emulator_manifest`
  `tierB_reserved_inputs`) now names a consumer for every carried-but-unused
  CAMS field, closing §7's fetch-and-drop gap; local-reference version +
  stale flag on every scored row with a validation WARN on mismatch (§10
  loudness); duplicate-wavelength diagnostics now precede monotonicity so the
  error names the actual defect (§19).
- Pinned: spectrum rejection paths (negative/non-monotonic/duplicated/
  truncated/missing), impossible-irradiance rejection, manifest metadata
  contract, pigment/opportunity separation — 88 tests passing.
- Honestly remaining (need network, raw files, or libRadtran): live-run
  refresh of committed `latest/` tables, raw-CAMS phase-anchor trace,
  equatorial/high-altitude corpus + Tier-B training, TanResponse fitting
  (spec-gated), South-Bend-specific run inspection (no SB latest locally).

## 2026-09-23 (follow-up 6) — first live v4 South Bend run (Open-Meteo live, CAMS absent)

- Ran `sunstack run --site south-bend --allow-degraded` (no ADS credentials
  in this environment, so direct CAMS was empty and the tier system behaved
  as designed: `tan_calibration_tier=nasa_power_ml`, spectral tier C,
  UVI-agreement confidence path idle). 336 hourly -> full 30-min/daily chain
  with all v4 columns, `local_reference_stale=false`, local scores 100%
  against the rebuilt reference, daily TanDose complete coverage.
- Headline SB question answered on live late-September data: peak hour
  Absolute 47.8 / Local 91.8 (UVI 5.35, UVA 43.7) — excellent locally without
  becoming globally near-100. v4 mean/max 8.8/47.8 vs legacy 9.3/43.2,
  Spearman 0.989; divergence bins on live data repeat the climatology result
  (most UVB-rich +3.1, most UVA-rich -2.9).
- Export pipeline verified end-to-end on the live run: `docs/data.json`
  payload carries v4 columns + full §20 summary keys, `calendar.ics` 13
  daily events, new `calendar-30min.ics` 671 interval events.
- The run's auto-publish commit was reverted to keep generated docs out of
  the feature PR (publishing belongs to the scheduled workflow); run tables
  remain locally under data/ (gitignored) for inspection.

## 2026-09-23 (follow-up 7) — live export surface verified to scratch

- `sunstack export --site south-bend` against the live v4 run: payload
  complete at all levels, §20 summary keys present with honestly degraded
  CAMS fields (`direct_cams_used=false`, `cams_cycle=null`,
  `calibration_tier=nasa_power_ml`), CAMS ERROR retained in
  `validation_issues`, 13 daily + 671 interval calendar events, all UI
  anchors present. Details: `docs/validation/live_export_verification.md`.
  Export wrote only the scratch dir; committed docs untouched.

## 2026-09-23 (follow-up 8) — migration report answers §25 on live SB data

- `docs/migration/legacy_vs_v4_comparison.md` gains a live-South-Bend section
  (336 hourly rows, dual-scored in production, not recomputed): peak Absolute
  47.8 at Local 91.8 (CONFIRMED excellent-locally/not-globally-near-100);
  confidence/lead Spearman -0.43 vs Absolute/lead -0.00 (CONFIRMED separate).
- Cloud-cover proxy check came back INCONCLUSIVE rather than forced:
  matched-level deltas (-0.8 cloudy vs -1.3 clear, n=41/44) slightly favor
  clear, because this run's cloudy sample is small and low-sun. The
  UVA/UVB-ratio bins — the direct mechanism test — confirm strongly in the
  same data (+3.1 most UVB-rich to -2.9 most UVA-rich), so the report says
  exactly that instead of laundering a weak proxy into a pass.

## 2026-09-23 (follow-up 9) — degrade loud, never needlessly, never silently

- Missing inputs now integrate as UNKNOWN (NaN + incomplete) at every level:
  `_trapezoidal_dose` returns NaN/False/0.0 on zero valid samples and
  0.0/False/0.0 on a lone sample; `add_interval_doses` no longer `fillna(0)`s
  absent irradiance (only measured night zeros integrate as zero);
  `day_totals`/`window_dose` treat missing columns as NaN; interior NaN
  samples are skipped as absent rather than zeroed. SED still derives from
  UVI when erythemal is absent (data we have), via shared `_ery_or_uvi`.
- No-extrapolation rule in the 30-min resample: pandas time-interpolation
  forward-fills trailing NaNs, which flatlined every CAMS column across the
  9 days past the 5-day CAMS horizon. Stamps outside each column's hourly
  valid span now revert to NaN; interior interpolation kept. Run-constant
  tier/version metadata (spectral_tier, model versions, cams_cycle, …) is
  carried forward instead — data we have, kept; observations we lack, never
  fabricated. Time-varying CAMS fields are explicitly excluded from carrying.

## 2026-09-23 (follow-up 10) — no-extrapolation verified on real CAMS data

- Re-ran the Palisades v4 re-score post-hardening: 30-min `uvi_cams` is valid
  on exactly the hourly valid span (ends 06:00 local 9/27) with zero stamps
  fabricated past the CAMS horizon, while `spectral_tier=C`,
  `tan_score_model_version`, and `cams_cycle` carry through all 671 rows and
  the new 30-min complete/coverage flags populate (mean coverage 0.999).
- Near-miss documented: scratch analysis initially read a 7-hour discrepancy
  into the tails by parsing tz-naive local `dt` strings as UTC. The pipeline
  was correct; the notebook was wrong. Timezone-naive wall times must never
  be compared against UTC stamps without localization — added here so the
  next audit does not re-litigate it.

## 2026-09-23 (follow-up 11) — dashboard JS proven, dose-row labels fixed

- The inline dashboard script is invisible to ruff, so it was checked with
  `node --check` (parses clean) and executed headlessly: full page script
  evaluated with a stub DOM against the live South Bend `data.json`, then
  `renderDoses()` driven for a mid-forecast day. Row renders with real values
  and no NaN/undefined leaks (peak-30m 1299 J mel, best-window 8571 J,
  day 15463 J / 161 ref-min, SED 27.54, IPD ~3x TanDose as expected from the
  spectra). Harness was /tmp scratch (no node infra in repo); method kept
  here for repeatability.
- Label bug fixed by that exercise: the row showed the day's first two
  (midnight) rows under "this 30 min / next hour" headings. It now reads
  peak-30m (with timestamp), best-hour (with timestamp), best-window, and
  day values, with Visible-Darkening Potential computed as the day's max
  30-min IPD dose.
