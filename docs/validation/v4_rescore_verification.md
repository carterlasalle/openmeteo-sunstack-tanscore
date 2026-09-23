# v4 offline re-score verification (real forecast data, no network)

Site: pacific-palisades; input rows: hourly=336, half-hour=671, days=14.
Validators: photobiology + scored-hourly ERROR count = 0.

## Score migration on this run

v4 Absolute mean/max: 14.7 / 68.9; legacy mean/max: 13.3 / 52.2; Spearman: 0.978.
E_mel max: 1.103 W/m^2 (global ref 1.6).

## Doses

Daily TanDose range: 15576-22501 J/m^2 mel; daily SED range: 27.65-40.23.
tan_dose_complete all: True; coverage min: 1.000.

## Windows (intensity-ranked, dose-reported)

Top hourly window overall: 69.7; best-window TanDose example (day 1): 10854 J/m^2, SED 19.61.
Daily ICS events: 14; 30-min ICS events: 671.

Artifacts (scratch, not committed): /tmp/v4_rescore/pacific-palisades

## Coverage (pre-existing data-availability behavior, unchanged by v4)

Local scores non-null: 1.000 (rebuilt v4 reference); atmosphere: 0.583; confidence: 0.500; CAMS UVI present: 0.366 (5-day CAMS horizon vs 14-day forecast).

## Degraded-mode rescore, 2026-09-23 (no direct-CAMS artifact)

South Bend live tables (336 hourly / 671 half-hour / 14 days) rescore end
to end with zero validation errors after the CAMS-tolerant rescore fix; the
report line carries "direct CAMS artifact absent (degraded run): rescoring
without direct CAMS". v4 Absolute mean/max 9.0/47.8 vs legacy 9.3/43.2,
Spearman 0.989; daily TanDose 2045–15761 J/m² mel, daily SED 3.90–30.75, all
complete with coverage 1.000; 13 daily + 671 interval calendar events; local
scores 1.000, CAMS UVI present 0.000.
