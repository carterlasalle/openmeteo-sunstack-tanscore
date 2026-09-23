# TanDose

**TanDose is not an internationally standardized dose. It is SunStack's
action-spectrum-weighted cumulative delayed-melanogenesis exposure metric**
using `parrish_delayed_melanogenesis` version `action-spectrum-v1`
(tier: provisional; see `docs/ACTION_SPECTRA.md`).

## Definitions

```text
TanDose(t1,t2) = integral[E_mel(t) dt]   [melanogenic-effective J/m^2]
E_mel(t) = integral[E_lambda(t,lambda) S_mel(lambda) dlambda]  [W/m^2]
```

Canonical column: `tan_dose_melanogenic_j_m2`. Also exposed:
`tan_dose_15m_j_m2`, `tan_dose_30m_j_m2`, `tan_dose_1h_j_m2`,
`tan_dose_best_window_j_m2`, `tan_dose_day_j_m2`.

Column mapping: the `integrate_tandose` primitive returns the canonical
`tan_dose_melanogenic_j_m2` key; forecast frames carry the suffixed interval
(`tan_dose_15m/30m/1h_j_m2`), window (`tan_dose_best_window_j_m2`), and daily
(`tan_dose_day_j_m2`) variants of the same melanogenic-effective J/m^2
quantity.

## Integration rules

- Trapezoidal time integration over **actual timestamps**, never
  value * nominal interval. Samples are instantaneous: window ends are
  inclusive, so a one-hour window on a 30-minute grid integrates two full
  legs (E × 3600 s at constant irradiance).
- Integration is order-invariant (inputs sort stably by timestamp) and a
  single unparseable timestamp degrades only its own row, never the frame.
- Gaps larger than `SUNSTACK_TANDOSE_MAX_GAP_S` (default 10800 s) split the
  integral; the output marks `tan_dose_complete = false` with
  `tan_dose_coverage_fraction` (covered seconds / total span). Missing hours
  are never silently integrated across.
- Missing input is UNKNOWN, never zero: wholly missing irradiance integrates
  as NaN (a lone sample spans zero time but still reports incomplete), while
  only genuinely measured zeros — night rows carry real `0.0` — integrate as
  complete zeros. Row-level `tan_dose_{15m,30m,1h}_complete` and
  `tan_dose_{15m,30m,1h}_coverage_fraction` flags (plus SED pairs) expose this
  per interval; day rows carry `tan_dose_complete` /
  `tan_dose_coverage_fraction` (plus SED pairs); best-window and best-hour
  doses carry `tan_dose_best_window_complete` /
  `tan_dose_best_window_coverage_fraction` (plus SED pairs, hour variants
  under `best_hour_*`). A sample-free window reports NaN doses with
  `complete = false`, never zero.
- Night integrates as zero.

## Presentation unit

`tan_dose_reference_minutes = TanDose / E_mel_global_reference / 60`:
equivalent minutes at the fixed global reference melanogenic irradiance.
Presentation only. Do not call it MMD or a standardized tanning dose.

## What TanDose is not

- Not SED (erythemal channel, independent; never increases TanScore).
- Not MMD (a personal threshold; see `personal_mmd_fraction` when a measured
  or compatible MMD exists, labeled MEASURED / OBJECTIVE_ESTIMATE /
  COARSE_ESTIMATE; Fitzpatrick-only estimates disabled by default).
- Not UVA/UVB broadband dose (diagnostic physical doses
  `uva_dose_*_j_m2`, `uvb_dose_*_j_m2`, never biological endpoints).
- Not TanResponse (future delayed-pigmentation response model; repeated
  exposure never rescales TanDose photons).

## Assumptions and limitations

- Tier-C spectral reconstruction (uniform intra-band) pending a validated
  libRadtran emulator; band weights derive from the action spectrum itself.
- Provisional delayed-melanogenesis shape (Parrish-approximated); strict
  canonical mode refuses it until CIE 103/3 is obtained in usable form.
- Horizontal environmental reference unless a skin-plane tilt is configured
  (direct incidence + isotropic diffuse + albedo bounce; diffuse never dropped).
