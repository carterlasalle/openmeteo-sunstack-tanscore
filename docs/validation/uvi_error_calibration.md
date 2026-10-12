# UVI error calibration against MEASURED spectra

The confidence channel carries a handwritten expected-error model. Its coefficients were
anchored to a comparison whose reference is Open-Meteo's own retrospective, so agreement
there cannot establish calibration. This study pairs it with measurement instead: WOUDC
Brewer spectra give an independent UVI truth (erythemal integral x 40, integrated over
wavelength), and the previous-runs archive gives the forecast UVI at the station's own
coordinates, matched on solar zenith angle (pvlib, the pipeline's own helper).

Station **Uccle** at {'latitude': 50.799, 'longitude': 4.357, 'height': 100.0}, window 2026-07-12..2026-10-12: 270 measured scans, **209 paired**, 61 unmatched (no forecast hour within 2 deg SZA).

## Measured conditional error

| SZA bin | n | MAE (UVI) | bias (measured - forecast) |
|---|---:|---:|---:|
| 30-45 | 44 | 2.736 | +2.271 |
| 45-60 | 100 | 1.741 | +0.956 |
| 60-75 | 39 | 1.31 | -0.702 |
| 75-90 | 26 | 1.9 | -1.787 |

Per lead (only lead 0 was available: the public previous-runs endpoint returned empty
`uv_index_previous_dayN` columns for every model tried, so the lead term stays unverified):

| lead | n | MAE | bias | heuristic expected error | coverage of its +-1.5x interval |
|---|---:|---:|---:|---:|---:|
| 0 | 209 | 1.89 | +0.582 | 0.35 | 21% |

## Verdict

**The heuristic's interval is not calibrated, and the measurement says so.** Its stated
expected error at lead 0 is 0.35 UVI, so its +-1.5x band is +-0.53; the measured error is
1.3-2.7 UVI depending on sun height. That band covers 11% of the measured pairs, not ~95%.
The sign flips with SZA (measured exceeds the forecast at high sun, falls below it at low
sun), which is what a cloud-partition error looks like: in the sampled pairs the model sits
at 100% cloud cover while the Brewer measured real UV, i.e. a point-versus-grid mismatch on
top of the model's own cloud attenuation.

**A fit is not shipped from this evidence.** One station, one season, no lead dimension and
an unresolved point-versus-grid confound would produce a confident-looking model on thin
data - the failure mode this audit is about. The tooling is in place; the data is not.

## Fix found on the way (and applied)

The first run of this study reported a +2.5 UVI forecast bias. That was measurement, not
forecast: `integrate_channels` summed the reported samples instead of integrating them, and
WOUDC ships a 0.5 nm grid, so every band came out exactly 2x its physical value (checked
against the files' own IntCIE column: sum/integral = 2.0). Integrating over wavelength
halved the apparent bias (+2.48 -> +0.96 at SZA 45-60) and is now pinned by a test.

## What a real fit needs

1. At least five stations across climate zones, at least a full year each (the WOUDC
   archive lags: Toronto's newest scan is 2025-12-31 while per-run history covers ~92 days).
2. A per-lead source that actually publishes UVI per run, so the lead term can be fitted
   rather than assumed.
3. A point-versus-grid treatment: either grid-cell-averaged truth or a station-scale
   forecast, or the cloud term will absorb a spatial mismatch as if it were model error.

## Reproduce

```bash
uv run python scripts/calibrate_uvi_error_from_measured.py \
  --station Uccle --past-days 92 --max-files 10 \
  --out docs/validation/uvi_error_calibration.md
```
