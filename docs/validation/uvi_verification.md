# UVI verification (retrospective reference, not truth)

Snapshots: 127 | 1-day-lead rows: 333

| source | n | MAE | bias | RMSE |
|---|---|---|---|---|
| om | 333 | 0.48 | -0.11 | 0.77 |
| cams | 159 | 1.14 | -1.03 | 1.37 |
| epa | 0 | -- | -- | -- |
| cons | 147 | 0.62 | -0.53 | 0.71 |

Reference: Open-Meteo previous-runs best_match (shared-DNA caveat).
Target: MAE < 1.0, |bias| < 0.3 per source at 1-day lead.
