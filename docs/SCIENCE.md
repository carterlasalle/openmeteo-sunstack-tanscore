# SunStack Science — the complete mathematical and physical record

> **What this file is.** Every formula, weight, threshold, data source, and connection in the
> SunStack solar/UV forecast stack, transcribed from the code (`src/sunstack/`) and the dated
> research log (`docs/RESEARCH_NOTES.md`), with literature provenance. If a number below
> disagrees with the code, **the code wins** — file a correction against the cited path.
>
> **Honesty contract (architectural, enforced in code).** Environmental physics
> (radiation → skin-weighted exposure) and outdoor usability (can a human actually lie
> outside?) are separate layers that never contaminate each other. Missing data integrates
> as UNKNOWN (`NaN` + `complete=false`), never as zero. Confidence discounts *trust*;
> it never rescales photons. Skin type changes *interpretation*; it never multiplies the
> environment. Every place an older version violated one of these, the log entry is cited.
>
> **v5 model identity.** `schema_version = sunstack-output-v5`; temporal support
> `interval-contract-v1`; photobiology `delayed-pigmentation-v2`; action spectrum
> `parrish-fda-3630-v1`; surface `uv-surface-v1`; fusion `calibrated-uvi-fusion-v2`;
> confidence `calibrated-error-v1`; window rank `fixed-duration-dose-v2`. Strict,
> gate-passing spectra identify `tierB-libradtran-emulator-v1`; explicitly degraded
> spectra identify `tierC-broadband-proxy-v2`.

---

## 0. The two questions, kept apart on purpose

| # | Question | Answered by | Uses temperature, rain, wind? |
|---|----------|-------------|-------------------------------|
| 1 | **How strong is the tanning radiation, physically?** | Environmental TanScore: Absolute (global), Local (seasonal percentile), Atmosphere (geometry-matched percentile) | **No.** By design (`docs/RESEARCH_NOTES.md` §"Outdoor feasibility is not biology"). |
| 2 | **Can I actually use it lying outside right now?** | Outdoor feasibility → Overall opportunity | **Yes** — as usability penalties and hard blocks, never as melanogenesis weights. |

The pipeline answers Q1 first (`tanscore.score_forecast`), then multiplies by usability
(`opportunity.apply_outdoor_feasibility`). Nothing downstream ever flows backward:
feasibility cannot change $E_{\mathrm{mel}}$, Absolute, or any dose.

**The score family at a glance** (all 0–100 unless noted):

- `tan_score_absolute_0_100` — global melanogenic intensity. Physics.
- `local_tan_score_0_100` — seasonal percentile of Absolute against local climatology. Interpretation.
- `atmospheric_quality_percentile_0_100` — same percentile but restricted to matching solar geometry. Interpretation.
- `tan_forecast_confidence_0_100` — trust in the forecast. Uncertainty, not physics.
- `outdoor_feasibility_0_100` — usability multiplier (1.0 = perfect, 0.0 = hard-blocked).
- `overall_components_unblocked_0_100` — geometric merge of the four above, *before* feasibility.
- `overall_tan_opportunity_0_100` — LEGACY composite (deprecated product heuristic), not the recommendation ranking.

---

## 1. Data sources — everything in, nothing invented

### 1.1 Live forecast feeds (Open-Meteo)

Base URLs (`src/sunstack/fetch.py`): `https://api.open-meteo.com/v1/forecast`,
`https://ensemble-api.open-meteo.com/v1/ensemble`,
`https://air-quality-api.open-meteo.com/v1/air-quality`. Shared params: site
lat/lon/timezone, `temperature_unit=fahrenheit`, `wind_speed_unit=mph`,
`precipitation_unit=inch`, `cell_selection=land`, `forecast_days=14`
(`SUNSTACK_FORECAST_DAYS`). HTTP: 120 s timeout, 5 retries, 0.35 backoff; live runs
bypass the 900 s cache (`fresh=True`); historical endpoints use a 30-day cache.

**Deterministic models** (each fetched separately, `config.DETERMINISTIC_MODELS`):

```text
best_match, ncep_hrrr_conus, ncep_nbm_conus, ncep_nam_conus, ncep_gfs_global,
ncep_aigfs025, ecmwf_ifs, ecmwf_aifs025_single, icon_seamless, cmc_gem_seamless,
gem_regional, gem_hrdps_continental, ukmo_seamless, bom_access_global, cma_grapes_global
```

Only `best_match` scores — every other deterministic model exists for the
deterministic-agreement confidence term (§6.1). Per-variable truth: `best_match` itself
is per-variable, so GHI can come from one model while UVI comes from another (§6.3
handles the resulting incoherence).

**Hourly variables** (`config.HOURLY_VARIABLES`, the full scoring surface): temperature,
RH, dew point, apparent temperature, wet-bulb (`temperature_2m`, `relative_humidity_2m`,
`dew_point_2m`, `apparent_temperature`, `wet_bulb_temperature_2m`), pressure/visibility/
weather-code, 4 cloud layers (`cloud_cover{,_low,_mid,_high}`), precipitation family
(`precipitation_probability`, `precipitation`, `rain`, `showers`, `snowfall`), wind
(`wind_speed_10m`, `wind_direction_10m`, `wind_gusts_10m`), UV (`uv_index`,
`uv_index_clear_sky`, `sunshine_duration`, `is_day`), CAPE/LI/CIN/freezing level/
boundary layer/water-vapour/ET0/VPD, broadband radiation (`shortwave_radiation`,
`direct_radiation`, `diffuse_radiation`, `direct_normal_irradiance`,
`terrestrial_radiation`, plus all five `_instant` variants), and upper-air
profiles (RH/cloud/geopotential at 925/850/700/500/300 hPa). Daily aggregates
(`config.DAILY_VARIABLES`) and current conditions ride along.

**Deep profiles** (`PROFILE_MODELS` × 8 levels 1000→300 hPa × 6 fields) are fetched
separately so an unsupported pressure field can never break the main request.

**HRRR 15-minute truth** (`hrrr_15min_params`): `ncep_hrrr_conus`,
`forecast_minutely_15 = 72` steps (`SUNSTACK_HRRR_15MIN_STEPS`), radiation + weather
subset (`config.HRRR_15MIN_VARIABLES`). Native `:00/:30` stamps override interpolation
(§8); the full 15-min grid enriches hourly UV by inside-only time interpolation with
explicit `uv_temporal_source = best_match_hourly_time_interpolated` labeling
(`derive.enrich_15min_with_hourly_uv`).

**Ensembles** (confidence only, never scored directly): full-member
`ncep_gefs025`, `ncep_aigefs025`, `ecmwf_ifs025_ensemble`, `ecmwf_aifs025_ensemble`
plus 9 mean+spread systems (`config.ENSEMBLE_MEAN_VARIABLES` = each ensemble variable
× `{value, _spread}`). Member thresholds feed §6.1 probabilities.

**Air quality** (`domains=cams_global`, 7 days): PM, gases, `aerosol_optical_depth`
(AOD550 — fallback/context only, never a substitute for spectral AOD), dust, UVI pair,
US AQI family. Merged onto best-match by `derive.merge_air_quality` as `air__*`.

**Feed-use ledger** (`fetch._FEED_USE`): every fetched feed declares its consumer —
scoring core, sub-hour correction, confidence, or `diagnostic-only (persisted,
unscored)`. The run manifest records raw payload SHA256s; the UI "Source range"
line is generated from this ledger, so an unscored feed can never silently pose as
a scoring input.

### 1.2 EPA/NWS operational UVI (third UVI vote)

`https://enviro.epa.gov/enviro/efservice/getEnvirofactsUVHOURLY/ZIP/{zip}/JSON`
(+ daily-peak sibling). US ZIP sites only, opportunistic: absence degrades to
two-source consensus, never gates the run (`history.fetch_epa_uv_forecast`,
`normalize_epa_hourly`). Values are integer-rounded at low sun — the design-gap
note in the log records that display rounding can hide sub-threshold spreads.

### 1.3 Direct CAMS (Copernicus ADS — the spectral backbone)

Dataset `cams-global-atmospheric-composition-forecasts` via `cdsapi`, 5 request
groups isolating incompatibilities (`config.CAMS_FORECAST_VARIABLE_GROUPS`):

- **uv**: `uv_biologically_effective_dose`, `..._clear_sky`, `downward_uv_radiation_at_the_surface`
- **spectral_aod**: total + absorption AOD at **340/355/380/400 nm** (8 fields)
- **aerosol_optics**: SSA + asymmetry factor at 340/355/380/400 nm (8 fields)
- **columns**: total-column ozone, water vapour, cloud liquid/ice water, forecast albedo, total cloud
- **radiation_context**: direct + downward surface solar radiation

Strict mode requires the spectral AOD pair around the UVA band plus total-column
ozone; without ADS credentials the run fails loudly (`DataValidationError` + FATAL
banner) unless `--allow-degraded`. Cycle selection walks newest-first from the
latest safe cycle, skipping unpublished cycles (ADS 400 = "not published yet",
retried, not fatal); the run records **all** contributing cycles
(`cams_cycles_used`), because `iloc[0]` once hid mixed-cycle runs. Decoded grids
are 121 hourly rows; the time decoder reads bare numeric steps as leadtime-hours,
never `pd.to_timedelta`'s nanosecond default (which would collapse a forecast onto
its reference time) — pinned by `tests/test_cams_time_decode.py`.

**CAMS field semantics** (`tanscore._cams_features`, the unit mapping the user asked
to have done carefully):

- UVBED fields are dose **rates** (erythemally weighted $\mathrm{W\,m^{-2}}$) mapping
  1:1 to erythemal irradiance; CAMS UVI $= 40 \times E_{\mathrm{ery}}$; transmission
  $T_{\mathrm{UV}} = \mathrm{UVBED}/\mathrm{UVBED_{clear}} \in [0, 1.5]$.
- Downward surface UV is an **accumulated dose** ($\mathrm{J\,m^{-2}}$) and is
  time-differenced to irradiance ($\mathrm{W\,m^{-2}}$, clipped ≥ 0, first stamp
  forward-filled when daytime).
- Ozone arrives in $\mathrm{kg\,m^{-2}}$ or DU: divided by $2.1415\times10^{-5}$ when
  the median is below 5 (auto-detect), else passed through.
- All 16 aerosol-optics fields propagate to every row (never fetch-and-drop);
  Tier-C consumes AOD340/380 (+355/400 via Ångström, §4.3) and ozone; the rest are
  reserved Tier-B emulator inputs by manifest contract.

### 1.4 Calibration history (how the model learned)

| Dataset | Endpoint / params | Role |
|---------|-------------------|------|
| NASA POWER hourly | `power.larc.nasa.gov/api/temporal/hourly/point`, **exactly 15 params** (API max): `ALLSKY_SFC_UVA/UVB/UV_INDEX` (targets), `SW_DWN/DNI/DIFF`, `CLRSKY_SFC_SW_DWN`, `ALLSKY_KT/SRF_ALB`, `AOD_55`, `CLOUD_AMT`, `SZA`, `T2M`, `RH2M`, `PS`; 2001 → today−120 d | UVA/UVB estimator training + local climatology |
| Open-Meteo Historical Forecast | `historical-forecast-api…/v1/forecast`, 16 vars, 2022 → today−2 d | NWP-fed skill measurement |
| Open-Meteo Previous Runs | `previous-runs-api…/v1/forecast`, 7 base vars × leads 0–7 d × {HRRR, NBM, GFS, IFS} | Model skill by lead time; retrospective UVI reference (`best_match`, shared-DNA caveat) |
| CAMS EAC4 reanalysis | 6 vars (AOD 469/550/670/865, ozone, cloud), 2003–2025, 3 workers, 1800 s timeout | Aerosol/ozone training columns |
| BSRN Payerne (Feb 2025, external) | SL-501A biometer + CMP22 + Brewer ozone, never in training | Independent validation (§11.2) |

`calibrate.prepare_nasa_training` renames POWER fields to the 15-feature schema
(`uva, uvb, uvi, ghi, dni, dhi, clear_ghi, kt, albedo, aod55, cloud, sza, temp_c,
rh, pressure_kpa` + CAMS `ozone_du, aod340, aod380` via Ångström interpolation),
drops constant/NaN columns **loudly** (logged + recorded in bundle/metrics — a
CAMS-less bootstrap once crashed inside sklearn binning instead), and merges
Open-Meteo history within ±35 min (`merge_asof`, single `datetime64[ns, UTC]` unit).

---

## 2. Photobiology core (v5 delayed-pigmentation endpoint)

Production TanScore normalizes the canonical environmental-horizontal
`delayed_pigmentation_effective_irradiance_horizontal_wm2`. It is an
action-spectrum-weighted exposure endpoint, not measured melanin synthesis or a
prediction of future skin color. Optional `skin_plane_*` values are separately
reported geometry/surface context; they never overwrite the environmental field.
No hand weights. No square-root interaction. (`docs/PHOTOBIOLOGY_MODEL.md`.)

### 2.1 The master equations

Environmental-horizontal spectral irradiance $E_{\lambda,h}(t,\lambda)$
[$\mathrm{W\,m^{-2}\,nm^{-1}}$], 280–400 nm at 1 nm, is convolved with the
delayed-pigmentation action spectrum $S_{\mathrm{DP}}(\lambda)$:

$$E_{\mathrm{DP},h}(t) = \int_{280}^{400} E_{\lambda,h}(t,\lambda)\, S_{\mathrm{DP}}(\lambda)\, d\lambda$$

$$ \mathrm{Absolute}(t) = \mathrm{clip}\!\left(100\,\frac{E_{\mathrm{DP},h}(t)}{E_{\mathrm{ref}}},\, 0,\, 100\right), \qquad E_{\mathrm{ref}} = 1.6\ \mathrm{W\,m^{-2}} $$

The optional skin-plane counterpart is built from direct, diffuse, and local
reflected components before the same action-spectrum convolution. The action
spectrum identity is `parrish-fda-3630-v1`; strict canonical gates fail loudly
when its required source/backend is unavailable, while degraded output remains
explicitly labeled.

**Why no interaction term.** Keong et al. 1990 (PMID 2103131) exposed humans at
290 + 360 nm: fractional UVA/UVB minimal-pigmentation doses combine by
**photoaddition**, even across a 3-hour gap — so the irradiance model is
wavelength-additive, $\sum E_\lambda \cdot w_\lambda$, not $\sqrt{\mathrm{UVA}\cdot
\mathrm{UVB}}$. Wolber et al. 2008 synergy is downstream-response evidence,
quarantined in the interface-only `tan_response.py`, never allowed to rescale
photons inside TanDose.

### 2.2 Tier-C degraded broadband proxy (`tierC-broadband-proxy-v2`)

The estimator predicts broadband UVA (315–400) and UVB (280–315); Tier-C spreads
each uniformly within its band and convolves with $S_{\mathrm{mel}}$. The band
weights **derive from the spectrum itself** (trapezoidal band means), not tuning:

$$w_{\mathrm{uvb}} = \frac{1}{35}\int_{280}^{315} S_{\mathrm{mel}}\,d\lambda = 0.572430, \qquad w_{\mathrm{uva}} = \frac{1}{85}\int_{315}^{400} S_{\mathrm{mel}}\,d\lambda = 0.005124$$

$$E_{\mathrm{mel}} = \mathrm{UVB}\cdot w_{\mathrm{uvb}} + \mathrm{UVA}\cdot w_{\mathrm{uva}}$$

($0.572430$ / $0.005124$ evaluated live from the shipped spectrum via
`spectral.band_effective_weights()` — constants, not inputs.) So
$w_{\mathrm{uvb}} \gg w_{\mathrm{uva}}$: a unit of UVB carries $\approx 112\times$ the
delayed-melanogenesis weight of a unit of UVA. Known limitation (documented,
secondary on current evidence): real spectra concentrate UVB at 305–315 nm where
effectiveness differs steeply from the band mean — but Tier-C on measured POWER
broadband yields a ratio flat at ~7.4 across SZA 0–80°, so the live-run SZA fall
(§11.3) is attributed to forecast-UVI bias, not band shape. Full libRadtran
emulation (Tier-B) must reproduce the SZA-ratio curve against real spectra.

**Tiers:** A = reference reconstruction (reserved); B =
`tierB-libradtran-emulator-v1`, usable only after the manifest gates version,
training-manifest SHA, libRadtran provenance, parameter ranges, and held-out
metrics; C = explicitly degraded `tierC-broadband-proxy-v2`; D = unavailable
(strict fails). A/B can never be claimed without their manifest gate, and C is
never a silent fallback.

**Degraded parametric clear-sky path** (`degraded_clear_sky_parametric_v1`;
legacy alias `tierB-clear-sky-v1`, used only with no ML bundle):
Beer–Lambert direct + parametric diffuse against TOA band integrals (UVA 68,
UVB 4.6 $\mathrm{W\,m^{-2}}$), Ridge-fitted once on POWER train years:

$$T_{\mathrm{UVA}} = e^{-0.0021\,O_3/\mu - 0.55\,\tau/\mu}(1+0.35\alpha), \qquad T_{\mathrm{UVB}} = e^{-0.0110\,O_3/\mu - 0.85\,\tau/\mu}(1+0.30\alpha)$$

$$ \mathrm{UVA} = 68\,\mu\,\mathrm{clip}(T_{\mathrm{UVA}},0,1.2), \qquad \mathrm{UVB} = 4.6\,\mu\,\mathrm{clip}(T_{\mathrm{UVB}},0,1.2) $$

$\mu = \cos(\mathrm{SZA})$, $O_3$ in DU, $\tau$ = AOD340, $\alpha$ = albedo.
Honest error bars (~11 / 0.37 on the POWER test split) disclosed in the docstring;
a residual-transmission ML on top was attempted and **rejected** (UVA test-MAE
0.59 vs raw-ML 0.35). Missing physics inputs fall back per-row to
$\mathrm{UVA} = 0.055\times\mathrm{GHI}$ (cap 70), $\mathrm{UVB} = 0.10\times
\mathrm{UVI}$ (cap 3), labeled `uncalibrated_fallback`. Night (`is_day=0`) clamps
all of UVA/UVB/$E_{\mathrm{mel}}$ to exactly 0 — the ML otherwise leaks small
positive values through the night.

### 2.3 Separate channels (never merged into TanScore)

- **Erythemal / SED channel:** $E_{\mathrm{ery}} = \mathrm{UVI_{consensus}}/40$
  (UVI 1 ≡ 25 $\mathrm{mW\,m^{-2}}$ erythemal), SED $= \int E_{\mathrm{ery}}\,dt / 100$.
  Independent, never increases scores.
- **Pigment-darkening (IPD) channel:** same Tier-C machinery through the
  `ipd_action_spectrum` (UVA-dominant, existing-pigment oxidation/redistribution
  endpoint) — diagnostic context, including "Visible-Darkening Potential" (day-max
  30-min IPD dose, ~3× TanDose in practice).
- **Physical UVA/UVB doses:** broadband energy, diagnostic only.
- **MMD** (minimal melanogenesis dose): a *measured* subject/source/endpoint
  threshold, never modeled here (§9).
- **TanResponse** (`tan_response.py`, `none-v1`, interface-only): the future
  delayed-pigmentation response model. Production returns cumulative TanDose with
  `predicted_response = None`; any fitted candidate must beat it on held-out study
  aggregates (Miller 2008, Ravnbak ×3, Keong, Wolber, MITF-timer prior) before
  shipping. Repeated exposure NEVER modifies physical TanDose.

---

## 3. UVA/UVB estimator — the calibrated mapping

Two `HistGradientBoostingRegressor`s (one per band; `learning_rate=0.045`,
`max_iter=350`, `max_leaf_nodes=31`, `min_samples_leaf=30`, `l2=0.15`, seed 23),
trained on daylight rows ($\mathrm{GHI} > 10$, SZA < 90°), split by year
($\mathrm{year_{max}}-2$; 80/20 fallback), on the 15 `MODEL_FEATURES`. The live
frame maps Open-Meteo fields onto the identical schema (`tanscore.build_live_feature_frame`),
crucially preferring **preceding-hour-mean** radiation over `_instant` fields
(POWER trained on hourly means), with `(°F−32)×5/9`, `surface_pressure/10` (kPa),
and conservative albedo 0.20 when CAMS albedo is absent. Solar position +
Ineichen clear-sky come from one shared `solar_features()` (pvlib, altitude 220 m)
used by **both** training and serving — a 58/120 $\mathrm{W\,m^{-2}}$
median/p90 train/serve clear-sky seam was found and killed (cost: UVA MAE
0.324→0.327, negligible against live consistency).

**Skill (as recorded, not as marketing):** mapping on POWER inputs UVA MAE ~0.30
daylight (held-out R² 0.9989 / UVB 0.9894; trees earn most on UVB, 4× over
linear); NWP-fed (38k archived-forecast hours) UVA MAE ~5.8, bias +2.1 — inputs
run ~20% brighter, the converter is faithful. Independent BSRN Payerne: +42%
bias root-caused to **instrument scale** (CERES clear-sky UVA/GHI 5.02% vs station
3.5%), no model change. Per-row calibration tier stamps CAMS presence honestly:
`nasa_power_ml_plus_cams_spectral` vs `nasa_power_ml`. Bundle manifest binds
pickle ↔ training-code SHA ↔ sklearn version (drift warns; model-version drift
errors); predictions reindex to the bundle's feature list and clip at 0.

---

## 4. UVI fusion, disagreement, and confidence

### 4.1 Calibrated UVI fusion (`fusion_version = calibrated-uvi-fusion-v2`)

`uvi_consensus` is finalized only after the contributing source values and
sub-hour corrections are final; source counts identify unique providers, not
weighted votes. `erythemal_irradiance_wm2 = uvi_consensus / 40` is then derived
from that final consensus. SED integrates this final-consensus erythemal field,
never a raw provider value or a pre-fusion intermediate.

### 4.2 Confidence (`confidence_version = calibrated-error-v1`)

`tan_forecast_confidence_0_100` is calibrated reliability/error context, never
sun strength and never a multiplier on photons. Source disagreement, coverage,
and forecast error affect confidence; they do not alter delayed-pigmentation
irradiance, SED, or dose. `strong_sun_probability_0_100` remains a separate
useful-sun probability.

---

## 5. Local and Atmosphere — percentiles, not physics

`add_local_scores` percentiles each row's Absolute against the v4-rebuilt local
reference (SB 108,744 rows, Palisades 111,696; legacy kept as diagnostic column
for one migration version; pooled p99.9 = 1.522 recorded in `reference.json`):

$$ \mathrm{percentile}(v) = 100\,\overline{(\mathrm{ref} \le v)} $$

- **Local:** reference rows within ±21 d circular day-of-year
  (`LOCAL_DOY_WINDOW_DAYS`); <250 rows → whole reference.
- **Atmosphere:** additionally within ±7.5° solar elevation
  (`LOCAL_SOLAR_ELEVATION_WINDOW_DEG`; ±15° fallback); <100 rows → fallback.
  Same-sun comparison: is the air (clouds/aerosols/ozone) unusually clear for
  this sun position?

**Version gate (loud):** `local_reference_version.json` must match
`tan_score_model_version` **and** reference version/value, else percentiles are
NaN, `local_reference_stale=true`, and validation WARNs — legacy-55/30/15
percentiles must never mix into v4 Overall. Absolute grades:
80 extreme · 65 very strong · 50 strong · 35 moderate · 20 low-moderate · else
low. Local grades: 98 exceptional · 90 excellent · 75 good · 50 typical-to-good ·
25 below typical · else poor.

---

## 6. Outdoor feasibility and legacy Overall

`overall_tan_opportunity_0_100` is retained only as a **LEGACY composite
(deprecated product heuristic)**. It can summarize weather usability beside
physical scores, but it is not the fixed-duration recommendation objective.

### 6.1 Legacy merge

The available-component weighted geometric mean uses
`OVERALL_SCORE_WEIGHTS = {absolute: 0.70, local: 0.15, atmosphere: 0.05,
confidence: 0.10}` and is capped at `Absolute+20`:

$$G = \exp\!\sum_{k} \hat{w}_k \ln\!\max(v_k, 0.25), \qquad G \leftarrow \min(G,\, \mathrm{Absolute} + 20)$$

$$ \mathrm{Overall_{unblocked}} = \mathrm{clip}(G,0,100), \qquad \mathrm{Overall} = \mathrm{clip}(\mathrm{Overall_{unblocked}} \times m_{\mathrm{wx}}, 0, 100) $$

Missing components renormalize with explicit coverage; this legacy composite
does not make Local part of the dose objective.

### 6.2 Hard blocks vs soft penalties

Hard blocks are practical rules, not melanocyte claims: active rain
(> 0.001″ rain/showers or WMO 51–67/80–82), active snow (> 0.001″ or
71–78/85–86), thunder (95/96/97/99), heat ≥ 110°F, cold < 50°F, and declared
missing hard-block inputs. Soft usability penalties cover cold comfort,
100–110°F heat, precipitation probability, wind, and hot/humid conditions.
Snow may raise reflected radiation while snow cover blocks lying outside; the
two layers stay separate.

### 6.3 Demoted sun-warming heuristic

`sun_adjusted_feels_like_f` is retained as the deprecated alias of
`sun_warming_heuristic_f`, with
`comfort_model_version=sun-warming-heuristic-v1 (demoted: not a validated feels-like)`.
It frames a resting/reclining user with resting metabolic rate and does not use
an absent-metabolism assumption. UVI is not thermal loading: this is a comfort
heuristic, not a validated thermal model, and it never affects ranking: the
fixed-duration dose objective does.
Comfort bands use the heuristic; hard blocks use the air-temperature
thermometer.

The retained arithmetic is
$$F = T_{\mathrm{air}} + 18\,\mathrm{clip}\!\left(\tfrac{\mathrm{UVI}}{10},0,1.2\right)T + 0.6\,\mathrm{clip}(T_{\mathrm{dew}}-65,0,15) - 8\,\mathrm{clip}\!\left(\tfrac{W}{25},0,1.5\right),$$
where $T=\mathrm{clip}(\mathrm{UVI}/\mathrm{UVI_{clear}},0,1)$ and $W$ is mph.
A 75°F dew point contributes +6°F: $(75-65)\times0.6$. A 20 mph wind subtracts
6.4°F: $8\times20/25$.

---

## 7. Doses — TanDose, SED, and the unknown-vs-zero contract

All doses follow `interval-contract-v1`: an interval-mean radiation value is
integrated over its declared `interval_start_utc`/`interval_end_utc` support;
point samples use trapezoidal integration over actual timestamps, never a
nominal interval. Gaps over `TANDOSE_MAX_INTERP_GAP_S` (default **3600 s**)
split coverage. Missing input is UNKNOWN, never zero: no valid or lone sample
over a nonzero window is `NaN`/incomplete; only measured night zeros integrate
as complete zeros. Every dose level carries `(complete, coverage_fraction)`.

| Dose | Integral | Unit | Levels |
|------|----------|------|--------|
| **TanDose** (delayed-melanogenesis exposure) | $\int E_{\mathrm{mel}}\,dt$ | $\mathrm{J\,m^{-2}}$ | trailing 15 m / 30 m / 1 h (`tan_dose_{15m,30m,1h}_j_m2`) + ref-minutes, day total, best-window, best-hour |
| **SED** (sunburn load, independent) | $\int E_{\mathrm{ery}}\,dt / 100$ | SED | same levels (`sed_{…}`), own complete/coverage pair |
| UVA / UVB physical | $\int \mathrm{UVA{,}UVB}\,dt$ | $\mathrm{J\,m^{-2}}$ (+ $\mathrm{J\,cm^{-2}}$ = /10⁴) | same levels + day |
| IPD pigment-darkening | $\int E_{\mathrm{pig}}\,dt$ | $\mathrm{J\,m^{-2}}$ | same levels |
| **Reference minutes** (presentation only) | $\mathrm{TanDose} / 1.6 / 60$ | min | "equivalent minutes at fixed global reference" |

Windows are `[start, end]` **inclusive** (the end stamp bounds the final
trapezoid leg — half-open ends silently dropped the last 30 min of every window
dose until review caught it). Trailing columns END at their stamp: the dose for
$[t, t{+}30m)$ lives on the row at $t{+}30m$. Day totals group by **local** date
(UTC-grouping once leaked dawn hours out of non-UTC day totals).

---

## 8. Sub-hour engine — native HRRR forecast + clear-sky-index interpolation

`build_30min_forecast` resamples hourly → 30-min on the union grid with
time-interpolation **inside** each column's observed span only (past-horizon
stamps revert to NaN); booleans/codes forward-fill; run-constant metadata
(tiers, versions, `cams_cycle`) carries; time-varying CAMS never does. Solar
geometry is recomputed per :30 stamp. Native HRRR values are native HRRR
**forecast** inputs, not observation truth.

- **Clear-sky-index GHI** (measured quantity only): $kt = \mathrm{GHI}/\mathrm{TOA}$
  ($\mathrm{TOA} = 1361.1\cos\mathrm{SZA}$, exact astronomy) interpolated, then
  $\mathrm{GHI}_{:30} = kt_{:30}\times\mathrm{TOA}_{:30}$, night-zeroed. Grounded
  in 720 native HRRR rows: daylight MAE 53.8→**51.5**, median 16.0→**12.1**,
  low-sun 23.3→20.6; cloud-edge passages (~p90 140) are irreducible to any
  interpolator. Propagated to UV by bounded ratio $r \in [0.7, 1.3]$: UVA × $r$,
  UVB/UVI × $\sqrt{r}$ (sublinear broadband response, **not** a scoring weight —
  the removed 55/30/15 interaction stays removed).
- **Native-HRRR override** (`:00/:30` stamps): same pattern against the
  kt-improved baseline, bounds $[0.45, 1.55]$, single compounding (a stacked
  0.7×0.45 → 0.31 double-correction was found in production data and fixed).
- After either correction, final derived channels recompute in place (an
  interpolated spectral value is never presented as native; `subhour_source`
  is retained), then final UVI fusion, percentiles, feasibility, and trailing
  doses are recomputed from those final parents. Pre-sunrise ghost-light and
  clear-sky-index plumbing remain independently checked.

---

## 9. Skin — context, personalization, posture, plane

**Fitzpatrick I–VI is display + risk context, never a multiplier.**
`attach_fitzpatrick` writes labels (I "usually burns, little tanning" … VI
"lowest erythema susceptibility") plus qualitative `personal_uv_risk_context`;
the response note states published MED/MMD ranges overlap substantially within
types (Westerhof 2355184; Wulf 21091784; Ravnbak 20584251; Diffey 20648713), so
objective color or measured MED/MMD is more precise. No numeric skin
coefficient exists anywhere in scoring.

**My-MMD (personal fractions).** `personal_mmd_fraction = TanDose /
personal_mmd_equivalent_dose`, unclamped (>1 = over-threshold, by design), in
melanogenic-effective $\mathrm{J\,m^{-2}}$, computed per-request only —
persisted run tables are stripped of personal columns for privacy, and shared
calendars stay environmental-only. An MMD **without an explicit basis is
rejected** (400/ValueError): bases `MEASURED > OBJECTIVE_ESTIMATE >
COARSE_ESTIMATE` (Fitzpatrick-only estimates disabled by default, wide
uncertainty). CLI (`--personal-mmd/--personal-mmd-basis`), API
(`personal_mmd`/`personal_mmd_basis`), dashboard My-MMD inputs, and static
export all thread the same parser. The UI dose row shows the day-max fraction
with null-safe max filtering (a null-coercion bug once rendered absent as
0.00). `personalization_context()` additionally accepts ITA (constitutive/
facultative), melanin index, L*, pigment-protection factor, measured MED (SED)
— objective inputs outrank Fitzpatrick by construction.

**Sun posture** is context, never a default ranking input: the UI can render
solar geometry and a selected plane, but it must not confuse guidance with an
actual selected pose.

**Surface profiles and the skin plane.** Local `surface` presets describe the
material immediately around the user. Each context row identifies the selected
profile with `surface_material_slug` and `surface_reflectance_source`. Regional
CAMS `forecast_albedo` remains an atmospheric/RT input and is never substituted
for local reflection.

`surface_extent_mode = local|broad` defaults to `local`. In local mode,
changing surface leaves horizontal environmental radiation, dose, and ranking
bit-identical; it changes only local reflected/skin-plane context. `broad`
declares broad homogeneity and may enter the Tier-B backend RT boundary
condition. Without backend RT it is backend-only: static export explains that
it cannot rerun broad-mode RT.

The defaults are `SUNSTACK_SKIN_TILT_DEG=0` and
`SUNSTACK_SKIN_AZIMUTH_DEG=180`; an explicit azimuth of 360 normalizes to 0, and
omitted values fall back to these defaults. A flat horizontal plane has
ground-view factor 0, so local ground reflection is exactly zero. At fixed
nonzero tilt, Lambertian reflected components rise monotonically with profile
reflectance;
`open_water` instead uses geometry-dependent Fresnel reflection, not a flat
Lambertian scalar. `unknown` asserts no local correction; it never silently
becomes 0.20. The dry-sand proxy is 0.1650 and summer-grass proxy is 0.0285,
but their modeled effect remains material/state/wavelength/geometry dependent.

`/api/data`, `/api/refresh`, and `/api/calendar.ics` accept `surface`,
`surface_extent`, `skin_tilt_deg`, and `skin_azimuth_deg`; invalid values return
400. CLI equivalents are `--surface`, `--surface-extent`, `--skin-tilt-deg`,
and `--skin-azimuth-deg`. Persisted runs and static exports retain
`exposure_basis=environmental_horizontal`; `skin_plane_*` columns are context.

---

## 10. Windows, calendar, export, and provenance

- `strongest_30m_*` is the maximum expected 30-minute
  delayed-pigmentation dose regardless of comfort. `best_usable_30m_*` is the
  maximum such dose among hard-usable windows. The primary selector is
  `fixed-duration-dose-v2`: Local never enters its objective, and confidence
  breaks only defined dose ties before deterministic ordering.
- `best_window_*` remains the legacy contiguous Overall stretch. It is kept for
  continuity, not used as the dose objective. The hero presents strongest
  physical versus best-usable windows separately.
- Calendar DTSTART/DTEND and SUMMARY derive from the physical window
  (`best_usable_30m_*` → `strongest_30m_*` → legacy `best_window_*`), with
  UID/SEQUENCE stability unchanged; when best-usable and strongest differ, the
  description names both and which is blocked. It does not imply a safety
  recommendation.
- Static export and `/api/data` served rows use one astronomical daylight mask:
  `is_day` when it supplies a signal, otherwise positive `solar_elevation_deg`;
  fixtures without either signal retain all rows, and source parquet/CSV tables
  keep every row. Fit is the share of half-hours on exactly that daylight mask
  which are not hard-blocked.
- Reskin is renderer-only: `forecast_code_sha` remains the forecast identity
  while `renderer_code_sha` records the renderer revision. Static export writes
  `surfaces.json` from `surface.PRESETS` and labels the client-side
  reflected-context line (`GHI × proxy × (1 − cos tilt)/2`) as `(client-side)`;
  the page fetches `data.json` run-stamped.

---

## 11. Verification — receipts, not claims

- **UVI scoreboard** (`docs/validation/uvi_verification.md`, 107 snapshots,
  1-day lead): OM 0.49/−0.11/0.78, CAMS 1.22/−1.12/1.42, consensus 0.66/−0.58
  (MAE/bias/RMSE) — the OM×2 fusion vote, quantified. Rolling verifier:
  `scripts/verify_uvi.py`.
- **Estimator:** POWER holdout UVA R² 0.9989 / UVB 0.9894, stratified by
  SZA/cloud/season/AOD/ozone (`docs/validation/external_validation.md`);
  NWP-fed MAE ~5.8 explained by +20% input brightness (BSRN corroboration
  +29%/+48 $\mathrm{W\,m^{-2}}$); Payerne +42% attributed to biometer-vs-integral
  scale (CERES 5.02% vs station 3.5%), model unchanged.
- **Literature gates** (`scripts/check_literature.py` → 6/6 PASS): Parrish
  UVB/UVA effectiveness 1247×, Keong photoaddition exact, erythema/melanogenesis
  spectral crossing 1.44× @300 nm vs 3.11× @340 nm, IPD UVA-dominant/UVB-silent,
  SED/TanDose divergence 5.40 vs 2706. Two provisional-shape bugs caught and
  fixed by these gates (IPD shortwave cutoff, 320 nm ordering).
- **Migration signature** (`compare_legacy_v4.py`, byte-reproducible):
  most-UVB-rich +9.8/+3.1, most-UVA-rich −0.7/−2.9 — v4 reorders exactly as the
  physics predicts; cloudy-day run monotonic +2.77→−1.07 across ratio quintiles
  while the crude cloud-cover split stays honestly INCONCLUSIVE.
- **Live proofs:** offline v4 re-score (336→671→14, zero photobiology errors,
  TanDose 15.6–22.5 kJ mel/day); SB peak Absolute 47.8/Local 91.8 — excellent
  locally without touching global 100; Palisades 66.1/91.5; wheel installs and
  scores from the artifact; references rebuild byte-identically; suite green
  (only pre-existing canonical-env failure excepted).

## 12. Literature backbone

Parrish–Jaenicke–Anderson 1982 (PMID 7122713, action spectrum) · Keong et al.
1990 (PMID 2103131, photoaddition — the reason there is no interaction term) ·
Wolber et al. 2008 (PMID 18627527, downstream synergy kept out of physics) ·
Ravnbak & Wulf 2007 (PMID 17256147) · Miller et al. 2008 (PMID 18616777) ·
Ravnbak 2009 (PMID 19688146) · Ravnbak 2010 (PMID 20584251, MMD/MED ratio vs
pigmentation) · Wulf et al. (PMID 21091784, objective color beats Fitzpatrick) ·
Westerhof et al. (PMID 2355184) · Diffey et al. (PMID 20648713) · Mahmoud et al.
(PMID 23111621, UVA/UVB review) · MITF timer (PMID 30401431, mechanistic prior
only). Aggregates encoded in `data/research/exposure_studies.json` — no
fabricated subject data, ever.

## 13. Known limits (open, not hidden)

Tier-C uniform-band shape error (real, currently secondary) · provisional
Parrish anchors incl. assumed 280–289 nm unity · CAMS-vs-OM ~4–5 h phase offset
under investigation (closure bias at high sun; disagreement penalty is the
architectural response) · POWER truth itself modeled (attributions
corroborating, not definitive) · clear-sky seam closed by shared code path ·
no libRadtran corpus/emulator here (scaffold + contract only) · TanResponse
unfitted by gate · EPA integer rounding at low sun · pre-v4 payloads render
with legacy provenance + em-dash doses.

## Appendix A — pipeline map

`bootstrap` (fetch history → train UVA/UVB → rebuild local reference, per site
under `data/sites/<slug>`) → `run_live` (fetch_all → normalize → consensus /
ensemble probs / AQ merge / EPA / CAMS → `score_forecast` → feasibility →
Fitzpatrick/personalization → hourly doses → gate 1 → `build_30min_forecast`
(HRRR/kt) → `build_daily_summary` → gate 2 → persist + `summary.json`) →
`export` (static site + calendars + CSVs) / `serve` (FastAPI per-request
personalization) / `reskin` (renderer-only refresh) / `doctor` (pre-flight
gates incl. spectra + reference + CAMS credentials).

## Appendix B — environment knobs (defaults)

`SUNSTACK_GLOBAL_MEL_REF_WM2=1.6` · `SUNSTACK_TANDOSE_MAX_GAP_S=3600` ·
`SUNSTACK_UVI_DISAGREE_FRAC=0.35` / `STRONG=0.60` · `MIN_TAN_TEMP_F=50` ·
`COMFORTABLE=68` · `HEAT_WARNING=100` · `MAX=110` · precip/snow 0.001″ ·
`PRECIP_PROBABILITY_PENALTY_MAX=0.55` · wind 25/35 mph · `SKIN_TILT=0`/`AZIMUTH=180` ·
`STRICT=1`, `REQUIRE_DIRECT_CAMS=1`, `REQUIRE_CANONICAL_SPECTRUM`, `TIERB_MANIFEST`
(unset = no A/B claims) · sites: south-bend default (41.703293, −86.238292,
America/Indiana/Indianapolis) + pacific-palisades via `locations.yaml`.
