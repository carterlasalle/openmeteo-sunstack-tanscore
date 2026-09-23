# External validation (NASA POWER / CAMS / Open-Meteo)

## NASA POWER held-out (year-split) UVA/UVB estimator skill

Rows: 108956; split year: 2024.

```json
{
  "rows": 108956,
  "validation_split_year": 2024,
  "uva": {
    "mae": 0.32672572126342153,
    "rmse": 0.483055263348548,
    "r2": 0.9988747231151854,
    "median_absolute_error": 0.21654770289529424
  },
  "uvb": {
    "mae": 0.02374961585268027,
    "rmse": 0.04105674446319054,
    "r2": 0.9894220785132187,
    "median_absolute_error": 0.010954301020847185
  }
}
```

### Holdout UVA error by SZA / cloud / season / AOD / ozone

(post-2024 holdout, n=12024; AOD340 median 0.182; ozone median 321 DU)

| stratum | n | MAE | RMSE | bias |
|---|---|---|---|---|
| SZA=0-30 | 440 | 0.6809 | 0.9027 | 0.3626 |
| SZA=30-50 | 1290 | 0.4733 | 0.6256 | 0.2526 |
| SZA=50-65 | 1576 | 0.3417 | 0.4562 | 0.1465 |
| SZA=65-80 | 1706 | 0.2288 | 0.3082 | 0.0638 |
| SZA=80-95 | 7012 | 0.512 | 0.5427 | 0.5038 |
| cloud=clear 0-20 | 2909 | 0.4553 | 0.53 | 0.3839 |
| cloud=partly 20-60 | 2242 | 0.4368 | 0.5154 | 0.3295 |
| cloud=cloudy 60-100 | 6873 | 0.4547 | 0.5402 | 0.3641 |
| season=DJF | 3576 | 0.4469 | 0.502 | 0.3652 |
| season=MAM | 4056 | 0.4556 | 0.5558 | 0.3699 |
| season=JJA | 2208 | 0.4587 | 0.5626 | 0.3421 |
| season=SON | 2184 | 0.4443 | 0.5089 | 0.3644 |
| AOD340=low | 4382 | 0.4374 | 0.4968 | 0.3587 |
| AOD340=high | 4377 | 0.4425 | 0.5319 | 0.3405 |
| ozone=low | 4380 | 0.4543 | 0.532 | 0.3609 |
| ozone=high | 4379 | 0.4256 | 0.4965 | 0.3382 |

### Holdout UVB error by SZA / cloud / season / AOD / ozone

(post-2024 holdout, n=12024; AOD340 median 0.182; ozone median 321 DU)

| stratum | n | MAE | RMSE | bias |
|---|---|---|---|---|
| SZA=0-30 | 440 | 0.0511 | 0.0695 | 0.0213 |
| SZA=30-50 | 1290 | 0.042 | 0.0618 | 0.0119 |
| SZA=50-65 | 1576 | 0.0272 | 0.0392 | 0.0125 |
| SZA=65-80 | 1706 | 0.0099 | 0.0148 | 0.0031 |
| SZA=80-95 | 7012 | 0.0015 | 0.0022 | 0.0012 |
| cloud=clear 0-20 | 2909 | 0.0143 | 0.0347 | 0.0062 |
| cloud=partly 20-60 | 2242 | 0.0135 | 0.0321 | 0.0038 |
| cloud=cloudy 60-100 | 6873 | 0.0109 | 0.0243 | 0.0046 |
| season=DJF | 3576 | 0.0077 | 0.0179 | 0.0039 |
| season=MAM | 4056 | 0.0186 | 0.0415 | 0.0088 |
| season=JJA | 2208 | 0.0119 | 0.0234 | 0.0022 |
| season=SON | 2184 | 0.008 | 0.0158 | 0.0015 |
| AOD340=low | 4382 | 0.0087 | 0.0186 | 0.0022 |
| AOD340=high | 4377 | 0.0103 | 0.0217 | 0.0023 |
| ozone=low | 4380 | 0.0091 | 0.0178 | 0.003 |
| ozone=high | 4379 | 0.0099 | 0.0225 | 0.0015 |

<!-- refreshed 2026-09-23: POWER holdout section regenerated against the retrained bundle (rows 108956); CAMS-closure and POWER-bias sections below are retained evidence from a CAMS-bearing run, not reproducible without ADS credentials -->
## CAMS UVBED vs Open-Meteo UVI (erythemal closure)

CAMS UVBED field: `cams_uv_biologically_effective_dose` (dose rate, W/m^2 erythemal); CAMS UVI = 40 * UVBED; Open-Meteo `uv_index`; n_overlap_daylight=51.

```json
{
  "n": 51,
  "mae": 3.25,
  "rmse": 3.7182,
  "bias": -2.7463,
  "r2": -2.5565
}
```

### Closure error by SZA / cloud / season / AOD / ozone

(AOD340 median split at 0.200; ozone median split at 285 DU; CAMS UVI predicted, Open-Meteo UVI as comparator — NOT truth: see the forecast-UVI bias section below)

| stratum | n | MAE | RMSE | bias |
|---|---|---|---|---|
| SZA=0-30 | 0 | — | — | — |
| SZA=30-50 | 25 | 4.409 | 4.6997 | -4.3928 |
| SZA=50-65 | 15 | 2.423 | 2.7344 | -0.8081 |
| SZA=65-80 | 0 | — | — | — |
| SZA=80-95 | 0 | — | — | — |
| cloud=clear 0-20 | 19 | 3.506 | 4.1337 | -3.0352 |
| cloud=partly 20-60 | 16 | 3.4324 | 3.7444 | -3.2063 |
| cloud=cloudy 60-100 | 16 | 2.7635 | 3.1232 | -1.9433 |
| season=DJF | 0 | — | — | — |
| season=MAM | 0 | — | — | — |
| season=JJA | 0 | — | — | — |
| season=SON | 51 | 3.25 | 3.7182 | -2.7463 |
| AOD340=low | 26 | 2.999 | 3.4506 | -2.4219 |
| AOD340=high | 25 | 3.511 | 3.9774 | -3.0837 |
| ozone=low | 26 | 2.8849 | 3.3778 | -2.2624 |
| ozone=high | 25 | 3.6296 | 4.0419 | -3.2496 |

No training touched CAMS UVBED targets, so this comparison is independent.
NOTE: the bias concentrates at high sun (SZA 30-50) with near-zero CAMS values while Open-Meteo peaks — consistent with a ~4-5 h diurnal phase offset in the decoded CAMS valid times (under investigation in history._dataset_time_column), not with a radiometric scale error. This attribution is unconfirmed until a measured phase analysis supports it; meanwhile the UVI-disagreement confidence penalty is the correct architectural response.

## Forecast UVI bias vs POWER truth by SZA

Archived Open-Meteo UVI minus NASA POWER UVI, relative, on overlapping hours (POWER truth is itself modeled, so corroborating rather than definitive):

| stratum | n | mean relative bias |
|---|---|---|
| SZA 0-30 | 2356 | -0.125 |
| SZA 30-50 | 4509 | +0.059 |
| SZA 50-65 | 5244 | +0.511 |
| SZA 65-80 | 2723 | +1.745 |

Reading: the comparator in the closure section runs hot at low sun, which depresses live E_mel/E_ery with SZA independent of any Tier-C shape error.

## Open-Meteo UVI self-consistency

Modeled UVI in the hourly table IS Open-Meteo UVI (plus bounded HRRR/kt geometry corrections); an independent Open-Meteo check is therefore the CAMS-closure comparison above, not a self-comparison. Year-holdout discipline applies to the UVA/UVB estimators (see model_metrics.json).

