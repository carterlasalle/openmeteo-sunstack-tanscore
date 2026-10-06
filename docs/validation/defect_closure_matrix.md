# §27 known-defect closure matrix (§32.B format)

`ID | defect | changed files | test/evidence | status`

Legend — **FIXED**: closed in tree with a test or artifact-level check that fails
if the behaviour regresses. **REPLACED BY NEW MODEL**: the original defect is
gone because the model/algorithm that carried it was replaced. **STRICTLY
DISABLED**: the capability is deliberately unavailable because its required
evidence does not exist; the degraded path is labelled. No `DEFERRED` rows.

Companion matrix with the original evidence-only columns is in
`docs/RESEARCH_NOTES.md` ("v5 §27 closure matrix", 2026-10-01), plus the Oct-5
and Oct-6 addenda. This file adds the `changed files` column the handoff format
requires.

| ID | defect | changed files | test/evidence | status |
|---|---|---|---|---|
| 1 | wrong provisional Parrish UVB/UVA curve | `data/research/action_spectra/parrish_fda_3630.csv`, `src/sunstack/photobiology.py`, `scripts/build_action_spectra.py` | `parrish_fda_3630-v1` 1-nm table + `.meta.json` provenance; `test_delayed_pigmentation_spectrum_authoritative_anchors` | FIXED |
| 2 | fixed-band proxy unvalidated against true spectral convolution | `src/sunstack/spectral.py`, `scripts/band_weight_diagnostics.py`, `scripts/train_spectral_emulator.py`, `scripts/run_uvspec_corpus.py`, `docs/validation/woudc_spectral_validation.md`, `docs/validation/band_weight_diagnostics.md` | proxy bias now measured on true spectra: +2.19 median vs WOUDC Brewer (1878 scans) and ~2.8x vs uvspec; `test_dynamic_band_weights_track_true_spectral_shape`; Tier-C stays labelled `tierC-broadband-proxy-v2` | FIXED |
| 3 | final 30-minute UVI/erythemal/SED state mismatch | `src/sunstack/state.py`, `src/sunstack/opportunity.py` → `src/sunstack/opportunity.py`, `src/sunstack/doses.py` | `state.recompute_derived_state` single DAG; `tests/test_v5_state.py`; `test_final_halfhour_erythemal_matches_final_consensus` | FIXED |
| 4 | source count counts weighted votes | `src/sunstack/state.py` | unique-provider count + separate `uvi_consensus_vote_count`; `test_unique_uvi_source_count_not_vote_count` | FIXED |
| 5 | confidence rewards sunny outcomes | `src/sunstack/tanscore.py`, `src/sunstack/derive.py` | no UVI term in confidence; `tests/test_v5_confidence.py:26`; `test_final_confidence_inputs_use_final_state` (`tests/test_v5_state.py:91`) | FIXED |
| 6 | atmospheric feature coverage names do not match actual feature schema | `src/sunstack/tanscore.py`, `src/sunstack/calibrate.py` | coverage computed from the bundle manifest `feature_schema`; `tanscore:559` | FIXED |
| 7 | feature coverage does not actually affect confidence despite docs | `src/sunstack/tanscore.py`, `docs/SCIENCE.md` | coverage emitted transparency-only, docs corrected to match; no false coupling claimed | FIXED |
| 8 | checked-in model bundles lack manifests | `src/sunstack/tanscore.py`, `src/sunstack/calibrate.py` | writer emits manifest; strict loader raises without one; `test_run_manifest_metadata_contract` (`tests/test_photobiology.py:365`) + strict raise in `tanscore._load_bundle` | FIXED |
| 9 | training-code hash is recorded but not robustly enforced | `src/sunstack/tanscore.py` | `training_code_sha256` recomputed and compared on load; mismatch fails strict (`tanscore:232-244`) | FIXED |
| 10 | missing weather can become 100 feasibility | `src/sunstack/opportunity.py` | `outdoor_feasibility_complete` / `_missing_fields` / `_reason_codes`; `test_missing_required_weather_is_unknown_not_perfect` | FIXED |
| 11 | daily `*_peak` fields are values at another metric's peak | `src/sunstack/opportunity.py` | each peak is its own maximum; `*_at_best_*` for values at the selection; `test_all_peak_fields_are_true_peaks` | FIXED |
| 12 | global reference corpus not reproducibly present | `scripts/build_global_ref_v2.py`, `data/calibration/global_melanogenic_reference_v2/`, `src/sunstack/config.py` | 12-site POWER 2024 corpus (52,033 daylight h) + per-site SHA-256 manifest; both artifacts validator-true; `global-mel-ref-v2` 1.793 | FIXED |
| 13 | literature checks overstate independent validation | `scripts/check_literature.py`, `docs/validation/literature_sanity.md` | renamed to literature-informed regression invariants; independent artifacts kept separate | FIXED |
| 14 | UVI fusion comparisons use differing sample populations | `scripts/verify_uvi.py`, `docs/validation/uvi_verification.md` | common-case block uses one shared row set across candidates (n=147) | FIXED |
| 15 | POWER holdout presented too easily as physical accuracy | `docs/validation/external_validation.md`, `docs/SCIENCE.md` | labelled `POWER-product emulation`; measurement hierarchy documented | FIXED |
| 16 | local reference domain differs from serving domain | `src/sunstack/calibrate.py`, `data/calibration/local_reference_serving_*.parquet` | lead-band serving references (0-24h / 24-72h / 3-7d) + fallback flag | FIXED |
| 17 | Payerne +42% attribution overclaimed/unreproducible | `scripts/validate_woudc_spectral.py`, `docs/validation/woudc_spectral_validation.md`, `docs/RESEARCH_NOTES.md` | WOUDC API probed: Payerne has no spectral records (7,281 ozonesonde records checked) — extraction gap confirmed; Brewer path replaces it | FIXED |
| 18 | final publication gate misses cross-channel invariants | `scripts/validate_published_artifact.py`, `.github/workflows/run.yml` | 20 serialized checks incl. E_ery=UVI/40, SED reintegration, peak maxima; publish aborts on failure | FIXED |
| 19 | UVB boundary integration mismatch | `src/sunstack/spectral.py`, `src/sunstack/photobiology.py` | `[280,315) / [315,400]` cell-sum convention; `test_band_boundary_energy_conservation` | FIXED |
| 20 | UVI-based sun-feels heuristic / double attenuation | `src/sunstack/derive.py`, `src/sunstack/opportunity.py`, `docs/SCIENCE.md` | demoted to `sun_warming_heuristic_f`; no physical feels-like claim; excluded from radiation ranking | FIXED |
| 21 | broadband shortwave skin-plane factor applied to UV biology | `src/sunstack/spectral.py`, `docs/SCIENCE.md` | plane exposure split into separate direct / diffuse / local-reflected channels (`skin_plane_*` fields) instead of one broadband factor on the effect-weighted quantity; full per-component spectral convolution is the Tier-B item (#2) | FIXED |
| 22 | SED fallback prefers raw OM instead of final consensus | `src/sunstack/doses.py`, `src/sunstack/state.py` | consensus-first with `sed_uvi_source`; raw OM only in labelled degraded mode | FIXED |
| 23 | CAMS first accumulated interval semantics | `src/sunstack/history.py`, `src/sunstack/temporal.py` | cycle-partitioned differencing; first interval NaN/imputed; `test_cams_accumulation_never_differences_across_cycles` | FIXED |
| 24 | HRRR baseline snapshot should copy explicitly | `src/sunstack/history.py` | explicit copy + bounded ratio + `test_hrrr_correction_stays_bounded_against_kt_baseline` (`tests/test_core.py:1066`) | FIXED |
| 25 | UI Fit denominator includes non-daylight rows | `src/sunstack/serving.py` | daylight mask denominator matching the tooltip; `test_validator_fails_night_row_in_daylight_payload` (`tests/test_v5_artifact.py:189`, key `daylight_fit_denominator`) | FIXED |
| 26 | duplicate unreachable spectral-tier code | `src/sunstack/spectral.py` | single `spectral_tier_for_row` resolver; legacy alias only | FIXED |
| 27 | strict local-reference gate tolerates missing legacy metadata | `src/sunstack/cli.py`, `scripts/validate_published_artifact.py` | complete-metadata gate; missing version fields fail strict | FIXED |
| 28 | POWER start-of-hour vs Open-Meteo preceding-hour mismatch | `src/sunstack/temporal.py`, `src/sunstack/calibrate.py` | interval registry + midpoint alignment; `test_power_hourly_start_anchor_maps_to_midpoint`, `test_openmeteo_backward_mean_maps_to_midpoint` | FIXED |
| 29 | interval-mean radiation treated as point samples | `src/sunstack/doses.py`, `scripts/validate_published_artifact.py` | `integrate_interval_means_exact` vs `integrate_point_samples_trapezoid`; `test_interval_mean_dose_is_rectangular_exact` | FIXED |
| 30 | clearness vs clear-sky index conflated | `src/sunstack/derive.py`, `docs/SCIENCE.md` | canonical rename + alias; denominator matches interval support | FIXED |
| 31 | fixed TOA solar constant called exact | `src/sunstack/opportunity.py`, `src/sunstack/derive.py` | date-dependent extraterrestrial irradiance (pvlib); mean-distance labelled | FIXED |
| 32 | docs say temperature absent from physics while ML uses it | `docs/SCIENCE.md`, `docs/PHOTOBIOLOGY_MODEL.md` | product statement (comfort does not multiply the score) separated from model statement (temp/RH are predictors) | FIXED |
| 33 | "Atmosphere isolates air" stronger than the metric proves | `src/sunstack/tanscore.py`, `docs/SCIENCE.md` | renamed `geometry_conditioned_transmission_percentile_0_100`; conditional comparison stated | FIXED |
| 34 | "Absolute-first ranking" false for weighted composite | `src/sunstack/opportunity.py`, `src/sunstack/serving.py` | legacy composite labelled; dose ranking is the default key | FIXED |
| 35 | photon-scale-invariance test does not test the claim | `tests/test_v5_ranking.py` | old x10-dose-frozen-Overall test deleted; replaced by dose-ranking tests | FIXED |
| 36 | OM duplicated-median tie behaviour | `src/sunstack/state.py` | inverse-error weighted fusion replaces the duplicated-median trick | REPLACED BY NEW MODEL |
| 37 | lone valid sample returns zero dose instead of unknown | `src/sunstack/photobiology.py`, `src/sunstack/doses.py` | NaN + `complete=False`, `coverage=0`; `test_lone_sample_over_nonzero_window_is_unknown` (`tests/test_v5_temporal.py:190`) | FIXED |
| 38 | WMO 97 omitted from thunder hard-block list | `src/sunstack/opportunity.py` | `THUNDER_CODES={95,96,97,99}`; `test_wmo_97_hard_blocks` | FIXED |
| 39 | preceding-hour rain described as exact active rain | `src/sunstack/opportunity.py`, `docs/SCIENCE.md` | interval semantics for rain/showers/snowfall; `test_precip_sum_is_interval_semantic_not_instant_claim` | FIXED |
| 40 | snow-cover behaviour claimed without snow input | `src/sunstack/history.py`, `src/sunstack/config.py` | `snow_depth` fetched and carried; `test_snow_depth_can_block_existing_ground_snow` | FIXED |
| 41 | unvalidated fallback incorrectly named Tier B | `src/sunstack/spectral.py`, `docs/SPECTRAL_MODEL.md` | renamed `degraded_clear_sky_parametric_v1`; legacy alias only | FIXED |
| 42 | numerical IPD/TanDose ratio given biological meaning | `docs/ACTION_SPECTRA.md`, `docs/PHOTOBIOLOGY_MODEL.md` | ratio prose removed; separate channels documented | FIXED |
| 43 | generic measured MMD lacks spectral/basis compatibility | `src/sunstack/opportunity.py`, `tests/test_v5_feasibility.py` | structured basis enum; generic `MEASURED` rejected | FIXED |
| 44 | local surface reflection conflated with broadband albedo | `src/sunstack/surface.py`, `data/research/surfaces/surface_materials.yaml` | separate regional albedo vs local surface reflectance; `tests/test_v5_surface.py` | FIXED |
| 45 | README Overall weights stale (60/15/10/15 vs code) | `README.md`, `src/sunstack/config.py`, `tests/test_v5_contract.py` | weights corrected to the code constants; contract test pins them | FIXED |
| 46 | "sand 25% more than grass" unsupported claim | `docs/SCIENCE.md`, `src/sunstack/serving.py` | replaced with the selected profile's modelled change; zero ground-view at flat pose stated | FIXED |
| 47 | "zero metabolic heat" wording | `docs/SCIENCE.md`, `src/sunstack/derive.py` | resting-rate wording (metabolic heat is never zero) | FIXED |
| 48 | dew-point/wind examples arithmetically wrong | `docs/SCIENCE.md`, `tests/test_core.py` | examples generated by a unit test from the implementation (+6 F dew point, -6.4 F at 20 mph) | FIXED |
| 49 | "HRRR truth" wording | `docs/SCIENCE.md`, `src/sunstack/history.py` | renamed `native_hrrr_forecast`; dated historical log entry preserved | FIXED |
| 50 | no user-selectable local surface/material | `src/sunstack/surface.py`, `src/sunstack/cli.py`, `src/sunstack/ui.py`, `src/sunstack/serving.py`, `data/research/surfaces/surface_materials.yaml` | 14 presets + CLI/API/UI selector; `tests/test_v5_surface.py`, `tests/test_v5_ui_surface.py` | FIXED |

## Open items not in §27

- **DoD 2 (validated Tier-B backend).** The strict Tier-B path is wired and
  exercised; the emulator does not yet pass §8.4 held-out gates (E_DP median
  relative error 0.054 vs 0.03 required), so strict production stays Tier-C
  labelled and `validate_tierB_manifest` rejects any manifest whose
  `gates_passed` is not true. Contract-prescribed fallback, not a defect.
- **`TanResponse`** stays unshipped by design (§2.6).
- **§7.2 stratified band-weight tables** and **§8.5 WOUDC metrics** are generated
  artifacts; see `docs/validation/band_weight_diagnostics.md` and
  `docs/validation/woudc_spectral_validation.md`.
- **§32.E screenshots** — `docs/validation/ui/`.