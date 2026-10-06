"""Tier-B gate contract tests (v5 contract §8.4, §24.1).

evaluate_gates() enforces the held-out corpus release gates. These tests pin
both outcomes on synthetic fixtures: a near-perfect emulator passes, a 50%
biased one fails. The real corpus training runs where libRadtran is installed;
the gate contract itself is fully testable here.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from typing import Protocol, cast

import numpy as np


class _TrainerModule(Protocol):
    def evaluate_gates(
        self, pred_emel: np.ndarray, true_emel: np.ndarray,
        pred_ery: np.ndarray, true_ery: np.ndarray,
        pred_uva: np.ndarray, true_uva: np.ndarray,
        pred_uvb: np.ndarray, true_uvb: np.ndarray,
        regime_ids: np.ndarray,
    ) -> dict[str, object]: ...

    def train_emulator(self, corpus_dir: Path, out_dir: Path) -> Path: ...


def _load_trainer() -> _TrainerModule:
    spec = importlib.util.spec_from_file_location(
        "train_spectral_emulator", "scripts/train_spectral_emulator.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["train_spectral_emulator"] = module
    spec.loader.exec_module(module)
    return cast(_TrainerModule, cast(object, module))


def _fixture(n: int = 200, seed: int = 0) -> dict[str, np.ndarray]:
    rng = np.random.default_rng(seed)
    true: np.ndarray = rng.uniform(0.02, 0.3, n)
    return {
        "true_emel": true,
        "true_ery": true * 0.5,
        "true_uva": true * 100.0,
        "true_uvb": true * 5.0,
        "regimes": np.array(["low_sun"] * (n // 2) + ["high_sun"] * (n - n // 2)),
    }


def _passed(out: dict[str, object]) -> bool:
    val = out["passed"]
    assert isinstance(val, bool)
    return val


def _emedian(out: dict[str, object]) -> float:
    val = out["emel_median_abs_rel_err"]
    assert isinstance(val, float)
    return val


def test_gate_evaluator_passes_near_perfect_emulator() -> None:
    module = _load_trainer()
    fx = _fixture()
    pred: np.ndarray = fx["true_emel"] * 1.01
    out = module.evaluate_gates(
        pred, fx["true_emel"], pred * 0.5, fx["true_ery"],
        pred * 100.0, fx["true_uva"], pred * 5.0, fx["true_uvb"], fx["regimes"])
    assert _passed(out) is True
    assert _emedian(out) < 0.03


def test_gate_evaluator_fails_biased_emulator() -> None:
    module = _load_trainer()
    fx = _fixture()
    pred: np.ndarray = fx["true_emel"] * 1.5
    out = module.evaluate_gates(
        pred, fx["true_emel"], pred * 0.5, fx["true_ery"],
        pred * 100.0, fx["true_uva"], pred * 5.0, fx["true_uvb"], fx["regimes"])
    assert _passed(out) is False


def test_gate_evaluator_rejects_too_few_rows() -> None:
    module = _load_trainer()
    tiny = np.array([0.05, 0.06])
    out = module.evaluate_gates(
        tiny, tiny, tiny, tiny, tiny, tiny, tiny, tiny, np.array(["a", "a"]))
    assert _passed(out) is False


def test_fixed_band_proxy_is_labeled_degraded() -> None:
    from sunstack.spectral import SPECTRAL_BACKEND_VERSION

    assert SPECTRAL_BACKEND_VERSION == "tierC-broadband-proxy-v2"
    assert "proxy" in SPECTRAL_BACKEND_VERSION


def test_tier_b_manifest_required_for_tier_b_label() -> None:
    import pytest

    from sunstack.spectral import validate_tierB_manifest

    with pytest.raises((ValueError, TypeError)):
        _ = validate_tierB_manifest({})
    with pytest.raises((ValueError, TypeError)):
        _ = validate_tierB_manifest({"spectral_emulator_version": "x"})


def test_tier_b_manifest_rejects_gate_failing_emulator() -> None:
    # §8.4: a structurally complete manifest whose held-out gates FAILED must
    # never back a Tier-B claim — strict mode keeps Tier-C labeled instead.
    import pytest

    from sunstack.spectral import validate_tierB_manifest

    complete: dict[str, object] = {
        "spectral_emulator_version": "tierB-libradtran-emulator-v1",
        "spectral_training_manifest_sha256": "abc",
        "libradtran_version": "libRadtran-2.0.6",
        "parameter_ranges": {"sza_deg": [0, 88]},
        "validation_metrics": {"A_pca": {"passed": False}},
        "gates_passed": False,
    }
    with pytest.raises(ValueError, match="gates_passed"):
        _ = validate_tierB_manifest(complete)
    complete["gates_passed"] = True
    assert validate_tierB_manifest(complete) is complete


def test_band_boundary_energy_conservation() -> None:
    # UVB integral over [280,315) plus UVA over [315,400] reconstructs the
    # 280-400 broadband energy without double-counting the boundary cell.
    from sunstack.spectral import (
        SPECTRAL_WAVES_NM,
        UVA_MASK,
        UVB_MASK,
        reconstruct_spectrum_tierC,
    )

    uva, uvb = 40.0, 0.8
    e = reconstruct_spectrum_tierC(uva, uvb)
    assert abs(float(np.sum(e[UVB_MASK])) - uvb) < 1e-9
    assert abs(float(np.sum(e[UVA_MASK])) - uva) < 1e-9
    assert len(SPECTRAL_WAVES_NM[UVB_MASK]) == 35
    assert len(SPECTRAL_WAVES_NM[UVA_MASK]) == 86
    assert float(np.sum(e)) == uva + uvb




def test_dynamic_band_weights_track_true_spectral_shape() -> None:
    # §7.2: on a uniform intra-band spectrum the dynamic weights reduce to
    # the cell-mean effectiveness; on a real (blue-heavy) spectrum they move
    # with the shape instead of staying fixed.
    from sunstack.spectral import (
        band_effective_weights,
        dynamic_band_weights,
        reconstruct_spectrum_tierC,
    )

    e = reconstruct_spectrum_tierC(60.0, 1.5)
    wu, wa = dynamic_band_weights(e)
    fu, fa = band_effective_weights()
    assert abs(wu - fu) < 0.01  # half-cell endpoint weighting only
    assert abs(wa - fa) / fa < 0.1
    # Blue-heavy spectrum (all energy at 315-320): UVA weight must rise
    # toward the local effectiveness, far above the band mean.
    import numpy as np

    from sunstack.spectral import SPECTRAL_WAVES_NM

    blue = np.zeros_like(SPECTRAL_WAVES_NM, dtype=float)
    blue[(SPECTRAL_WAVES_NM >= 315) & (SPECTRAL_WAVES_NM < 320)] = 1.0
    _, wa_blue = dynamic_band_weights(blue)
    assert wa_blue > 5 * fa

def test_trainer_refuses_without_corpus(tmp_path: Path) -> None:
    import pytest

    module = _load_trainer()
    with pytest.raises(FileNotFoundError, match="spectra.npz"):
        _ = module.train_emulator(tmp_path, tmp_path / "out")


def test_tierB_loader_returns_none_when_unwired(monkeypatch) -> None:
    from sunstack import config as _config
    from sunstack.spectral import predict_tierB_channels

    monkeypatch.setattr(_config, "TIERB_MANIFEST_PATH", None)
    import pandas as pd

    assert predict_tierB_channels(pd.DataFrame({"a": [1.0]})) is None


def test_tierB_loader_rejects_unknown_kind() -> None:
    import pytest

    from sunstack.spectral import predict_tierB_channels

    with pytest.raises(ValueError, match="unknown Tier-B emulator kind"):
        predict_tierB_channels(
            __import__("pandas").DataFrame(
                {c: [0.0] for c in
                 ["sza_deg", "ozone_du", "altitude_m", "aod340", "angstrom",
                  "ssa340", "asymmetry", "albedo", "total_cloud_cover",
                  "cloud_liquid_g_m2", "cloud_ice_g_m2", "water_vapor_kg_m2"]}),
            {"emulator": "Z_nope", "features": ["sza_deg"],
             "x_mu": [0.0], "x_sd": [1.0],
             "grid_nm": [300.0], "dp_s": [0.0], "ery_s": [0.0]})

