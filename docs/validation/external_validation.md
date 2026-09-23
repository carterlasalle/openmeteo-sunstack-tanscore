# External validation (NASA POWER / CAMS / Open-Meteo)

## NASA POWER held-out (year-split) UVA/UVB estimator skill

Rows: 111761; split year: 2024.

```json
{
  "rows": 111761,
  "validation_split_year": 2024,
  "uva": {
    "mae": 0.42540930440997204,
    "rmse": 0.6704849781593735,
    "r2": 0.9984897972027242,
    "median_absolute_error": 0.2542877526601899
  },
  "uvb": {
    "mae": 0.030920149270148294,
    "rmse": 0.05370308516066549,
    "r2": 0.9900210082487843,
    "median_absolute_error": 0.014291591724237107
  }
}
```

### Holdout UVA error by SZA / cloud / season / AOD / ozone

(post-2024 holdout, n=12240; AOD340 median 0.208; ozone median 303 DU)

| stratum | n | MAE | RMSE | bias |
|---|---|---|---|---|
| SZA=0-30 | 714 | 0.9446 | 1.2867 | 0.7712 |
| SZA=30-50 | 1432 | 0.5823 | 0.7796 | 0.3299 |
| SZA=50-65 | 1683 | 0.4166 | 0.5685 | 0.2191 |
| SZA=65-80 | 1391 | 0.2312 | 0.3108 | 0.0927 |
| SZA=80-95 | 7020 | 0.531 | 0.5634 | 0.5217 |
| cloud=clear 0-20 | 7007 | 0.5246 | 0.6654 | 0.4549 |
| cloud=partly 20-60 | 2612 | 0.4859 | 0.5944 | 0.385 |
| cloud=cloudy 60-100 | 2621 | 0.5011 | 0.5971 | 0.3777 |
| season=DJF | 3576 | 0.4461 | 0.5079 | 0.3421 |
| season=MAM | 4272 | 0.5616 | 0.7486 | 0.4803 |
| season=JJA | 2208 | 0.553 | 0.6704 | 0.4838 |
| season=SON | 2184 | 0.4776 | 0.5458 | 0.3843 |
| AOD340=low | 4380 | 0.4655 | 0.541 | 0.3863 |
| AOD340=high | 4379 | 0.5077 | 0.6075 | 0.4093 |
| ozone=low | 4382 | 0.4875 | 0.5673 | 0.4147 |
| ozone=high | 4377 | 0.4857 | 0.583 | 0.3809 |

### Holdout UVB error by SZA / cloud / season / AOD / ozone

(post-2024 holdout, n=12240; AOD340 median 0.208; ozone median 303 DU)

| stratum | n | MAE | RMSE | bias |
|---|---|---|---|---|
| SZA=0-30 | 714 | 0.0728 | 0.1019 | 0.0461 |
| SZA=30-50 | 1432 | 0.0495 | 0.069 | 0.0269 |
| SZA=50-65 | 1683 | 0.0295 | 0.0426 | 0.0139 |
| SZA=65-80 | 1391 | 0.0098 | 0.0142 | 0.0026 |
| SZA=80-95 | 7020 | 0.0017 | 0.0024 | 0.0014 |
| cloud=clear 0-20 | 7007 | 0.0172 | 0.0418 | 0.01 |
| cloud=partly 20-60 | 2612 | 0.0156 | 0.0341 | 0.0078 |
| cloud=cloudy 60-100 | 2621 | 0.014 | 0.0297 | 0.0068 |
| season=DJF | 3576 | 0.0096 | 0.0212 | 0.0025 |
| season=MAM | 4272 | 0.0259 | 0.0559 | 0.0179 |
| season=JJA | 2208 | 0.0151 | 0.0305 | 0.0077 |
| season=SON | 2184 | 0.0089 | 0.0162 | 0.0027 |
| AOD340=low | 4380 | 0.0104 | 0.0216 | 0.0041 |
| AOD340=high | 4379 | 0.012 | 0.0245 | 0.0032 |
| ozone=low | 4382 | 0.0094 | 0.0187 | 0.0046 |
| ozone=high | 4377 | 0.013 | 0.0267 | 0.0027 |

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

