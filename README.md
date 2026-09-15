# SunStack TanScore 3.0

A strict, source-transparent solar/UV forecasting and calibration system that answers two different questions without mixing them up:

1. **How strong is the actual melanogenic radiation on an absolute global scale?**
2. **How good is this outdoor tanning opportunity here, given local climatology, forecast confidence, rain/snow, and temperature?**

It fetches live Open-Meteo forecasts, full ensemble data, native HRRR sub-hourly radiation, CAMS air-quality data, **direct Copernicus CAMS spectral/ozone forecasts**, NASA POWER historical UVA/UVB, archived Open-Meteo forecasts, and Previous Runs for lead-time skill calibration.

## Scores

Every hour and 30-minute period exposes the components separately:

- `tan_score_absolute_0_100` — globally anchored environmental melanogenic intensity. **Not** graded on a South Bend curve.
- `local_tan_score_0_100` — percentile versus historical daylight around this location and season.
- `atmospheric_quality_percentile_0_100` — local percentile after controlling for season and solar elevation.
- `tan_forecast_confidence_0_100` — how trustworthy the predicted window is from deterministic/ensemble evidence.
- `outdoor_feasibility_0_100` — practical outdoor usability only.
- `overall_tan_opportunity_0_100` — the easy-to-read overall number.

### Overall formula

The unblocked composite is a weighted geometric mean:

```text
60% Absolute TanScore
15% Local percentile
10% Atmospheric quality
15% Forecast confidence
```

It is capped at `Absolute + 20`, so local rarity can never turn weak physical UV into a fake elite score. Then it is multiplied by outdoor feasibility.

This means a result like:

```text
Absolute    44
Local       97
Atmosphere  94
Confidence  91
Overall     ~60 before weather usability
```

can mean **excellent for South Bend but only moderate on an absolute terrestrial scale**.

## Outdoor hard blocks and flags

Outdoor usability is deliberately separate from melanogenesis physics.

Default hard blocks:

- active rain/drizzle/showers -> Overall = 0
- active snow -> Overall = 0
- thunderstorm -> Overall = 0
- temperature `< 50°F` -> Overall = 0 (configurable)
- temperature `>= 110°F` -> Overall = 0

Soft penalties/warnings:

- 50–68°F cold/marginal comfort
- 100–110°F heat
- forecast precipitation probability
- high wind
- hot + very humid/sweaty conditions

These rules **do not alter Absolute TanScore**. A rainy hour can therefore correctly show strong UV physics but `Overall = 0` because it is not a practical outdoor tanning window.

Configure thresholds in `.env.example` / environment variables.

## Fitzpatrick skin type

The dashboard and CLI accept optional Fitzpatrick I–VI:

```bash
uv run sunstack run --skin-type 2
```

or select it in the UI.

Fitzpatrick type is used for **qualitative personal-response/risk context only**. It does not multiply environmental TanScore. Human studies show substantial overlap in experimentally measured minimal erythema dose (MED) and minimal melanogenesis dose (MMD) inside Fitzpatrick groups, so assigning a fake exact `Type II = 0.63x` coefficient would reduce accuracy. Objective skin color or an experimentally measured MED/MMD would be a better personalization variable if ever available.

## Data sources

### Live Open-Meteo

Every normal `run` bypasses the live HTTP cache by default and makes real requests to:

- Best Match
- HRRR
- NBM
- NAM
- GFS / AI-GFS
- ECMWF IFS / AIFS
- ICON
- GEM + HRDPS
- UKMO
- ACCESS
- CMA GRAPES
- full-member GEFS/AIGEFS/ECMWF ensembles
- ensemble mean/spread systems
- native HRRR 15-minute data
- Open-Meteo CAMS air quality / AOD550
- deep pressure profiles

Use `--cached-live` only if you intentionally want live-response caching.

### Direct CAMS / Copernicus ADS

Strict mode requires direct CAMS spectral atmospheric data, including the UV-region aerosol/ozone inputs used by the high-quality tier:

- AOD 340 / 355 / 380 / 400 nm
- absorption AOD at those wavelengths
- single-scattering albedo
- asymmetry factor
- total-column ozone
- total-column water vapour
- cloud liquid/ice water columns
- forecast albedo
- CAMS UV diagnostics
- solar-radiation context

Group requests are attempted first. If ADS rejects a group, SunStack retries each variable independently and writes the exact failure to `raw/cams_forecast/manifest.json`.

### Historical calibration

`setup` / `bootstrap` obtains:

- **NASA POWER hourly UVA + UVB** from 2001 onward
- Open-Meteo Historical Forecast archive
- Open-Meteo Previous Runs for forecast lead-time skill
- CAMS EAC4 historical aerosol/ozone data when ADS credentials are present

Historical data is cached because repeatedly redownloading immutable decades of calibration data is wasteful. Use `--force` when you deliberately want to refetch it.

## First-time setup

### 1. Install

```bash
unzip openmeteo-sunstack-tanscore-v3.zip
cd openmeteo-sunstack-tanscore
uv sync
```

### 2. Configure Copernicus ADS

Create a free Copernicus Atmosphere Data Store account, accept the terms for the CAMS datasets, and configure the standard `cdsapi` credentials (`~/.cdsapirc`).

Then verify everything:

```bash
uv run sunstack doctor --probe
```

`--probe` makes **real live Open-Meteo requests** and prints each feed's latency and exact failure if one occurs.

### 3. One-command full setup

```bash
uv run sunstack setup
```

This:

1. fetches NASA POWER historical UVA/UVB
2. fetches Open-Meteo historical forecasts
3. fetches Previous Runs
4. fetches CAMS EAC4
5. trains UVA/UVB estimators
6. creates the local historical reference distribution
7. computes model/lead-time skill
8. makes a fresh live Open-Meteo run
9. makes a fresh direct CAMS forecast request
10. produces hourly, 30-minute, and daily-best-time output

Strict is the default. If a critical source is missing, SunStack exits non-zero with a clear error rather than silently inventing values.

For deliberate troubleshooting only:

```bash
uv run sunstack run --allow-degraded
```

## Daily use

### Dashboard

```bash
uv run sunstack ui
```

It opens `http://127.0.0.1:8765` and shows:

- best days
- best multi-hour window each day
- best hour each day
- best 30-minute period
- hourly values
- 30-minute predictions
- Overall / Absolute / Local / Atmospheric / Confidence components
- rain/snow/temp blocks and warnings
- Fitzpatrick selector
- source/debug status
- **Refresh APIs** button that executes fresh live requests

### Terminal

```bash
uv run sunstack run
```

Optional:

```bash
uv run sunstack run --skin-type 3 --min-temp 55
```

## Outputs

Latest snapshot:

```text
data/latest/
├── summary.json
├── raw/
│   ├── manifest.json
│   └── cams_forecast/manifest.json
└── tables/
    ├── tan_daily_summary.csv/.parquet
    ├── tan_forecast_hourly.csv/.parquet
    ├── tan_forecast_30min.csv/.parquet
    ├── best_tan_windows.csv/.parquet
    ├── deterministic_hourly...
    ├── ensemble_members_long...
    ├── ensemble_probabilities...
    ├── hrrr_native_15min...
    └── cams_direct_forecast...
```

Calibration:

```text
data/calibration/
├── uva_uvb_models.joblib
├── model_metrics.json
├── local_reference.parquet
├── openmeteo_model_skill.parquet
└── training_calibration_hourly.parquet
```

Debug log:

```text
data/logs/sunstack.log
```

## 30-minute semantics

Near-term periods use native HRRR radiation/weather at true sub-hourly timestamps when available. UV itself is not native HRRR 15-minute data; SunStack interpolates hourly UV and applies a bounded HRRR broadband-radiation correction to the predicted UVA/UVB estimate.

Farther out, 30-minute rows are clearly labeled `interpolated_hourly`. They are for calendar/UI usability, not fake independent 30-minute atmospheric forecasts.

## Failing loudly

Strict mode validates:

- Best Match
- native HRRR 15-minute feed
- Open-Meteo CAMS air-quality feed
- minimum deterministic-model count
- minimum ensemble-system count
- calibrated UVA/UVB model
- local historical climatology
- direct CAMS data
- CAMS AOD340/AOD380 + ozone fields
- score completeness/ranges

Any critical failure exits with code 1 and prints both the exact failure and the path to `data/logs/sunstack.log`.

`uv run sunstack debug` prints the latest run summary and raw source manifest.

## Important interpretation

TanScore is an environmental/pigmentation-potential model, **not a safe exposure-time recommendation**. UV-induced tanning and erythema are both consequences of UV exposure; Fitzpatrick class does not make a given UV dose harmless. The UI deliberately keeps radiation intensity, local context, weather feasibility, and personal skin-response context separate rather than turning them into exposure-time advice.
