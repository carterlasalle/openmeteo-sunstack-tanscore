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
