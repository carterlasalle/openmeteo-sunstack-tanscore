"""Temporal interval contract tests (v5 contract §5, §24.2).

Every test pins provider-documented timestamp semantics or the dose-engine
contract against independently recomputed expectations — never against the
implementation's own output.
"""

from __future__ import annotations

import numpy as np
import pandas as pd


def test_power_hourly_start_anchor_maps_to_midpoint() -> None:
    from sunstack.temporal import power_hourly_to_intervals

    frame = pd.DataFrame({
        "time_utc": pd.to_datetime(["2026-06-21T12:00Z"], utc=True),
        "uva": [30.0],
    })
    out = power_hourly_to_intervals(frame)
    assert out["interval_start"].iloc[0] == pd.Timestamp("2026-06-21T12:00Z")
    assert out["interval_end"].iloc[0] == pd.Timestamp("2026-06-21T13:00Z")
    assert out["interval_midpoint"].iloc[0] == pd.Timestamp("2026-06-21T12:30Z")
    assert out["radiation_support_type"].iloc[0] == "interval_mean"
    assert out["temporal_semantics_version"].iloc[0] == "interval-contract-v1"


def test_openmeteo_backward_mean_maps_to_midpoint() -> None:
    from sunstack.temporal import openmeteo_hourly_to_intervals

    frame = pd.DataFrame({"time": ["2026-06-21T12:00"]})
    out = openmeteo_hourly_to_intervals(frame)
    mid = pd.to_datetime(out["interval_midpoint"], utc=True).iloc[0]
    # Backward mean stamped 12:00 covers [11:00, 12:00): midpoint 11:30.
    assert mid == pd.Timestamp("2026-06-21T11:30Z")
    assert pd.to_datetime(out["interval_start"], utc=True).iloc[0] == pd.Timestamp("2026-06-21T11:00Z")


def test_training_intervals_align_not_raw_timestamps() -> None:
    from sunstack.temporal import (
        align_training_intervals,
        openmeteo_hourly_to_intervals,
        power_hourly_to_intervals,
    )

    # POWER 12:00 start-anchor means [12:00,13:00); OM 13:00 backward-mean
    # means [12:00,13:00): same interval, different stamps. Raw-timestamp
    # merge would pair POWER 12:00 with OM 12:00 ([11:00,12:00)) — wrong hour.
    power = power_hourly_to_intervals(pd.DataFrame({
        "time_utc": pd.to_datetime(["2026-06-21T12:00Z"], utc=True),
        "uva": [30.0],
    }))
    preds = openmeteo_hourly_to_intervals(pd.DataFrame({
        "time": ["2026-06-21T12:00", "2026-06-21T13:00"],
        "ghi": [100.0, 800.0],
    }))
    merged = align_training_intervals(power, preds)
    assert len(merged) == 1
    assert float(merged["pred_ghi"].iloc[0]) == 800.0


def test_interval_mean_dose_is_rectangular_exact() -> None:
    from sunstack.temporal import integrate_interval_means_exact

    dose, complete, coverage = integrate_interval_means_exact(
        np.array([3600.0, 3600.0]), np.array([0.5, 0.25]))
    # Rectangular: 0.5*3600 + 0.25*3600 = 2700, NOT trapezoid 2250.
    assert dose == 2700.0
    assert complete is True
    assert coverage == 1.0


def test_point_sample_dose_is_trapezoidal() -> None:
    from sunstack.temporal import integrate_point_samples_trapezoid

    dose, complete, _ = integrate_point_samples_trapezoid(
        np.array([0.0, 3600.0]), np.array([0.0, 1.0]))
    assert dose == 1800.0
    assert complete is True


def test_lone_sample_over_nonzero_window_is_unknown() -> None:
    from sunstack.temporal import integrate_point_samples_trapezoid

    # Contract §17.1: one valid sample cannot claim a nonzero window's energy.
    dose, complete, coverage = integrate_point_samples_trapezoid(
        np.array([0.0, 1800.0]), np.array([0.5, np.nan]))
    assert bool(np.isnan(dose))
    assert complete is False
    assert coverage == 0.0


def test_clearness_denominator_matches_temporal_support() -> None:
    from sunstack.temporal import extra_radiation_date_dependent

    # Date-dependent extraterrestrial: June perihelion-side differs from
    # January, and neither equals the fixed 1361.1 approximation exactly.
    doys = np.array([15, 172])
    vals = extra_radiation_date_dependent(doys)
    assert vals.shape == (2,)
    assert bool(np.isfinite(vals).all())
    assert abs(float(vals[0]) - float(vals[1])) > 1.0
    assert abs(float(vals[1]) - 1361.1) > 0.5


def test_cams_accumulation_never_differences_across_cycles() -> None:
    from sunstack.temporal import cams_accumulation_to_interval_means

    times = pd.Series(pd.to_datetime(
        ["2026-06-21T00:00Z", "2026-06-21T01:00Z", "2026-06-21T02:00Z"], utc=True))
    out = cams_accumulation_to_interval_means(
        times, pd.Series([0.0, 3600.0, 3600.0]), pd.Series(["a", "a", "b"]))
    # Row 0: first interval unknown. Row 1: 3600 J / 3600 s = 1.0 W/m².
    # Row 2: new cycle — no cross-cycle difference, unknown, not negative.
    assert bool(np.isnan(out["interval_mean_wm2"].iloc[0]))
    assert out["interval_mean_wm2"].iloc[1] == 1.0
    assert bool(np.isnan(out["interval_mean_wm2"].iloc[2]))
    assert not bool(out["reset_signal"].iloc[2])


def test_cams_first_interval_is_unknown_or_explicitly_imputed() -> None:
    from sunstack.temporal import cams_accumulation_to_interval_means

    times = pd.Series(pd.to_datetime(
        ["2026-06-21T00:00Z", "2026-06-21T01:00Z"], utc=True))
    out = cams_accumulation_to_interval_means(
        times, pd.Series([100.0, 3700.0]), pd.Series(["a", "a"]))
    first = out.iloc[0]
    assert bool(np.isnan(first["interval_mean_wm2"]))
    assert not bool(first["complete"]) or bool(first["imputed"])


def test_cams_negative_increment_is_reset_signal_not_clipped() -> None:
    from sunstack.temporal import cams_accumulation_to_interval_means

    times = pd.Series(pd.to_datetime(
        ["2026-06-21T00:00Z", "2026-06-21T01:00Z"], utc=True))
    out = cams_accumulation_to_interval_means(
        times, pd.Series([5000.0, 1000.0]), pd.Series(["a", "a"]))
    assert bool(out["reset_signal"].iloc[1])
    assert bool(np.isnan(out["interval_mean_wm2"].iloc[1]))
