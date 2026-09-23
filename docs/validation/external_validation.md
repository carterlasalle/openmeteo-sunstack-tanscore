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

Stratification (error by SZA/cloud/season/AOD/ozone) requires the multi-condition corpus and is tracked as follow-up; current report covers topline closure plus the held-out estimator metrics above. No training touched CAMS UVBED targets, so this comparison is independent.

## Open-Meteo UVI self-consistency

Modeled UVI in the hourly table IS Open-Meteo UVI (plus bounded HRRR/kt geometry corrections); an independent Open-Meteo check is therefore the CAMS-closure comparison above, not a self-comparison. Year-holdout discipline applies to the UVA/UVB estimators (see model_metrics.json).

