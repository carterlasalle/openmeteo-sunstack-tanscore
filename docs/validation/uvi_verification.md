# UVI verification (retrospective reference, not truth)

Snapshots: 144 | 1-day-lead rows: 333

| source | n | MAE | bias | RMSE |
|---|---|---|---|---|
| om | 333 | 0.48 | -0.11 | 0.77 |
| cams | 159 | 1.14 | -1.03 | 1.37 |
| epa | 0 | -- | -- | -- |
| cons | 147 | 0.62 | -0.53 | 0.71 |

Common case: 147 rows (om/cams/cons/reference all present).

Common-case MAE (identical rows, ranking metric):
- om: n=147 MAE 0.13 bias +0.03
- cams: n=147 MAE 1.19 bias -1.09
- cons: n=147 MAE 0.62 bias -0.53

Reference: Open-Meteo previous-runs best_match (shared-DNA caveat).
Target: MAE < 1.0, |bias| < 0.3 per source at 1-day lead.
