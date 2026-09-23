"""Audit-driven v4 scoring tests (§3/§7/§8/§15/§16/§21-gaps/§13).

Exercises the production scoring path offline (uncalibrated fallback tier):
new Absolute from E_mel, full CAMS propagation with real sanitized column
names, UVI-fusion confidence separation, dose-invariant window ranking,
canonical dose columns, SED gap handling, and the TanResponse baseline.
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

from sunstack.doses import add_interval_doses, day_totals, window_dose
from sunstack.opportunity import build_daily_summary
from sunstack.photobiology import integrate_sed, integrate_tandose
from sunstack.spectral import melanogenic_from_broadband
from sunstack.tanscore import score_forecast


def _best_air() -> pd.DataFrame:
    return pd.DataFrame({
        "time": ["2026-06-21T11:00", "2026-06-21T12:00", "2026-06-21T13:00"],
        "shortwave_radiation": [600.0, 800.0, 700.0],
        "direct_normal_irradiance": [700.0, 850.0, 750.0],
        "diffuse_radiation": [100.0, 120.0, 110.0],
        "terrestrial_radiation": [1000.0, 1100.0, 1050.0],
        "cloud_cover": [10.0, 5.0, 15.0],
        "temperature_2m": [78.0, 82.0, 80.0],
        "relative_humidity_2m": [50.0, 45.0, 48.0],
        "surface_pressure": [10000.0, 10000.0, 10000.0],
        "uv_index": [5.0, 6.5, 6.0],
        "uv_index_clear_sky": [6.0, 7.0, 6.5],
        "is_day": [1, 1, 1],
        "precipitation_probability": [0.0, 0.0, 0.0],
    })


def _cams(uvbed: list[float], clear: list[float]) -> pd.DataFrame:
    base = {
        "time_utc": pd.to_datetime(
            ["2026-06-21 15:00", "2026-06-21 16:00", "2026-06-21 17:00"], utc=True),
        "cams_uv_biologically_effective_dose": uvbed,
        "cams_uv_biologically_effective_dose_clear_sky": clear,
        "cams_surface_downward_uv_radiation": [3_000_000.0, 3_000_900.0, 3_001_800.0],
        "cams_gems_total_column_ozone": [300.0, 301.0, 299.0],
        "cams_total_column_vertically_integrated_water_vapour": [20.0, 21.0, 19.0],
        "cams_total_column_cloud_liquid_water": [0.001, 0.002, 0.001],
        "cams_total_column_cloud_ice_water": [0.0001, 0.0001, 0.0002],
        "cams_total_cloud_cover": [0.1, 0.2, 0.15],
        "cams_forecast_albedo": [0.18, 0.18, 0.19],
        "cams_surface_direct_normal_short_wave_solar_radiation": [700.0, 800.0, 750.0],
        "cams_surface_short_wave_solar_radiation_downwards": [600.0, 700.0, 650.0],
        "cams_cycle": ["2026-06-21T00:00Z"] * 3,
        "source": ["cams_direct_forecast"] * 3,
    }
    for wave in ("340", "355", "380", "400"):
        base[f"cams_total_aerosol_optical_depth_at_{wave}_nm"] = [0.15, 0.16, 0.14]
        base[f"cams_total_absorption_aerosol_optical_depth_at_{wave}_nm"] = [0.008] * 3
        base[f"cams_single_scattering_albedo_at_{wave}_nm"] = [0.94] * 3
        base[f"cams_asymmetry_factor_at_{wave}_nm"] = [0.68] * 3
    return pd.DataFrame(base)


def _confidence(value: float = 80.0) -> pd.DataFrame:
    return pd.DataFrame({
        "time": ["2026-06-21T11:00", "2026-06-21T12:00", "2026-06-21T13:00"],
        "sun_window_confidence_0_100": [value] * 3,
    })


def test_v4_absolute_is_normalized_emel_with_legacy_diagnostic(tmp_path):
    out = score_forecast(_best_air(), Path(tmp_path), None, _confidence())
    assert out["tan_score_model_version"].unique().tolist() == ["action-spectrum-v1"]
    expected_emel = melanogenic_from_broadband(
        out["predicted_uva_wm2"].to_numpy(), out["predicted_uvb_wm2"].to_numpy())
    assert np.allclose(out["melanogenic_effective_irradiance_wm2"].to_numpy(),
                       np.round(expected_emel, 5))
    from sunstack import config as _config

    expected_score = np.round(
        np.clip(100.0 * expected_emel / _config.GLOBAL_MELANOGENIC_REFERENCE_WM2, 0, 100), 1)
    assert np.allclose(out["tan_score_absolute_0_100"].to_numpy(), expected_score)
    # Legacy diagnostic present for migration comparison, never the headline.
    assert "legacy_absolute_tan_score_55_30_15" in out
    assert not out["legacy_absolute_tan_score_55_30_15"].equals(
        out["tan_score_absolute_0_100"])
    assert (out["erythemal_irradiance_wm2"].to_numpy() ==
            out["uv_index"].to_numpy() / 40.0).all()


def test_all_direct_cams_fields_propagate(tmp_path):
    uvbed = [0.125, 0.1625, 0.15]
    out = score_forecast(_best_air(), Path(tmp_path),
                         _cams(uvbed, [0.15, 0.175, 0.1625]), _confidence())
    assert np.allclose(out["cams_erythemal_irradiance_wm2"].to_numpy(), uvbed)
    assert np.allclose(out["cams_uv_index"].to_numpy(), np.array(uvbed) * 40.0)
    assert np.allclose(out["cams_uv_index_clear_sky"].to_numpy(),
                       np.array([0.15, 0.175, 0.1625]) * 40.0)
    assert np.allclose(out["cams_uv_transmission"].to_numpy(),
                       np.array(uvbed) / np.array([0.15, 0.175, 0.1625]))
    for col in ("cams_aod_340", "cams_aod_355", "cams_aod_380", "cams_aod_400",
                "cams_abs_aod_340", "cams_ssa_340", "cams_asymmetry_340",
                "cams_ozone_du", "cams_water_vapor", "cams_cloud_liquid_water",
                "cams_cloud_ice_water", "cams_total_cloud",
                "cams_forecast_albedo", "cams_downward_uv_accumulated_j_m2"):
        assert col in out, col
        assert out[col].notna().all(), col
    assert (out["cams_ozone_du"].to_numpy() > 200).all()
    # Accumulated downward UV differentiates back to a physical irradiance.
    assert np.allclose(out["cams_downward_surface_uv_wm2"].to_numpy(),
                       0.25, atol=0.01)


def test_uvi_disagreement_moves_confidence_not_physics(tmp_path):
    agree = score_forecast(_best_air(), Path(tmp_path),
                           _cams([0.125, 0.1625, 0.15], [0.15, 0.175, 0.1625]),
                           _confidence(80.0))
    clash = score_forecast(_best_air(), Path(tmp_path),
                           _cams([0.01, 0.01, 0.01], [0.15, 0.175, 0.1625]),
                           _confidence(80.0))
    assert (agree["tan_forecast_confidence_0_100"].to_numpy() == 80.0).all()
    assert (clash["tan_forecast_confidence_0_100"].to_numpy() ==
            round(80.0 * 0.65, 1)).all()
    assert clash["uvi_source_disagree"].all()
    # Identical broadband inputs => identical melanogenic physics.
    assert np.allclose(agree["melanogenic_effective_irradiance_wm2"].to_numpy(),
                       clash["melanogenic_effective_irradiance_wm2"].to_numpy())
    assert np.allclose(agree["tan_score_absolute_0_100"].to_numpy(),
                       clash["tan_score_absolute_0_100"].to_numpy())


def _half_hour_frame(emel_scale: float = 1.0) -> pd.DataFrame:
    dts = pd.date_range("2026-06-21 11:00", periods=8, freq="30min")
    return pd.DataFrame({
        "dt": dts,
        "time": dts.strftime("%Y-%m-%dT%H:%M"),
        "overall_tan_opportunity_0_100": [80.0, 82.0, 81.0, 79.0, 20.0, 90.0, 91.0, 5.0],
        "outdoor_blocked": [False] * 8,
        "temperature_2m": [80.0] * 8,
        "apparent_temperature": [80.0] * 8,
        "wind_speed_10m": [5.0] * 8,
        "wind_gusts_10m": [6.0] * 8,
        "melanogenic_effective_irradiance_wm2": np.full(8, 0.5) * emel_scale,
        "erythemal_irradiance_wm2": np.full(8, 0.15) * emel_scale,
        "predicted_uva_wm2": np.full(8, 35.0),
        "predicted_uvb_wm2": np.full(8, 1.0),
    })


def test_window_ranking_is_dose_invariant():
    # A 4-slot eligible group outranks a 2-slot group on sustained opportunity;
    # scaling all photons x10 (dose x10) must not change the selection.
    first = build_daily_summary(_half_hour_frame(1.0))
    scaled = build_daily_summary(_half_hour_frame(10.0))
    assert first.loc[0, "best_window_start"] == scaled.loc[0, "best_window_start"]
    assert first.loc[0, "best_window_end"] == scaled.loc[0, "best_window_end"]
    # The longer eligible group wins on sustained opportunity, not on dose.
    assert first.loc[0, "best_window_start"] == "2026-06-21T11:00:00"
    assert first.loc[0, "best_window_end"] == "2026-06-21T13:00:00"
    # Windows display average intensity AND cumulative dose side by side.
    assert np.isfinite(first.loc[0, "best_window_mean_0_100"])
    assert first.loc[0, "tan_dose_best_window_j_m2"] > 0
    assert scaled.loc[0, "tan_dose_best_window_j_m2"] == (
        first.loc[0, "tan_dose_best_window_j_m2"] * 10)


def test_canonical_dose_columns_exist():
    times = pd.Series(pd.to_datetime(
        ["2026-06-21T12:00Z", "2026-06-21T12:30Z", "2026-06-21T13:00Z"], utc=True))
    e = pd.Series([0.5, 0.6, 0.55])
    primitive = integrate_tandose(times, e)
    assert "tan_dose_melanogenic_j_m2" in primitive  # canonical primitive key
    frame = pd.DataFrame({
        "time": ["2026-06-21T12:00", "2026-06-21T12:30", "2026-06-21T13:00"],
        "melanogenic_effective_irradiance_wm2": [0.5, 0.6, 0.55],
        "erythemal_irradiance_wm2": [0.15, 0.16, 0.155],
        "predicted_uva_wm2": [35.0, 40.0, 38.0],
        "predicted_uvb_wm2": [1.0, 1.1, 1.05],
        "pigment_darkening_effective_irradiance": [0.2, 0.22, 0.21],
    })
    dosed = add_interval_doses(frame)
    for col in ("tan_dose_15m_j_m2", "tan_dose_30m_j_m2", "tan_dose_1h_j_m2",
                "tan_dose_15m_reference_minutes",
                "sed_15m", "sed_30m", "sed_1h",
                "uva_dose_30m_j_m2", "uva_dose_30m_j_cm2",
                "uvb_dose_30m_j_m2", "pigment_darkening_dose_30m_j_m2",
                "tan_dose_30m_complete", "tan_dose_30m_coverage_fraction",
                "sed_30m_complete", "sed_30m_coverage_fraction"):
        assert col in dosed, col
    # Row 0 has no history: doses UNKNOWN (NaN), never zero; flags loud.
    assert pd.isna(dosed.loc[0, "tan_dose_30m_j_m2"])
    assert not dosed.loc[0, "tan_dose_30m_complete"]
    assert dosed.loc[0, "tan_dose_30m_coverage_fraction"] == 0.0
    # Row 1 has one 30-min leg: finite dose, full coverage.
    assert dosed.loc[1, "tan_dose_30m_j_m2"] > 0
    assert bool(dosed.loc[1, "tan_dose_30m_complete"])
    assert dosed.loc[1, "tan_dose_30m_coverage_fraction"] == 1.0
    win = window_dose(
        frame.assign(dt=pd.to_datetime(frame["time"])),
        "2026-06-21T12:00", "2026-06-21T13:30")
    assert {"tan_dose_best_window_j_m2", "sed_best_window"}.issubset(win)
    days = day_totals(
        frame.assign(time_utc=pd.to_datetime(frame["time"], utc=True)))
    assert {"tan_dose_day_j_m2", "sed_day_total",
            "tan_dose_complete", "tan_dose_coverage_fraction"}.issubset(days.columns)


def test_sed_gap_splits_and_marks_incomplete():
    times = pd.Series(pd.to_datetime(
        ["2026-06-21T10:00Z", "2026-06-21T11:00Z",
         "2026-06-21T16:00Z", "2026-06-21T17:00Z"], utc=True))
    ery = pd.Series([0.15] * 4)  # UVI 6 equivalent
    out = integrate_sed(times, ery, max_gap_s=3 * 3600)
    assert abs(out["sed"] - 2 * 5.4) < 1e-9  # 5.4 SED per contiguous UVI-6 hour
    assert out["sed_complete"] is False
    assert 0.0 < out["sed_coverage_fraction"] < 1.0


def test_tan_response_baseline_is_cumulative_dose_only():
    import pytest

    from sunstack.tan_response import ExposureHistory, TanResponseModel

    history = ExposureHistory()
    history.add_episode(1000.0)
    history.add_episode(2000.0, interval_since_previous_s=86400.0)
    assert history.cumulative_tandose_j_m2 == 3000.0
    result = TanResponseModel().predict(history)
    assert result["tan_response_status"] == "interface-only"
    assert result["cumulative_tandose_j_m2"] == 3000.0
    assert result["predicted_response"] is None
    with pytest.raises(ValueError):
        history.add_episode(-5.0)


def test_sub_grid_windows_are_nan_not_zero():
    # Hourly grid: trailing-30m/15m doses are unknowable -> NaN (not 0, which
    # would imply no exposure); trailing-1h dose is computable.
    from sunstack.doses import add_interval_doses

    frame = pd.DataFrame({
        "time": ["2026-06-21T12:00", "2026-06-21T13:00", "2026-06-21T14:00"],
        "melanogenic_effective_irradiance_wm2": [0.5, 0.6, 0.55],
        "erythemal_irradiance_wm2": [0.15, 0.16, 0.155],
        "predicted_uva_wm2": [35.0, 40.0, 38.0],
        "predicted_uvb_wm2": [1.0, 1.1, 1.05],
    })
    dosed = add_interval_doses(frame)
    assert dosed["tan_dose_30m_j_m2"].isna().all()
    assert dosed["tan_dose_15m_j_m2"].isna().all()
    assert not dosed.loc[0, "tan_dose_30m_complete"]
    assert dosed.loc[1, "tan_dose_1h_j_m2"] > 0
    assert bool(dosed.loc[1, "tan_dose_1h_complete"])
    # Night rows with real coverage integrate as true zero, not NaN.
    night = frame.copy()
    night["melanogenic_effective_irradiance_wm2"] = 0.0
    night_dosed = add_interval_doses(night)
    assert night_dosed.loc[1, "tan_dose_1h_j_m2"] == 0.0
    assert bool(night_dosed.loc[1, "tan_dose_1h_complete"])


def test_absolute_ignores_location_while_local_uses_it():
    # §21: LocalTanScore changes with local climatology, Absolute does not.
    from sunstack.photobiology import absolute_tan_score_from_melanogenic_irradiance
    from sunstack.tanscore import add_local_scores

    e_mel = 0.75
    assert (absolute_tan_score_from_melanogenic_irradiance(e_mel, 1.6) ==
            absolute_tan_score_from_melanogenic_irradiance(e_mel, 1.6))
    ref_low = pd.DataFrame({
        "time_utc": pd.to_datetime(["2026-06-21T12:00Z"] * 500, utc=True),
        "day_of_year": [172] * 500,
        "solar_elevation_deg": [60.0] * 500,
        "absolute_tan_score_0_100": [10.0] * 500,
    })
    ref_high = ref_low.copy()
    ref_high["absolute_tan_score_0_100"] = [90.0] * 500
    fc = pd.DataFrame({
        "time_utc": pd.to_datetime(["2026-06-21T12:00Z"], utc=True),
        "solar_elevation_deg": [60.0],
        "tan_score_absolute_0_100": [50.0],
    })
    assert (add_local_scores(fc, ref_low).loc[0, "local_tan_score_0_100"] >
            add_local_scores(fc, ref_high).loc[0, "local_tan_score_0_100"])


def test_pigment_channel_never_enters_opportunity():
    from sunstack.opportunity import apply_outdoor_feasibility

    base = pd.DataFrame([{
        "tan_score_absolute_0_100": 40.0, "local_tan_score_0_100": 50.0,
        "atmospheric_quality_percentile_0_100": 50.0,
        "tan_forecast_confidence_0_100": 50.0,
        "temperature_2m": 78.0, "apparent_temperature": 78.0,
        "rain": 0.0, "showers": 0.0, "snowfall": 0.0, "precipitation": 0.0,
        "precipitation_probability": 0.0, "weather_code": 0,
        "wind_speed_10m": 5.0, "relative_humidity_2m": 50.0,
        "pigment_darkening_effective_irradiance": 0.5,
        "pigment_darkening_dose_1h_j_m2": 1800.0,
    }])
    boosted = base.copy()
    boosted["pigment_darkening_effective_irradiance"] *= 10.0
    boosted["pigment_darkening_dose_1h_j_m2"] *= 10.0
    a = apply_outdoor_feasibility(base)
    b = apply_outdoor_feasibility(boosted)
    assert (a["overall_tan_opportunity_0_100"].to_numpy() ==
            b["overall_tan_opportunity_0_100"].to_numpy()).all()
    assert (a["overall_components_unblocked_0_100"].to_numpy() ==
            b["overall_components_unblocked_0_100"].to_numpy()).all()


def test_tierB_contract_covers_every_carried_cams_field(tmp_path):
    from sunstack.spectral import emulator_manifest

    contract = emulator_manifest()["tierB_reserved_inputs"]
    for key in ("cams_aod_355", "cams_aod_400", "cams_abs_aod_380",
                "cams_ssa_355", "cams_asymmetry_400", "cams_water_vapor",
                "cams_cloud_liquid_water", "cams_cloud_ice_water",
                "cams_total_cloud", "cams_erythemal_irradiance_wm2"):
        assert key in contract, key
    # And the scored frame actually emits every contracted column.
    out = score_forecast(_best_air(), Path(tmp_path),
                         _cams([0.125, 0.1625, 0.15], [0.15, 0.175, 0.1625]),
                         _confidence())
    missing = [k for k in contract if k not in out.columns]
    assert missing == [], missing


def test_local_reference_staleness_is_loud(tmp_path):
    import json

    from sunstack.validation import validate_scored_hourly

    out = score_forecast(_best_air(), Path(tmp_path), None, _confidence())
    assert out["local_reference_stale"].all()  # no version file in tmp caldir
    warns = [i for i in validate_scored_hourly(out)
             if i.source == "local_reference"]
    assert warns and all(w.severity == "WARN" for w in warns)
    caldir = Path(tmp_path) / "cal"
    caldir.mkdir()
    (caldir / "local_reference_version.json").write_text(json.dumps(
        {"tan_score_model_version": "action-spectrum-v1"}))
    out2 = score_forecast(_best_air(), caldir, None, _confidence())
    assert not out2["local_reference_stale"].any()
    assert out2["local_reference_version"].unique().tolist() == ["action-spectrum-v1"]
