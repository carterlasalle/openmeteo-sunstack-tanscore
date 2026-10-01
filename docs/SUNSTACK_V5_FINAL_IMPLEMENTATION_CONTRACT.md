# SunStack v5 — Final Science, Physics, Data, Product, and Implementation Contract

**Status:** mandatory completion contract for a coding agent with zero prior context  
**Repository:** `openmeteo-sunstack-tanscore-main`  
**Purpose:** take the current SunStack codebase from a thoughtful but internally inconsistent v4 research prototype to a coherent, reproducible, spectrally validated, interval-correct, source-transparent production system.  
**Scope:** **everything in this document is in scope.** Do not defer items to “v6”, “future work”, or TODOs unless this document explicitly marks them as an allowed degraded-mode capability.  
**Package/runtime policy:** Python must be managed with **uv**, using the repository-pinned version and lockfile. Do not use `pip`, Poetry, Conda, or ad-hoc virtualenv commands. The existing frontend is embedded/static JavaScript; do not introduce a Node build unless a frontend extraction is genuinely necessary. If a Node toolchain is introduced, use **Yarn** exclusively.  
**Authority order:** executable source/runtime behavior > immutable source data/manifests > this contract > prose documentation. If existing docs disagree with code, fix both. If a source assumption is scientifically unresolved, surface the uncertainty rather than choosing the more convenient interpretation.

---

# 0. Executive directive to the implementation agent

This is **not** a narrow bug-fix round. It is a finish-and-converge round.

The current project has several good architectural boundaries that must be preserved—environmental radiation versus outdoor usability, exposure versus biological response, environmental physics versus personal skin context, missing versus zero, and versioned provenance—but important pieces violate those boundaries in practice. The final implementation must make the published artifact internally self-consistent and must narrow or remove scientific claims that are stronger than the evidence.

The agent must complete all of the following categories:

1. repair the final derived-state DAG so every published field describes the same final inputs;
2. implement explicit temporal-support semantics for all radiation/weather quantities;
3. correct and version the delayed-pigmentation action spectrum;
4. stop presenting the current fixed UVA/UVB band reduction as validated spectral physics;
5. build and validate a real spectral Tier-B path, with a deliberately labeled degraded broadband fallback;
6. rebuild local/global references in the correct serving domain;
7. redesign UVI fusion and confidence so “confidence” means uncertainty/reliability, not sunniness;
8. change ranking so the product directly answers the user’s actual question: strongest fixed-duration delayed-pigmentation-weighted exposure among usable times;
9. add a real **surface/material selection model** so the user can choose grass, sand, concrete, asphalt, water, snow, etc. without abusing CAMS broadband albedo as a local ground-reflection coefficient;
10. upgrade skin-plane exposure so local reflected/direct/diffuse radiation is represented explicitly and separately from horizontal environmental fields;
11. replace or clearly demote the current UVI-based “sun-feels” heuristic;
12. fix precipitation/snow/thunderstorm semantics, including WMO code 97 and actual snow-cover state;
13. make personal MMD compatibility explicit; a generic `MEASURED` label is insufficient;
14. make model/data/reference manifests mandatory in strict mode;
15. rebuild validation as independent, artifact-level invariants and external measurement checks;
16. repair UI/API/static export/documentation so labels match exact semantics;
17. add release gates that make it impossible to ship a `validation_issues=[]` artifact that violates the core equations.

No item is complete because “the tests pass” if the tests merely assert the existing implementation. Every material semantic must be validated against an independently recomputed expectation, authoritative source, or a deliberately defined product policy.

---

# 1. Mandatory working procedure

Before changing code:

1. Read `AGENTS.md`, `README.md`, `docs/SCIENCE.md`, `docs/PHOTOBIOLOGY_MODEL.md`, `docs/SPECTRAL_MODEL.md`, `docs/TANDOSE.md`, `docs/ACTION_SPECTRA.md`, and `docs/RESEARCH_NOTES.md`.
2. Run the repository context commands required by `AGENTS.md`:
   - `scc context startup`
   - `scc drift`
   - use `scc impact <files>` before each cross-layer refactor.
3. Install exactly with:
   - `uv sync --locked`
4. Establish a baseline:
   - `uv run pytest tests/ -q`
   - `uv run ruff check src tests scripts`
   - `uv run basedpyright` if configured/working in the locked environment
   - `uv run sunstack doctor` and `uv run sunstack debug`
5. Preserve the baseline result as `docs/validation/v5_baseline.md`; failures that already exist must be distinguished from regressions introduced by this work.
6. Do not edit committed historical run evidence in place. Migrations produce new artifacts/versions.

During implementation:

- no `pip install`;
- no silently generated lockfile changes;
- no catch-all exception that converts a science failure into a plausible number;
- no placeholder implementation behind a production-looking label;
- no TODO/FIXME for an item in this contract;
- no copying old composite columns forward after any primitive parent changes;
- no use of `fillna(0)` on an environmental or usability input unless zero is physically/policy-correct and the missingness has already been handled explicitly;
- no field named `peak` unless it is independently proven to be that field’s maximum;
- no field named `confidence` unless it is empirically tied to predictive reliability/error;
- no field named `spectral`, `canonical`, `validated`, `global`, or `truth` unless the definition in this contract is met.

Before completion:

- run every release gate in §24;
- rebuild the actual static artifact and validate the **serialized JSON/CSV/ICS**, not just in-memory DataFrames;
- inspect the UI at desktop and narrow/mobile widths;
- update all docs and examples from the new versioned semantics;
- leave the tree clean except for intended changes.

---

# 2. Product semantics after this work

SunStack must answer several different questions without merging them into one scientifically ambiguous number.

## 2.1 Primary environmental outputs

The primary physical quantities are:

### A. Delayed-pigmentation-weighted spectral irradiance

There are **two different exposure bases** and they must never be conflated.

**Environmental horizontal reference** (user-independent):

`delayed_pigmentation_effective_irradiance_horizontal_wm2`

\[
E_{DP,h}(t)=\int_{280}^{400} E_{\lambda,h}(t,\lambda)S_{DP}(\lambda)d\lambda
\]

This is the canonical site/environment quantity. Local surface choice, Fitzpatrick type, body posture, clothing, and personal MMD may not change it.

**User skin-plane exposure** (optional, geometry/surface dependent):

`skin_plane_delayed_pigmentation_effective_irradiance_wm2`

\[
E_{DP,p}(t)=\int_{280}^{400} E_{\lambda,p}(t,\lambda)S_{DP}(\lambda)d\lambda
\]

The plane spectrum is built from direct + diffuse + local reflected components under the selected posture/surface model.

For one migration release, `melanogenic_effective_irradiance_wm2` remains a deprecated alias of the **horizontal environmental** value, not the user plane value.

Both quantities are **effect-weighted exposure quantities for the action-spectrum endpoint**. Do not describe either as measured melanin synthesis or a prediction of future skin color.

### B. Delayed-pigmentation-weighted dose

Canonical names:

- `delayed_pigmentation_dose_15m_j_m2`
- `delayed_pigmentation_dose_30m_j_m2`
- `delayed_pigmentation_dose_1h_j_m2`
- `delayed_pigmentation_dose_day_j_m2`
- `delayed_pigmentation_dose_best_window_j_m2`

The existing `tan_dose_*` names may remain as one-version aliases, but UI/docs must prefer the explicit endpoint wording.

### C. Erythemal channel

Keep:

`erythemal_irradiance_wm2 = uvi_consensus / 40`

and SED, entirely separate from delayed-pigmentation ranking.

### D. Rapid/persistent pigment-darkening proxy

Keep a separate UVA-dominant channel but rename it so it cannot be confused with actual visible color outcome. Preferred:

`pigment_darkening_effective_irradiance_wm2`

and corresponding dose fields.

Do **not** render statements such as “3× TanDose” as a biological comparison. Different action-spectrum normalizations produce different effective-unit scales.

## 2.2 Interpretation/context outputs

Keep but clarify:

- `local_strength_percentile_0_100`: percentile of the physical delayed-pigmentation intensity/dose against a serving-domain local reference.
- replace/rename `atmospheric_quality_percentile_0_100` with `geometry_conditioned_transmission_percentile_0_100`.
- expose the underlying physical ratio `delayed_pigmentation_transmission_ratio = E_DP_all_sky / E_DP_clear_sky` where the backend can compute both.

Do not claim that this percentile causally “isolates the atmosphere.” It is a conditional comparison.

## 2.3 Forecast reliability outputs

Separate four different concepts:

1. `strong_sun_probability_0_100` — probability that radiation exceeds useful strength thresholds;
2. `forecast_expected_error_*` — expected model error;
3. `forecast_prediction_interval_*` — calibrated uncertainty interval;
4. `tan_forecast_confidence_0_100` — optional reader-friendly reliability score derived from the calibrated error model, not from how sunny the predicted outcome is.

## 2.4 Outdoor usability outputs

Keep hard/soft outdoor context separate from radiation:

- `outdoor_feasibility_0_100` is display scale 0–100;
- `outdoor_feasibility_multiplier` is 0–1 if retained;
- `outdoor_feasibility_complete` and missing reasons are mandatory.

## 2.5 User-facing headline/ranking outputs

The primary recommendation surface must no longer use the current geometric `Overall` as the answer to “best tanning time.”

Every ranking carries `exposure_basis = environmental_horizontal | skin_plane`. API/default scientific exports use `environmental_horizontal` unless the caller explicitly supplies a user exposure configuration. Interactive UI may use `skin_plane` after the user selects/accepts posture and surface; it must visibly display that basis. Changing local surface is therefore allowed to change **skin-plane ranking**, but never horizontal-environment ranking.

Expose three distinct rankings for the selected exposure basis:

1. **Strongest 30 min** — maximum expected 30-minute delayed-pigmentation-weighted dose, regardless of comfort, among physically complete daylight windows.
2. **Best usable 30 min** — maximum expected 30-minute dose among windows that pass hard outdoor constraints and user schedule constraints.
3. **Best comfortable usable 30 min** — same physical dose ranking, but among windows satisfying a user-selected comfort threshold; confidence and comfort may break near-ties but may not manufacture radiation.

Repeat for 15/60 minutes where useful.

The old `overall_tan_opportunity_0_100` may remain for one migration version as a **deprecated product heuristic**, clearly labeled “legacy composite,” and must not be the default ranking key.

## 2.6 Actual visible future tan

`TanResponse` remains unshipped until independently validated. Production must continue returning no quantitative prediction of future color change.

---

# 3. Version migration

Mint new semantic versions. Do not mutate v4 values under old labels.

Minimum target version identities:

- `schema_version = sunstack-output-v5`
- `temporal_semantics_version = interval-contract-v1`
- `photobiology_model_version = delayed-pigmentation-v2`
- `tan_score_model_version = action-spectrum-v2`
- `action_spectrum_version = parrish-fda-3630-v1` unless a better legally/reproducibly distributable canonical source is obtained and documented
- `spectral_backend = tierB-libradtran-emulator-v1` in strict production after it passes gates
- `spectral_degraded_backend = tierC-broadband-proxy-v2`
- `surface_model_version = uv-surface-v1`
- `fusion_version = calibrated-uvi-fusion-v2`
- `confidence_version = calibrated-error-v1`
- `window_rank_version = fixed-duration-dose-v2`
- `global_reference_version = global-mel-ref-v2` only after rebuilding the corpus

Every row and summary must carry enough versions to identify the exact semantics.

Old v4 committed files remain historical evidence. Do not rewrite them to pretend they were generated by v5.

---

# 4. Workstream A — make the final derived-state graph single-pass and coherent

## Problem

The current 30-minute path can recompute primitive/source fields and then leave dependent columns from an earlier state. This is how `uvi_consensus`, erythemal irradiance, SED, source count, and confidence diverged in a published artifact.

## Required architecture

Create an explicit dependency pipeline. Prefer a dedicated module such as:

`src/sunstack/state.py`

with pure stages. The exact module name may differ, but the graph may not remain implicit across scattered functions.

Required final order:

1. normalized primitive provider fields;
2. temporal-support alignment/reconstruction;
3. final broadband radiation correction/native override;
4. final source UVI values;
5. final UVI fusion;
6. final UVI range/spread/unique-provider count;
7. final erythemal irradiance from final consensus;
8. final spectral/broadband UVA/UVB and delayed-pigmentation channel;
9. final clear-sky counterpart/transmission;
10. local and geometry-conditioned reference percentiles;
11. final uncertainty/error estimates and reliability score;
12. surface + skin-plane exposure variants;
13. outdoor feasibility/comfort;
14. fixed-duration interval dose calculations;
15. window ranking;
16. daily summaries;
17. serialization;
18. artifact-level validation.

No stage is allowed to interpolate or carry a derived child field when any parent is modified afterward.

## Specific fixes

- In `src/sunstack/opportunity.py`, eliminate the pattern where `_recompute_v4_scores()` runs before final UVI fusion and then only a subset of dependent fields is overwritten.
- Create one `recompute_derived_state(frame, context)` function or equivalent that regenerates all child values from final primitive inputs.
- `uvi_consensus_sources` counts unique providers (`OM`, `CAMS`, `EPA`), never weighted votes.
- If weighted votes remain internally during migration, expose optional `uvi_consensus_vote_count` separately.
- Recompute `erythemal_irradiance_wm2` after final UVI fusion and nowhere else.
- Recompute disagreement and confidence after final source values/fusion.
- Recompute all doses only after all final irradiance channels are frozen.

## Acceptance tests

Add artifact-level tests asserting, for every finite serialized half-hour row:

- `erythemal_irradiance_wm2 == uvi_consensus / 40` within `1e-9` before serialization rounding and agreed serialized tolerance afterward;
- `uvi_consensus_sources == count_unique_finite_source_providers`;
- re-integrated SED from final consensus exactly matches emitted SED within numerical tolerance;
- no derived field has an older `state_revision` than its parents if a revision mechanism is used;
- mutation of any source UVI in a fixture forces all dependent fields to move or remain provably invariant.

---

# 5. Workstream B — explicit temporal-support semantics

This is a core science fix, not metadata polish.

## 5.1 Known mismatch

NASA POWER hourly timestamps identify the **start of the hour**. Open-Meteo ordinary solar-radiation fields are backward means over the **preceding hour**. The current code explicitly requests NASA POWER in UTC, which is correct and must remain.

Therefore a POWER value stamped `12:00` and an Open-Meteo hourly mean stamped `12:00` do not describe the same interval.

## 5.2 Introduce a first-class interval contract

Every normalized time-varying source variable used in physics must have or inherit:

- `valid_time`
- `support_type`: `instant | interval_mean | interval_sum | cumulative_since_cycle`
- `interval_start`
- `interval_end`
- `interval_midpoint`
- `source_cycle` when applicable
- `native_resolution_seconds`
- `time_standard`
- `temporal_source`

Do not add six columns per variable to every wide table if that is unwieldy. A versioned variable-semantics registry plus normalized frame-level interval bounds is acceptable, but the runtime must be able to prove the support of every field.

Recommended module:

`src/sunstack/temporal.py`

with a registry such as:

```python
TemporalSemantics(
    source="nasa_power",
    variable="ALLSKY_SFC_UVA",
    support="interval_mean",
    anchor="interval_start",
    duration_s=3600,
)
```

and:

```python
TemporalSemantics(
    source="open_meteo",
    variable="shortwave_radiation",
    support="interval_mean",
    anchor="interval_end",
    duration_s=3600,
)
```

## 5.3 Training alignment

In `history.py` / `calibrate.py`:

- retain POWER raw timestamp as source metadata;
- convert POWER hourly mean targets to interval `[t,t+1h)` and midpoint `t+30m`;
- convert Open-Meteo preceding-hour means stamped `t` to `[t-1h,t)` and midpoint `t-30m`;
- merge interval-mean predictors/targets by interval overlap or canonical midpoint, not by raw timestamp with ±35-minute tolerance;
- instantaneous variables must be sampled/interpolated at the same canonical midpoint or handled through explicit support-aware feature construction;
- solar geometry used for an interval-mean target must be either interval-mean geometry/radiation geometry or explicitly midpoint geometry; choose one and use it in both training and serving.

A raw `merge_asof(... tolerance=35min)` is not sufficient evidence of temporal alignment.

## 5.4 Dose integration semantics

For an interval-mean irradiance `Ebar` over `[a,b]`, energy is:

`dose = Ebar * (b-a)`.

Do not trapezoid-integrate adjacent interval means as if they were point samples.

Implement two primitives:

- `integrate_point_samples_trapezoid(...)`
- `integrate_interval_means_exact(...)`

Mixed/reconstructed series must first become a canonical interval representation with explicit energy conservation.

For the 30-minute product, recommended canonical support is half-hour intervals. Emit both:

- `interval_start`
- `interval_end`
- display label/time separately if needed.

Trailing doses must state exactly which interval they cover.

## 5.5 Sub-hour radiation

Use Open-Meteo `_instant` radiation fields as point values only when they truly are `_instant`. Use ordinary 15-minute/hourly values as backward interval means according to provider documentation.

Do not call native HRRR output “truth.” Rename everywhere to `native_hrrr_forecast`, `native_hrrr_subhour`, or similar.

## 5.6 Clearness versus clear-sky index

Rename:

- `clearness_index = GHI / extraterrestrial_horizontal_irradiance`
- `clear_sky_index = GHI / clear_sky_GHI`

Do not use the terms interchangeably.

For interval means, denominator must match the interval support. Do not divide a one-hour mean GHI by an instantaneous TOA value at the endpoint.

Use date-dependent extraterrestrial irradiance rather than the fixed `1361.1*cos(SZA)` approximation when describing the result as exact. `pvlib.irradiance.get_extra_radiation` or an equivalent accepted implementation is appropriate.

## 5.7 CAMS accumulated fields

For accumulated downward surface UV:

- partition by CAMS forecast cycle before differencing;
- sort by valid lead within cycle;
- never difference across cycles;
- detect/reset accumulation explicitly;
- negative increments are an error/reset signal, not something to hide by clipping without provenance;
- the first interval is unknown unless the provider supplies a defined zero accumulation at cycle start;
- any inferred first interval must be labeled `imputed` and incomplete.

Add a fixture with two cycles and an accumulation reset. It must not generate a giant negative/zero-clipped pseudo-interval.

---

# 6. Workstream C — correct the delayed-pigmentation action spectrum

## 6.1 Replace the existing provisional curve

The current anchors are not a faithful reconstruction of the Parrish-derived table, particularly around 280–305 nm and in UVA.

Use a reproducible 1-nm source table with explicit provenance. The FDA Form 3630 table is acceptable as a public, reproducible Parrish-derived reference unless the project acquires a more authoritative distributable table.

Required metadata:

- source title;
- source URL/identifier;
- exact table/appendix location;
- endpoint wording;
- population/protocol limitation;
- normalization wavelength/value;
- any transcription/digitization method;
- checksum;
- wavelength coverage;
- interpolation rule;
- uncertainty note;
- license/distribution note.

Do not carry the current assumption “280–289 unity.”

## 6.2 Terminology

Prefer “delayed pigmentation action spectrum” over implying that the experiment directly measured molecular melanogenesis.

Required documentation wording:

> SunStack uses an action-spectrum-based exposure index derived from a delayed-pigmentation endpoint. It is not a universal prediction of melanin production or visible future skin color.

## 6.3 Interpolation

Log-space interpolation remains an acceptable chosen reconstruction method where interpolation is necessary. Change docs from “linear interpolation is INVALID” to a precise statement: linear-effectiveness interpolation is not the selected method and is inappropriate for this reconstruction because effectiveness spans orders of magnitude unless independently validated.

If the new table is already 1-nm, interpolation within the production 1-nm grid should generally be unnecessary.

## 6.4 Boundary conventions

Define UVB and UVA interval boundaries once in code and docs. Remove the current `<315` / divide-by-35 mismatch.

Recommended convention:

- UVB integral over `[280,315)`
- UVA integral over `[315,400]` or a clearly specified integration-edge representation

Use numerical integration edges so the sum reconstructs the original 280–400 broadband energy without double-counting or dropping a 1-nm boundary cell.

Add energy-conservation tests.

---

# 7. Workstream D — stop treating fixed band means as validated spectral convolution

Even with the corrected action spectrum, the current Tier-C equation:

`E_DP = UVA * mean(S_UVA) + UVB * mean(S_UVB)`

assumes a uniform irradiance distribution within each band. Real surface UV—especially UVB—is not spectrally uniform and changes with ozone, solar zenith angle, aerosols, clouds, albedo, altitude, and multiple scattering.

## 7.1 Rename the fallback honestly

Rename production metadata from `tierC-broadband-v1` to `tierC-broadband-proxy-v2` after the new spectrum.

Strict scientific production must not label this Tier B.

Remove/rename `tierB-clear-sky-v1`; an unvalidated parametric clear-sky fallback cannot simultaneously be called Tier B when Tier B is contractually defined as a validated spectral emulator.

Allowed naming:

- `degraded_clear_sky_parametric_v1`
- tier `C` or `D`, depending on completeness

## 7.2 Dynamic effective band weights as diagnostics

For every true spectrum in validation/corpus work, calculate:

`w_band(t) = integral(E_lambda*S)/integral(E_lambda)`

for UVA/UVB. Use this to quantify how far the fixed-band approximation moves across regimes.

Required plots/tables stratified by:

- SZA bins;
- total ozone;
- AOD;
- SSA/absorption;
- cloud state;
- altitude;
- surface albedo;
- season/site.

Do not claim the band-shape error is “secondary” until these comparisons support that statement.

---

# 8. Workstream E — implement a real Tier-B spectral backend

The final intended strict backend is a validated fast emulator/reconstruction trained on a deterministic radiative-transfer corpus and checked against independent measured spectra.

## 8.1 Reference engine

Use libRadtran or an equivalently validated UV radiative-transfer engine to generate 280–400 nm spectral irradiance with at least 1-nm output. Store direct, diffuse, and global horizontal spectral components separately.

The reference corpus build must be deterministic and manifest-driven.

Required input dimensions include, at minimum:

- solar zenith/elevation;
- Earth-Sun distance/date;
- altitude/pressure;
- total column ozone;
- spectral aerosol optical depth / Angstrom behavior;
- aerosol single scattering albedo;
- aerosol asymmetry parameter;
- water vapor as needed;
- cloud optical state sufficient for the selected RT setup;
- surface spectral albedo;
- direct/diffuse geometry.

CAMS variables already fetched should be used where physically compatible; do not invent precision for unsupported cloud microphysics.

## 8.2 Corpus design

`scripts/build_spectral_corpus.py` must become a complete reproducible builder rather than a scaffold.

Use stratified sampling / Latin hypercube / Sobol design over plausible parameter ranges, with explicit regime enrichment near:

- low sun;
- high ozone and low ozone;
- high AOD / absorbing aerosol;
- bright snow/sand surfaces;
- cloud transitions;
- high altitude.

Manifest must contain:

- libRadtran version and executable hash/container digest;
- every config template;
- parameter ranges/distributions;
- random/quasi-random seed;
- number of simulations;
- failed simulation count/reasons;
- spectral wavelength grid;
- hashes of corpus partitions.

## 8.3 Emulator architecture

Implement and benchmark at least:

A. spectral PCA/low-rank basis + supervised coefficient predictors;
B. direct prediction of key integrated channels as an auxiliary model;
C. the current Tier-C proxy as baseline.

Do not choose a model based only on aggregate R². Select based on held-out spectral and biological-channel errors by regime.

The spectral emulator must reconstruct non-negative direct/diffuse spectra and preserve band energy to defined tolerances.

## 8.4 Required held-out corpus gates

For daytime rows above a defined minimum signal threshold:

- median absolute relative error in `E_DP` <= 3%;
- 95th percentile absolute relative error in `E_DP` <= 10%;
- median absolute relative error in erythemal irradiance <= 3%;
- 95th percentile erythemal relative error <= 10%;
- integrated UVA and UVB energy error <= 2% median and <= 5% p95;
- no major regime bin (SZA/ozone/AOD/albedo) with median `E_DP` bias magnitude > 7%;
- reconstructed spectra non-negative;
- no material energy discontinuity at 315 nm caused by model decomposition.

If these cannot be achieved, strict mode must remain unavailable rather than relabeling the proxy as Tier B.

## 8.5 Independent measured spectral validation

Use public ground spectral UV data such as WOUDC Spectral UV records. Preserve station/instrument metadata and QC flags. Match forecast/reference inputs to observed times/locations.

Validation must independently compute from measured spectra:

- UVA;
- UVB;
- erythemal irradiance/UVI;
- delayed-pigmentation-weighted irradiance using the same action spectrum;
- pigment-darkening proxy if used.

Required reporting:

- overall bias/MAE/RMSE;
- clear-sky and cloudy subsets;
- SZA bins;
- station-held-out results;
- seasonal subsets;
- measurement uncertainty/context.

A release target is median absolute relative `E_DP` error <=15% across qualified measured cases, <=10% in clear-sky high-quality cases, with no broad regime showing >20% median error unless explicitly downgraded and investigated.

These thresholds are product release gates, not claims that the instruments themselves are exact.

---

# 9. Workstream F — UVA/UVB calibration and train/serve consistency

## 9.1 Keep POWER skill in its proper category

Rename claims such as “UVA MAE 0.30” to `POWER-product emulation MAE` unless the target is independent measured UVA.

Keep NWP-fed and independent-observation skill separate.

## 9.2 Rebuild training data with temporal alignment

After §5 temporal changes, retrain all bundles. Do not reuse v4 models.

## 9.3 Feature semantics

The science docs currently imply temperature/rain never affect physics, but `temp_c` and RH are actual ML predictors. Required correction:

- product statement: weather comfort does not directly multiply the radiation score;
- model statement: meteorological variables may be predictive features in an empirical radiation estimator and therefore can indirectly change the radiation estimate.

If the team wants stronger physical invariance, run ablations. Do not remove useful features merely to preserve a slogan.

## 9.4 Serving-domain references

Local percentile references must be built from historical archived **serving-style inputs**, through the same feature mapping/model/backend as live production.

Use historical forecast/previous-run data and preserve lead-time information.

Recommended lead bands:

- 0–24 h;
- 24–72 h;
- 3–7 d;
- 7–14 d.

Percentiles should use the matching lead regime where enough history exists; otherwise use a documented fallback with a reduced-reference-quality flag.

---

# 10. Workstream G — UVI fusion v2

## 10.1 Remove hard-coded duplicate-vote semantics from the scientific claim

The current duplicated OM vote combined with ordinary `np.nanmedian` has non-obvious behavior; e.g. `[0,2,6,6]` produces 4, not an OM tie-break to 6.

Replace the headline fusion rather than trying to explain this as a principled weighted median.

## 10.2 Calibrate against independent observations

Use independent UVI/erythemal measurements where possible (WOUDC UVI/broadband/spectral datasets are acceptable sources).

Evaluate OM, CAMS, EPA, and candidate fusions on **the same common-case rows**.

Always report:

- common-case n;
- source-specific availability n;
- lead time;
- site/region;
- SZA;
- cloud regime;
- bias/MAE/RMSE.

Do not compare OM n=321 against CAMS n=147 and interpret the raw MAEs as a controlled head-to-head ranking.

## 10.3 Fusion model

Implement a robust bias-corrected fusion:

1. estimate source bias by lead/regime;
2. bias-correct each source;
3. estimate source error variance/MAE by lead/regime;
4. compute robust inverse-error weights or another validated robust estimator;
5. cap any single-source weight to prevent false certainty;
6. inflate uncertainty when source count drops;
7. expose source contributions/weights per row.

Required fields:

- `uvi_consensus`
- `uvi_source_values`
- `uvi_source_weights`
- `uvi_consensus_sources`
- `uvi_source_spread`
- `uvi_expected_abs_error`
- `uvi_prediction_interval_low/high`
- `fusion_version`

EPA integer rounding must be represented in its error model.

If insufficient independent data exists for a regime, fall back to a clearly labeled heuristic and lower reliability; do not silently apply a global fixed weight.

---

# 11. Workstream H — make confidence mean reliability

Delete the current semantic coupling where sunny outcomes raise “confidence.”

## 11.1 Strong-sun probability

Keep ensemble probability of useful sun as a separate product quantity:

`strong_sun_probability_0_100`

It may use DNI/GHI/cloud/precip thresholds, but it must not be called confidence.

## 11.2 Error model

Train historical error models for key predicted channels using available verification:

- UVI;
- GHI/DNI where observed/retrospective truth exists;
- delayed-pigmentation irradiance where measured spectral validation exists;
- optionally UVA/UVB.

Predict expected absolute/relative error from:

- lead time;
- ensemble spread;
- deterministic spread;
- source count;
- source age/freshness;
- feature coverage;
- SZA;
- cloud regime;
- aerosol/ozone availability;
- backend tier;
- native versus interpolated sub-hour source.

## 11.3 Reliability score

If retaining `tan_forecast_confidence_0_100`, define it from calibrated expected error, e.g. a monotonic transform of the error distribution. Its exact mapping must be versioned and tested for calibration.

A confidence bin should have empirical meaning. At minimum, higher bins must show monotonically lower realized error on holdout data.

Do not multiply physical irradiance by confidence. Confidence affects ranking only as a tie-break or optional conservative lower-bound mode.

## 11.4 Feature coverage

Compute coverage from the **actual bundle/backend manifest feature list after mapping**. Remove hand-written names that do not match model features.

Expose:

- `model_feature_coverage_fraction`
- `spectral_feature_coverage_fraction`
- `source_coverage_fraction`

Only let coverage change uncertainty if historical calibration demonstrates that relationship.

---

# 12. Workstream I — surface/material selection (new required feature)

The user must be able to change the surface they are on. This must be a physically separate local-exposure input, not an overwrite of CAMS grid-cell albedo.

## 12.1 Critical distinction

Maintain two different concepts:

1. **regional/background surface albedo** — relevant to atmospheric radiative transfer and multiple scattering over a broad area; comes from RT inputs/CAMS/land-surface context;
2. **local user surface reflectance** — grass/sand/concrete/snow/water immediately around the user, relevant to ground-reflected exposure onto the body/skin plane.

Never overwrite one with the other.

Fields should reflect this:

- `regional_surface_albedo_*`
- `local_surface_material`
- `local_surface_uv_reflectance_*`
- `surface_extent_mode`

## 12.2 New module/data

Add:

- `src/sunstack/surface.py`
- `data/research/surfaces/surface_materials.yaml`
- optional spectral CSVs under `data/research/surfaces/spectra/`

Define immutable dataclasses/types for a surface profile.

Each preset contains:

- stable slug;
- display name;
- optical model (`lambertian`, `water_fresnel`, etc.);
- UVA reflectance/albedo estimate or spectral curve;
- UVB reflectance/albedo estimate or spectral curve;
- wavelength domain;
- uncertainty/range;
- source citation;
- state descriptors (dry/wet/fresh/aged);
- spectral-quality tier (`measured_spectral`, `measured_broadband`, `literature_range`, `custom`);
- whether the value is appropriate only for local reflection or also for broad RT background.

## 12.3 Required presets

At minimum:

- `unknown`
- `grass_summer`
- `grass_winter`
- `dry_beach_sand`
- `wet_beach_sand`
- `light_concrete`
- `aged_concrete`
- `fresh_asphalt`
- `aged_asphalt`
- `weathered_wood_deck`
- `open_water`
- `sea_foam`
- `fresh_snow`
- `aged_snow`
- `custom`

Use literature values/ranges rather than inventing exact precision. Useful UVB reference ranges from IARC/WHO literature include summer lawn grass roughly 2.0–3.7%, dry light beach sand 15–18%, wet sand about 7%, light concrete 10–12%, fresh asphalt about 4–5%, open-water diffuse measurements around a few percent with important specular geometry, sea foam roughly 25–30%, and fresh snow potentially very high. These are starting data with provenance, not universal constants.

## 12.4 Water is not a flat Lambertian constant

Implement a water-specific optical model if `open_water` is selected:

- Fresnel/specular reflection based on incidence angle;
- configurable/estimated surface roughness/wind effect if feasible;
- diffuse/background component separately.

If the full model is not available for a condition, downgrade to a documented broadband approximation and mark `surface_model_quality` accordingly.

## 12.5 Snow state

Fresh and aged snow must be distinct. If weather data provide snow depth/age context, allow auto-suggesting a snow profile, but never silently override an explicit user choice.

## 12.6 Surface extent

Add:

`surface_extent_mode = local | broad`

Default: `local`.

- `local`: selected material changes near-field ground-reflected skin-plane exposure only.
- `broad`: selected surface may also feed the Tier-B RT surface boundary condition because the user declares that the surrounding area is broadly homogeneous (beach, snowfield, large water body, etc.).

Do not infer `broad` from the material alone.

## 12.7 API/CLI/UI

Add consistent parameters:

CLI:

- `--exposure-basis environmental_horizontal|skin_plane`
- `--surface grass_summer`
- `--surface-extent local|broad`
- `--skin-tilt-deg` / `--skin-azimuth-deg` or `--posture` preset
- custom mode options: `--surface-uva-reflectance`, `--surface-uvb-reflectance`

API query:

- `exposure_basis`
- `surface`
- `surface_extent`
- `skin_tilt_deg` / `skin_azimuth_deg` or posture preset
- optional custom reflectances

Static UI:

- visible “Surface” selector;
- grouped presets;
- explanation of local reflection versus regional atmosphere;
- persist the selection in browser local storage only unless the user explicitly exports it;
- changing surface must immediately update the relevant skin-plane exposure context in live mode; for static export, precompute variants or provide a mathematically identical client-side local-reflection recomputation using serialized direct/diffuse spectral/channel components.

Never pretend a static client can rerun Tier-B atmospheric RT if it cannot. Broad-mode changes requiring backend RT should be disabled/explained in pure static mode unless precomputed.

## 12.8 Surface output fields

At minimum:

- `surface_material_slug`
- `surface_display_name`
- `surface_extent_mode`
- `surface_model_quality`
- `surface_uva_reflectance`
- `surface_uvb_reflectance`
- `surface_reflectance_source`
- `surface_reflection_uncertainty`
- `skin_plane_ground_reflected_uva_wm2`
- `skin_plane_ground_reflected_uvb_wm2`
- `skin_plane_ground_reflected_delayed_pigmentation_wm2`

## 12.9 Surface tests

- grass produces less ground-reflected UV than dry sand under identical geometry;
- dry sand > wet sand for the literature preset;
- fresh snow strongly increases reflected component versus grass;
- local surface selection never changes horizontal environmental irradiance;
- `broad` surface can change RT output only through the spectral backend path;
- flat horizontal plane has zero local ground-view factor in the existing isotropic geometry, and the UI must not claim a ground-reflection boost in that exact geometry;
- tilted/reclined plane responds monotonically to reflectance for Lambertian surfaces;
- water reflection varies with geometry and is not forced monotonic like a Lambertian scalar.

## 12.10 Canonical preset defaults and uncertainty

Do not leave preset numeric choices to agent discretion. For v1, use the following **UVB/broadband-UV proxy defaults** when a more complete measured spectral profile is not available. The default is the midpoint of the cited IARC representative range; preserve the range as uncertainty metadata. These are not universal material constants.

| Surface slug | Proxy default | Literature range/state | Optical handling |
|---|---:|---|---|
| `grass_summer` | 0.0285 | 0.020–0.037 UVB | Lambertian proxy |
| `grass_winter` | 0.0400 | 0.030–0.050 UVB | Lambertian proxy |
| `dry_beach_sand` | 0.1650 | 0.150–0.180 UVB | Lambertian proxy |
| `wet_beach_sand` | 0.0710 | representative measured value | Lambertian proxy |
| `light_concrete` | 0.1100 | 0.100–0.120 UVB | Lambertian proxy |
| `aged_concrete` | 0.0760 | 0.070–0.082 UVB | Lambertian proxy |
| `fresh_asphalt` | 0.0455 | 0.041–0.050 UVB | Lambertian proxy |
| `aged_asphalt` | 0.0695 | 0.050–0.089 UVB | Lambertian proxy |
| `weathered_wood_deck` | 0.0640 | representative measured value | Lambertian proxy |
| `open_water` | 0.0330 diffuse baseline | geometry-dependent; specular can be much higher | water Fresnel model; scalar only as degraded baseline |
| `sea_foam` | 0.2750 | 0.25–0.30 UVB | Lambertian proxy |
| `fresh_snow` | 0.88 | representative UVB; literature commonly ~0.8–0.9 | spectral snow model preferred |
| `aged_snow` | 0.50 | representative two-day-old snow | spectral snow model preferred |

Rules:

1. A scalar above is **not** automatically copied into both UVA and UVB and called spectral truth.
2. If only the scalar proxy exists, set `surface_spectral_quality="broadband_uv_proxy"`, use it as a flat 280–400 nm degraded reflectance only when the caller allows degraded surface modeling, and propagate the literature range into surface-reflection uncertainty.
3. Strict Tier-B surface modeling should use a measured/validated spectral reflectance curve where available. A preset without adequate spectral data remains usable in degraded local-reflection mode but may not claim `measured_spectral`.
4. `unknown` means no asserted local-reflection correction; it does **not** silently fall back to 0.20.
5. CAMS `forecast_albedo` remains regional/background input and must never substitute for one of these local presets.

## 12.11 Surface selection and ranking behavior

- With `exposure_basis=environmental_horizontal`, changing `surface` must produce bit-identical primary radiation/dose/ranking outputs; only surface-context fields may differ.
- With `exposure_basis=skin_plane`, changing surface may change reflected component, plane E_DP, plane SED, fixed-window dose, and the resulting skin-plane ranking.
- Surface cannot change source UVI itself.
- A horizontal plane with zero ground-view factor cannot gain local reflected exposure under the isotropic geometry; the UI must explain why surface choice has little/no effect in that pose.
- For a reclined/vertical plane, high-reflectance surfaces must produce the expected reflected-component increase.

---

# 13. Workstream J — skin-plane and posture physics

## 13.1 Keep horizontal environment immutable

Environmental horizontal fields remain source/reference quantities. User geometry produces additional fields only.

## 13.2 Direct, diffuse, reflected components

Stop applying one broadband shortwave factor to an already effect-weighted UV quantity as if UV direct/diffuse spectral composition were identical to broadband solar radiation.

Tier-B path should produce or reconstruct spectral/direct/diffuse components. Compute skin-plane spectrum/channel by component:

- direct: incidence-cosine geometry;
- diffuse: selected sky model (at minimum isotropic; preferably Perez-like only if validated in UV);
- local reflected: surface optical model + ground-view geometry;
- regional multiple-scattering effect belongs in RT, not local reflection.

Then convolve the final plane spectrum with each biological action spectrum.

## 13.3 Geometry parameters

Keep tilt/azimuth but make them user-configurable consistently across CLI/API/UI.

Consider posture presets:

- lying flat face-up;
- reclined;
- seated;
- standing/front-facing;
- custom tilt/azimuth.

The current posture guidance can remain as guidance, but it must not be confused with a user-selected actual pose.

## 13.4 Terminology correction

Delete the unsupported blanket statement “sand reflects ~25% more UV than grass.” Surface reflection is material/state/wavelength/geometry dependent. Use the selected profile and show the actual modeled change for the current geometry.

---

# 14. Workstream K — outdoor feasibility and weather semantics

## 14.1 Missingness

Essential missing weather cannot equal perfect feasibility.

Define required fields per rule and output:

- `outdoor_feasibility_complete`
- `outdoor_feasibility_missing_fields`
- `outdoor_feasibility_reason_codes`

If an essential hard-block variable is unavailable and cannot be replaced by a valid equivalent, Overall/usable-window status is `UNKNOWN`, not 100.

## 14.2 Thunderstorm codes

Include WMO code 97 in thunderstorm hard blocks. Current `{95,96,99}` is incomplete.

Expected set for Open-Meteo WMO semantics:

`{95,96,97,99}`

## 14.3 Precipitation timing

Open-Meteo rain/showers/snowfall fields are preceding-interval sums. Rename rule semantics from “active rain at timestamp” to something interval-accurate unless using instantaneous weather code/radar evidence.

Recommended logic:

- instantaneous precipitating WMO code => current-condition hard block;
- preceding-interval rain/snow amount => block interval as having precipitation exposure, not claim exact instant;
- precipitation probability => future reliability/feasibility penalty, not biological physics.

## 14.4 Snow cover

Fetch/use `snow_depth` where provider/model availability permits. Existing falling-snow detection does not prove ground snow cover.

Surface and feasibility interact but remain conceptually distinct:

- selected `fresh_snow` surface raises reflected UV exposure;
- snow-covered ground may make “lie outside” usability false;
- these happen in separate layers.

## 14.5 Temperature

Keep hard absolute air-temperature policy if desired, but call it a product/user rule.

---

# 15. Workstream L — replace/demote `sun_adjusted_feels_like_f`

The current formula is an unvalidated heuristic and uses UVI for thermal radiant loading. It also multiplies attenuated UVI by `UVI/UVI_clear`, effectively applying UV transmission twice.

## Required path

Preferred: replace with a physically grounded solar-comfort calculation using broadband direct/diffuse radiation and human geometry.

A practical implementation may use a tested thermal-comfort library/model, but must expose exact assumptions:

- air temperature;
- humidity/dew point;
- wind;
- mean radiant temperature / absorbed shortwave;
- body/posture geometry;
- clothing level appropriate to selected user mode;
- resting metabolic rate (not zero metabolic heat).

If a validated model cannot be implemented immediately, rename the existing quantity to something like:

`sun_warming_heuristic_f`

and remove physical “feels-like” claims. It may not affect radiation ranking.

Fix documentation examples:

- dew point 75°F contributes +6°F under the old formula, not +9°F;
- 20 mph wind subtracts 6.4°F under the old formula.

No old example survives unless it is generated by a unit test from the implementation.

---

# 16. Workstream M — ranking and windows

## 16.1 Remove false “Absolute-first” claim

A weighted geometric mean with a cap is not lexicographic ordering. Do not claim it is.

## 16.2 Remove false scale-invariance claim

The current test that multiplies the dose input while holding `overall_tan_opportunity` fixed only proves that the dose column is not used by that function. It does not prove physical photon-scale invariance of the full pipeline. Clipping and fixed thresholds break scale invariance.

Rename/rewrite the test accordingly.

## 16.3 Fixed-duration physical ranking

Implement candidate windows from explicit intervals. For each 15/30/60-minute candidate:

- expected delayed-pigmentation dose;
- completeness/coverage;
- uncertainty interval;
- hard usability state;
- schedule availability;
- comfort score separately.

Primary `best_30m` selector:

1. require daylight and complete enough physical data;
2. exclude hard-blocked/unknown usability for the “usable” variant;
3. maximize expected `E_DP` dose;
4. if doses are effectively tied within a defined tolerance (e.g. <=1% or <= model uncertainty floor), prefer lower expected error/higher reliability;
5. then prefer comfort;
6. then deterministic earliest start for stability.

Do not add Local percentile to the physical objective.

## 16.4 Sustained window

If keeping a long contiguous “best sustained outdoor period,” name it accordingly and state its objective. It is not the maximum-dose fixed-duration window.

## 16.5 Daily fields

For every field containing `peak`, compute its own maximum.

Add separate fields for values at the selected best window/overall time:

- `day_absolute_peak_*`
- `day_absolute_at_best_usable_30m_*`
- `day_local_peak_*`
- `day_local_at_best_usable_30m_*`
- etc.

No ambiguous `*_at_peak` without naming which peak.

---

# 17. Workstream N — dose engine

## 17.1 Lone sample

Change one valid sample over a nonzero requested window from numeric zero to unknown:

`NaN, complete=False, coverage=0`

unless the requested interval itself truly has zero duration.

## 17.2 Partial dose

A partial integral may be emitted, but must be unmistakably labeled partial. Add fields such as:

- `*_dose_observed_j_m2`
- `*_dose_complete`
- `*_dose_coverage_fraction`

Do not call a partial observed integral an estimated full-window dose.

## 17.3 Interval-aware engine

Implement exact interval-mean integration from §5 and trapezoidal point integration only for true point samples.

## 17.4 SED source hierarchy

SED uses final `uvi_consensus` / final erythemal irradiance first. Raw OM UVI is allowed only in explicitly degraded mode with a field indicating the degraded source.

---

# 18. Workstream O — personal MMD and personalization

## 18.1 Reject ambiguous measured MMD

A measured MMD from another lamp/source cannot automatically be compared to SunStack delayed-pigmentation-effective J/m² unless the source spectrum and weighting basis are compatible.

Replace the current simple `(value, basis="MEASURED")` concept with a structured basis.

Accepted types should include:

- `SUNSTACK_EFFECTIVE_DOSE_MEASURED` — already expressed in this exact action-spectrum basis;
- `SOURCE_SPECTRUM_MEASURED` — value + source spectral irradiance/profile, convertible by SunStack;
- `OBJECTIVE_ESTIMATE` — documented model/measurement derivation;
- `COARSE_ESTIMATE` — disabled by default or wide uncertainty.

Generic `MEASURED` without compatibility metadata must fail validation.

## 18.2 Required metadata

For convertible measured values:

- source/lamp spectrum ID or uploaded curve;
- exposure geometry;
- endpoint definition;
- action-spectrum normalization if already weighted;
- body site if relevant;
- measurement date/protocol;
- uncertainty.

## 18.3 Output meaning

Personal MMD fraction is context only. It must not be phrased as safe exposure allowance or recommendation.

## 18.4 Fitzpatrick

Keep qualitative only; do not multiply environmental radiation. Objective pigmentation data can inform future response modeling, not environmental photons.

---

# 19. Workstream P — global and local references

## 19.1 Global reference

Do not call a two-site percentile “global.”

Build a reproducible corpus behind `global-mel-ref-v2`.

Required design:

- broad latitude coverage including equatorial/tropical/subtropical/mid/high latitude;
- low and high altitude;
- high-UV high-altitude cases;
- representative aerosol/ozone regimes;
- bright surfaces such as snow/sand;
- full seasonal/daylight sampling;
- strict manifest with locations, periods, inputs, model versions, hashes.

The normalization reference remains a product scale. Record the exact policy, e.g. empirical p99.9 plus an explicit fixed headroom rule. Do not describe headroom as proving coverage of all natural extremes.

## 19.2 Raw physics remains primary

The raw `E_DP` and fixed-duration dose are primary. The 0–100 score is a presentation normalization and may clip; users/validators must still be able to distinguish values above the reference via raw irradiance.

## 19.3 Local reference

Build from serving-domain hindcasts using the same backend/version and lead-time regime.

## 19.4 Geometry-conditioned transmission

Prefer percentiling a transmission ratio against matching geometry instead of percentiling raw Absolute and calling it atmosphere. Preserve fallback labels when clear-sky counterpart is unavailable.

---

# 20. Workstream Q — model/reference manifests and provenance

Strict mode must fail closed on stale/unverifiable artifacts.

## 20.1 Model bundle manifest required

Rebuild current model bundles. Manifest fields must include:

- schema version;
- model version;
- backend version;
- exact feature names/order/types/units;
- training start/end;
- training site/data sources;
- training row counts;
- target definitions;
- temporal-semantics version;
- code git SHA;
- hash of relevant training source code or full build tree fingerprint;
- dependency versions;
- training-data manifest hash;
- metrics by split/regime;
- random seed;
- creation timestamp.

Strict loader must reject a bundle with missing manifest.

## 20.2 Verify—not merely record—hashes

If a training-code hash is part of the contract, compare it against the expected compatible code/version on load. A recorded unused SHA is not an enforcement mechanism.

## 20.3 Local reference manifest

Strict gate must require all of:

- score model version;
- action spectrum version/hash;
- spectral backend version;
- temporal semantics version;
- global reference version/value;
- reference build code hash;
- source/hindcast manifest hash.

Missing metadata is stale, not backward-compatible “okay,” in strict v5.

---

# 21. Workstream R — validation methodology

## 21.1 Rename “literature gates”

Rename `scripts/check_literature.py` outputs to **literature-informed regression invariants** unless a test actually reproduces an independent published numeric result.

The fact that an additive function adds is not independent validation of Keong.

## 21.2 Add independent literature/source checks

Where public numerical source tables exist, test exact externally sourced values:

- selected delayed-pigmentation action-spectrum wavelengths;
- UVI conversion;
- SED conversion;
- provider temporal semantics registry against pinned expected metadata;
- surface preset ranges/provenance sanity.

## 21.3 Payerne

Preserve any external station validation dataset, extraction script, response curve, and exact matching logic needed to reproduce the result. Until then, replace “root-caused” with “plausibly explained by instrument/definition mismatch; unresolved as independent absolute validation.”

## 21.4 Measurement hierarchy

Documentation must distinguish:

- same-product emulation;
- NWP/hindcast verification;
- independent broadband ground observations;
- independent spectral ground observations;
- biological outcome studies.

Do not collapse these into one “validation” number.

---

# 22. Workstream S — final publication validator

Create a single script/module that validates the serialized product itself, e.g.:

`scripts/validate_published_artifact.py`

It must read `data.json`/CSV outputs as consumers see them and independently recompute invariants.

Required fatal checks:

1. schema/version fields present;
2. action spectrum checksum/version matches metadata;
3. model/reference manifests compatible;
4. unique UVI source count valid;
5. UVI consensus lies within source range where applicable;
6. `E_ery = UVI/40`;
7. SED independently recomputes from final erythemal series with interval semantics;
8. delayed-pigmentation dose independently recomputes;
9. no finite night UV/exposure beyond numeric tolerance unless explicitly twilight definition says otherwise;
10. all `peak` fields equal actual maxima;
11. all `at_best_*` fields come from the selected interval/time;
12. feasibility missingness cannot serialize as 100 complete;
13. confidence/reliability fields match the calibrated model output contract;
14. source counts are integers and <= known provider count;
15. surface selection never mutates horizontal environment in local mode;
16. static Fit denominator equals daylight eligible denominator;
17. no deprecated v4 column is used as a v5 ranking key;
18. every row’s version/provenance agrees with summary versions;
19. no stale local reference accepted in strict output;
20. no pre-manifest model accepted in strict output.

`validation_issues=[]` may only be emitted after this serialized check passes.

---

# 23. Workstream T — API, CLI, static export, and UI

## 23.1 API contract

Update `GET /api/data`, `/api/refresh`, calendar endpoints, and root UI parameters to support:

- `surface`
- `surface_extent`
- user skin plane/posture parameters if exposed
- revised MMD structured fields
- duration/ranking mode if applicable

Invalid slugs/values return 400 with allowed options.

## 23.2 Output schema

Add `schema_version`. Publish a machine-readable schema under `docs/schema/` or package data.

Maintain one-version deprecated aliases with explicit `deprecated_fields` metadata.

## 23.3 UI information hierarchy

Top of page should answer:

- strongest physical 30m stimulus;
- best usable 30m window;
- confidence/expected error;
- surface selected;
- current backend tier.

Then show:

- raw E_DP/intensity;
- local context;
- transmission context;
- UVI/SED;
- comfort/usability;
- surface + posture effect;
- provenance.

Do not make legacy Overall the hero.

## 23.4 Surface control

Visible selector with brief plain-English effect. Changing from grass -> dry sand should change local reflected/skin-plane exposure where geometry permits, without changing horizontal environmental E_DP.

## 23.5 Static export

Current static export clips rows to wall-clock 7–20. Replace with astronomy/daylight-derived filtering plus a small configurable margin if needed for UI context. The “Fit” denominator must use the exact daylight mask described by its tooltip.

## 23.6 Calendar

Calendar event summary should include the physically ranked fixed-duration window and state whether it is strongest versus best usable. Do not imply a safety recommendation.

## 23.7 Documentation drift

The current `README.md` says Overall weights are 60/15/10/15 while `config.py` uses 70/15/5/10. Eliminate this failure class.

Create a semantics export (e.g. `score_semantics()` or generated JSON) from code constants and test docs/examples against it. At minimum, CI must fail when documented weights/version IDs/default thresholds disagree with executable constants.

---

# 24. Workstream U — test and release contract

All existing useful tests remain. Add the following. Names are suggestions; behavior is mandatory.

## 24.1 Photobiology/source tests

- `test_delayed_pigmentation_spectrum_authoritative_anchors`
- `test_action_spectrum_normalization_at_reference_wavelength`
- `test_band_boundary_energy_conservation`
- `test_fixed_band_proxy_is_labeled_degraded`
- `test_tier_b_manifest_required_for_tier_b_label`

## 24.2 Temporal tests

- `test_power_hourly_start_anchor_maps_to_midpoint`
- `test_openmeteo_backward_mean_maps_to_midpoint`
- `test_training_intervals_align_not_raw_timestamps`
- `test_interval_mean_dose_is_rectangular_exact`
- `test_point_sample_dose_is_trapezoidal`
- `test_clearness_denominator_matches_temporal_support`
- `test_cams_accumulation_never_differences_across_cycles`
- `test_cams_first_interval_is_unknown_or_explicitly_imputed`

## 24.3 Final-state tests

- `test_final_halfhour_erythemal_matches_final_consensus`
- `test_final_sed_reintegrates_from_final_consensus`
- `test_unique_uvi_source_count_not_vote_count`
- `test_final_confidence_uses_final_state`
- `test_all_peak_fields_are_true_peaks`

## 24.4 Feasibility tests

- `test_missing_required_weather_is_unknown_not_perfect`
- `test_wmo_97_hard_blocks`
- `test_precip_sum_is_interval_semantic_not_instant_claim`
- `test_snow_depth_can_block_existing_ground_snow`

## 24.5 Surface tests

All tests in §12.9 plus:

- preset schema/provenance completeness;
- custom reflectance bounds `[0,1]`;
- changing local surface never changes source UVI or horizontal E_DP;
- broad surface is disallowed without a backend capable of recomputing RT or is clearly degraded/precomputed.

## 24.6 Confidence/fusion tests

- confidence does not increase merely because identical-confidence forecast changes from overcast to sunny;
- stronger ensemble dispersion increases expected error / lowers reliability all else equal;
- common-case UVI evaluator uses identical row set across candidates;
- source weight contributions sum to 1 over available sources;
- lone source widens uncertainty.

## 24.7 Ranking tests

- lower Local percentile cannot make weaker fixed-duration physical dose win;
- fixed 30m rank equals independent interval integration;
- hard-blocked strongest physical window is excluded from `best_usable_30m` but retained as `strongest_30m`;
- confidence only breaks defined ties, not arbitrarily rescales photons;
- old “x10 dose while Overall frozen” test is deleted/replaced.

## 24.8 Provenance tests

- strict loader rejects old no-manifest bundle;
- code/data hash mismatch fails strict;
- stale local reference fails strict;
- summary/row versions must agree.

## 24.9 Artifact tests

Generate a complete fixture artifact, serialize JSON/CSV/ICS, reload it, and run the same validator used before publish.

## 24.10 Property testing

Use Hypothesis where appropriate:

- nonnegative irradiance -> nonnegative doses;
- increasing local Lambertian reflectance cannot reduce reflected component for fixed geometry;
- final fusion always within min/max of finite source values for convex fusion;
- missing inputs never become finite “perfect” metrics without explicit fallback;
- raw horizontal environment invariant under personal skin type;
- local-surface mode invariant for horizontal environmental quantities.

---

# 25. CI/workflow changes

## 25.1 Core CI

Add/extend a science correctness workflow that runs for changes touching:

- `src/sunstack/**`
- `data/research/**`
- calibration/reference scripts
- `docs/SCIENCE.md`
- validation scripts

It runs:

```bash
uv sync --locked
uv run ruff check src tests scripts
uv run pytest tests/ -q
uv run basedpyright
uv run python scripts/check_literature.py   # renamed output semantics
uv run python scripts/validate_published_artifact.py <fixture/current rebuilt artifact>
```

Add the repository’s existing deeper quality checks where runtime permits.

## 25.2 Scheduled publish

`forecast-run` must validate the final serialized artifact before any commit/publish step. Fatal science-contract failures abort publication.

## 25.3 Reskin

Renderer-only refresh may never mutate forecast/science identity. Preserve the existing good forecast-vs-renderer SHA separation.

If a UI change changes interpretation text but not forecast values, renderer version changes only.

---

# 26. Documentation rewrite requirements

Update all major docs after code stabilizes.

## README

Must no longer open with “actual melanogenic radiation” as if directly measured/validated. Preferred framing:

> SunStack estimates spectrally weighted delayed-pigmentation exposure from forecast atmospheric conditions, reports independent erythemal exposure, and separately evaluates outdoor usability. Strict mode uses a validated spectral backend; degraded mode is explicitly labeled.

## SCIENCE.md

Must include:

- exact temporal support;
- endpoint terminology;
- measured-versus-modeled validation hierarchy;
- surface model;
- user surface local vs regional distinction;
- ranking objective;
- confidence calibration;
- limitations.

## PHOTOBIOLOGY_MODEL.md

State clearly:

- action spectrum endpoint/population/protocol;
- Keong supports additivity under tested conditions, not universal response linearity;
- Wolber/repeated exposure belongs in future response model;
- TanDose is exposure, not predicted tan color.

## SPECTRAL_MODEL.md

Document real Tier-B gates and degraded Tier-C proxy.

## TANDOSE.md

Document interval-mean versus point-sample integration.

## RESEARCH_NOTES.md

Append migration evidence; do not rewrite historical entries to hide prior claims.

---

# 27. Exact known defects that must be closed

The agent must explicitly close each item below in the final PR/commit summary.

1. wrong provisional Parrish UVB/UVA curve;
2. fixed-band proxy not validated against true spectral convolution;
3. final 30-minute UVI/erythemal/SED state mismatch;
4. source count counts weighted votes;
5. confidence rewards sunny outcomes;
6. atmospheric feature coverage names do not match actual feature schema;
7. feature coverage does not actually affect confidence despite docs;
8. checked-in model bundles lack manifests;
9. training-code hash is recorded but not robustly enforced;
10. missing weather can become 100 feasibility;
11. daily `*_peak` fields are values at another metric’s peak;
12. global reference corpus not reproducibly present;
13. literature checks overstate independent validation;
14. UVI fusion comparisons use differing sample populations and shared-provider reference;
15. POWER holdout presented too easily as physical accuracy rather than product emulation;
16. local reference domain differs from serving domain;
17. Payerne +42% attribution overclaimed/unreproducible;
18. final publication gate misses cross-channel invariants;
19. UVB boundary integration mismatch;
20. UVI-based sun-feels heuristic/double attenuation;
21. broadband shortwave skin-plane factor applied to UV biology;
22. SED fallback prefers raw OM instead of final consensus;
23. CAMS first accumulated interval semantics not day/availability correct;
24. HRRR baseline snapshot should copy explicitly and assert non-unity response;
25. UI Fit denominator includes non-daylight export rows;
26. duplicate unreachable spectral-tier code;
27. strict local-reference gate tolerates missing legacy metadata;
28. POWER start-of-hour vs Open-Meteo preceding-hour temporal mismatch;
29. interval-mean radiation treated downstream like point samples;
30. terminology conflates clearness and clear-sky index;
31. fixed TOA solar constant called exact despite Earth-Sun variation;
32. docs say temperature is absent from physics while ML uses temperature/RH predictors;
33. “Atmosphere isolates air” is stronger than the metric proves;
34. “Absolute-first ranking” is false for current weighted composite;
35. photon-scale-invariance test does not test the full physics/ranking claim;
36. OM duplicated-median tie behavior does not equal documented OM tie-break;
37. lone valid sample returns numeric zero dose instead of unknown;
38. WMO 97 omitted from thunder hard-block list;
39. preceding-hour rain amounts described as exact active rain at a timestamp;
40. snow-cover behavior claimed without snow-depth/cover input;
41. unvalidated fallback incorrectly named Tier B;
42. numerical IPD/TanDose ratio given biological meaning despite different normalizations;
43. generic measured MMD lacks spectral/basis compatibility;
44. default/local surface reflection conflated with CAMS/generic broadband albedo;
45. README Overall weights are stale (60/15/10/15 vs code 70/15/5/10);
46. “sand 25% more than grass” claim unsupported and incompatible with default zero ground-view factor for a horizontal plane;
47. “zero metabolic heat” wording physically wrong;
48. dew-point/wind examples arithmetically wrong;
49. “HRRR truth” wording wrong—forecast is not observation;
50. no user-selectable local surface/material despite surface reflection mattering to plane exposure.

A final handoff that does not enumerate these as fixed/replaced/deprecated with evidence is incomplete.

---

# 28. Data model / schema additions

At minimum the v5 hourly/half-hour schema should support these fields (not every row requires every optional field):

## Temporal

- `interval_start_utc`
- `interval_end_utc`
- `interval_midpoint_utc`
- `radiation_support_type`
- `temporal_semantics_version`

## Delayed pigmentation

- `delayed_pigmentation_effective_irradiance_horizontal_wm2`
- `skin_plane_delayed_pigmentation_effective_irradiance_wm2` when configured
- `delayed_pigmentation_clear_sky_horizontal_wm2`
- `delayed_pigmentation_transmission_ratio`
- `tan_intensity_reference_0_100` or retained renamed score
- `action_spectrum_version`
- `action_spectrum_sha256`

## Spectral/backend

- `spectral_backend`
- `spectral_tier`
- `spectral_model_quality`
- `spectral_expected_error`
- direct/diffuse UVA/UVB where available

## UVI

- `uvi_consensus`
- `uvi_consensus_sources`
- `uvi_source_spread`
- `uvi_source_weights`
- `uvi_expected_abs_error`
- `uvi_interval_low/high`
- `fusion_version`

## Reliability

- `strong_sun_probability_0_100`
- `forecast_expected_relative_error`
- `tan_forecast_confidence_0_100`
- `confidence_version`
- `model_feature_coverage_fraction`
- `spectral_feature_coverage_fraction`

## Surface/plane

- all fields from §12.8
- `skin_plane_delayed_pigmentation_effective_irradiance_wm2`
- `skin_plane_erythemal_irradiance_wm2`
- direct/diffuse/reflected components
- user geometry/posture IDs

## Usability

- `outdoor_feasibility_0_100`
- `outdoor_feasibility_complete`
- `outdoor_feasibility_reason_codes`
- `comfort_model_version`
- physically named comfort outputs

## Ranking/dose

- 15m/30m/1h delayed-pigmentation doses and completeness;
- strongest/best-usable fixed-duration windows;
- uncertainty for window dose;
- versioned ranking objective.

---

# 29. Recommended file-level implementation map

This is guidance, not permission to leave related logic scattered.

### `src/sunstack/config.py`

- new v5 version constants;
- remove stale semantic comments;
- surface defaults/allowed modes;
- no duplicated doc-only constants.

### `src/sunstack/temporal.py` (new)

- temporal support registry;
- interval conversion/alignment;
- interval mean/instant utilities.

### `src/sunstack/surface.py` (new)

- surface presets/provenance;
- local reflection models;
- water special case;
- custom validation.

### `src/sunstack/photobiology.py`

- corrected action spectrum/version;
- endpoint naming;
- one-sample unknown;
- point versus interval dose primitives.

### `src/sunstack/spectral.py`

- Tier-B emulator loader/manifest;
- Tier-C degraded proxy;
- direct/diffuse spectral plane transform;
- regional versus local surface semantics.

### `src/sunstack/history.py`

- interval metadata;
- POWER midpoint conversion;
- independent validation ingestion where appropriate;
- snow depth where source APIs support it.

### `src/sunstack/calibrate.py`

- interval-aligned training;
- mandatory manifests;
- serving-domain local references;
- calibrated confidence/error training.

### `src/sunstack/tanscore.py`

- reduce responsibility; no duplicated derived-state logic;
- v2 UVI fusion hooks;
- feature coverage from actual model manifest.

### `src/sunstack/state.py` (new recommended)

- single final dependency DAG.

### `src/sunstack/opportunity.py`

- feasibility only + ranking orchestration;
- WMO97/snow-depth/missingness;
- remove scientific ranking from legacy Overall.

### `src/sunstack/doses.py`

- interval-aware dose engine;
- final consensus only for SED;
- coverage/partial naming.

### `src/sunstack/derive.py`

- separate strong-sun probability from confidence;
- clear-sky vs clearness terminology.

### `src/sunstack/validation.py`

- runtime gates plus shared invariant helpers.

### `scripts/validate_published_artifact.py` (new)

- independent serialization-level release gate.

### `scripts/build_spectral_corpus.py`

- fully reproducible libRadtran corpus.

### `scripts/verify_uvi.py`

- common-case evaluation and independent observations.

### `scripts/check_literature.py`

- regression-invariant naming; external numeric checks where possible.

### `src/sunstack/ui.py` / `output.py`

- v5 ranking/UI;
- surface selector;
- daylight denominator;
- schema/version display;
- exact semantics.

---

# 30. Definition of done

The work is complete only when **all** of the following are true:

1. v5 output uses the corrected versioned delayed-pigmentation action spectrum.
2. Strict production uses a validated Tier-B spectral backend; if Tier B cannot meet gates, strict publish fails and the broadband proxy is only available in explicit degraded mode.
3. Training and serving radiation intervals are aligned under a documented interval contract.
4. Dose integration respects interval means versus point samples.
5. Final half-hour UVI, erythemal irradiance, SED, spectral channels, confidence, and source counts are one coherent state.
6. User can change local surface/material and see a physically appropriate effect on skin-plane/reflected exposure without mutating horizontal environmental radiation.
7. Regional and local surface albedo are separate concepts.
8. Open water is not treated as a generic Lambertian constant without a degraded label.
9. WMO 97 and snow cover are handled.
10. Missing feasibility inputs cannot become perfect conditions.
11. The primary ranking is fixed-duration physical delayed-pigmentation dose, not Local/Atmo/confidence geometric blending.
12. Every field called `peak` is a true peak.
13. Confidence is calibrated to predictive reliability/error and sunniness is a separate probability.
14. UVI fusion is evaluated on common independent cases and exposes source weights/uncertainty.
15. Model/reference manifests are mandatory and enforced in strict mode.
16. Local references are serving-domain/lead-aware.
17. Global reference v2 is reproducibly backed by its claimed corpus.
18. Personal MMD cannot be used without compatible dose basis metadata.
19. Literature checks are named honestly and independent validation artifacts are reproducible.
20. The published serialized artifact passes the independent artifact validator.
21. README/docs/version text agree with executable constants; no stale 60/15/10/15-style drift remains.
22. Static UI Fit and every tooltip match the actual calculation.
23. All tests/linters/type checks pass under `uv sync --locked`.
24. Scheduled CI refuses to publish on a science-contract failure.
25. There are no TODOs/stubs/dead duplicate code introduced for this work.
26. The final implementation summary maps all 50 known defects in §27 to evidence of closure.

---

# 31. Research/source anchors that should be preserved in the implementation notes

These are evidence anchors, not permission to hard-code a claim without checking the exact source text/version used during implementation.

- NASA POWER Hourly API / time semantics: https://power.larc.nasa.gov/docs/services/api/temporal/hourly/
- NASA POWER FAQ noting hourly timestamp represents start of hour: https://power.larc.nasa.gov/docs/faqs/other/
- Open-Meteo radiation semantics, preceding-hour means versus `_instant`: https://open-meteo.com/en/docs/
- Open-Meteo/WMO weather codes including 97 on model/historical pages: https://open-meteo.com/en/docs/historical-weather-api
- FDA Form 3630 Parrish-derived melanogenic action spectrum: https://www.fda.gov/media/72567/download
- WHO UV surface reflection overview: https://www.who.int/news-room/questions-and-answers/item/radiation-ultraviolet-(uv)
- IARC/NCBI terrain UV reflectance table: https://www.ncbi.nlm.nih.gov/books/NBK401584/
- WOUDC spectral UV datasets: https://www.woudc.org/en/data/data-search-and-download/?dataset=spectral
- WOUDC data access/API: https://woudc.org/en/data/data-access/
- QASUME reference spectroradiometer literature for measurement quality context: PMID 16149356
- UV albedo review: PMID 30018236

The repo should eventually pin downloaded research inputs by checksum/metadata, not rely on live web pages at runtime.

---

# 32. Final agent handoff format

When the coding agent finishes, its response/PR body must contain exactly these evidence categories:

## A. Semantic/version changes

List every new v5 version ID and why it changed.

## B. Known-defect closure matrix

A 50-row table corresponding to §27:

`ID | defect | changed files | test/evidence | status`

Every row must be `FIXED`, `REPLACED BY NEW MODEL`, or—only where physically impossible with available evidence—`STRICTLY DISABLED`. No `DEFERRED`.

## C. Science validation results

- action-spectrum anchor check;
- Tier-B held-out corpus metrics;
- independent measured spectral metrics;
- UVI common-case metrics;
- local/global reference corpus manifests;
- confidence calibration results.

## D. Runtime/artifact validation

- full test suite result;
- artifact validator result;
- generated `docs/data.json` invariant result;
- one example showing final `UVI -> E_ery -> SED` closure;
- one example showing surface grass -> dry sand changes only local skin-plane reflection, not horizontal environment;
- one example showing missing weather becomes unknown rather than perfect feasibility.

## E. UI verification

Screenshots or equivalent evidence for:

- desktop;
- narrow/mobile;
- surface selector;
- strongest vs best usable window;
- provenance/backend tier;
- unknown/degraded state.

## F. Cleanliness

- no new TODO/FIXME;
- no stale legacy labels used as v5 truth;
- no uncommitted generated drift;
- `git status` clean.

Only after all six categories are complete should the implementation be called finished.
