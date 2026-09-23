# v4 offline re-score verification (real forecast data, no network)

Site: pacific-palisades; input rows: hourly=336, half-hour=671, days=14.
Validators: photobiology + scored-hourly ERROR count = 0.

## Score migration on this run

v4 Absolute mean/max: 14.7 / 68.9; legacy mean/max: 13.3 / 52.2; Spearman: 0.978.
E_mel max: 1.103 W/m^2 (global ref 1.6).

## Doses

Daily TanDose range: 15569-22501 J/m^2 mel; daily SED range: 27.65-40.23.
tan_dose_complete all: True; coverage min: 1.000.

## Windows (intensity-ranked, dose-reported)

Top hourly window overall: 69.7; best-window TanDose example (day 1): 9610 J/m^2, SED 17.27.
Daily ICS events: 14; 30-min ICS events: 671.

Artifacts (scratch, not committed): /tmp/v4_rescore/pacific-palisades

## Coverage (pre-existing data-availability behavior, unchanged by v4)

Local scores non-null: 1.000 (rebuilt v4 reference); atmosphere: 0.583; confidence: 0.500; CAMS UVI present: 0.366 (5-day CAMS horizon vs 14-day forecast).
