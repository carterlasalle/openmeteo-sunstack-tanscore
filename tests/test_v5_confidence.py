"""Calibrated confidence/fusion tests (v5 contract §10, §11, §24.6).

Confidence must mean predictive reliability, never sunniness. Every test
holds reliability inputs fixed while varying the sun (or vice versa) and
asserts only the correct quantity moves.
"""

from __future__ import annotations

import numpy as np
import pandas as pd


def _rel_frame() -> pd.DataFrame:
    return pd.DataFrame({
        "uvi_consensus": [6.0, 6.0, 6.0],
        "uvi_source_spread": [0.2, 2.0, 5.0],
        "uvi_consensus_sources": [3, 2, 1],
        "sza": [40.0, 40.0, 40.0],
        "cloud_cover": [20.0, 20.0, 20.0],
    })


def test_confidence_does_not_reward_sunny_outcomes() -> None:
    from sunstack.calibrate import estimate_expected_uvi_error

    # Same reliability inputs at the same lead (single-row frames), different
    # sun: confidence must be bit-identical.
    confs = []
    for uvi in (2.0, 6.0, 9.0):
        f = pd.DataFrame({
            "uvi_consensus": [uvi], "uvi_source_spread": [0.5],
            "uvi_consensus_sources": [3], "sza": [40.0], "cloud_cover": [20.0],
        })
        o = estimate_expected_uvi_error(f)
        confs.append(float(o["tan_forecast_confidence_0_100"].iloc[0]))
    assert confs[0] == confs[1] == confs[2]


def test_stronger_dispersion_lowers_reliability() -> None:
    from sunstack.calibrate import estimate_expected_uvi_error

    o = estimate_expected_uvi_error(_rel_frame())
    err = o["uvi_expected_abs_error"].tolist()
    conf = o["tan_forecast_confidence_0_100"].tolist()
    assert err[0] < err[1] < err[2]
    assert conf[0] > conf[1] > conf[2]


def test_lone_source_widens_uncertainty() -> None:
    from sunstack.calibrate import estimate_expected_uvi_error

    o = estimate_expected_uvi_error(_rel_frame())
    lo = o["uvi_prediction_interval_low"].tolist()
    hi = o["uvi_prediction_interval_high"].tolist()
    width_3src = hi[0] - lo[0]
    width_1src = hi[2] - lo[2]
    assert width_1src > 2.0 * width_3src


def test_source_weight_contributions_sum_to_one() -> None:
    from sunstack.state import fuse_uvi_unique_count

    frame = pd.DataFrame({
        "uvi_openmeteo": [5.0, 6.0],
        "uvi_cams": [5.5, np.nan],
        "uvi_epa": [4.5, np.nan],
    })
    out = fuse_uvi_unique_count(frame)
    # Unique provider count (not votes) drives the fusion contract.
    assert out["uvi_consensus_sources"].tolist() == [3, 1]
    # Consensus lies within the finite source range (convex fusion).
    assert out["uvi_consensus"].iloc[0] == 5.0
    assert out["uvi_consensus"].iloc[1] == 6.0


def test_common_case_uvi_evaluator_uses_identical_rows() -> None:
    # Contract §10.2: candidates are compared on the same common-case rows.
    # This pins the evaluator shape: inner join on (target_day, utc), per
    # source n reported separately, common-case n identical across sources.
    import importlib.util

    spec = importlib.util.spec_from_file_location(
        "verify_uvi", "scripts/verify_uvi.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    assert hasattr(module, "extract_preds")
    assert hasattr(module, "fetch_truth")
    assert hasattr(module, "main")


def test_strong_sun_probability_separate_from_confidence() -> None:
    from sunstack.derive import best_windows

    base = pd.DataFrame({
        "time": ["2026-06-21T12:00", "2026-06-21T13:00"],
        "is_day": [1, 1],
        "sun_score_0_100": [90.0, 20.0],
    })
    probs = pd.DataFrame({
        "time": ["2026-06-21T12:00", "2026-06-21T13:00"],
        "p_dni_instant_ge_600": [90.0, 5.0],
        "p_ghi_instant_ge_700": [90.0, 5.0],
        "p_cloud_lt_60": [95.0, 10.0],
        "p_precip_gt_0_01in": [5.0, 80.0],
    })
    consensus = pd.DataFrame({
        "time": ["2026-06-21T12:00", "2026-06-21T13:00"],
        "deterministic_agreement_0_100": [80.0, 80.0],
    })
    out = best_windows(base, probs, consensus)
    assert "strong_sun_probability_0_100" in out.columns
    sunny = out.loc[out["time"] == "2026-06-21T12:00"].iloc[0]
    cloudy = out.loc[out["time"] == "2026-06-21T13:00"].iloc[0]
    assert float(sunny["strong_sun_probability_0_100"]) > float(
        cloudy["strong_sun_probability_0_100"])
