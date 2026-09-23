# Legacy 55/30/15 vs v4 action-spectrum comparison

Source: `data/calibration/training_calibration_hourly.parquet` (222408 rows; v4 recomputed Tier-C provisional).

Mean legacy: 8.5; mean v4: 9.6; mean delta (v4-legacy): +1.2.
Median delta: +0.0; p10 -0.6; p90 +5.3.
Rank correlation (Spearman): 0.999.

### UVA-rich vs UVB-rich divergence

| spectrum bin | n | mean legacy | mean v4 | mean delta |
|---|---|---|---|---|
| most UVB-rich | 20653 | 39.3 | 49.1 | +9.8 |
| UVB-leaning | 20652 | 25.2 | 29.0 | +3.8 |
| middle | 20655 | 15.0 | 15.5 | +0.5 |
| UVA-leaning | 20653 | 8.2 | 7.4 | -0.8 |
| most UVA-rich | 20648 | 3.2 | 2.5 | -0.7 |

Reading: UVA-rich hours (cloudy/high-SZA, relatively more UVA per UVB joule) score lower under v4 than under legacy at the same legacy level, because delayed-melanogenesis effectiveness per joule near 360-365 nm is ~3 orders below 290-295 nm while legacy weights UVA at 30%. UVB-rich clear midday hours move the opposite way. This is the intended science-driven reordering.

## Current South Bend runs (live South Bend 2026-09-23 run (336 hourly rows, degraded/no-CAMS))

Source: `data/latest/tables/tan_forecast_hourly.parquet` (336 rows).

Mean legacy: 9.3; mean v4: 8.8; mean delta (v4-legacy): -0.4.
Median delta: +0.0; p10 -3.0; p90 +1.4.
Rank correlation (Spearman): 0.989.

### UVA-rich vs UVB-rich divergence

| spectrum bin | n | mean legacy | mean v4 | mean delta |
|---|---|---|---|---|
| most UVB-rich | 31 | 29.2 | 32.3 | +3.1 |
| UVB-leaning | 31 | 30.3 | 31.2 | +0.9 |
| middle | 30 | 23.7 | 21.7 | -2.0 |
| UVA-leaning | 31 | 12.2 | 8.6 | -3.6 |
| most UVA-rich | 31 | 5.4 | 2.5 | -2.9 |

Reading: UVA-rich hours (cloudy/high-SZA, relatively more UVA per UVB joule) score lower under v4 than under legacy at the same legacy level, because delayed-melanogenesis effectiveness per joule near 360-365 nm is ~3 orders below 290-295 nm while legacy weights UVA at 30%. UVB-rich clear midday hours move the opposite way. This is the intended science-driven reordering.

## Inspection questions, answered on the live run

- Excellent-locally without globally near-100: peak Absolute hour scores v4 47.8 (legacy 43.2) with Local 91.8. CONFIRMED.
- Cloudy/high-UVA move (legacy 10-40 band): mean delta at cloud>=60 is -0.8 (n=41) vs -1.3 at cloud<30 (n=44). INCONCLUSIVE on cloud_cover alone this run (small/low-sun cloudy sample); the UVA/UVB-ratio bins are the direct mechanism test.
- Confidence vs intensity over lead time: confidence/lead Spearman -0.43 (declines distantly), Absolute/lead Spearman -0.00 (physics independent of horizon). CONFIRMED separate.
- UVA-rich vs UVB-rich behavior: see divergence bins above; the pigment-darkening (IPD) channel moves the opposite way by construction (UVA-dominant) and is never merged into TanScore.

## What to inspect
- September-11-like excellent-local hours should remain excellent locally without becoming globally near-100 (Absolute stays anchored to the fixed melanogenic reference).
- Cloudy/high-UVA cases move down relative to UVB-rich clear cases because delayed-melanogenesis effectiveness per joule is orders of magnitude higher near 290-295 nm than near 360-365 nm.
- UVA-rich vs UVB-rich spectra separate for delayed melanogenesis while IPD (pigment-darkening channel) moves the opposite way.
- Distant-forecast confidence stays separate from physical intensity.

Ordering changes are science-driven (photoaddition per Keong 1990, no sqrt interaction) and are not preserved for compatibility.
