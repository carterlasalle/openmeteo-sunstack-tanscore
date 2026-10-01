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



def test_history_normalizers_attach_interval_metadata() -> None:
    from sunstack.history import _openmeteo_hourly_frame, normalize_nasa_power

    power = normalize_nasa_power({
        "properties": {"parameter": {"ALLSKY_SFC_UVA": {"2026062112": 30.0}}}
    })
    openmeteo = _openmeteo_hourly_frame(
        {"hourly": {"time": ["2026-06-21T13:00Z"], "shortwave_radiation": [800.0]}},
        "openmeteo_historical_forecast",
        "best_match",
    )
    required = {
        "interval_start", "interval_end", "interval_midpoint",
        "radiation_support_type", "temporal_semantics_version",
    }
    assert required.issubset(power.columns)
    assert required.issubset(openmeteo.columns)
    assert power["time_utc"].iloc[0] == pd.Timestamp("2026-06-21T12:00Z")
    assert openmeteo["time_utc"].iloc[0] == pd.Timestamp("2026-06-21T13:00Z")
    assert openmeteo["interval_start"].iloc[0] == pd.Timestamp("2026-06-21T12:00Z")


def test_build_training_dataset_joins_openmeteo_by_midpoint(monkeypatch, tmp_path) -> None:
    from sunstack import calibrate

    monkeypatch.setattr(
        calibrate,
        "prepare_nasa_training",
        lambda *_: pd.DataFrame({
            "time_utc": pd.to_datetime(["2026-06-21T12:00Z"], utc=True),
            "uva": [30.0],
        }),
    )
    openmeteo = pd.DataFrame({
        "time_utc": pd.to_datetime(
            ["2026-06-21T12:00Z", "2026-06-21T13:00Z"], utc=True
        ),
        "shortwave_radiation": [100.0, 800.0],
    })
    training = calibrate.build_training_dataset(
        pd.DataFrame(), openmeteo, pd.DataFrame(), tmp_path
    )
    # POWER's 12:00 start-anchored interval matches OM's 13:00 end-anchored
    # interval; a raw timestamp merge would select the 100 W/m² row instead.
    assert float(training["om_shortwave_radiation"].iloc[0]) == 800.0


def test_dose_routing_uses_exact_interval_means_and_point_trapezoids() -> None:
    from sunstack.doses import add_interval_doses, day_totals, window_dose

    ends = pd.date_range("2026-06-21T12:00Z", periods=3, freq="30min")
    interval_means = pd.DataFrame({
        "time_utc": ends,
        "dt": ends,
        "interval_start_utc": ends - pd.Timedelta(minutes=30),
        "interval_end_utc": ends,
        "radiation_support_type": "interval_mean",
        "melanogenic_effective_irradiance_wm2": [1.0, 2.0, 3.0],
        "erythemal_irradiance_wm2": [1.0, 2.0, 3.0],
        "predicted_uva_wm2": [1.0, 2.0, 3.0],
        "predicted_uvb_wm2": [1.0, 2.0, 3.0],
    })
    point_samples = interval_means.drop(
        columns=["interval_start_utc", "interval_end_utc"]
    ).assign(radiation_support_type="instant")

    interval_out = add_interval_doses(interval_means)
    point_out = add_interval_doses(point_samples)
    assert float(interval_out["tan_dose_1h_j_m2"].iloc[-1]) == 9000.0
    assert float(point_out["tan_dose_1h_j_m2"].iloc[-1]) == 7200.0
    assert float(day_totals(interval_means)["tan_dose_day_j_m2"].iloc[0]) == 10800.0
    assert float(day_totals(point_samples)["tan_dose_day_j_m2"].iloc[0]) == 7200.0
    assert window_dose(
        interval_means, ends[0], ends[-1]
    )["tan_dose_best_window_j_m2"] == 9000.0
    assert window_dose(
        point_samples, ends[0], ends[-1]
    )["tan_dose_best_window_j_m2"] == 7200.0


def test_half_hour_interval_columns_survive_record_serialization() -> None:
    from sunstack.opportunity import build_30min_forecast
    from sunstack.ui import _records

    half_hour = build_30min_forecast(pd.DataFrame({
        "time": ["2026-06-21T12:00", "2026-06-21T13:00"],
        "uv_index": [5.0, 5.0],
        "is_day": [True, True],
        "temperature_2m": [24.0, 24.0],
        "relative_humidity_2m": [50.0, 50.0],
        "wind_speed_10m": [1.0, 1.0],
        "weather_code": [0, 0],
    }))
    record = _records(half_hour)[0]
    assert {
        "interval_start_utc", "interval_end_utc", "interval_midpoint_utc"
    }.issubset(record)
    assert record["radiation_support_type"] == "interval_mean"
    assert record["temporal_semantics_version"] == "interval-contract-v1"
    start = pd.Timestamp(record["interval_start_utc"])
    end = pd.Timestamp(record["interval_end_utc"])
    midpoint = pd.Timestamp(record["interval_midpoint_utc"])
    assert end - start == pd.Timedelta(minutes=30)
    assert midpoint - start == pd.Timedelta(minutes=15)


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
