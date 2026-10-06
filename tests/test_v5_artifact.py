"""Artifact validator tests (v5 contract §22, §24.9).

Generate a complete fixture artifact, serialize JSON, reload it, and run the
same validator used before publish — on passing and failing fixtures. The
fixture publishes the v5 canonical twins next to the legacy names; both the
twin equality rule and the legacy-only migration window are covered.
"""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path
from typing import Protocol, cast

import pandas as pd


class _ValidatorModule(Protocol):
    def validate_artifact(self, data_path: Path) -> dict[str, object]: ...


class _CaptureLog(Protocol):
    text: str


def _load_validator() -> _ValidatorModule:
    spec = importlib.util.spec_from_file_location(
        "validate_published_artifact", "scripts/validate_published_artifact.py")
    assert spec is not None and spec.loader is not None
    raw = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(raw)
    return cast(_ValidatorModule, cast(object, raw))

_TIMES = ("2026-06-21T12:00", "2026-06-21T12:30", "2026-06-21T13:00")
_E_MEL = (0.4, 0.6, 0.5)
_UVI = (4.0, 6.0, 5.0)


def _trailing_30m(i: int) -> float:
    """Trapezoid over the 30-min leg ending at row i (the published dose)."""
    return 0.5 * (_E_MEL[i - 1] + _E_MEL[i]) * 1800.0


def _good_artifact() -> dict[str, object]:
    import math as _math

    rows: list[dict[str, object]] = []
    for i, (t, u, e) in enumerate(zip(_TIMES, _UVI, _E_MEL)):
        _err = round(0.5 + 0.1 * i, 3)
        _conf = round(min(100.0, max(1.0, 100.0 * _math.exp(-_err / 1.2))), 1)
        row: dict[str, object] = {
            "time": t,
            "uv_index": u, "uvi_cams": u + 0.5, "uvi_epa": u - 0.5,
            "uvi_consensus": u, "uvi_consensus_sources": 3,
            "erythemal_irradiance_wm2": round(u / 40.0, 5),
            "melanogenic_effective_irradiance_wm2": e,
            "delayed_pigmentation_effective_irradiance_horizontal_wm2": e,
            "tan_score_absolute_0_100": 30.0 + i,
            "local_tan_score_0_100": 50.0 + i,
            "tan_forecast_confidence_0_100": _conf,
            "uvi_expected_abs_error": _err,
            "confidence_version": "calibrated-error-v1",
            "temperature_2m": 70.0 + i,
            "precipitation_probability": float(i),
            "tan_score_model_version": "action-spectrum-v2",
            "spectral_backend": "tierC-broadband-proxy-v2",
            "tan_calibration_tier": "nasa_power_ml_plus_cams_spectral",
            "local_reference_stale": False,
            "is_day": 1,
            "outdoor_feasibility_0_100": 90.0,
            "outdoor_feasibility_complete": True,
        }
        if i:
            dose = round(_trailing_30m(i), 3)
            row["sed_30m"] = round(0.5 * (_UVI[i - 1] + u) / 40.0 * 1800.0 / 100.0, 6)
            row["tan_dose_30m_j_m2"] = dose
            row["delayed_pigmentation_dose_30m_j_m2"] = dose
        rows.append(row)
    day_dose = round(_trailing_30m(1) + _trailing_30m(2), 3)
    return {
        "summary": {
            "schema_version": "sunstack-output-v5",
            "tan_score_model_version": "action-spectrum-v2",
            "photobiology_model_version": "delayed-pigmentation-v2",
            "action_spectrum_version": "parrish-fda-3630-v1",
            "fusion_version": "calibrated-uvi-fusion-v2",
            "confidence_version": "calibrated-error-v1",
            "window_rank_version": "fixed-duration-dose-v2",
            "spectral_backend": "tierC-broadband-proxy-v2",
            "exposure_basis": "environmental_horizontal",
            "deprecated_fields": ["overall_tan_opportunity_0_100"],
            "deprecated_aliases": {"melanogenic_effective_irradiance_wm2": "delayed_pigmentation_effective_irradiance_horizontal_wm2"},
            "score_semantics": {
                "tan_score_model_version": "action-spectrum-v2",
                "photobiology_model_version": "delayed-pigmentation-v2",
                "action_spectrum_version": "parrish-fda-3630-v1",
                "fusion_version": "calibrated-uvi-fusion-v2",
                "confidence_version": "calibrated-error-v1",
                "window_rank_version": "fixed-duration-dose-v2",
                "spectral_backend_strict": "tierB-libradtran-emulator-v1",
                "spectral_backend_degraded": "tierC-broadband-proxy-v2",
            },
        },
        "hourly": [],
        "half_hour": rows,
        "daily": [{
            "date": "2026-06-21",
            "day_absolute_peak_0_100": 32.0,
            "day_local_peak_0_100": 52.0,
            # Values at the selected best 30-min interval (12:30 row), never
            # another metric's peak.
            "day_local_at_best_usable_30m_0_100": 51.0,
            "day_confidence_at_peak_0_100": 60.7,
            "uvi_at_best": 6.0,
            "temperature_at_best_f": 71.0,
            "precip_at_best_pct": 1.0,
            "best_30m_start": "2026-06-21T12:30:00",
            "best_usable_30m_start": "2026-06-21T12:00:00",
            "best_usable_30m_end": "2026-06-21T12:30:00",
            "best_usable_30m_dose_j_m2": round(_trailing_30m(1), 3),
            "best_window_start": "2026-06-21T12:00:00",
            "best_window_end": "2026-06-21T13:00:00",
            "tan_dose_best_window_j_m2": day_dose,
            "delayed_pigmentation_dose_best_window_j_m2": day_dose,
            "tan_dose_best_window_complete": True,
            "delayed_pigmentation_dose_best_window_complete": True,
            "tan_dose_day_j_m2": day_dose,
            "delayed_pigmentation_dose_day_j_m2": day_dose,
            "tan_dose_complete": True,
            "delayed_pigmentation_dose_complete": True,
            "window_rank_version": "fixed-duration-dose-v2",
            "window_rank_key": "tan_dose_30m_j_m2",
            "exposure_basis": "environmental_horizontal",
        }],
    }


def _validate(module: _ValidatorModule, tmp_path: Path,
              doc: dict[str, object], name: str = "data.json") -> dict[str, object]:
    p = tmp_path / name
    _ = p.write_text(json.dumps(doc), encoding="utf-8")
    return module.validate_artifact(p)


def _failures(out: dict[str, object]) -> dict[str, object]:
    failures = out["failures"]
    assert isinstance(failures, dict)
    return cast(dict[str, object], failures)


def _row(doc: dict[str, object], i: int) -> dict[str, object]:
    rows = doc["half_hour"]
    assert isinstance(rows, list)
    raw = cast(list[object], rows)[i]
    assert isinstance(raw, dict)
    return cast(dict[str, object], raw)


def _day(doc: dict[str, object]) -> dict[str, object]:
    daily = doc["daily"]
    assert isinstance(daily, list)
    raw = cast(list[object], daily)[0]
    assert isinstance(raw, dict)
    return cast(dict[str, object], raw)


def test_validator_passes_clean_fixture(tmp_path: Path) -> None:
    module = _load_validator()
    out = _validate(module, tmp_path, _good_artifact())
    assert out["passed"] is True, out["failures"]
    checks = out["checks"]
    assert isinstance(checks, list)
    assert len(cast(list[object], checks)) == 21

def test_validator_fails_diverged_fixture(tmp_path: Path) -> None:
    module = _load_validator()
    bad = _good_artifact()
    first = _row(bad, 0)
    first["erythemal_irradiance_wm2"] = 0.999  # != UVI/40
    first["uvi_consensus_sources"] = 7  # > providers
    out = _validate(module, tmp_path, bad, "bad.json")
    assert out["passed"] is False
    failures = _failures(out)
    assert "ery_equals_uvi_over_40" in failures
    assert "source_counts_bounded" in failures or "unique_uvi_source_count" in failures


def test_validator_fails_night_row_in_daylight_payload(tmp_path: Path) -> None:
    module = _load_validator()
    bad = _good_artifact()
    _row(bad, 1)["is_day"] = 0  # night row would enter Fit's denominator
    out = _validate(module, tmp_path, bad, "night.json")
    assert out["passed"] is False
    assert "daylight_fit_denominator" in _failures(out)
    module = _load_validator()
    bad = _good_artifact()
    _row(bad, 1)["delayed_pigmentation_dose_30m_j_m2"] = 123.0
    out = _validate(module, tmp_path, bad)
    assert out["passed"] is False
    assert "dp_dose_recomputes" in _failures(out)


def test_validator_fails_dose_that_does_not_recompute(tmp_path: Path) -> None:
    module = _load_validator()
    bad = _good_artifact()
    _row(bad, 2)["tan_dose_30m_j_m2"] = 4321.0
    _row(bad, 2)["delayed_pigmentation_dose_30m_j_m2"] = 4321.0
    out = _validate(module, tmp_path, bad)
    assert out["passed"] is False
    assert "dp_dose_recomputes" in _failures(out)


def test_validator_accepts_legacy_only_artifact(tmp_path: Path) -> None:
    """Migration window: legacy names without twins still validate."""
    module = _load_validator()
    legacy = _good_artifact()
    for i in range(len(_TIMES)):
        row = _row(legacy, i)
        _ = row.pop("delayed_pigmentation_dose_30m_j_m2", None)
        _ = row.pop("delayed_pigmentation_effective_irradiance_horizontal_wm2", None)
    day = _day(legacy)
    for key in [k for k in day if k.startswith("delayed_pigmentation")]:
        _ = day.pop(key)
    out = _validate(module, tmp_path, legacy)
    assert out["passed"] is True, out["failures"]


def test_validator_fails_at_best_from_wrong_row(tmp_path: Path) -> None:
    module = _load_validator()
    bad = _good_artifact()
    _day(bad)["day_absolute_at_best_usable_30m_0_100"] = 30.0  # 12:00 row, not the selected 12:30
    out = _validate(module, tmp_path, bad)
    assert out["passed"] is False
    assert "at_best_from_window" in _failures(out)


def test_validator_fails_deprecated_ranking_key(tmp_path: Path) -> None:
    module = _load_validator()
    bad = _good_artifact()
    _day(bad)["window_rank_key"] = "overall_tan_opportunity_0_100"
    out = _validate(module, tmp_path, bad)
    assert out["passed"] is False
    assert "no_deprecated_ranking_key" in _failures(out)


def test_validator_fails_manifest_disagreement(tmp_path: Path) -> None:
    module = _load_validator()
    bad = _good_artifact()
    summary_raw = bad["summary"]
    assert isinstance(summary_raw, dict)
    summary = cast(dict[str, object], summary_raw)
    semantics_raw = summary["score_semantics"]
    assert isinstance(semantics_raw, dict)
    semantics = cast(dict[str, object], semantics_raw)
    semantics["fusion_version"] = "other-fusion-v9"
    out = _validate(module, tmp_path, bad)
    assert out["passed"] is False
    assert "manifests_compatible" in _failures(out)


def test_validator_accepts_consistent_clear_sky_ratio(tmp_path: Path) -> None:
    """§2.2/§28: the clear-sky counterpart and its transmission ratio are
    allowed, and a self-consistent pair passes."""
    module = _load_validator()
    doc = _good_artifact()
    for i in range(3):
        row = _row(doc, i)
        e = float(cast(float, row["delayed_pigmentation_effective_irradiance_horizontal_wm2"]))
        row["delayed_pigmentation_clear_sky_horizontal_wm2"] = round(e * 2.0, 5)
        row["delayed_pigmentation_transmission_ratio"] = 0.5
        row["delayed_pigmentation_clear_sky_source"] = "degraded_clear_sky_parametric_v1"
    out = _validate(module, tmp_path, doc)
    assert out["passed"] is True, _failures(out)


def test_validator_fails_inconsistent_clear_sky_ratio(tmp_path: Path) -> None:
    """A ratio that is not E_DP / clear-sky, or that claims the atmosphere
    amplified the sun, is a fatal artifact defect."""
    module = _load_validator()
    doc = _good_artifact()
    row = _row(doc, 1)
    e = float(cast(float, row["delayed_pigmentation_effective_irradiance_horizontal_wm2"]))
    row["delayed_pigmentation_clear_sky_horizontal_wm2"] = round(e, 5)
    row["delayed_pigmentation_transmission_ratio"] = 2.0  # both wrong and > 1
    row["delayed_pigmentation_clear_sky_source"] = "degraded_clear_sky_parametric_v1"
    out = _validate(module, tmp_path, doc)
    assert out["passed"] is False
    assert "clear_sky_transmission_consistent" in _failures(out)


def test_validator_fails_undeclared_clear_sky_source(tmp_path: Path) -> None:
    """The counterpart must name how it was derived; an invented provenance
    string is a fatal artifact defect."""
    module = _load_validator()
    doc = _good_artifact()
    row = _row(doc, 1)
    e = float(cast(float, row["delayed_pigmentation_effective_irradiance_horizontal_wm2"]))
    row["delayed_pigmentation_clear_sky_horizontal_wm2"] = round(e * 2.0, 5)
    row["delayed_pigmentation_transmission_ratio"] = 0.5
    row["delayed_pigmentation_clear_sky_source"] = "measured_libradtran"
    out = _validate(module, tmp_path, doc)
    assert out["passed"] is False
    assert "clear_sky_transmission_consistent" in _failures(out)


def _reference_forecast(rows: int) -> pd.DataFrame:
    times = pd.date_range("2026-06-21 13:00", periods=rows, freq="h")
    return pd.DataFrame({
        "time": times.strftime("%Y-%m-%dT%H:%M"),
        "shortwave_radiation": 600.0,
        "direct_normal_irradiance": 500.0,
        "diffuse_radiation": 100.0,
        "terrestrial_radiation": 800.0,
        "cloud_cover": 20.0,
        "uv_index": 5.0,
        "is_day": 1,
    })


def _write_serving_hindcasts(previous_runs_dir: Path) -> None:
    from sunstack import config

    previous_runs_dir.mkdir(parents=True)
    rows = 32
    frame: dict[str, object] = {
        "time_utc": pd.date_range("2026-06-21T17:00:00Z", periods=rows, freq="min"),
        "elevation_m": [220.0] * rows,
    }
    uv_by_lead = {
        0: (0.0, 0.0), 1: (0.0, 0.0),
        2: (1000.0, 100.0), 3: (1000.0, 100.0),
        4: (0.0, 0.0), 5: (0.0, 0.0), 6: (0.0, 0.0), 7: (0.0, 0.0),
    }
    for lead, (uva, uvb) in uv_by_lead.items():
        suffix = "" if lead == 0 else f"_previous_day{lead}"
        for column, value in {
            "cloud_cover": 20.0,
            "shortwave_radiation": 600.0,
            "diffuse_radiation": 100.0,
            "direct_normal_irradiance": 500.0,
            "uv_index": 5.0,
            "uva": uva,
            "uvb": uvb,
        }.items():
            frame[f"{column}{suffix}"] = [value] * rows
    for model in config.PREVIOUS_RUN_MODELS:
        _ = pd.DataFrame(frame).to_parquet(
            previous_runs_dir / f"previous_runs__{model}.parquet",
            index=False,
        )


def _write_legacy_reference(calibration_dir: Path) -> None:
    from sunstack import config

    calibration_dir.mkdir(parents=True, exist_ok=True)
    _ = pd.DataFrame({
        "day_of_year": [172] * 300,
        "solar_elevation_deg": [60.0] * 300,
        "absolute_tan_score_0_100": [0.0] * 300,
    }).to_parquet(calibration_dir / "local_reference.parquet", index=False)
    _ = (calibration_dir / "local_reference_version.json").write_text(json.dumps({
        "tan_score_model_version": config.TAN_SCORE_MODEL_VERSION,
        "action_spectrum_version": config.ACTION_SPECTRUM_VERSION,
        "spectral_backend_version": config.SPECTRAL_DEGRADED_BACKEND,
        "temporal_semantics_version": config.TEMPORAL_SEMANTICS_VERSION,
        "global_reference_version": config.GLOBAL_MELANOGENIC_REFERENCE_VERSION,
        "global_reference_e_mel_wm2": config.GLOBAL_MELANOGENIC_REFERENCE_WM2,
    }), encoding="utf-8")


def test_serving_reference_preferred_by_forecast_lead(tmp_path: Path) -> None:
    from sunstack.calibrate import build_serving_reference
    from sunstack.tanscore import score_forecast

    calibration_dir = tmp_path / "calibration"
    previous_runs_dir = tmp_path / "previous_runs"
    _write_serving_hindcasts(previous_runs_dir)
    refs = build_serving_reference(
        previous_runs_dir,
        calibration_dir,
        "America/Indiana/Indianapolis",
    )

    manifest = cast(dict[str, object], json.loads(
        (calibration_dir / "lead_reference_manifest.json").read_text(encoding="utf-8")
    ))
    bands = manifest["bands"]
    row_counts = manifest["row_counts"]
    assert isinstance(bands, list)
    assert isinstance(row_counts, dict)
    assert set(cast(list[str], bands)) == set(refs)
    assert all(
        isinstance(row_counts.get(band), int) and row_counts[band] > 0
        for band in refs
    )
    assert all(
        (calibration_dir / f"local_reference_serving_{band}.parquet").exists()
        for band in refs
    )

    out = score_forecast(_reference_forecast(169), calibration_dir)
    assert not bool(out["local_reference_fallback"].iloc[0])
    assert not bool(out["local_reference_fallback"].iloc[24])
    assert bool(out["local_reference_fallback"].iloc[168])
    assert out["local_tan_score_0_100"].iloc[0] == 100.0
    assert out["local_tan_score_0_100"].iloc[24] == 0.0


def test_serving_reference_absence_falls_back_to_legacy(
    tmp_path: Path,
    caplog: _CaptureLog,
) -> None:
    from sunstack.tanscore import score_forecast

    calibration_dir = tmp_path / "calibration"
    _write_legacy_reference(calibration_dir)

    out = score_forecast(_reference_forecast(1), calibration_dir)
    assert bool(out["local_reference_fallback"].iloc[0])
    assert out["local_tan_score_0_100"].iloc[0] == 100.0
    assert "Serving local references unavailable" in caplog.text
