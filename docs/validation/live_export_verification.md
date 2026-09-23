# Live export surface verification (South Bend, 2026-09-23 live run)

`sunstack export --site south-bend --site-dir <scratch>` against the live
v4 run (336 hourly rows, degraded/no-CAMS tiers). Export writes only the
given dir; committed `docs/` untouched.

- Payload: 196 hourly / 392 half-hour / 14 daily rows. All v4 columns
  present at every level (E_mel, v4 Absolute + legacy diagnostic, erythemal,
  pigment channel, interval/bed doses, tiers, model version, staleness).
  `local_reference_stale` false everywhere; spectral tier C throughout.
- 26/392 half-hour rows carry the native-HRRR source label; the rest are
  explicitly interpolated-hourly (never presented as native resolution).
- Summary carries every §20 key; `calibration_tier=nasa_power_ml`,
  `direct_cams_used=false`, `cams_cycle=null` — degraded state honestly
  exposed. The CAMS ERROR issue is recorded in `validation_issues` (loud,
  non-fatal only under explicit `--allow-degraded`).
- `calendar.ics`: 13 daily best-window events. `calendar-30min.ics`: 671
  interval events with Absolute/Overall, TanDose/SED/UVA/UVB, confidence,
  feasibility, tier, and native-vs-interpolated labeling.
- `index.html` contains the dose row, provenance line, all three chart
  canvases, Visible-Darkening Potential, and spectral-tier references.
- `sunstack debug --out data --photobiology` on the fresh run lists the
  complete photobiology column set (previously reported stale-run gaps),
  including the first-row NaN vs night-zero distinction working as designed.
