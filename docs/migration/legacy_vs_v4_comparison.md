# Legacy 55/30/15 vs v4 action-spectrum comparison

Source: `data/calibration/training_calibration_hourly.parquet` (222408 rows; v4 recomputed Tier-C provisional).

Mean legacy: 8.5; mean v4: 9.6; mean delta (v4-legacy): +1.2.
Median delta: +0.0; p10 -0.6; p90 +5.3.
Rank correlation (Spearman): 0.999.

## What to inspect
- September-11-like excellent-local hours should remain excellent locally without becoming globally near-100 (Absolute stays anchored to the fixed melanogenic reference).
- Cloudy/high-UVA cases move down relative to UVB-rich clear cases because delayed-melanogenesis effectiveness per joule is orders of magnitude higher near 290-295 nm than near 360-365 nm.
- UVA-rich vs UVB-rich spectra separate for delayed melanogenesis while IPD (pigment-darkening channel) moves the opposite way.
- Distant-forecast confidence stays separate from physical intensity.

Ordering changes are science-driven (photoaddition per Keong 1990, no sqrt interaction) and are not preserved for compatibility.
