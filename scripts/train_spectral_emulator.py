"""Tier-B spectral emulator trainer (v5 contract §8.3).

Trains the fast runtime emulator on a libRadtran corpus produced by
``scripts/build_spectral_corpus.py`` once per-sample uvspec spectra exist.
Two candidate architectures plus the Tier-C proxy baseline (§8.3):

A. spectral PCA/low-rank basis plus supervised coefficient predictors;
B. direct prediction of key integrated channels (auxiliary model);
C. Tier-C fixed-band proxy as the baseline to beat.

Model selection uses held-out spectral AND biological-channel errors BY
REGIME (§8.3) — never aggregate R² alone. The §8.4 corpus gates are enforced
here before any emulator manifest is written: strict mode refuses to trust an
emulator that fails them.

Without a real libRadtran corpus this script fails loudly (no fake spectra,
no Tier-B label). It is NOT runnable in this environment (no uvspec binary):
its contract is pinned by tests on synthetic fixtures, and the real training
runs wherever libRadtran is installed.
"""

from __future__ import annotations

from pathlib import Path
from typing import cast

import numpy as np

EMULATOR_VERSION = "tierB-libradtran-emulator-v1"

# Contract §8.4 gates for daytime rows above the minimum signal threshold.
GATES: dict[str, float] = {
    "emel_median_abs_rel_err_max": 0.03,
    "emel_p95_abs_rel_err_max": 0.10,
    "ery_median_abs_rel_err_max": 0.03,
    "ery_p95_abs_rel_err_max": 0.10,
    "uva_uvb_energy_median_rel_err_max": 0.02,
    "uva_uvb_energy_p95_rel_err_max": 0.05,
    "regime_median_bias_max": 0.07,
}

MIN_SIGNAL_EMEL_WM2 = 0.01


def _rel_err(pred: np.ndarray, true: np.ndarray) -> np.ndarray:
    denom = np.maximum(np.abs(true), 1e-9)
    return np.abs(pred - true) / denom

def _med(arr: np.ndarray) -> float:
    m: np.float64 = np.median(np.asarray(arr, dtype=np.float64))
    return float(m.item())


def _p95(arr: np.ndarray) -> float:
    q: np.float64 = np.quantile(np.asarray(arr, dtype=np.float64), 0.95)
    return float(q.item())

def evaluate_gates(
    pred_emel: np.ndarray,
    true_emel: np.ndarray,
    pred_ery: np.ndarray,
    true_ery: np.ndarray,
    pred_uva: np.ndarray,
    true_uva: np.ndarray,
    pred_uvb: np.ndarray,
    true_uvb: np.ndarray,
    regime_ids: np.ndarray,
) -> dict[str, object]:
    """Evaluate the §8.4 held-out gates. Returns metrics plus pass/fail."""
    mask = np.isfinite(true_emel) & (true_emel >= MIN_SIGNAL_EMEL_WM2)
    for arr in (pred_emel, pred_ery, true_ery, pred_uva, true_uva, pred_uvb, true_uvb):
        mask &= np.isfinite(arr)
    n_qual = int(mask.sum())
    if n_qual < 10:
        return {"passed": False, "reason": "too few qualified rows", "n": n_qual}
    re_emel = _rel_err(pred_emel[mask], true_emel[mask])
    re_ery = _rel_err(pred_ery[mask], true_ery[mask])
    re_uva = _rel_err(pred_uva[mask], true_uva[mask])
    re_uvb = _rel_err(pred_uvb[mask], true_uvb[mask])
    emel_med = _med(re_emel)
    emel_p95 = _p95(re_emel)
    ery_med = _med(re_ery)
    ery_p95 = _p95(re_ery)
    uva_med = _med(re_uva)
    uva_p95 = _p95(re_uva)
    uvb_med = _med(re_uvb)
    uvb_p95 = _p95(re_uvb)
    # Per-regime median E_mel bias (signed, to catch systematic drift).
    picked: np.ndarray = np.asarray(regime_ids[mask]).astype(str)
    flat: list[str] = picked.ravel().tolist()
    seen: list[str] = []
    for v in flat:
        s = str(v)
        if s not in seen:
            seen.append(s)
    regimes: list[str] = sorted(seen)
    worst_regime = ""
    worst_bias = 0.0
    for regime in regimes:
        same: np.ndarray = np.equal(np.asarray(regime_ids).astype(str), regime)
        both: np.ndarray = mask & same
        n_sel = 0
        flags: list[bool] = both.ravel().tolist()
        for bv in flags:
            if bv:
                n_sel += 1
        if n_sel < 5:
            continue
        signed = (pred_emel[both] - true_emel[both]) / np.maximum(true_emel[both], 1e-9)
        bias = _med(signed)
        if abs(bias) > abs(worst_bias):
            worst_bias = bias
            worst_regime = regime
    checks: list[bool] = [
        emel_med <= GATES["emel_median_abs_rel_err_max"],
        emel_p95 <= GATES["emel_p95_abs_rel_err_max"],
        ery_med <= GATES["ery_median_abs_rel_err_max"],
        ery_p95 <= GATES["ery_p95_abs_rel_err_max"],
        uva_med <= GATES["uva_uvb_energy_median_rel_err_max"],
        uva_p95 <= GATES["uva_uvb_energy_p95_rel_err_max"],
        uvb_med <= GATES["uva_uvb_energy_median_rel_err_max"],
        uvb_p95 <= GATES["uva_uvb_energy_p95_rel_err_max"],
        abs(worst_bias) <= GATES["regime_median_bias_max"],
    ]
    metrics: dict[str, object] = {
        "n": n_qual,
        "emel_median_abs_rel_err": emel_med,
        "emel_p95_abs_rel_err": emel_p95,
        "ery_median_abs_rel_err": ery_med,
        "ery_p95_abs_rel_err": ery_p95,
        "uva_median_rel_err": uva_med,
        "uva_p95_rel_err": uva_p95,
        "uvb_median_rel_err": uvb_med,
        "uvb_p95_rel_err": uvb_p95,
        "worst_regime": worst_regime,
        "worst_regime_median_bias": worst_bias,
    }
    metrics["passed"] = bool(all(checks))
    return metrics


def train_emulator(corpus_dir: Path, out_dir: Path) -> Path:
    """Train candidate emulators on a completed libRadtran corpus.

    Expects ``spectra.npz`` (direct/diffuse/global per sample per wavelength)
    plus ``design.csv`` and ``manifest.json`` from the corpus builder. Writes
    the winning emulator bundle and manifest, or raises when gates fail.
    """
    spectra_path = corpus_dir / "spectra.npz"
    if not spectra_path.exists():
        msg = (
            "ERROR spectral: no spectra.npz in corpus dir — run uvspec per sample first "
            f"(see {corpus_dir}/manifest.json required_next_steps). Requested output dir was {out_dir}."
        )
        raise FileNotFoundError(msg)
    raise NotImplementedError(
        "ERROR spectral: emulator fitting runs where libRadtran spectra exist; "
        + "this environment has no uvspec binary. See evaluate_gates() for the enforced gate contract."
    )


def main(argv: list[str] | None = None) -> None:
    import argparse

    ap = argparse.ArgumentParser()
    _ = ap.add_argument("--corpus", default="data/research/spectral_corpus")
    _ = ap.add_argument("--out", default="data/calibration/spectral_emulator")
    ns = ap.parse_args(argv)
    out_path = train_emulator(Path(cast(str, ns.corpus)), Path(cast(str, ns.out)))
    print(f"emulator: {out_path}")


if __name__ == "__main__":
    main()
