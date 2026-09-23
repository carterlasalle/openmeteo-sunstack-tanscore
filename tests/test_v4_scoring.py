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


def test_empty_window_dose_is_nan_not_zero():
    # A window containing no samples is unknowable -> NaN on every channel
    # (0.0 would claim a measured absence of sun).
    frame = pd.DataFrame({
        "dt": pd.to_datetime(["2026-06-21T12:00", "2026-06-21T13:00"]),
        "melanogenic_effective_irradiance_wm2": [0.5, 0.6],
        "erythemal_irradiance_wm2": [0.15, 0.16],
        "predicted_uva_wm2": [35.0, 40.0],
        "predicted_uvb_wm2": [1.0, 1.1],
    })
    win = window_dose(frame, "2026-06-22T12:00", "2026-06-22T13:00")
    assert pd.isna(win["tan_dose_best_window_j_m2"])
    assert pd.isna(win["sed_best_window"])
    assert pd.isna(win["uva_dose_window_j_m2"])
    assert pd.isna(win["uvb_dose_window_j_m2"])
    assert win["tan_dose_best_window_complete"] is False
    assert pd.isna(win["tan_dose_best_window_coverage_fraction"])
    assert win["sed_best_window_complete"] is False
    assert pd.isna(win["sed_best_window_coverage_fraction"])


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


def test_half_hour_keeps_constants_without_fabricating_observations():
    from sunstack.opportunity import build_30min_forecast

    hourly = pd.DataFrame({
        "time": ["2026-06-21T11:00", "2026-06-21T12:00", "2026-06-21T13:00"],
        "temperature_2m": [78.0, 82.0, 80.0],
        "shortwave_radiation_instant": [600.0, 800.0, 700.0],
        "predicted_uva_wm2": [33.0, 44.0, 38.5],
        "predicted_uvb_wm2": [0.5, 0.65, 0.6],
        "uv_index": [5.0, 6.5, 6.0],
        "overall_tan_opportunity_0_100": [28.0, 37.0, 33.0],
        "tan_score_absolute_0_100": [28.5, 37.3, 33.8],
        "melanogenic_effective_irradiance_wm2": [0.455, 0.597, 0.541],
        "erythemal_irradiance_wm2": [0.125, 0.1625, 0.15],
        "spectral_tier": ["C", "C", "C"],
        "tan_score_model_version": ["action-spectrum-v1"] * 3,
        "cams_cycle": ["2026-06-21T00:00Z"] * 3,
        "uvi_cams": [5.1, np.nan, np.nan],  # CAMS horizon ends: must stay NaN
    })
    out = build_30min_forecast(hourly, None)
    half = out.loc[out["time"] == "2026-06-21T11:30"].iloc[0]
    assert half["spectral_tier"] == "C"
    assert half["tan_score_model_version"] == "action-spectrum-v1"
    assert half["cams_cycle"] == "2026-06-21T00:00Z"
    late = out.loc[out["time"] == "2026-06-21T13:00"].iloc[0]
    assert pd.isna(late["uvi_cams"])  # never forward-filled into fabrication


def test_missing_inputs_integrate_as_unknown_not_zero():
    from sunstack.doses import add_interval_doses, day_totals

    frame = pd.DataFrame({
        "time": ["2026-06-21T12:00", "2026-06-21T12:30", "2026-06-21T13:00"],
        "uv_index": [5.0, 6.0, 5.5],
    })
    dosed = add_interval_doses(frame)  # no melanogenic column at all
    assert dosed["tan_dose_30m_j_m2"].isna().all()
    assert not dosed["tan_dose_30m_complete"].any()
    # But the erythemal path (UVI present) still integrates: no needless degrade.
    assert dosed.loc[2, "sed_30m"] > 0
    assert bool(dosed.loc[2, "sed_30m_complete"])
    days = day_totals(
        frame.assign(time_utc=pd.to_datetime(frame["time"], utc=True)))
    assert pd.isna(days.loc[0, "tan_dose_day_j_m2"])
    assert not bool(days.loc[0, "tan_dose_complete"])
    assert days.loc[0, "sed_day_total"] > 0


def test_primitive_with_no_valid_samples_is_unknown():
    from sunstack.photobiology import integrate_band_dose, integrate_tandose

    t = pd.Series(pd.to_datetime(["2026-06-21T12:00Z"], utc=True))
    out = integrate_tandose(t, pd.Series([np.nan]))
    assert pd.isna(out["tan_dose_melanogenic_j_m2"])
    assert out["tan_dose_complete"] is False
    assert out["tan_dose_coverage_fraction"] == 0.0
    solo = integrate_band_dose(
        pd.Series(pd.to_datetime(["2026-06-21T12:00Z", "2026-06-21T13:00Z"], utc=True)),
        pd.Series([0.4, np.nan]))
    assert solo["dose_j_m2"] == 0.0  # lone finite sample spans zero time
    assert solo["complete"] is False  # ...but cannot claim a complete window


def test_doctor_checks_photobiology_resources(tmp_path, capsys):
    from sunstack.cli import _global_reference_status, doctor

    ok, detail = _global_reference_status()
    assert ok and "1.6" in detail  # real repo resources resolve
    # Empty root: missing models fail loud, spectra still resolve from repo.
    assert doctor(Path(tmp_path)) is False
    out = capsys.readouterr().out
    assert "action spectra" in out
    assert "global melanogenic reference" in out
    assert "local_reference_version.json" in out  # unknown-version note


def test_doctor_flags_stale_local_reference(tmp_path, capsys):
    import json

    (Path(tmp_path) / "local_reference_version.json").write_text(json.dumps(
        {"tan_score_model_version": "legacy-55-30-15"}))
    # doctor() resolves the *default-site* calibration dir for the tmp root;
    # emulate it so the stale file is seen.
    from sunstack import cli as _cli
    from sunstack import config as _config

    real_paths = _cli._calibration_paths
    _cli._calibration_paths = lambda root, slug=None: (
        root / "x", Path(tmp_path), root / "y")
    try:
        _cli.doctor(Path(tmp_path))
    finally:
        _cli._calibration_paths = real_paths
    out = capsys.readouterr().out
    assert "STALE" in out and "rebuild_v4_references" in out
    assert _config.TAN_SCORE_MODEL_VERSION in out


def test_tierAB_claim_without_manifest_fails_loud(tmp_path, monkeypatch):
    import pytest

    import sunstack.spectral as _spectral
    from sunstack.tanscore import score_forecast

    monkeypatch.setattr(_spectral, "spectral_tier_for_row",
                        lambda *a, **k: "B")
    with pytest.raises(RuntimeError, match="no emulator manifest"):
        score_forecast(_best_air(), Path(tmp_path), None, _confidence())


def test_best_hour_dose_integrates_full_hour():
    # Constant E_mel over a full hour must dose E*3600 (the old exclusive end
    # integrated only 30 minutes here).
    from sunstack.doses import window_dose

    stamps = pd.date_range("2026-06-21 12:00", periods=3, freq="30min")
    frame = pd.DataFrame({
        "dt": stamps,
        "time": stamps.strftime("%Y-%m-%dT%H:%M"),
        "melanogenic_effective_irradiance_wm2": [0.5, 0.5, 0.5],
        "erythemal_irradiance_wm2": [0.15, 0.15, 0.15],
        "predicted_uva_wm2": [35.0] * 3,
        "predicted_uvb_wm2": [1.0] * 3,
    })
    got = window_dose(frame, stamps[0], stamps[0] + pd.Timedelta(minutes=60))
    assert abs(got["tan_dose_best_window_j_m2"] - 0.5 * 3600) < 1e-6
    assert abs(got["sed_best_window"] - 0.15 * 3600 / 100) < 1e-9


def test_best_30m_dose_belongs_to_forward_interval():
    from sunstack.doses import add_interval_doses
    from sunstack.opportunity import build_daily_summary

    dts = pd.date_range("2026-06-21 11:00", periods=5, freq="30min")
    frame = pd.DataFrame({
        "dt": dts,
        "time": dts.strftime("%Y-%m-%dT%H:%M"),
        "overall_tan_opportunity_0_100": [10.0, 90.0, 10.0, 10.0, 10.0],
        "outdoor_blocked": [False] * 5,
        "temperature_2m": [80.0] * 5,
        "apparent_temperature": [80.0] * 5,
        "wind_speed_10m": [5.0] * 5,
        "wind_gusts_10m": [6.0] * 5,
        "melanogenic_effective_irradiance_wm2": [1.0, 1.0, 0.0, 0.0, 0.0],
        "erythemal_irradiance_wm2": [0.1, 0.1, 0.0, 0.0, 0.0],
        "predicted_uva_wm2": [30.0] * 5,
        "predicted_uvb_wm2": [0.5] * 5,
    })
    out = build_daily_summary(add_interval_doses(frame))
    row = out.iloc[0]
    # Best slot starts 11:30; its forward half hour [11:30, 12:00) doses the
    # 1.0->0.0 leg: 0.5*1.0*1800 = 900, not the trailing 1800 ending at 11:30.
    assert abs(row["best_30m_tan_dose_j_m2"] - 900.0) < 1e-6


def test_day_totals_use_wall_date_without_time_utc(monkeypatch):
    from sunstack import config as _config
    from sunstack.doses import day_totals

    monkeypatch.setattr(_config, "TIMEZONE", "America/Los_Angeles")
    stamps = ([f"2026-06-21T{h:02d}:{m:02d}"
               for h in range(7) for m in (0, 30)] +
              ["2026-06-21T12:00"])
    frame = pd.DataFrame({
        "time": stamps,
        "melanogenic_effective_irradiance_wm2": [0.4] * len(stamps),
        "erythemal_irradiance_wm2": [0.1] * len(stamps),
        "predicted_uva_wm2": [30.0] * len(stamps),
        "predicted_uvb_wm2": [0.5] * len(stamps),
    })
    days = day_totals(frame)
    assert len(days) == 1 and days.loc[0, "date"] == "2026-06-21"
    assert days.loc[0, "tan_dose_day_j_m2"] > 0


def test_configured_gap_threshold_reaches_day_and_window(monkeypatch):
    from sunstack import config as _config
    from sunstack.doses import day_totals, window_dose

    stamps = pd.to_datetime(
        ["2026-06-21T10:00", "2026-06-21T11:00",
         "2026-06-21T13:00", "2026-06-21T14:00"])
    frame = pd.DataFrame({
        "time": stamps.strftime("%Y-%m-%dT%H:%M"),
        "time_utc": stamps.tz_localize("UTC"),
        "melanogenic_effective_irradiance_wm2": [0.5] * 4,
        "erythemal_irradiance_wm2": [0.15] * 4,
        "predicted_uva_wm2": [35.0] * 4,
        "predicted_uvb_wm2": [1.0] * 4,
    })
    assert window_dose(frame, stamps[0], stamps[3])["tan_dose_best_window_j_m2"] > 0
    assert day_totals(frame).loc[0, "tan_dose_complete"]
    monkeypatch.setattr(_config, "TANDOSE_MAX_INTERP_GAP_S", 3600.0)
    split = window_dose(frame, stamps[0], stamps[3])
    assert split["tan_dose_best_window_j_m2"] == 2 * 0.5 * 3600
    days = day_totals(frame)
    assert not bool(days.loc[0, "tan_dose_complete"])
    assert days.loc[0, "tan_dose_coverage_fraction"] < 1.0


def test_daily_summary_carries_sed_completeness():
    from sunstack.doses import add_interval_doses
    from sunstack.opportunity import build_daily_summary

    out = build_daily_summary(add_interval_doses(_half_hour_frame(1.0)))
    row = out.iloc[0]
    assert "sed_complete" in out.columns and "sed_coverage_fraction" in out.columns
    assert bool(row["sed_complete"])
    assert row["sed_coverage_fraction"] == 1.0


def test_daily_summary_carries_window_completeness():
    # Window/hour doses must expose the same complete/coverage contract as
    # day/interval doses; a window with a missing endpoint is partial, and
    # each channel reports independently.
    from sunstack.doses import add_interval_doses, window_dose
    from sunstack.opportunity import build_daily_summary

    out = build_daily_summary(add_interval_doses(_half_hour_frame(1.0)))
    row = out.iloc[0]
    for col in ("tan_dose_best_window_complete",
                "tan_dose_best_window_coverage_fraction",
                "sed_best_window_complete",
                "sed_best_window_coverage_fraction",
                "best_hour_tan_dose_complete",
                "best_hour_tan_dose_coverage_fraction",
                "best_hour_sed_complete",
                "best_hour_sed_coverage_fraction"):
        assert col in out.columns, col
    assert bool(row["tan_dose_best_window_complete"])
    assert row["tan_dose_best_window_coverage_fraction"] == 1.0
    assert bool(row["sed_best_window_complete"])
    assert bool(row["best_hour_tan_dose_complete"])

    gappy = _half_hour_frame(1.0)
    gappy.loc[7, "melanogenic_effective_irradiance_wm2"] = np.nan
    dts = pd.to_datetime(gappy["dt"])
    win = window_dose(gappy, dts.iloc[0], dts.iloc[-1])
    assert not win["tan_dose_best_window_complete"]
    assert win["tan_dose_best_window_coverage_fraction"] < 1.0
    assert win["sed_best_window_complete"]


def test_day_dose_failure_defaults_to_incomplete(monkeypatch):
    from sunstack import doses as _doses
    from sunstack.opportunity import build_daily_summary

    def _boom(frame):
        raise RuntimeError("no climatology")

    monkeypatch.setattr(_doses, "day_totals", _boom)
    out = build_daily_summary(_half_hour_frame(1.0))
    row = out.iloc[0]
    assert pd.isna(row["tan_dose_day_j_m2"])
    assert not bool(row["tan_dose_complete"])
    assert pd.isna(row["tan_dose_coverage_fraction"])


def test_stale_reference_yields_no_local_percentiles(tmp_path):
    import json

    import pandas as pd

    from sunstack.tanscore import score_forecast

    caldir = Path(tmp_path)
    (caldir / "local_reference_version.json").write_text(json.dumps(
        {"tan_score_model_version": "legacy-55-30-15",
         "global_reference_version": "global-mel-ref-v1-provisional",
         "global_reference_e_mel_wm2": 1.6}))
    ref = pd.DataFrame({
        "time_utc": pd.to_datetime(["2026-06-21T12:00Z"] * 300, utc=True),
        "day_of_year": [172] * 300,
        "solar_elevation_deg": [60.0] * 300,
        "absolute_tan_score_0_100": [10.0] * 300,
    })
    ref.to_parquet(caldir / "local_reference.parquet", index=False)
    out = score_forecast(_best_air(), caldir, None, _confidence())
    assert out["local_tan_score_0_100"].isna().all()
    assert out["local_reference_stale"].all()


def test_reference_value_override_flags_stale(tmp_path):
    import json

    from sunstack.tanscore import score_forecast

    caldir = Path(tmp_path)
    (caldir / "local_reference_version.json").write_text(json.dumps(
        {"tan_score_model_version": "action-spectrum-v1",
         "global_reference_version": "global-mel-ref-v1-provisional",
         "global_reference_e_mel_wm2": 999.0}))
    out = score_forecast(_best_air(), caldir, None, _confidence())
    assert out["local_reference_stale"].all()
    assert out["local_tan_score_0_100"].isna().all()


def test_interval_ics_closes_events_and_skips_night(tmp_path):
    from sunstack.output import export_static_site
    from sunstack.ui import build_interval_ics

    half = pd.DataFrame({
        "time": ["2026-09-15T12:00", "2026-09-15T12:30", "2026-09-15T02:00"],
        "tan_score_absolute_0_100": [40.0, 42.0, 0.0],
        "overall_tan_opportunity_0_100": [50.0, 55.0, 0.0],
        "tan_dose_30m_j_m2": [900.0, 950.0, 0.0],
        "sed_30m": [2.5, 2.6, 0.0],
        "uv_index": [5.0, 5.2, 0.0],
        "is_day": [1, 1, 0],
        "subhour_source": ["interpolated_hourly"] * 3,
    })
    ics = build_interval_ics(half, "20260915_004803")
    assert ics.count("BEGIN:VEVENT") == 3
    assert ics.count("END:VEVENT") == 3

    latest = tmp_path / "latest"
    (latest / "tables").mkdir(parents=True)
    hourly = pd.DataFrame({
        "time": ["2026-09-15T12:00", "2026-09-15T02:00"],
        "temperature_2m": [80.0, 60.0],
        "overall_tan_opportunity_0_100": [50.0, 0.0],
        "tan_score_absolute_0_100": [40.0, 0.0],
        "local_tan_score_0_100": [80.0, 5.0],
        "atmospheric_quality_percentile_0_100": [60.0, 5.0],
        "tan_forecast_confidence_0_100": [50.0, 10.0],
    })
    dayhalf = pd.DataFrame({
        "dt": pd.to_datetime(["2026-09-15 12:00", "2026-09-15 12:30",
                              "2026-09-15 02:00", "2026-09-15 02:30"]),
        "time": ["2026-09-15T12:00", "2026-09-15T12:30",
                 "2026-09-15T02:00", "2026-09-15T02:30"],
        "temperature_2m": [80.0, 81.0, 60.0, 60.0],
        "overall_tan_opportunity_0_100": [50.0, 55.0, 0.0, 0.0],
        "tan_score_absolute_0_100": [40.0, 42.0, 0.0, 0.0],
        "local_tan_score_0_100": [80.0, 82.0, 5.0, 5.0],
        "atmospheric_quality_percentile_0_100": [60.0, 62.0, 5.0, 5.0],
        "tan_forecast_confidence_0_100": [50.0, 52.0, 10.0, 10.0],
        "uv_index": [5.0, 5.2, 0.0, 0.0],
        "is_day": [1, 1, 0, 0],
    })
    hourly.to_parquet(latest / "tables" / "tan_forecast_hourly.parquet", index=False)
    dayhalf.to_parquet(latest / "tables" / "tan_forecast_30min.parquet", index=False)
    (latest / "summary.json").write_text(
        '{"run": "test123", "created_at": "2026-09-15T00:00:00-04:00"}')
    export_static_site(tmp_path, tmp_path / "site")
    site_ics = (tmp_path / "site" / "calendar-30min.ics").read_text()
    assert site_ics.count("BEGIN:VEVENT") == 2
    assert site_ics.count("END:VEVENT") == 2
    assert "02:00" not in site_ics


def test_compare_guards_pre_v4_secondary_input(tmp_path, monkeypatch):
    import sys

    sys.path.insert(0, "src")
    from scripts.compare_legacy_v4 import main as _compare_main

    hourly2 = tmp_path / "hourly2.parquet"
    pd.DataFrame({
        "time": ["2026-09-15T12:00"],
        "predicted_uva_wm2": [30.0],
        "predicted_uvb_wm2": [0.5],
    }).to_parquet(hourly2, index=False)
    out = tmp_path / "report.md"
    monkeypatch.setattr(sys, "argv", ["compare", "--hourly",
                                      "data/calibration/training_calibration_hourly.parquet",
                                      "--hourly2", str(hourly2),
                                      "--out", str(out)])
    _compare_main()
    text = out.read_text(encoding="utf-8")
    assert "predates v4" in text


def test_version_constants_have_single_source():
    from sunstack import config as _config
    from sunstack import photobiology as _pb

    assert _config.TAN_SCORE_MODEL_VERSION == _pb.TAN_SCORE_MODEL_VERSION
    assert _config.TAN_SCORE_MODEL_VERSION == _pb.PHOTOBIOLOGY_MODEL_VERSION
    assert _config.TAN_SCORE_MODEL_VERSION == _pb.TAN_DOSE_MODEL_VERSION


def test_canonical_env_parsing_is_explicit():
    import subprocess

    for value, want in (
        ("off", "False"), ("", "False"), ("0", "False"),
        ("no", "False"), ("1", "True"), ("yes", "True"),
        ("YES", "True"),
    ):
        proc = subprocess.run(
            ["python3", "-c",
             ("import sys; sys.path.insert(0, 'src'); "
              "from sunstack import config; print(config.REQUIRE_CANONICAL_SPECTRUM)")],
            capture_output=True, text=True, check=False, env={
                "PATH": "/usr/bin:/bin", "SUNSTACK_REQUIRE_CANONICAL_SPECTRUM": value,
                "HOME": "/home/ubuntu"},
        )
        assert proc.stdout.strip() == want, (value, proc.stdout, proc.stderr)


def _load_script(name):
    import importlib.util

    spec = importlib.util.spec_from_file_location(name, f"scripts/{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_rebuild_adopt_orders_manifest_before_references(tmp_path, monkeypatch):
    import json
    import sys

    import numpy as np
    import pandas as pd
    import yaml

    (tmp_path / "locations.yaml").write_text(yaml.safe_dump(
        [{"slug": "town", "name": "Town", "lat": 40.0, "lon": -80.0,
          "timezone": "UTC", "enabled": True, "default": True}]),
        encoding="utf-8")
    caldir = tmp_path / "data" / "calibration"
    caldir.mkdir(parents=True)
    n = 400
    stamps = pd.date_range("2020-06-01", periods=n, freq="h", tz="UTC")
    pd.DataFrame({
        "time_utc": stamps,
        "uva": np.linspace(0, 45, n),
        "uvb": np.linspace(0, 1.2, n),
        "uvi": np.linspace(0, 8, n),
        "sza": np.linspace(85, 20, n),
        "ghi": np.linspace(5, 900, n),
    }).to_parquet(caldir / "training_calibration_hourly.parquet", index=False)
    refdir = caldir / "global_melanogenic_reference"
    refdir.mkdir(parents=True)
    (refdir / "reference.json").write_text(json.dumps(
        {"global_reference_e_mel_wm2": 1.6,
         "global_reference_version": "global-mel-ref-v1-provisional"}),
        encoding="utf-8")
    rb = _load_script("rebuild_v4_references")
    # The script legitimately mutates global config when adopting; pin the
    # originals here so teardown restores them for every other test.
    import sunstack.config as _sconfig

    monkeypatch.setattr(_sconfig, "GLOBAL_MELANOGENIC_REFERENCE_WM2",
                        _sconfig.GLOBAL_MELANOGENIC_REFERENCE_WM2)
    monkeypatch.setattr(_sconfig, "GLOBAL_MELANOGENIC_REFERENCE_VERSION",
                        _sconfig.GLOBAL_MELANOGENIC_REFERENCE_VERSION)
    monkeypatch.setattr(sys, "argv",
                        ["rebuild", "--root", str(tmp_path),
                         "--adopt-empirical-p999", "--new-version", "test-v9"])
    rb.main()
    manifest = json.loads((refdir / "reference.json").read_text(encoding="utf-8"))
    assert manifest["global_reference_version"] == "test-v9"
    assert manifest["global_reference_e_mel_wm2"] == manifest["empirical_two_site_grounding"]["distribution"]["p99.9"]
    ver = json.loads((caldir / "local_reference_version.json").read_text(encoding="utf-8"))
    assert ver["global_reference_version"] == "test-v9"
    assert ver["global_reference_e_mel_wm2"] == manifest["global_reference_e_mel_wm2"]
    check = pd.read_parquet(caldir / "local_reference.parquet")
    e = check["melanogenic_effective_irradiance_wm2"].to_numpy(dtype=float)
    # Builder clips scores at 100 (adopted ref == p99.9 < p100max). Tolerance
    # covers last-ulp drift: the builder scores unrounded E_mel while the
    # parquet stores it rounded to 1e-5, which can flip a 0.1 rounding boundary.
    got = check["absolute_tan_score_0_100"].to_numpy(dtype=float)
    expect = np.clip(np.round(100.0 * e / manifest["global_reference_e_mel_wm2"], 1),
                     0, 100)
    assert np.allclose(got, expect, atol=0.11, equal_nan=True)
    # Sensitivity guard: the OLD reference must NOT explain these scores.
    stale = np.clip(np.round(100.0 * e / 1.6, 1), 0, 100)
    assert not np.allclose(got, stale, atol=0.11, equal_nan=True)


def test_corpus_builder_survives_empty_uvspec_output(tmp_path, monkeypatch):
    import json
    import shutil
    import subprocess
    import sys

    rb = _load_script("build_spectral_corpus")

    class _Done:
        stdout = ""
        stderr = ""

    monkeypatch.setattr(shutil, "which", lambda name: "/fake/uvspec")
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: _Done())
    monkeypatch.setattr(sys, "argv",
                        ["build", "--samples", "8", "--out", str(tmp_path / "corpus")])
    rb.main()
    manifest = json.loads((tmp_path / "corpus" / "manifest.json").read_text(encoding="utf-8"))
    # Fake binary present but versionless: no crash, design + manifest land.
    assert manifest["status"] == "ready-to-run"
    assert manifest["libRadtran"] == "uvspec-found-version-unknown"
    assert (tmp_path / "corpus" / "design.csv").exists()


def test_offline_corpus_design_is_deterministic_but_not_tierB(tmp_path, monkeypatch):
    # Without libRadtran the builder's artifact is the deterministic design +
    # manifest (never fake spectra), and that manifest must NOT satisfy the
    # Tier-B admission contract.
    import json
    import sys

    import pytest

    from sunstack.spectral import validate_tierB_manifest

    rb = _load_script("build_spectral_corpus")
    outs = []
    for i in (1, 2):
        out = tmp_path / f"corpus{i}"
        monkeypatch.setattr(sys, "argv",
                            ["build", "--samples", "16", "--seed", "7",
                             "--out", str(out)])
        rb.main()
        outs.append(out)
    assert (outs[0] / "design.csv").read_bytes() == (outs[1] / "design.csv").read_bytes()
    manifest = json.loads((outs[0] / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["status"] == "spectra-pending"
    with pytest.raises(ValueError, match="Tier-B manifest"):
        validate_tierB_manifest(manifest)


def test_closure_requires_canonical_utc(tmp_path, monkeypatch):
    import sys

    rb = _load_script("validate_external")
    latest = tmp_path / "latest"
    latest.mkdir(parents=True)
    cams = pd.DataFrame({
        "time_utc": pd.date_range("2026-09-22 12:00", periods=6, freq="h", tz="UTC"),
        "cams_uv_biologically_effective_dose": [0.05] * 6,
        "cams_uv_biologically_effective_dose_clear_sky": [0.06] * 6,
    })
    hourly = pd.DataFrame({
        "time": ["2026-09-22T12:00"] * 6,  # naive local-looking, NO time_utc
        "uv_index": [2.0] * 6,
    })
    cams.to_parquet(latest / "cams_direct_forecast.parquet", index=False)
    hourly.to_parquet(latest / "tan_forecast_hourly.parquet", index=False)
    (tmp_path / "cal").mkdir()
    (tmp_path / "cal" / "model_metrics.json").write_text(
        '{"rows": 0, "validation_split_year": 2024}')
    out = tmp_path / "report.md"
    monkeypatch.setattr(sys, "argv",
                        ["validate", "--latest", str(latest),
                         "--calibration", str(tmp_path / "cal"),
                         "--out", str(out)])
    rb.main()
    text = out.read_text(encoding="utf-8")
    assert "never parsed as UTC" in text
    assert "calibration_sources archive tables not present" in text


def test_csv_export_covers_all_days_with_v4_columns():
    # Merge-resolution pin: upstream's all-days export combined with the
    # v4-extended column sets. If either side regresses, this fails loudly
    # instead of silently shipping a narrowed or de-columned export.
    from sunstack.ui import HTML

    assert "sunstack-all-hourly.csv" in HTML
    assert "sunstack-all-30min.csv" in HTML
    assert "sunstack-all-days.csv" in HTML
    assert "DATA.hourly||[]" in HTML.replace(" ", "")
    assert "DATA.half_hour||[]" in HTML.replace(" ", "")
    for col in ("melanogenic_effective_irradiance_wm2",
                "tan_dose_30m_j_m2", "sed_30m",
                "tan_dose_best_window_j_m2", "sed_day_total",
                "tan_dose_best_window_complete",
                "tan_dose_best_window_coverage_fraction",
                "sed_best_window_complete",
                "sed_best_window_coverage_fraction",
                "legacy_absolute_tan_score_55_30_15"):
        assert col in HTML, col


def test_all_days_csv_head_matches_daily_row_keys():
    # The all-days CSV head is a fixed list inside the dashboard template;
    # every key it reads must exist on the daily summary rows (a head/row
    # drift would silently export `undefined` columns).
    import re

    from sunstack.doses import add_interval_doses
    from sunstack.opportunity import build_daily_summary
    from sunstack.ui import HTML

    m = re.search(r"const dHead=\[(.*?)\]", HTML)
    assert m, "dHead export head not found in dashboard template"
    head = re.findall(r"'([^']+)'", m.group(1))
    assert len(head) > 10, head
    row_keys = set(build_daily_summary(
        add_interval_doses(_half_hour_frame(1.0))).iloc[0].index)
    missing = [k for k in head if k not in row_keys]
    assert not missing, missing


def test_cli_personal_mmd_flags_and_threading():
    import inspect

    from sunstack import cli as _cli

    for fn in (_cli.run_live, _cli._run_live_inner, _cli.run_one_site,
               _cli._run_all_sites):
        params = inspect.signature(fn).parameters
        assert "personal_mmd_j_m2" in params, fn.__name__
        assert "personal_mmd_basis" in params, fn.__name__
    ns = _cli._build_parser().parse_args(
        ["run", "--personal-mmd", "2500", "--personal-mmd-basis", "MEASURED"])
    assert ns.personal_mmd == 2500.0
    assert ns.personal_mmd_basis == "MEASURED"
    plain = _cli._build_parser().parse_args(["run"])
    assert plain.personal_mmd is None and plain.personal_mmd_basis is None
    import pytest

    with pytest.raises(SystemExit):
        _cli._build_parser().parse_args(
            ["run", "--personal-mmd-basis", "FOLKLORE"])


def test_personal_mmd_fraction_on_live_shaped_frame():
    import pandas as pd
    import pytest

    from sunstack.opportunity import attach_personalization

    src = Path("data/latest/tables/tan_forecast_hourly.parquet")
    if not src.exists():
        pytest.skip("needs a local live run (gitignored data/)")
    h = pd.read_parquet(src)
    out = attach_personalization(h, personal_mmd_j_m2=12000.0, basis="MEASURED")
    frac = pd.to_numeric(out["personal_mmd_fraction"], errors="coerce")
    assert float(frac.notna().mean()) > 0.9
    for col in ("tan_score_absolute_0_100", "tan_dose_1h_j_m2",
                "melanogenic_effective_irradiance_wm2"):
        a = out[col].to_numpy()
        b = h[col].to_numpy()
        assert bool(((a == b) | (pd.isna(a) & pd.isna(b))).all()), col


def test_parse_personal_mmd_is_loud():
    import pytest

    from sunstack.ui import _parse_personal_mmd

    assert _parse_personal_mmd("", "") == (None, None)
    assert _parse_personal_mmd(None, None) == (None, None)
    assert _parse_personal_mmd("12000", "MEASURED") == (12000.0, "MEASURED")
    with pytest.raises(ValueError, match="provenance|basis"):
        _parse_personal_mmd("12000", "")
    with pytest.raises(ValueError, match="one of"):
        _parse_personal_mmd("12000", "FOLKLORE")
    with pytest.raises(ValueError, match="number"):
        _parse_personal_mmd("a lot", "MEASURED")
    for bad in ("0", "-5", "nan", "inf"):
        with pytest.raises(ValueError, match="positive finite"):
            _parse_personal_mmd(bad, "MEASURED")


def _payload_fixture(tmp_path):
    latest = tmp_path / "latest"
    (latest / "tables").mkdir(parents=True)
    dts = pd.date_range("2026-09-15 11:00", periods=6, freq="30min")
    hourly = pd.DataFrame({
        "time": ["2026-09-15T11:00", "2026-09-15T12:00", "2026-09-15T13:00"],
        "temperature_2m": [80.0, 82.0, 81.0],
        "overall_tan_opportunity_0_100": [40.0, 60.0, 50.0],
        "tan_score_absolute_0_100": [35.0, 45.0, 40.0],
        "local_tan_score_0_100": [80.0, 85.0, 82.0],
        "atmospheric_quality_percentile_0_100": [60.0, 65.0, 62.0],
        "tan_forecast_confidence_0_100": [50.0, 55.0, 52.0],
        "tan_dose_1h_j_m2": [1000.0, 2000.0, 1500.0],
        "melanogenic_effective_irradiance_wm2": [0.4, 0.5, 0.45],
    })
    half = pd.DataFrame({
        "dt": dts,
        "time": dts.strftime("%Y-%m-%dT%H:%M"),
        "temperature_2m": [80.0] * 6,
        "overall_tan_opportunity_0_100": [40.0, 45.0, 60.0, 58.0, 50.0, 48.0],
        "tan_score_absolute_0_100": [35.0, 38.0, 45.0, 44.0, 40.0, 39.0],
        "local_tan_score_0_100": [80.0] * 6,
        "atmospheric_quality_percentile_0_100": [60.0] * 6,
        "tan_forecast_confidence_0_100": [50.0] * 6,
        "tan_dose_30m_j_m2": [500.0, 800.0, 1000.0, 900.0, 700.0, 600.0],
        "melanogenic_effective_irradiance_wm2": [0.4] * 6,
        "apparent_temperature": [80.0] * 6,
        "wind_speed_10m": [5.0] * 6,
        "wind_gusts_10m": [6.0] * 6,
        "outdoor_blocked": [False] * 6,
    })
    hourly.to_parquet(latest / "tables" / "tan_forecast_hourly.parquet", index=False)
    half.to_parquet(latest / "tables" / "tan_forecast_30min.parquet", index=False)
    (latest / "summary.json").write_text(
        '{"run": "mmdtest", "created_at": "2026-09-15T00:00:00-04:00"}')
    return tmp_path


def test_filtered_payload_personal_mmd(tmp_path):
    from sunstack.ui import _filtered_payload

    root = _payload_fixture(tmp_path)
    _, hourly, half, _, _ = _filtered_payload(root, None, None, None, 2000.0, "MEASURED")
    assert (hourly["personal_mmd_fraction"].to_numpy() ==
            np.array([0.5, 1.0, 0.75])).all()
    assert (hourly["personalization_basis"] == "MEASURED").all()
    assert (half["personal_mmd_fraction"].to_numpy()[:3] ==
            np.array([0.25, 0.4, 0.5])).all()
    _, plain_hourly, _, _, _ = _filtered_payload(root, None, None, None)
    assert plain_hourly["personal_mmd_fraction"].isna().all()
    assert (plain_hourly["tan_dose_1h_j_m2"].to_numpy() ==
            hourly["tan_dose_1h_j_m2"].to_numpy()).all()


def _api_fixture(tmp_path):
    import pandas as pd

    latest = tmp_path / "latest"
    (latest / "tables").mkdir(parents=True)
    dts = pd.date_range("2026-09-15 11:00", periods=6, freq="30min")
    pd.DataFrame({
        "time": ["2026-09-15T11:00", "2026-09-15T12:00", "2026-09-15T13:00"],
        "temperature_2m": [80.0, 82.0, 81.0],
        "overall_tan_opportunity_0_100": [40.0, 60.0, 50.0],
        "tan_score_absolute_0_100": [35.0, 45.0, 40.0],
        "local_tan_score_0_100": [80.0, 85.0, 82.0],
        "atmospheric_quality_percentile_0_100": [60.0, 65.0, 62.0],
        "tan_forecast_confidence_0_100": [50.0, 55.0, 52.0],
        "tan_dose_1h_j_m2": [1000.0, 2000.0, 1500.0],
        "melanogenic_effective_irradiance_wm2": [0.4, 0.5, 0.45],
    }).to_parquet(latest / "tables" / "tan_forecast_hourly.parquet", index=False)
    pd.DataFrame({
        "dt": dts,
        "time": dts.strftime("%Y-%m-%dT%H:%M"),
        "temperature_2m": [80.0] * 6,
        "overall_tan_opportunity_0_100": [40.0, 45.0, 60.0, 58.0, 50.0, 48.0],
        "tan_score_absolute_0_100": [35.0, 38.0, 45.0, 44.0, 40.0, 39.0],
        "local_tan_score_0_100": [80.0] * 6,
        "atmospheric_quality_percentile_0_100": [60.0] * 6,
        "tan_forecast_confidence_0_100": [50.0] * 6,
        "tan_dose_30m_j_m2": [500.0, 800.0, 1000.0, 900.0, 700.0, 600.0],
        "melanogenic_effective_irradiance_wm2": [0.4] * 6,
        "apparent_temperature": [80.0] * 6,
        "wind_speed_10m": [5.0] * 6,
        "wind_gusts_10m": [6.0] * 6,
        "outdoor_blocked": [False] * 6,
    }).to_parquet(latest / "tables" / "tan_forecast_30min.parquet", index=False)
    (latest / "summary.json").write_text(
        '{"run": "apitest", "created_at": "2026-09-15T00:00:00-04:00"}')
    return tmp_path


def test_api_data_personal_mmd(tmp_path):
    import pytest

    try:
        from fastapi.testclient import TestClient
    except (ImportError, RuntimeError):
        # RuntimeError: starlette raises (not ImportError) when httpx is
        # absent, so importorskip alone cannot guard this import.
        pytest.skip("httpx/TestClient not installed")

    from sunstack.ui import create_app

    client = TestClient(create_app(_api_fixture(tmp_path)))
    plain = client.get("/api/data", params={"location": "south-bend"})
    assert plain.status_code == 200, plain.text
    assert plain.json()["hourly"][0]["personal_mmd_fraction"] is None
    mmd = client.get("/api/data", params={
        "location": "south-bend", "personal_mmd": "2000",
        "personal_mmd_basis": "MEASURED"})
    assert mmd.status_code == 200, mmd.text
    rows = mmd.json()["hourly"]
    assert [r["personal_mmd_fraction"] for r in rows] == [0.5, 1.0, 0.75]
    assert {r["personalization_basis"] for r in rows} == {"MEASURED"}
    bad = client.get("/api/data", params={
        "location": "south-bend", "personal_mmd": "2000",
        "personal_mmd_basis": "FOLKLORE"})
    assert bad.status_code == 400
    assert "one of" in bad.json()["detail"]
    unlabeled = client.get("/api/data", params={
        "location": "south-bend", "personal_mmd": "2000"})
    assert unlabeled.status_code == 400


def test_api_refresh_rejects_bad_mmd_without_running(tmp_path):
    import pytest

    try:
        from fastapi.testclient import TestClient
    except (ImportError, RuntimeError):
        # RuntimeError: starlette raises (not ImportError) when httpx is
        # absent, so importorskip alone cannot guard this import.
        pytest.skip("httpx/TestClient not installed")

    from sunstack.ui import create_app

    client = TestClient(create_app(_api_fixture(tmp_path)))
    bad = client.post("/api/refresh", params={
        "location": "south-bend", "personal_mmd": "2000",
        "personal_mmd_basis": "FOLKLORE"})
    assert bad.status_code == 400
    assert "one of" in bad.json()["detail"]


def test_export_bakes_personal_mmd_when_asked(tmp_path):
    from sunstack.output import export_static_site

    root = _api_fixture(tmp_path)
    export_static_site(root, tmp_path / "plain")
    import json as _json

    payload = _json.loads((tmp_path / "plain" / "data.json").read_text())
    assert payload["hourly"][0]["personal_mmd_fraction"] is None
    export_static_site(root, tmp_path / "pers", personal_mmd_j_m2=2000.0,
                       personal_mmd_basis="MEASURED")
    payload = _json.loads((tmp_path / "pers" / "data.json").read_text())
    assert [r["personal_mmd_fraction"] for r in payload["hourly"]] == [0.5, 1.0, 0.75]
    assert payload["half_hour"][0]["personalization_basis"] == "MEASURED"


def test_rescore_gate_exits_on_validation_errors(tmp_path, monkeypatch):
    import sys

    rb = _load_script("rescore_latest_v4")
    tdir = tmp_path / "sites" / "pacific-palisades" / "latest" / "tables"
    tdir.mkdir(parents=True)
    (tmp_path / "sites" / "pacific-palisades" / "calibration").mkdir(parents=True)
    times = ["2026-09-22T12:00", "2026-09-22T13:00", "2026-09-22T14:00"]
    pd.DataFrame({
        "time": times,
        "shortwave_radiation": [600.0, 700.0, 650.0],
        "direct_normal_irradiance": [700.0, 750.0, 720.0],
        "diffuse_radiation": [100.0, 110.0, 105.0],
        "terrestrial_radiation": [1000.0, 1050.0, 1020.0],
        "cloud_cover": [10.0, 15.0, 12.0],
        "temperature_2m": [78.0, 80.0, 79.0],
        "relative_humidity_2m": [50.0, 48.0, 49.0],
        "surface_pressure": [10000.0] * 3,
        "uv_index": [float("nan")] * 3,  # unknown UVI, not night
        "uv_index_clear_sky": [6.0, 6.5, 6.2],
        "is_day": [1, 1, 1],
        "precipitation_probability": [0.0] * 3,
    }).to_parquet(tdir / "best_match_enriched.parquet", index=False)
    pd.DataFrame().to_parquet(tdir / "cams_direct_forecast.parquet", index=False)
    pd.DataFrame({
        "time": times,
        "sun_window_confidence_0_100": [float("nan")] * 3,
    }).to_parquet(tdir / "best_sun_windows.parquet", index=False)
    pd.DataFrame().to_parquet(tdir / "hrrr_native_15min.parquet", index=False)
    report = tmp_path / "report.md"
    monkeypatch.setattr(sys, "argv",
                        ["rescore", "--site", "pacific-palisades",
                         "--root", str(tmp_path),
                         "--out", str(tmp_path / "out"),
                         "--report", str(report)])
    import pytest

    with pytest.raises(SystemExit, match="v4 validation errors"):
        rb.main()
    assert not report.exists()


def test_rescore_tolerates_missing_cams_artifact(tmp_path, monkeypatch, capsys):
    # Degraded (CAMS-less) runs write no cams_direct_forecast artifact; the
    # rescore must degrade to an empty frame (loudly) instead of crashing
    # with FileNotFoundError before its validation gate runs.
    import sys

    rb = _load_script("rescore_latest_v4")
    tdir = tmp_path / "sites" / "pacific-palisades" / "latest" / "tables"
    tdir.mkdir(parents=True)
    (tmp_path / "sites" / "pacific-palisades" / "calibration").mkdir(parents=True)
    times = ["2026-09-22T12:00", "2026-09-22T13:00", "2026-09-22T14:00"]
    pd.DataFrame({
        "time": times,
        "shortwave_radiation": [600.0, 700.0, 650.0],
        "direct_normal_irradiance": [700.0, 750.0, 720.0],
        "diffuse_radiation": [100.0, 110.0, 105.0],
        "terrestrial_radiation": [1000.0, 1050.0, 1020.0],
        "cloud_cover": [10.0, 15.0, 12.0],
        "temperature_2m": [78.0, 80.0, 79.0],
        "relative_humidity_2m": [50.0, 48.0, 49.0],
        "surface_pressure": [10000.0] * 3,
        "uv_index": [float("nan")] * 3,  # unknown UVI, not night
        "uv_index_clear_sky": [6.0, 6.5, 6.2],
        "is_day": [1, 1, 1],
        "precipitation_probability": [0.0] * 3,
    }).to_parquet(tdir / "best_match_enriched.parquet", index=False)
    # NOTE: no cams_direct_forecast.parquet — the degraded-run condition.
    pd.DataFrame({
        "time": times,
        "sun_window_confidence_0_100": [float("nan")] * 3,
    }).to_parquet(tdir / "best_sun_windows.parquet", index=False)
    pd.DataFrame().to_parquet(tdir / "hrrr_native_15min.parquet", index=False)
    report = tmp_path / "report.md"
    monkeypatch.setattr(sys, "argv",
                        ["rescore", "--site", "pacific-palisades",
                         "--root", str(tmp_path),
                         "--out", str(tmp_path / "out"),
                         "--report", str(report)])
    import pytest

    with pytest.raises(SystemExit, match="v4 validation errors"):
        rb.main()
    assert "degraded run" in capsys.readouterr().out
    assert not report.exists()


def test_site_stack_corruption_raises_without_assert():
    # use_site crossing must fail loudly even under python -O, where assert
    # vanishes: the guard is an explicit raise, pinned here behaviorally.
    import pathlib

    import pytest

    from sunstack import config as _config

    for line in pathlib.Path("src/sunstack/config.py").read_text().splitlines():
        assert not line.strip().startswith("assert "), line
    outer = next(s for s in _config.load_sites() if s.slug == "south-bend")
    inner = next(s for s in _config.load_sites() if s.slug == "pacific-palisades")
    ctx = _config.use_site(outer)
    ctx.__enter__()
    try:
        _config._SITE_STACK.append(inner)  # intruder: pop returns the wrong site
        with pytest.raises(RuntimeError, match="site stack corrupted"):
            ctx.__exit__(None, None, None)
    finally:
        _config._SITE_STACK.clear()
    assert _config.LATITUDE == 41.703293  # globals restored despite the raise


def test_cli_requires_basis_with_personal_mmd(tmp_path, monkeypatch):
    import sys

    from sunstack import cli as _cli

    calls = {}

    def _fake_run_all_sites(root, **kwargs):
        calls.update(kwargs)

    monkeypatch.setattr(_cli, "_run_all_sites", _fake_run_all_sites)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(sys, "argv",
                        ["sunstack", "run", "--site", "south-bend",
                         "--personal-mmd", "1000"])
    import pytest

    with pytest.raises(SystemExit) as exc:
        _cli.main()
    assert exc.value.code == 2
    assert calls == {}
    monkeypatch.setattr(sys, "argv",
                        ["sunstack", "run", "--site", "south-bend",
                         "--personal-mmd", "1000",
                         "--personal-mmd-basis", "OBJECTIVE_ESTIMATE"])
    _cli.main()
    assert calls["personal_mmd_j_m2"] == 1000.0
    assert calls["personal_mmd_basis"] == "OBJECTIVE_ESTIMATE"


def test_attach_rejects_unlabeled_mmd():
    import pandas as pd
    import pytest

    from sunstack.opportunity import attach_personalization

    df = pd.DataFrame({"tan_dose_1h_j_m2": [1000.0]})
    with pytest.raises(ValueError, match="explicit basis"):
        attach_personalization(df, personal_mmd_j_m2=2000.0)
    ok = attach_personalization(df, personal_mmd_j_m2=2000.0, basis="MEASURED")
    assert ok.loc[0, "personal_mmd_fraction"] == 0.5


def test_export_preserves_run_attached_fractions(tmp_path):
    import json as _json

    import pandas as pd
    import pytest

    from sunstack.output import export_static_site

    root = _api_fixture(tmp_path)
    half_path = root / "latest" / "tables" / "tan_forecast_30min.parquet"
    half = pd.read_parquet(half_path)
    half["personal_mmd_fraction"] = 0.25
    half["personalization_basis"] = "MEASURED"
    half.to_parquet(half_path, index=False)
    export_static_site(root, tmp_path / "kept")
    payload = _json.loads((tmp_path / "kept" / "data.json").read_text())
    assert {r["personal_mmd_fraction"] for r in payload["half_hour"]} == {0.25}
    with pytest.raises(ValueError, match="explicit basis"):
        export_static_site(root, tmp_path / "bad", personal_mmd_j_m2=2000.0)


def test_reference_builder_drops_missing_bands(tmp_path):
    from sunstack.calibrate import build_local_reference

    stamps = pd.date_range("2020-06-01", periods=6, freq="h", tz="UTC")
    training = pd.DataFrame({
        "time_utc": stamps,
        "uva": [30.0, 35.0, 40.0, 45.0, 50.0, 55.0],
        "uvb": [0.5, float("nan"), 0.7, 0.8, 0.9, 1.0],
        "uvi": [4.0, 5.0, 6.0, 7.0, 8.0, 9.0],
        "sza": [50.0] * 6,
        "ghi": [500.0] * 6,
    })
    ref = build_local_reference(training, tmp_path)
    assert len(ref) == 5  # NaN-UVB row excluded, not zero-scored
    assert ref["melanogenic_effective_irradiance_wm2"].notna().all()


def test_rolling_integration_is_order_invariant():
    from sunstack.doses import add_interval_doses

    dts = pd.date_range("2026-06-21 11:00", periods=6, freq="30min")
    frame = pd.DataFrame({
        "time": dts.strftime("%Y-%m-%dT%H:%M"),
        "melanogenic_effective_irradiance_wm2": [0.2, 0.5, 0.4, 0.6, 0.3, 0.1],
        "erythemal_irradiance_wm2": [0.1] * 6,
        "predicted_uva_wm2": [30.0] * 6,
        "predicted_uvb_wm2": [0.5] * 6,
    })
    straight = add_interval_doses(frame).set_index("time")
    shuffled = add_interval_doses(
        frame.sample(frac=1.0, random_state=7)).set_index("time")
    for col in ("tan_dose_30m_j_m2", "tan_dose_1h_j_m2", "sed_1h",
                "tan_dose_30m_coverage_fraction"):
        a = straight[col].to_numpy(dtype=float)
        b = shuffled.loc[straight.index, col].to_numpy(dtype=float)
        assert np.allclose(a, b, equal_nan=True), col


def test_garbage_timestamp_isolates_to_its_row():
    from sunstack.doses import add_interval_doses

    frame = pd.DataFrame({
        "time": ["2026-06-21T12:00", "not-a-time",
                 "2026-06-21T13:00", "2026-06-21T14:00"],
        "melanogenic_effective_irradiance_wm2": [0.5, 0.6, 0.55, 0.5],
        "erythemal_irradiance_wm2": [0.15, 0.16, 0.155, 0.15],
        "predicted_uva_wm2": [35.0] * 4,
        "predicted_uvb_wm2": [1.0] * 4,
    })
    out = add_interval_doses(frame)
    bad = out.loc[out["time"] == "not-a-time"].iloc[0]
    assert pd.isna(bad["tan_dose_1h_j_m2"])
    assert not bool(bad["tan_dose_1h_complete"])
    good = out.loc[out["time"] == "2026-06-21T14:00"].iloc[0]
    assert good["tan_dose_1h_j_m2"] > 0


def test_all_missing_bands_score_nan_loudly(tmp_path):
    from sunstack.tanscore import score_forecast
    from sunstack.validation import validate_scored_hourly

    broke = _best_air().copy()
    broke["shortwave_radiation"] = float("nan")
    broke["uv_index"] = float("nan")
    out = score_forecast(broke, Path(tmp_path), None, _confidence())
    assert out["tan_score_absolute_0_100"].isna().all()
    assert out["erythemal_irradiance_wm2"].isna().all()
    assert any(i.severity == "ERROR" for i in validate_scored_hourly(out))


def test_cams_cycle_labels_majority_cycle():
    from sunstack.tanscore import build_live_feature_frame

    cams = _cams([0.1, 0.12, 0.11], [0.15, 0.16, 0.15])
    cams["cams_cycle"] = ["2026-09-22T12:00Z"] * 2 + ["2026-09-22T00:00Z"]
    frame = build_live_feature_frame(_best_air(), cams)
    assert (frame["cams_cycle"] == "2026-09-22T12:00Z").all()


def test_training_drops_constant_features_loudly(tmp_path, caplog):
    import logging

    import numpy as np
    import pandas as pd

    from sunstack.calibrate import MODEL_FEATURES, train_uv_models

    n = 2500
    rng = np.random.default_rng(11)
    stamps = pd.date_range("2020-01-01", periods=n, freq="12h", tz="UTC")
    training = pd.DataFrame({
        "time_utc": stamps,
        "ghi": rng.uniform(50, 900, n),
        "sza": rng.uniform(20, 80, n),
        "uva": rng.uniform(5, 45, n),
        "uvb": rng.uniform(0.05, 1.2, n),
    })
    for feat in MODEL_FEATURES:
        if feat not in training:
            # Degraded tier: CAMS columns entirely absent.
            training[feat] = np.nan
    with caplog.at_level(logging.WARNING, logger="sunstack"):
        report = train_uv_models(training, tmp_path)
    assert set(report["dropped_constant_features"]) >= {"aod340", "ozone_du"}
    import joblib

    bundle = joblib.load(tmp_path / "uva_uvb_models.joblib")
    assert "aod340" not in bundle["features"]
    assert any("Calibration training without features" in r.message
               for r in caplog.records)


def test_degraded_bundle_serves_predictions(tmp_path):
    import numpy as np
    import pandas as pd

    from sunstack.calibrate import MODEL_FEATURES, train_uv_models
    from sunstack.tanscore import predict_uva_uvb

    # Reuse the degraded-training fixture pattern: train tiny, drop CAMS.

    n = 2500
    rng = np.random.default_rng(11)
    training = pd.DataFrame({
        "time_utc": pd.date_range("2020-01-01", periods=n, freq="12h", tz="UTC"),
        "ghi": rng.uniform(50, 900, n),
        "sza": rng.uniform(20, 80, n),
        "uva": rng.uniform(5, 45, n),
        "uvb": rng.uniform(0.05, 1.2, n),
    })
    for feat in MODEL_FEATURES:
        if feat not in training:
            training[feat] = np.nan
    caldir = tmp_path / "cal"
    train_uv_models(training, caldir)
    feats = pd.DataFrame([{
        "ghi": 700.0, "dni": 750.0, "dhi": 110.0, "clear_ghi": 1000.0,
        "kt": 0.7, "albedo": 0.2, "aod55": 0.1, "cloud": 10.0, "sza": 40.0,
        "temp_c": 25.0, "rh": 50.0, "pressure_kpa": 100.0,
        "ozone_du": np.nan, "aod340": np.nan, "aod380": np.nan,
        "uv_index": 6.0, "is_day": 1,
    }])
    uva, uvb, tier = predict_uva_uvb(feats, caldir)
    assert tier == "nasa_power_ml"
    assert bool(np.isfinite(uva).all()) and bool(np.isfinite(uvb).all())
    assert (uva > 0).all() and (uvb > 0).all()


def test_records_never_emit_browser_hostile_tokens():
    import json as _json
    import re as _re

    import pandas as pd

    from sunstack.ui import _records

    df = pd.DataFrame({
        "time": ["2026-09-15T12:00", "2026-09-15T13:00"],
        "tan_score_absolute_0_100": [45.0, float("inf")],
        "tan_dose_1h_j_m2": [float("-inf"), float("nan")],
        "note": ["Infinity and NaN as words are fine", "so is -Infinity text"],
    })
    rows = _records(df)
    text = _json.dumps(rows)
    stripped = _re.sub(r'"(?:[^"\\]|\\.)*"', '""', text)
    assert _re.findall(r"\b(Infinity|-Infinity|NaN)\b", stripped) == []
    # Values survive structurally: inf/nan readings become JSON null.
    assert rows[0]["tan_dose_1h_j_m2"] is None
    assert rows[1]["tan_score_absolute_0_100"] is None


def _valid_scored_frame(**overrides):
    base = {
        "uv_index": [5.0, 5.2, 5.1],
        "predicted_uva_wm2": [40.0, 42.0, 41.0],
        "tan_score_absolute_0_100": [30.0, 32.0, 31.0],
        "local_tan_score_0_100": [80.0, 82.0, 81.0],
        "tan_forecast_confidence_0_100": [70.0, 72.0, 71.0],
        "melanogenic_effective_irradiance_wm2": [0.5, 0.52, 0.51],
        "erythemal_irradiance_wm2": [0.125, 0.13, 0.128],
        "tan_score_model_version": ["action-spectrum-v1"] * 3,
        "spectral_backend": ["tierC-broadband-v1"] * 3,
        "spectral_tier": ["C"] * 3,
        "local_reference_stale": [False] * 3,
    }
    base.update(overrides)
    return pd.DataFrame({k: v for k, v in base.items() if v is not None})


def test_scored_hourly_validator_error_branches():
    from sunstack.validation import validate_scored_hourly

    def errors(df):
        return [i for i in validate_scored_hourly(df) if i.severity == "ERROR"]

    assert errors(_valid_scored_frame()) == []
    # Each corruption below must produce at least one ERROR (never silence).
    assert errors(_valid_scored_frame(
        tan_score_absolute_0_100=[30.0, 101.0, 31.0]))
    assert errors(_valid_scored_frame(
        melanogenic_effective_irradiance_wm2=[0.5, -0.1, 0.51]))
    assert errors(_valid_scored_frame(
        melanogenic_effective_irradiance_wm2=[0.5, 5.5, 0.51]))
    assert errors(_valid_scored_frame(
        tan_score_model_version=["legacy-55-30-15"] * 3))
    assert errors(_valid_scored_frame(spectral_tier=["Z"] * 3))
    assert errors(_valid_scored_frame(uv_index=None))
    assert errors(_valid_scored_frame(
        melanogenic_effective_irradiance_wm2=None))
    assert errors(_valid_scored_frame(
        tan_score_absolute_0_100=[float("nan")] * 3))
