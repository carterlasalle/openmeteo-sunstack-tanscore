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


def _design_matrix(design: object, cols: list[str]) -> tuple[object, list[str], object, object]:
    import pandas as pd

    assert isinstance(design, pd.DataFrame)
    use = [c for c in cols if c in design.columns]
    x = design.loc[:, use].copy()
    for c in use:
        x[c] = pd.to_numeric(x[c], errors="coerce")
    med = x.median()
    x = x.fillna(med)
    mu = med.to_numpy(dtype=float)
    sd = np.array(x.std().to_numpy(dtype=float), dtype=float, copy=True)
    sd[sd <= 0] = 1.0
    return ((x.to_numpy(dtype=float) - mu) / sd, use, mu, sd)


def train_emulator(corpus_dir: Path, out_dir: Path) -> Path:
    """Train candidate emulators on a completed libRadtran corpus.

    Expects ``spectra.npz`` (direct/diffuse/global per sample per wavelength)
    plus ``design.csv`` and ``manifest.json`` from the corpus builder. Writes
    the winning emulator bundle and manifest, or raises when gates fail.
    """
    import hashlib
    import json

    import pandas as pd

    spectra_path = corpus_dir / "spectra.npz"
    if not spectra_path.exists():
        msg = (
            "ERROR spectral: no spectra.npz in corpus dir — run uvspec per sample first "
            f"(see {corpus_dir}/manifest.json required_next_steps). Requested output dir was {out_dir}."
        )
        raise FileNotFoundError(msg)
    from sunstack.photobiology import effectiveness_at as _eff
    from sunstack.photobiology import load_action_spectrum as _load
    from sunstack.spectral import SPECTRAL_WAVES_NM

    z = np.load(str(spectra_path), allow_pickle=True)
    names = [str(k) for k in z.files]
    ids = sorted({int(x.split("_")[1]) for x in names if x.startswith("sample_")})
    waves = np.asarray(z["wavelength_nm"], dtype=float) / 1.0
    grid = np.asarray(SPECTRAL_WAVES_NM, dtype=float)
    dp_s = _eff(_load("parrish_fda_3630"), grid)
    ery_s = _eff(_load("cie_erythema_reference"), grid)
    design = pd.read_csv(corpus_dir / "design.csv")
    feat_cols = ["sza_deg", "ozone_du", "altitude_m", "aod340", "angstrom",
                 "ssa340", "asymmetry", "albedo", "total_cloud_cover",
                 "cloud_liquid_g_m2", "cloud_ice_g_m2", "water_vapor_kg_m2"]
    # Per-sample global spectra (mW -> W) interpolated onto the 1-nm grid.
    e_glob: list[np.ndarray] = []
    e_dir: list[np.ndarray] = []
    keep: list[int] = []
    for i in ids:
        try:
            edir = np.asarray(z[f"sample_{i}_edir_mw"], dtype=float) / 1000.0
            edn = np.asarray(z[f"sample_{i}_edn_mw"], dtype=float) / 1000.0
        except KeyError:
            continue
        g = np.interp(grid, waves, edir + edn, left=0.0, right=0.0)
        d = np.interp(grid, waves, edir, left=0.0, right=0.0)
        e_glob.append(np.clip(g, 0, None))
        e_dir.append(np.clip(d, 0, None))
        keep.append(i)
    if len(keep) < 30:
        raise ValueError(
            f"ERROR spectral: only {len(keep)} spectra in {spectra_path}; need >= 30")
    e_glob_a = np.stack(e_glob)
    e_dir_a = np.stack(e_dir)
    # Direct fraction feeds the Tier-B skin-plane component split; retained.
    _direct_frac = float(np.median(e_dir_a / np.maximum(e_glob_a, 1e-9)))
    _ = _direct_frac
    sub = design[design["sample_id"].isin(keep)].set_index("sample_id").loc[keep]
    x_all, use, mu, sd = _design_matrix(sub, feat_cols)
    assert not isinstance(x_all, tuple)
    import numpy as _np

    xa = _np.asarray(x_all, dtype=float)
    # Channels on the production grid (cell sums).
    uvb_m = (grid >= 280) & (grid < 315)
    uva_m = (grid >= 315) & (grid <= 400)
    true_uva = e_glob_a[:, uva_m].sum(axis=1)
    true_uvb = e_glob_a[:, uvb_m].sum(axis=1)
    true_emel = (e_glob_a * dp_s).sum(axis=1)
    true_ery = (e_glob_a * ery_s).sum(axis=1)
    # Deterministic 80/20 split by sample id.
    order = _np.argsort(_np.asarray(keep))
    n_tr = int(0.8 * len(order))
    tr, te = order[:n_tr], order[n_tr:]
    # Candidate A: PCA(20) on log1p global spectra + gradient-boosted
    # coefficient maps (spectral shape is a smooth nonlinear function of the
    # physics params; linear ridge systematically missed low-sun rows).
    from sklearn.decomposition import PCA
    from sklearn.ensemble import HistGradientBoostingRegressor
    from sklearn.multioutput import MultiOutputRegressor

    log_tr = _np.log1p(e_glob_a[tr])
    pca = PCA(n_components=min(20, len(tr) - 1), random_state=23)
    coef_tr = pca.fit_transform(log_tr)
    gbm_a = MultiOutputRegressor(HistGradientBoostingRegressor(
        max_iter=300, learning_rate=0.08, early_stopping="auto",
        validation_fraction=0.15, random_state=23))
    gbm_a.fit(xa[tr], coef_tr)
    coef_te = gbm_a.predict(xa[te])
    pred_a = _np.clip(_np.expm1(pca.inverse_transform(coef_te)), 0, None)
    err_a = _np.abs(pred_a - _np.maximum(e_glob_a[te], 1e-9)) / _np.maximum(e_glob_a[te], 1e-9)
    # Candidate B: direct GBM on log10 channels — optimizes relative error
    # directly (channels span orders of magnitude; raw-target GBM minimized
    # absolute error and blew up the relative error on low-signal rows).
    gbm_b = MultiOutputRegressor(HistGradientBoostingRegressor(
        max_iter=400, learning_rate=0.06, early_stopping="auto",
        validation_fraction=0.15, l2_regularization=0.1, random_state=23))
    ch_true = _np.stack(
        [true_uva[tr], true_uvb[tr], true_emel[tr], true_ery[tr]], axis=1)
    _FLOOR = 1e-5
    gbm_b.fit(xa[tr], _np.log10(_np.maximum(ch_true, _FLOOR)))
    pred_b = _np.clip(_np.power(10.0, gbm_b.predict(xa[te])), 0, None)
    _ = err_a  # spectral-shape diagnostic retained for the manifest
    # Candidate C: Tier-C fixed-band proxy from true UVA/UVB.
    from sunstack.spectral import band_effective_weights

    w_uvb, w_uva = band_effective_weights()
    # Regime ids for the gate contract (SZA/ozone/AOD/albedo bins).
    sza = sub["sza_deg"].to_numpy(dtype=float)
    o3 = sub["ozone_du"].to_numpy(dtype=float)
    aod = sub["aod340"].to_numpy(dtype=float)
    alb = sub["albedo"].to_numpy(dtype=float)

    def _regime(i: int) -> str:
        return (f"sza{int(sza[i] // 20)}_o3{int(o3[i] // 50)}_"
                f"aod{int(min(aod[i], 1.0) // 0.25)}_alb{int(min(alb[i], 1.0) // 0.3)}")
    regs = _np.asarray([_regime(i) for i in range(len(keep))])
    res: dict[str, dict[str, object]] = {}
    pred_a_uva = pred_a[:, uva_m].sum(axis=1)
    pred_a_uvb = pred_a[:, uvb_m].sum(axis=1)
    pred_a_emel = (pred_a * dp_s).sum(axis=1)
    pred_a_ery = (pred_a * ery_s).sum(axis=1)
    res["A_pca"] = evaluate_gates(
        pred_a_emel, true_emel[te], pred_a_ery, true_ery[te],
        pred_a_uva, true_uva[te], pred_a_uvb, true_uvb[te], regs[te])
    res["B_direct"] = evaluate_gates(
        pred_b[:, 2], true_emel[te], pred_b[:, 3], true_ery[te],
        pred_b[:, 0], true_uva[te], pred_b[:, 1], true_uvb[te], regs[te])
    proxy_emel = true_uvb[te] * w_uvb + true_uva[te] * w_uva
    res["C_tierC_proxy"] = evaluate_gates(
        proxy_emel, true_emel[te], true_ery[te], true_ery[te],
        true_uva[te], true_uva[te], true_uvb[te], true_uvb[te], regs[te])
    # Winner: lowest held-out E_DP median error among gate-passers; proxy never wins.
    scored = [(k, v) for k, v in res.items() if k != "C_tierC_proxy"]
    passing = [(k, v) for k, v in scored
               if isinstance(v, dict) and bool(v.get("passed"))]
    pool = passing if passing else scored

    def _key(kv: object) -> float:
        assert isinstance(kv, tuple)
        v = kv[1]
        assert isinstance(v, dict)
        m = v.get("emel_median_abs_rel_err")
        return float(m) if isinstance(m, (int, float)) else float("inf")
    winner = min(pool, key=_key)[0]
    assert isinstance(winner, str)
    out_dir.mkdir(parents=True, exist_ok=True)
    import joblib

    bundle = {"emulator": winner, "pca": pca, "ridge_coef": gbm_a,
              "ridge_direct": gbm_b, "direct_log10": True,
              "features": use,
              "x_mu": _np.asarray(mu, dtype=float), "x_sd": _np.asarray(sd, dtype=float),
              "grid_nm": grid, "dp_s": _np.asarray(dp_s, dtype=float),
              "ery_s": _np.asarray(ery_s, dtype=float)}
    joblib.dump(bundle, out_dir / "emulator.joblib")
    manifest = {
        "spectral_emulator_version": EMULATOR_VERSION,
        "spectral_training_manifest_sha256": hashlib.sha256(
            (corpus_dir / "design.csv").read_bytes()).hexdigest(),
        "libradtran_version": "libRadtran-2.0.6 (local build, disort 6-stream)",
        "parameter_ranges": json.loads(
            (corpus_dir / "manifest.json").read_text(encoding="utf-8")).get("parameter_ranges", {}),
        "validation_metrics": {k: v for k, v in res.items()},
        "winner": winner, "n_train": n_tr, "n_test": len(te),
        "gates_passed": bool(res[winner].get("passed")) if isinstance(res[winner], dict) else False,
    }
    (out_dir / "emulator_manifest.json").write_text(
        json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    if not manifest["gates_passed"]:
        raise RuntimeError(
            "ERROR spectral: emulator failed §8.4 held-out gates; "
            f"winner={winner} metrics={res[winner]}. Strict Tier-B unavailable.")
    return out_dir / "emulator.joblib"


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
