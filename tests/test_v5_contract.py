"""Executable v5 output and CLI contract."""

from __future__ import annotations

import json
from pathlib import Path


def _version_keys() -> dict[str, object]:
    from sunstack import config

    return {
        "schema_version": config.SCHEMA_VERSION,
        "temporal_semantics_version": config.TEMPORAL_SEMANTICS_VERSION,
        "photobiology_model_version": config.PHOTOBIOLOGY_MODEL_VERSION,
        "tan_score_model_version": config.TAN_SCORE_MODEL_VERSION,
        "action_spectrum_version": config.ACTION_SPECTRUM_VERSION,
        "spectral_backend_strict": config.SPECTRAL_BACKEND_VERSION_V5,
        "spectral_backend_degraded": config.SPECTRAL_DEGRADED_BACKEND,
        "surface_model_version": config.SURFACE_MODEL_VERSION,
        "fusion_version": config.FUSION_VERSION,
        "confidence_version": config.CONFIDENCE_VERSION,
        "window_rank_version": config.WINDOW_RANK_VERSION,
    }


def test_score_semantics_tracks_config_constants() -> None:
    from sunstack import config

    version_keys = _version_keys()
    semantics = config.score_semantics()

    assert semantics["overall_weights"] == config.OVERALL_SCORE_WEIGHTS
    assert semantics["overall_absolute_headroom"] == config.OVERALL_ABSOLUTE_HEADROOM
    assert {key: semantics[key] for key in version_keys} == version_keys
    assert {
        "min_tan_temp_f": semantics["min_tan_temp_f"],
        "comfortable_tan_temp_f": semantics["comfortable_tan_temp_f"],
        "heat_warning_temp_f": semantics["heat_warning_temp_f"],
        "max_tan_temp_f": semantics["max_tan_temp_f"],
        "active_precip_in_threshold": semantics["active_precip_in_threshold"],
        "active_snow_in_threshold": semantics["active_snow_in_threshold"],
        "precip_probability_penalty_max": semantics["precip_probability_penalty_max"],
        "wind_warning_mph": semantics["wind_warning_mph"],
        "wind_strong_mph": semantics["wind_strong_mph"],
        "uvi_disagreement_warn_frac": semantics["uvi_disagreement_warn_frac"],
        "uvi_disagreement_strong_frac": semantics["uvi_disagreement_strong_frac"],
        "skin_tilt_deg": semantics["skin_tilt_deg"],
        "skin_azimuth_deg": semantics["skin_azimuth_deg"],
        "tandose_max_interp_gap_s": semantics["tandose_max_interp_gap_s"],
    } == {
        "min_tan_temp_f": config.MIN_TAN_TEMP_F,
        "comfortable_tan_temp_f": config.COMFORTABLE_TAN_TEMP_F,
        "heat_warning_temp_f": config.HEAT_WARNING_TEMP_F,
        "max_tan_temp_f": config.MAX_TAN_TEMP_F,
        "active_precip_in_threshold": config.ACTIVE_PRECIP_IN_THRESHOLD,
        "active_snow_in_threshold": config.ACTIVE_SNOW_IN_THRESHOLD,
        "precip_probability_penalty_max": config.PRECIP_PROBABILITY_PENALTY_MAX,
        "wind_warning_mph": config.WIND_WARNING_MPH,
        "wind_strong_mph": config.WIND_STRONG_MPH,
        "uvi_disagreement_warn_frac": config.UVI_DISAGREEMENT_WARN_FRAC,
        "uvi_disagreement_strong_frac": config.UVI_DISAGREEMENT_STRONG_FRAC,
        "skin_tilt_deg": config.SKIN_TILT_DEG,
        "skin_azimuth_deg": config.SKIN_AZIMUTH_DEG,
        "tandose_max_interp_gap_s": config.TANDOSE_MAX_INTERP_GAP_S,
    }
    assert semantics["deprecated_fields"] == config.DEPRECATED_FIELDS
    assert semantics["deprecated_aliases"] == config.DEPRECATED_ALIASES


def test_schema_versions_and_deprecations_match_config() -> None:
    from sunstack import config

    version_keys = _version_keys()
    schema = json.loads(Path("docs/schema/sunstack-output-v5.json").read_text())

    assert {key: schema[key] for key in version_keys} == version_keys
    assert tuple(schema["deprecated_fields"]) == config.DEPRECATED_FIELDS
    assert schema["deprecated_aliases"] == config.DEPRECATED_ALIASES


def test_documented_v5_tokens_remain_current() -> None:
    tokens = (
        "sunstack-output-v5",
        "interval-contract-v1",
        "delayed-pigmentation-v2",
        "parrish-fda-3630-v1",
        "tierB-libradtran-emulator-v1",
        "tierC-broadband-proxy-v2",
        "uv-surface-v1",
        "calibrated-uvi-fusion-v2",
        "calibrated-error-v1",
        "fixed-duration-dose-v2",
        "70",
        "+20",
    )
    for path in (Path("README.md"), Path("docs/SCIENCE.md")):
        text = path.read_text(encoding="utf-8")
        assert not (missing := [token for token in tokens if token not in text]), (
            path,
            missing,
        )


def test_parser_exposes_surface_context_flags() -> None:
    from sunstack import cli

    parser = cli.build_parser()
    args = parser.parse_args([])
    actions = {
        option: action
        for action in parser._actions
        for option in action.option_strings
    }

    assert args.surface == "unknown"
    assert args.surface_extent == "local"
    assert args.skin_tilt_deg is None
    assert args.skin_azimuth_deg is None
    assert args.surface_uva_reflectance is None
    assert args.surface_uvb_reflectance is None
    surface_extent_choices = actions["--surface-extent"].choices
    assert surface_extent_choices is not None
    assert tuple(surface_extent_choices) == ("local", "broad")
    assert actions["--skin-tilt-deg"].type is float
    assert actions["--skin-azimuth-deg"].type is float
    assert actions["--surface-uva-reflectance"].type is float
    assert actions["--surface-uvb-reflectance"].type is float


def test_custom_skin_plane_keeps_environmental_columns() -> None:
    import pandas as pd

    from sunstack.spectral import apply_skin_plane

    frame = pd.DataFrame(
        {
            "melanogenic_effective_irradiance_wm2": [0.5],
            "tan_score_absolute_0_100": [30.0],
            "sza": [40.0],
            "solar_azimuth_deg": [180.0],
            "direct_radiation": [500.0],
            "diffuse_radiation": [200.0],
            "shortwave_radiation": [700.0],
        }
    )
    out = apply_skin_plane(frame, 45.0, 180.0, "custom", "local", 0.1, 0.2)

    assert out["melanogenic_effective_irradiance_wm2"].equals(
        frame["melanogenic_effective_irradiance_wm2"]
    )
    assert out["tan_score_absolute_0_100"].equals(
        frame["tan_score_absolute_0_100"]
    )
    assert out["surface_material_slug"].tolist() == ["custom"]
    assert {"skin_plane_e_mel_wm2", "skin_plane_factor"} <= set(out.columns)
