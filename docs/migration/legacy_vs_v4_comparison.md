# Legacy 55/30/15 vs v4 action-spectrum comparison

Source: `data/calibration/training_calibration_hourly.parquet` (222408 rows; v4 recomputed Tier-C provisional).

Mean legacy: 8.5; mean v4: 9.6; mean delta (v4-legacy): +1.2.
Median delta: +0.0; p10 -0.6; p90 +5.3.
Rank correlation (Spearman): 0.999.

## UVA-rich vs UVB-rich divergence (delayed melanogenesis separates spectra)

| spectrum bin | n | mean legacy | mean v4 | mean delta |
|---|---|---|---|---|
| most UVB-rich | 20653 | 39.3 | 49.1 | +9.8 |
| UVB-leaning | 20652 | 25.2 | 29.0 | +3.8 |
| middle | 20655 | 15.0 | 15.5 | +0.5 |
| UVA-leaning | 20653 | 8.2 | 7.4 | -0.8 |
| most UVA-rich | 20648 | 3.2 | 2.5 | -0.7 |

Reading: UVA-rich hours (cloudy/high-SZA, relatively more UVA per UVB joule) score lower under v4 than under legacy at the same legacy level, because delayed-melanogenesis effectiveness per joule near 360-365 nm is ~3 orders below 290-295 nm while legacy weights UVA at 30%. UVB-rich clear midday hours move the opposite way. This is the intended science-driven reordering.

## What to inspect
- September-11-like excellent-local hours should remain excellent locally without becoming globally near-100 (Absolute stays anchored to the fixed melanogenic reference).
- Cloudy/high-UVA cases move down relative to UVB-rich clear cases because delayed-melanogenesis effectiveness per joule is orders of magnitude higher near 290-295 nm than near 360-365 nm.
- UVA-rich vs UVB-rich spectra separate for delayed melanogenesis while IPD (pigment-darkening channel) moves the opposite way.
- Distant-forecast confidence stays separate from physical intensity.

Ordering changes are science-driven (photoaddition per Keong 1990, no sqrt interaction) and are not preserved for compatibility.
