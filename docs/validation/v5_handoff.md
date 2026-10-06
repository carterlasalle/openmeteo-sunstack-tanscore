# SunStack v5 — implementation handoff (§32 A–F)

Evidence for the mandatory completion contract, in the required six categories.
Every number below is reproducible from the repo with the command named beside
it; nothing here is asserted from memory.

---

## A. Semantic/version changes

Every v5 identity, and what forced the change. Read from the live artifact with
`uv run python -c "import json;print(json.load(open('docs/data.json'))['summary'])"`.

| Version ID | Value | Why it changed |
|---|---|---|
| `schema_version` | `sunstack-output-v5` | v4 columns carried mixed semantics; v5 rows state which contract they satisfy. |
| `temporal_semantics_version` | `interval-contract-v1` | POWER hourly stamps are interval *starts*, Open-Meteo hourly are *preceding-hour means*; v4 merged them by raw timestamp. |
| `photobiology_model_version` | `delayed-pigmentation-v2` | v4's provisional curve was not a faithful Parrish reconstruction, especially 280–305 nm. |
| `tan_score_model_version` | `action-spectrum-v2` | Score moved onto the corrected action spectrum. |
| `action_spectrum_version` | `parrish-fda-3630-v1` | 1-nm FDA Form 3630 Appendix B table with full provenance metadata. |
| `spectral_backend` (strict, reserved) | `tierB-libradtran-emulator-v1` | Reserved for a gate-passing emulator; see §C. |
| `spectral_degraded_backend` | `tierC-broadband-proxy-v2` | The shipped path: fixed-band proxy, explicitly labelled degraded. |
| `surface_model_version` | `uv-surface-v1` | New local surface/material model separate from regional albedo. |
| `fusion_version` | `calibrated-uvi-fusion-v2` | Replaced the duplicated-OM-median trick with bias-corrected inverse-error weights. |
| `confidence_version` | `calibrated-error-v1` | Confidence now means reliability, not sunniness. |
| `window_rank_version` | `fixed-duration-dose-v2` | Ranking is fixed-duration delayed-pigmentation dose, not a geometric composite. |
| `global_reference_version` | `global-mel-ref-v2` | 12-site POWER 2024 corpus replaces the two-site provisional estimate. |

Old v4 committed artifacts were left in place as historical evidence.

---

## B. Known-defect closure matrix

`docs/validation/defect_closure_matrix.md` — all 50 §27 defects in the required
`ID | defect | changed files | test/evidence | status` form. No `DEFERRED` rows.
The original evidence-only matrix, plus the Oct-5 and Oct-6 migration addenda,
stays in `docs/RESEARCH_NOTES.md`.

---

## C. Science validation results

### Action-spectrum anchors
`parrish_fda_3630-v1` 1-nm table, checksum + digitisation provenance in
`data/research/action_spectra/parrish_fda_3630.meta.json`; pinned by
`tests/test_photobiology.py::test_delayed_pigmentation_spectrum_authoritative_anchors`
and the band-boundary energy test (`test_band_boundary_energy_conservation`).

### Tier-B held-out corpus metrics (§8.4) — NOT PASSING, so not shipped
Deterministic libRadtran 2.0.6 corpus, 1-nm disort 6-stream spectra, 80/20
held-out split. Gate requirements: E_DP median ≤3 %, p95 ≤10 %; erythemal
median ≤3 %, p95 ≤10 %; UVA/UVB energy ≤2 % median, ≤5 % p95; no regime bin
with median bias >7 %.

| corpus | winner | E_DP median | E_DP p95 | UVA median | worst-regime bias | gates |
|---|---:|---:|---:|---:|---:|---|
| 2 000 samples (PCA(8) + ridge, raw channels) | A_pca | 0.645 | 6.62 | 0.517 | −0.476 | FAIL |
| 2 000 samples (PCA(20) + GBM, log10 channels) | B_direct | 0.0545 | 0.239 | 0.0288 | −0.122 | FAIL |
| 6 000 samples (same architecture) | B_direct | 0.0419 | 0.235 | 0.0221 | −0.226 | FAIL |
| 16 000 samples (same architecture, corrected split) | B_direct | **0.0286** | 0.135 | 0.0158 | **0.0756** | FAIL |

The E_DP median gate (≤3 %) and the erythemal median gate (≤3 %) now **pass**;
the tails do not (E_DP p95 0.135 vs ≤0.10; UVA p95 0.095 vs ≤0.05; UVB median
0.031 vs ≤0.02) and the worst-regime bias is marginally over (0.076 vs ≤0.07).
Overall the gates still fail, so strict Tier-B stays unavailable.

Evaluation note: the first version of the trainer sliced the held-out set
contiguously by sample id, while the stratified design lays its regime-enriched
blocks out in contiguous id ranges — so the test set was entirely composed of
regimes the model had never trained on and the reported error measured
extrapolation, not held-out accuracy. The split is now a fixed-seed shuffle, so
every regime appears in both halves and the numbers above are honest held-out
metrics. That is an evaluation fix, not a model improvement, and it is why the
2 000/6 000 rows above look worse than the artefacts an earlier revision
reported.

Reproduce: `uv run python scripts/build_spectral_corpus.py --samples 16000 --out data/research/spectral_corpus_v2`
→ `scripts/run_uvspec_corpus.py` (per-shard) → `scripts/merge_spectral_shards.py`
→ `scripts/train_spectral_emulator.py`.

Corpus of record: **16 000 samples, 0 failures**,
`merged_sha256 = a65b127ae0d0a8e9861240ef402c6aec2e3aef36b24c1154eaf7bf65f4f493dd`,
produced by `uvspec, version 2.0.6-MYSTIC`
(`sha256 = 604971d98039295b2be0156071a891aab7a6c80a17be6047e2da10f54f87f8ff`).
The merged manifest (per-shard hashes, design hash, uvspec identity) is tracked
at `data/research/spectral_corpus_v2/manifest.json`; the 105 MB `spectra.npz`
itself is not, and rebuilds deterministically from the manifest's seed.

Per contract §8.4, because the gates are not met the emulator is **not shipped
and not wireable**: no `emulator_manifest.json` is tracked,
`SUNSTACK_TIERB_MANIFEST` stays unset, and `validate_tierB_manifest` rejects any
manifest whose `gates_passed` is not true
(`tests/test_v5_tierb.py::test_tier_b_manifest_rejects_gate_failing_emulator`).
Strict runs therefore publish `tierC-broadband-proxy-v2` with its tier on every
row, which is the contract-prescribed outcome, not a defect.

### Independent measured spectral metrics (§8.5)
`docs/validation/woudc_spectral_validation.md` — **1878 measured Brewer scans**
from Toronto and Uccle (2023-01-01..2024-12-31), integrated against the shipped
action spectra. Reported: overall, clear/cloudy split, SZA bins, per-station,
seasonal subsets, and the release-target verdicts.

The measured set shows the Tier-C fixed-band proxy is biased by a median
**+219 %** (p95 +270 %), i.e. it overestimates the measured delayed-pigmentation
weighted irradiance roughly threefold. The §8.5 targets (median ≤15 %, clear
≤10 %) therefore **FAIL** for the proxy — which is exactly the evidence that
justifies keeping the proxy labelled degraded and refusing it a Tier-B claim.

### §7.2 dynamic band weights
`docs/validation/band_weight_diagnostics.md` — 1795 true uvspec spectra, dynamic
`w_band = Σ(E·S)/Σ(E)` versus the fixed band weights, stratified by SZA, ozone,
AOD, SSA, cloud, altitude and albedo. The fixed-band error is **not** secondary:
median +204 % (p05 +142 %, p95 +233 %), and `w_uvb` moves from 0.164 (SZA<40) to
0.081 (SZA>75).

### UVI common-case metrics
`docs/validation/uvi_verification.md` — 144 snapshots, 1-day-lead rows 333;
common-case (identical rows, n=147) OM MAE 0.13 bias +0.03, CAMS MAE 1.19 bias
−1.09, consensus MAE 0.62 bias −0.53.

### Local / global reference manifests
`data/calibration/global_melanogenic_reference_v2/reference.json` —
`global-mel-ref-v2`, 1.793 W/m², 12 sites, 52 033 daylight hours, per-site
SHA-256, p99.9 + 10 % fixed headroom policy. Local references rebuilt for both
sites (108 744 and 111 696 rows) and pinned by `local_reference_version.json`.

### Confidence calibration
`confidence_version = calibrated-error-v1`; monotonic error→reliability mapping
pinned by `tests/test_v5_confidence.py` (including
`test_confidence_does_not_reward_sunny_outcomes` and
`test_strong_sun_probability_separate_from_confidence`).

---

## D. Runtime / artifact validation

| Check | Command | Result |
|---|---|---|
| Test suite | `uv run pytest tests/ -q` | **295 passed** (1 pre-existing live-runner test excluded; it fails identically on a clean tree) |
| Lint | `uv run ruff check src tests scripts` | All checks passed |
| Types | `uv run basedpyright --level error` | 0 errors |
| Artifact validator | `uv run python scripts/validate_published_artifact.py docs/data.json` | `"passed": true` |
| Site artifact | `… docs/sites/pacific-palisades/data.json` | `"passed": true` |
| §28 row schema | emitted by `state.recompute_derived_state`, carried by the 30-min frame into `half_hour` | `action_spectrum_version`, `action_spectrum_sha256`, `outdoor_feasibility_reason_codes` — verified to survive `_daylight_payload_rows` → `_records` → JSON round-trip |

The published `docs/data.json` in the tree still carries `build_sha 43fa531`,
which predates §28. The first §28 publish exposed the real defect: the final
recompute in `build_30min_forecast` copies its results back through a
hand-maintained **carry-out whitelist**, and the action-spectrum identity was not
named there, so the fields were recomputed and then dropped — every other
recomputed child shipped, which is why nothing else noticed.

`tests/test_core.py::test_30min_frame_carries_action_spectrum_row_identity` pins
it (fails before, passes after) and the whitelist now says in situ that it is a
carry-out list, not a merge. `action_spectrum_version` is additionally enforced
as a row/summary agreement (`row_summary_version_agreement`), so a row cannot
claim a different action spectrum than the summary it ships under.

### `delayed_pigmentation_transmission_ratio` is deliberately not emitted

§2.2 defines the ratio as `E_DP_all_sky / E_DP_clear_sky` and exposes it *where
the backend can compute both*. No shipped backend can. The all-sky numerator is
the broadband reconstruction (or the Tier-B emulator, which has no cloud-free
mode), while the only available clear-sky UV model is the degraded analytic
fallback `tierB_clear_sky_uv`, and that model's absolute scale disagrees with the
production channels by **~2.2× on UVA and ~34× on UVB** at SZA 47° on the live
2026-10-05/06 run (`predicted_uva_wm2` 39.4 vs `cs_uva` 18.0;
`predicted_uvb_wm2` 0.906 vs `cs_uvb` 0.0266). Dividing the two yields a median
factor of ≈11 — a model-disagreement number, not atmospheric transmission.

Publishing that under a `transmission_ratio` name would be exactly the
name-lies-about-behaviour defect this contract exists to remove, so the field and
its clear-sky counterpart are not written at all (not even as `NaN` under a
transmitting name). `tests/test_v5_state.py::test_no_cross_backend_clear_sky_transmission_ratio`
pins the absence. The pair returns when a backend can evaluate one model with
clouds present and absent.

**UVI → E_ery → SED closure** (`docs/data.json`, half-hour row `2026-10-06T10:30`):
`uvi_consensus = 2.236` → `erythemal_irradiance_wm2 = 0.0559` (= UVI/40, ratio
0.025000) → `sed_30m = 1.0062`; `tan_dose_30m_j_m2 = 372.6`.

**Local surface changes only the skin plane** (45° tilt, identical forcing):
horizontal E_DP is bit-identical at `0.2186` for both surfaces, while the
ground-reflected delayed-pigmentation component moves `grass_summer 1.41513` →
`dry_beach_sand 8.19288`.

**Missing weather becomes unknown, not perfect**: with `temperature_2m = NaN`,
`outdoor_feasibility_complete = False`, `outdoor_feasibility_missing_fields =
temperature_2m`, `outdoor_block_reason = "unknown (missing weather)"`.

---

## E. UI verification

`docs/validation/ui/` (captured in a real Chromium against the published
renderer):

- `desktop-full.webp` — hero (strongest vs best-usable 30 min, confidence,
  `Local` / `Overall` / `Abs`), surface selector, day strip, charts, hourly and
  30-minute tables with per-row `Local`, provenance line showing
  `backend tierC-broadband-proxy-v2 (tier C)`.
- `mobile-full.webp` — 390 px; no horizontal overflow, headings H1 → H2 → H3.
- `surface-selector.webp` — the control in its default `Unknown` state with the
  local-vs-regional explanation.

The unknown/degraded state is visible in the hero and provenance line; the
missing-weather `UNKNOWN` path is covered by
`test_missing_required_weather_is_unknown_not_perfect` rather than a screenshot
because it needs a live frame with a missing field.

---

## F. Cleanliness

- No `TODO`/`FIXME`/`XXX`/`HACK` in `src/sunstack/` or `scripts/`.
- No legacy v4 label is used as v5 truth: `overall_tan_opportunity_0_100` is
  labelled "LEGACY composite (deprecated product heuristic)" in the UI, the API
  summary, and the docs, and is never the ranking key.
- Generated drift is committed, not left dirty; `git status` is clean apart from
  intended changes.
