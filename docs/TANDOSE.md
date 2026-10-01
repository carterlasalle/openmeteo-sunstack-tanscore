# TanDose

**TanDose is not an internationally standardized dose. It is SunStack's
action-spectrum-weighted cumulative delayed-pigmentation exposure metric** using
`parrish-fda-3630-v1`. It represents exposure, not measured melanin synthesis
or a melanin-color prediction.

## Definitions

```text
TanDose(t1,t2) = integral[E_DP(t) dt]   [delayed-pigmentation-effective J/m^2]
E_DP(t) = integral[E_lambda(t,lambda) S_DP(lambda) dlambda]  [W/m^2]
```

The canonical v5 fields are
`delayed_pigmentation_dose_15m_j_m2`,
`delayed_pigmentation_dose_30m_j_m2`,
`delayed_pigmentation_dose_1h_j_m2`,
`delayed_pigmentation_dose_day_j_m2`, and
`delayed_pigmentation_dose_best_window_j_m2`. `tan_dose_*` names remain
migration aliases for the same endpoint.

## Integration rules

- `interval-contract-v1` distinguishes interval means from point samples:
  interval-mean irradiance integrates over declared support; point samples use
  trapezoidal integration over actual timestamps, never value × a nominal
  interval. Window end stamps bound the final supported interval.
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

- Tier B is `tierB-libradtran-emulator-v1` only after its manifest gates pass.
  Tier C is the explicitly labeled degraded proxy `tierC-broadband-proxy-v2`;
  it is never a silent spectral fallback.
- `erythemal_irradiance_wm2 = uvi_consensus / 40` is derived from final UVI
  consensus, and SED integrates that final-consensus field independently.
- Environmental horizontal exposure is canonical. Optional skin-plane exposure
  is surface/geometry context and never a future-color prediction.
