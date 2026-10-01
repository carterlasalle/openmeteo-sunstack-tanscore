"""Artifact validator tests (v5 contract §22, §24.9).

Generate a complete fixture artifact, serialize JSON, reload it, and run the
same validator used before publish — on both a passing and a failing fixture.
"""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path
from typing import Protocol, cast


class _ValidatorModule(Protocol):
    def validate_artifact(self, data_path: Path) -> dict[str, object]: ...


def _load_validator() -> _ValidatorModule:
    spec = importlib.util.spec_from_file_location(
        "validate_published_artifact", "scripts/validate_published_artifact.py")
    assert spec is not None and spec.loader is not None
    raw = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(raw)
    return cast(_ValidatorModule, cast(object, raw))

def _good_artifact() -> dict[str, object]:
    rows = []
    for i, (uvi, emel) in enumerate([(4.0, 0.4), (6.0, 0.6)]):
        rows.append({
            "time": f"2026-06-21T1{i}:00",
            "uv_index": uvi, "uvi_cams": uvi + 0.5, "uvi_epa": uvi - 0.5,
            "uvi_consensus": uvi, "uvi_consensus_sources": 3,
            "erythemal_irradiance_wm2": round(uvi / 40.0, 5),
            "melanogenic_effective_irradiance_wm2": emel,
            "tan_score_absolute_0_100": 30.0 + i,
            "local_tan_score_0_100": 50.0 + i,
            "tan_score_model_version": "action-spectrum-v2",
            "spectral_backend": "tierC-broadband-proxy-v2",
            "is_day": 1,
            "outdoor_feasibility_0_100": 90.0,
            "outdoor_feasibility_complete": True,
        })
    return {
        "summary": {
            "schema_version": "sunstack-output-v5",
            "tan_score_model_version": "action-spectrum-v2",
            "action_spectrum_version": "parrish-fda-3630-v1",
            "fusion_version": "calibrated-uvi-fusion-v2",
            "confidence_version": "calibrated-error-v1",
            "window_rank_version": "fixed-duration-dose-v2",
            "spectral_backend": "tierC-broadband-proxy-v2",
        },
        "hourly": rows,
        "half_hour": [],
        "daily": [{
            "date": "2026-06-21",
            "day_absolute_peak_0_100": 31.0,
            "day_local_peak_0_100": 51.0,
        }],
    }


def test_validator_passes_clean_fixture(tmp_path: Path) -> None:
    module = _load_validator()
    p = tmp_path / "data.json"
    _ = p.write_text(json.dumps(_good_artifact()), encoding="utf-8")
    out = module.validate_artifact(p)
    assert out["passed"] is True, out["failures"]


def test_validator_fails_diverged_fixture(tmp_path: Path) -> None:
    module = _load_validator()
    bad = _good_artifact()
    rows = bad["hourly"]
    assert isinstance(rows, list)
    first = rows[0]
    assert isinstance(first, dict)
    first["erythemal_irradiance_wm2"] = 0.999  # != UVI/40
    first["uvi_consensus_sources"] = 7  # > providers
    p = tmp_path / "bad.json"
    _ = p.write_text(json.dumps(bad), encoding="utf-8")
    out = module.validate_artifact(p)
    assert out["passed"] is False
    failures = out["failures"]
    assert isinstance(failures, dict)
    assert "ery_equals_uvi_over_40" in failures
    assert "source_counts_bounded" in failures or "unique_uvi_source_count" in failures
