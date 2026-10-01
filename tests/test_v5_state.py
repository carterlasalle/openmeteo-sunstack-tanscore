"""Final derived-state coherence tests (v5 contract §4, §24.3).

Every test mutates a primitive/source field in a fixture and asserts all
dependent fields move (or remain provably invariant) — the regression that
shipped diverged uvi_consensus/erythemal/SED/source-count/confidence.
"""

from __future__ import annotations

import numpy as np
import pandas as pd


def _frame() -> pd.DataFrame:
    return pd.DataFrame({
        "uvi_openmeteo": [5.0, 6.0],
        "uvi_cams": [5.5, 4.0],
        "uvi_epa": [4.5, np.nan],
        "predicted_uva_wm2": [40.0, 42.0],
        "predicted_uvb_wm2": [0.6, 0.65],
        "is_day": [1, 1],
    })


def test_final_halfhour_erythemal_matches_final_consensus() -> None:
    from sunstack.state import recompute_derived_state

    out = recompute_derived_state(_frame())
    expected = (out["uvi_consensus"].to_numpy(dtype=float) / 40.0).round(5)
    assert np.allclose(out["erythemal_irradiance_wm2"].to_numpy(dtype=float), expected)


def test_final_sed_reintegrates_from_final_consensus() -> None:
    from sunstack.doses import add_interval_doses
    from sunstack.state import recompute_derived_state

    base = _frame()
    base["time"] = ["2026-06-21T11:00", "2026-06-21T11:30"]
    out = recompute_derived_state(base)
    out = add_interval_doses(out)
    # SED_30m on row 1 = trapezoid of final erythemal over 1800 s / 100.
    e0 = float(out["erythemal_irradiance_wm2"].iloc[0])
    e1 = float(out["erythemal_irradiance_wm2"].iloc[1])
    assert abs(float(out["sed_30m"].iloc[1]) - (0.5 * (e0 + e1) * 1800.0 / 100.0)) < 1e-9


def test_unique_uvi_source_count_not_vote_count() -> None:
    from sunstack.state import fuse_uvi_unique_count

    frame = pd.DataFrame({
        "uvi_openmeteo": [0.0, 5.0],
        "uvi_cams": [2.0, np.nan],
        "uvi_epa": [6.0, np.nan],
    })
    out = fuse_uvi_unique_count(frame)
    # Plain median: [2.0, 5.0]. Old OMx2 vote median gave [4.0, 5.0].
    assert out["uvi_consensus"].tolist() == [2.0, 5.0]
    assert out["uvi_consensus_sources"].tolist() == [3, 1]
    assert out["uvi_consensus_vote_count"].tolist() == [4, 2]


def test_final_confidence_inputs_use_final_state() -> None:
    from sunstack.state import recompute_derived_state

    base = _frame()
    before = recompute_derived_state(base)
    spread_before = before["uvi_source_spread"].tolist()
    mutated = base.copy()
    mutated.loc[0, "uvi_openmeteo"] = 9.0
    after = recompute_derived_state(mutated)
    # Spread, sunny/cloudy, erythemal, and E_mel-adjacent diagnostics move.
    assert after["uvi_source_spread"].iloc[0] != spread_before[0]
    assert after["uvi_sunny"].iloc[0] == 9.0
    assert after["erythemal_irradiance_wm2"].iloc[0] != before["erythemal_irradiance_wm2"].iloc[0]


def test_all_peak_fields_are_true_peaks() -> None:
    from sunstack.opportunity import build_daily_summary

    sub = pd.DataFrame({
        "dt": pd.to_datetime(["2026-06-21T10:00", "2026-06-21T11:00", "2026-06-21T12:00"]),
        "is_day": [1, 1, 1],
        "overall_tan_opportunity_0_100": [10.0, 50.0, 20.0],
        "tan_score_absolute_0_100": [40.0, 20.0, 30.0],
        "local_tan_score_0_100": [5.0, 6.0, 99.0],
        "atmospheric_quality_percentile_0_100": [7.0, 8.0, 9.0],
        "tan_forecast_confidence_0_100": [70.0, 71.0, 72.0],
        "outdoor_blocked": [False, False, False],
        "temperature_2m": [70.0, 75.0, 72.0],
        "uvi_consensus": [3.0, 6.0, 4.0],
        "uv_index": [3.0, 6.0, 4.0],
        "predicted_uva_wm2": [20.0, 40.0, 30.0],
        "precipitation_probability": [0.0, 0.0, 0.0],
        "wind_speed_10m": [5.0, 5.0, 5.0],
        "wind_gusts_10m": [6.0, 6.0, 6.0],
        "apparent_temperature": [70.0, 75.0, 72.0],
    })
    daily = build_daily_summary(sub)
    assert len(daily) == 1
    row = daily.iloc[0]
    # day_absolute_peak is the max of Absolute (40.0 at 10:00), NOT the
    # Absolute value at the Overall peak (20.0 at 11:00).
    assert float(row["day_absolute_peak_0_100"]) == 40.0
    assert float(row["day_local_peak_0_100"]) == 99.0
