# Tier-B emulator training outcome (v5 contract §8.3/§8.4)

**Verdict: the §8.4 held-out gates FAIL. Tier-B stays unpromoted; production continues Tier-C
(the labeled degraded proxy).**

This is a first-party result, not a quoted one: it is the repo's own trainer
(`scripts/train_spectral_emulator.py`) run against the repo's own libRadtran corpus
(`data/research/spectral_corpus/`). The trainer writes its manifest and then raises, so a
gate-failing emulator cannot be loaded even by accident; `validate_tierB_manifest` refuses any
manifest whose `gates_passed` is not `True`.

## What was run

| | |
|---|---|
| Command | `uv run python scripts/train_spectral_emulator.py --corpus data/research/spectral_corpus --out <scratch>` |
| Corpus | 2000 libRadtran spectra, 121 wavelengths, 280-400 nm at 0.5 nm (`spectra.npz`, `design.csv`) |
| Corpus design SHA-256 | `37c25a3c8ef09ae81ca5bb5690894270a1653f594dd9505b665bd15698dea3cf` |
| Radiative transfer | libRadtran 2.0.6, disort 6-stream, local build |
| Parameter ranges | sza 0-88°, ozone 200-450 DU, altitude 0-4000 m, AOD340 0.02-1.0, Ångström 0-2.0, SSA340 0.85-1.0 |
| Held-out rows | 369 daytime rows above the signal threshold |
| Candidates | A: spectral PCA basis + supervised coefficients; B: direct channel prediction |
| Winner (best median) | `B_direct` |

## Gate comparison (§8.4)

Gates: E_mel p95 relative error ≤ 0.10 · erythemal p95 ≤ 0.10 · UVA/UVB energy p95 ≤ 0.05.

| Metric | Gate | A (PCA) | B (direct) | Result |
|---|---:|---:|---:|---|
| E_mel median abs rel err | — | 0.0664 | **0.0535** | — |
| E_mel **p95** abs rel err | 0.10 | 0.4499 | **0.2531** | fail |
| Erythemal median abs rel err | — | 0.0631 | **0.0537** | — |
| Erythemal **p95** abs rel err | 0.10 | 0.4422 | **0.2609** | fail |
| UVA median rel err | — | 0.0270 | **0.0301** | — |
| UVA **p95** rel err | 0.05 | 0.1838 | **0.1776** | fail |
| UVB median rel err | — | 0.0606 | **0.0499** | — |
| UVB **p95** rel err | 0.05 | 0.5519 | **0.2437** | fail |
| Worst regime (B) | — | — | `sza3_o37_aod0_alb2` | median bias −0.0976 |

Both candidates are **median-accurate (~5%) and tail-inaccurate (18-26%)**. The gates are
written on p95, so the emulator fails them by design, not by accident.

## What this means

1. The Tier-C proxy remains the shipping backend. Its measured bias (+204% median against true
   spectra; +219% against 1878 WOUDC Brewer scans) is what the UI now states where the number is
   read.
2. A Tier-B promotion needs the **tails** inside gate. The median being 5% says the model captures
   the dominant spectral shape; the p95 says it misses the extremes (low sun, high aerosol, high
   albedo - the bracketing regimes the corpus only lightly samples).
3. Regenerating the corpus with denser sampling of those regimes, or a tail-weighted objective, is
   the next experiment. That is training work, not a code change.
4. The corpus `uvspec_template.inp` is still marked `DRAFT - requires operator review` in the
   corpus manifest, and its `required_next_steps` record the same sequence this run executed.

## Reproduce

```bash
uv run python scripts/train_spectral_emulator.py \
  --corpus data/research/spectral_corpus \
  --out /tmp/tierb
# Expected: RuntimeError "emulator failed §8.4 held-out gates" with the metrics above.
```
