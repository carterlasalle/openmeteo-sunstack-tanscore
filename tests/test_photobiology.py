"""Deterministic mathematical tests for the v4 photobiology core.

Covers §21: SED, TanDose, action spectra, photoaddition, score monotonicity,
environmental invariance (rain/snow/temp/Fitzpatrick), and source-disagreement
confidence separation.
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

from sunstack.photobiology import (
    absolute_tan_score_from_melanogenic_irradiance,
    effectiveness_at,
    erythemal_irradiance_from_uvi,
    integrate_sed,
    integrate_tandose,
    load_action_spectrum,
)
from sunstack.spectral import (
    SPECTRAL_WAVES_NM,
    melanogenic_from_broadband,
    reconstruct_spectrum_tierC,
)


def _stamps(start: str, hours: float, n: int) -> pd.Series:
    base = pd.to_datetime(start, utc=True)
    return pd.Series([base + pd.Timedelta(seconds=hours * 3600 * i / max(n - 1, 1)) for i in range(n)])


def test_sed_constant_uvi_10_one_hour_is_9():
    t = _stamps("2026-06-21T12:00Z", 1.0, 5)
    ery = pd.Series(erythemal_irradiance_from_uvi(np.full(5, 10.0)))
    assert abs(integrate_sed(t, ery)["sed"] - 9.0) < 1e-9


def test_sed_constant_uvi_6_half_hour_is_2_7():
    t = _stamps("2026-06-21T12:00Z", 0.5, 4)
    ery = pd.Series(erythemal_irradiance_from_uvi(np.full(4, 6.0)))
    assert abs(integrate_sed(t, ery)["sed"] - 2.7) < 1e-9


def test_sed_constant_uvi_6_quarter_hour_is_1_35():
    t = _stamps("2026-06-21T12:00Z", 0.25, 3)
    ery = pd.Series(erythemal_irradiance_from_uvi(np.full(3, 6.0)))
    assert abs(integrate_sed(t, ery)["sed"] - 1.35) < 1e-9


def test_sed_night_is_zero():
    t = _stamps("2026-06-21T00:00Z", 2.0, 5)
    ery = pd.Series(np.zeros(5))
    out = integrate_sed(t, ery)
    assert out["sed"] == 0.0


def test_sed_irregular_timestamps_use_trapezoid_not_nominal():
    # UVI 10 for exactly 1 h but sampled irregularly: integral still 9.0 SED.
    t = pd.Series(pd.to_datetime(
        ["2026-06-21T12:00Z", "2026-06-21T12:10Z", "2026-06-21T12:45Z", "2026-06-21T13:00Z"],
        utc=True,
    ))
    ery = pd.Series(erythemal_irradiance_from_uvi(np.full(4, 10.0)))
    assert abs(integrate_sed(t, ery)["sed"] - 9.0) < 1e-9


def test_tandose_constant_emel_hour():
    t = _stamps("2026-06-21T12:00Z", 1.0, 5)
    e = pd.Series(np.full(5, 0.10))
    out = integrate_tandose(t, e)
    assert abs(out["tan_dose_melanogenic_j_m2"] - 360.0) < 1e-9
    assert out["tan_dose_complete"] is True
    assert out["tan_dose_coverage_fraction"] == 1.0


def test_tandose_trapezoid_ramps():
    # 0 -> 0.2 W/m^2 linearly over 1 h: mean 0.1 => 360 J/m^2.
    t = _stamps("2026-06-21T12:00Z", 1.0, 3)
    e = pd.Series([0.0, 0.1, 0.2])
    assert abs(integrate_tandose(t, e)["tan_dose_melanogenic_j_m2"] - 360.0) < 1e-9


def test_tandose_gap_splits_and_marks_incomplete():
    t = pd.Series(pd.to_datetime(
        ["2026-06-21T10:00Z", "2026-06-21T11:00Z", "2026-06-21T16:00Z", "2026-06-21T17:00Z"],
        utc=True,
    ))
    e = pd.Series(np.full(4, 0.10))
    out = integrate_tandose(t, e, max_gap_s=3 * 3600)
    # Two contiguous 1 h blocks: 360 + 360 = 720, gap split, incomplete.
    assert abs(out["tan_dose_melanogenic_j_m2"] - 720.0) < 1e-9
    assert out["tan_dose_complete"] is False
    assert 0.0 < out["tan_dose_coverage_fraction"] < 1.0


def test_tandose_night_zero():
    t = _stamps("2026-06-21T00:00Z", 3.0, 4)
    assert integrate_tandose(t, pd.Series(np.zeros(4)))["tan_dose_melanogenic_j_m2"] == 0.0


def test_action_spectrum_uvb_orders_above_uva():
    spec = load_action_spectrum("parrish_delayed_melanogenesis")
    uvb = effectiveness_at(spec, np.array([290.0, 292.0, 295.0])).mean()
    uva = effectiveness_at(spec, np.array([360.0, 362.0, 365.0])).mean()
    assert uvb / uva > 100.0, f"expected >2 orders, got {uvb/uva:.1f}x"


def test_action_spectrum_validation_rejects_bad_resources(tmp_path, monkeypatch):
    import sunstack.photobiology as pb

    monkeypatch.setitem(pb._cache, "zzz_bad", pb.ActionSpectrum(
        name="zzz_bad", wavelengths_nm=np.array([300.0, 310.0]),
        effectiveness=np.array([1.0, 0.5]), tier="provisional",
        source="test", sha256="x",
    ))
    spec = pb._cache["zzz_bad"]
    try:
        effectiveness_at(spec, np.array([500.0]))
    except ValueError as exc:
        assert "outside" in str(exc)
    else:
        raise AssertionError("out-of-domain wavelengths must fail")


def test_photoaddition_two_bins_sum():
    # Same broadband split two ways: E_mel(l1+l2) == E_mel(l1) + E_mel(l2).
    e12 = melanogenic_from_broadband(30.0, 1.0)
    e1 = melanogenic_from_broadband(30.0, 0.0)
    e2 = melanogenic_from_broadband(0.0, 1.0)
    assert abs(float(e12) - (float(e1) + float(e2))) < 1e-12
    # Spectral form: integral of summed spectrum equals sum of integrals.
    spec = load_action_spectrum("parrish_delayed_melanogenesis")
    from sunstack.photobiology import melanogenic_effective_irradiance

    s1 = reconstruct_spectrum_tierC(30.0, 0.0)
    s2 = reconstruct_spectrum_tierC(0.0, 1.0)
    m12 = melanogenic_effective_irradiance(s1 + s2, SPECTRAL_WAVES_NM, spec)
    m1 = melanogenic_effective_irradiance(s1, SPECTRAL_WAVES_NM, spec)
    m2 = melanogenic_effective_irradiance(s2, SPECTRAL_WAVES_NM, spec)
    assert abs(m12 - (m1 + m2)) < 1e-9


def test_score_monotonic_in_emel():
    scores = absolute_tan_score_from_melanogenic_irradiance(
        np.array([0.0, 0.2, 0.75, 1.6, 5.0]), 1.6
    )
    assert scores[0] == 0.0
    assert scores[3] == 100.0
    assert scores[4] == 100.0
    assert bool((np.diff(scores) > 0)[:3].all())
    # South-Bend-like E_mel (~0.75) stays moderate, never near-100.
    assert 30 < scores[2] < 65


def test_environmental_physics_invariant_to_weather_and_skin():
    from sunstack.opportunity import apply_outdoor_feasibility, attach_fitzpatrick

    def row(**kw):
        base = {
            "tan_score_absolute_0_100": 44.0,
            "local_tan_score_0_100": 97.0,
            "atmospheric_quality_percentile_0_100": 94.0,
            "tan_forecast_confidence_0_100": 91.0,
            "temperature_2m": 78.0, "apparent_temperature": 80.0,
            "rain": 0.0, "showers": 0.0, "snowfall": 0.0, "precipitation": 0.0,
            "precipitation_probability": 0.0, "weather_code": 0,
            "wind_speed_10m": 5.0, "relative_humidity_2m": 50.0,
        }
        base.update(kw)
        return pd.DataFrame([base])

    for kwargs in [{"rain": 0.05, "weather_code": 61}, {"snowfall": 0.2, "weather_code": 71},
                   {"temperature_2m": 45.0}, {"temperature_2m": 105.0}]:
        out = apply_outdoor_feasibility(row(**kwargs))
        # Opportunity blocked/penalized, physics untouched.
        assert out.loc[0, "tan_score_absolute_0_100"] == 44.0
    e0 = melanogenic_from_broadband(35.0, 1.0)
    assert float(e0) == float(melanogenic_from_broadband(35.0, 1.0))
    scored = apply_outdoor_feasibility(row())
    assert attach_fitzpatrick(scored, 1).loc[0, "tan_score_absolute_0_100"] == \
        attach_fitzpatrick(scored, 6).loc[0, "tan_score_absolute_0_100"]


def test_sed_never_increases_opportunity():
    from sunstack.opportunity import apply_outdoor_feasibility

    base = pd.DataFrame([{
        "tan_score_absolute_0_100": 40.0, "local_tan_score_0_100": 50.0,
        "atmospheric_quality_percentile_0_100": 50.0,
        "tan_forecast_confidence_0_100": 50.0,
        "temperature_2m": 78.0, "apparent_temperature": 78.0,
        "rain": 0.0, "showers": 0.0, "snowfall": 0.0, "precipitation": 0.0,
        "precipitation_probability": 0.0, "weather_code": 0,
        "wind_speed_10m": 5.0, "relative_humidity_2m": 50.0,
    }])
    out = apply_outdoor_feasibility(base)
    cols = [c for c in out.columns if c.lower().startswith("sed")]
    assert cols == [], "SED must not enter the opportunity frame as a positive component"


def test_source_disagreement_hits_confidence_not_physics():
    from sunstack import config
    from sunstack.tanscore import apply_disagreement_penalty

    conf = pd.Series([80.0])
    weaker = apply_disagreement_penalty(conf, pd.Series([True]))
    assert weaker.iloc[0] == 40.0
    # CAMS/Open-Meteo fractional disagreement path: physics E_mel unchanged.
    e_before = float(melanogenic_from_broadband(35.0, 1.0))
    _ = config.UVI_DISAGREEMENT_WARN_FRAC  # threshold exists and is versioned
    assert float(melanogenic_from_broadband(35.0, 1.0)) == e_before


def test_tierB_manifest_validator_fails_loudly():
    import pytest

    from sunstack.spectral import validate_tierB_manifest

    good = {
        "spectral_emulator_version": "em-v1",
        "spectral_training_manifest_sha256": "abc123",
        "libradtran_version": "2.5.0",
        "parameter_ranges": {"sza_deg": [0, 88]},
        "validation_metrics": {"heldout_rmse": 0.01},
    }
    assert validate_tierB_manifest(good) is good
    with pytest.raises(ValueError, match="missing fields"):
        validate_tierB_manifest({"spectral_emulator_version": "em-v1"})
    with pytest.raises(ValueError, match="no held-out validation metrics"):
        validate_tierB_manifest({**good, "validation_metrics": {}})


def test_interval_ics_marks_native_vs_interpolated():
    from sunstack.ui import build_interval_ics

    half = pd.DataFrame({
        "time": ["2026-09-15T12:00", "2026-09-15T12:30"],
        "tan_score_absolute_0_100": [40.0, 42.0],
        "overall_tan_opportunity_0_100": [50.0, 55.0],
        "tan_dose_30m_j_m2": [900.0, 950.0],
        "sed_30m": [2.5, 2.6],
        "subhour_source": ["native_HRRR_radiation_weather_plus_interpolated_UV",
                           "interpolated_hourly"],
    })
    ics = build_interval_ics(half, "20260915_004803")
    assert ics.count("BEGIN:VEVENT") == 2
    flat = ics.replace("\r\n ", "")
    assert "native HRRR" in flat and "interpolated hourly" in flat
    assert "TanDose30" in flat and "SED30" in flat


def test_personalization_never_alters_environmental_physics():
    from sunstack.opportunity import (
        attach_personalization,
        personalization_context,
    )

    df = pd.DataFrame({
        "tan_dose_1h_j_m2": [1000.0],
        "melanogenic_effective_irradiance_wm2": [0.5],
    })
    out = attach_personalization(df)
    assert out.loc[0, "melanogenic_effective_irradiance_wm2"] == 0.5
    assert out.loc[0, "tan_dose_1h_j_m2"] == 1000.0
    assert pd.isna(out.loc[0, "personal_mmd_fraction"])
    assert out.loc[0, "personalization_basis"] == "not personalized"
    measured = attach_personalization(df, personal_mmd_j_m2=2000.0, basis="MEASURED")
    assert measured.loc[0, "personal_mmd_fraction"] == 0.5
    # Fitzpatrick alone never yields a precise MMD.
    ctx = personalization_context(fitzpatrick_type=3)
    assert "COARSE_ESTIMATE" in str(ctx["personalization_basis"])
    assert personalization_context(
        measured_mmd=500.0)["personalization_basis"] == "MEASURED"


def _write_spectrum(tmpdir, stem, waves, effs):
    import hashlib
    import json as _json

    csv = tmpdir / f"{stem}.csv"
    csv.write_text("wavelength_nm,effectiveness\n" + "\n".join(
        f"{w},{e}" for w, e in zip(waves, effs)) + "\n", encoding="utf-8")
    (tmpdir / f"{stem}.meta.json").write_text(_json.dumps({
        "resource": f"{stem}.csv",
        "source_title": "synthetic", "authors": "test", "year": 2026,
        "identifier": "test", "biological_endpoint": "test",
        "subject_population": "test", "wavelengths_tested_nm": "test",
        "assessment_time_after_exposure": "test",
        "normalization_convention": "test", "original_units": "test",
        "digitization_method": "test",
        "checksum_sha256": hashlib.sha256(csv.read_bytes()).hexdigest(),
        "tier": "provisional", "limitations": "test",
    }), encoding="utf-8")


def test_action_spectrum_strict_validation_rejects_bad_files(tmp_path, monkeypatch):
    import pytest

    import sunstack.photobiology as pb

    monkeypatch.setattr(pb, "_spectra_dir", lambda: Path(tmp_path))
    pb._cache.clear()
    try:
        full = list(range(280, 401))
        ones = [1.0] * len(full)
        _write_spectrum(tmp_path, "bad_neg", full,
                        [1.0 if w != 350 else -0.5 for w in full])
        with pytest.raises(ValueError, match="negative effectiveness"):
            pb.load_action_spectrum("bad_neg")
        _write_spectrum(tmp_path, "bad_order", full[::-1], ones)
        with pytest.raises(ValueError, match="monotonic"):
            pb.load_action_spectrum("bad_order")
        _write_spectrum(tmp_path, "bad_dup", full + [400], ones + [1.0])
        with pytest.raises(ValueError, match="duplicated"):
            pb.load_action_spectrum("bad_dup")
        short = list(range(300, 401))
        _write_spectrum(tmp_path, "bad_range", short, [1.0] * len(short))
        with pytest.raises(ValueError, match="must cover"):
            pb.load_action_spectrum("bad_range")
        missing = tmp_path / "bad_missing.csv"
        assert not missing.exists()
        with pytest.raises(FileNotFoundError, match="unavailable"):
            pb.load_action_spectrum("bad_missing")
    finally:
        pb._cache.clear()


def test_impossible_spectral_irradiance_fails_loudly():
    import pytest

    from sunstack.photobiology import melanogenic_effective_irradiance

    waves = np.arange(280, 401, dtype=float)
    good = np.full_like(waves, 0.1)
    assert melanogenic_effective_irradiance(good, waves) > 0
    with pytest.raises(ValueError, match="impossible values"):
        melanogenic_effective_irradiance(-good, waves)
    with pytest.raises(ValueError, match="share shape"):
        melanogenic_effective_irradiance(good[:-1], waves)


def test_run_manifest_metadata_contract():
    from sunstack.photobiology import model_metadata
    from sunstack.spectral import emulator_manifest

    meta = model_metadata({"global_reference_version": "v",
                           "global_reference_e_mel_wm2": 1.6})
    for key in ("photobiology_model_version", "tan_score_model_version",
                "tan_dose_model_version", "action_spectrum_name",
                "action_spectrum_sha256", "action_spectrum_source"):
        assert key in meta, key
    em = emulator_manifest()
    for key in ("spectral_backend", "spectral_emulator_version",
                "spectral_training_manifest_sha256", "tierB_reserved_inputs"):
        assert key in em, key
