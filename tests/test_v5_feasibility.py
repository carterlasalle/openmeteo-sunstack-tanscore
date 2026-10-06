"""Feasibility/weather/MMD contract tests (v5 contract §14, §15, §18, §24.4)."""

from __future__ import annotations

import pandas as pd


def _wx_frame(**overrides: object) -> pd.DataFrame:
    base: dict[str, object] = {
        "temperature_2m": [70.0, 70.0],
        "weather_code": [3, 3],
        "rain": [0.0, 0.0],
        "showers": [0.0, 0.0],
        "snowfall": [0.0, 0.0],
        "precipitation_probability": [10.0, 10.0],
        "wind_speed_10m": [5.0, 5.0],
        "dew_point_2m": [55.0, 55.0],
        "relative_humidity_2m": [50.0, 50.0],
        "uv_index": [5.0, 5.0],
        "uv_index_clear_sky": [6.0, 6.0],
        "tan_score_absolute_0_100": [40.0, 40.0],
    }
    base.update(overrides)
    return pd.DataFrame(base)


def test_missing_required_weather_is_unknown_not_perfect() -> None:
    from sunstack.opportunity import apply_outdoor_feasibility
    frame = _wx_frame(temperature_2m=[float("nan"), float("nan")])
    out = apply_outdoor_feasibility(frame)
    assert not bool(out["outdoor_feasibility_complete"].iloc[0])
    assert "temperature_2m" in str(out["outdoor_feasibility_missing_fields"].iloc[0])
    assert "unknown" in str(out["outdoor_block_reason"].iloc[0])


def test_wmo_97_hard_blocks() -> None:
    from sunstack.opportunity import THUNDER_CODES, apply_outdoor_feasibility

    assert 97 in THUNDER_CODES
    for code in (95, 96, 97, 99):
        out = apply_outdoor_feasibility(_wx_frame(weather_code=[code, 3]))
        assert bool(out["outdoor_blocked"].iloc[0]), code


def test_precip_sum_is_interval_semantic_not_instant_claim() -> None:
    from sunstack.opportunity import apply_outdoor_feasibility

    out = apply_outdoor_feasibility(_wx_frame(rain=[0.05, 0.0]))
    assert "precipitation in interval/code" in str(out["outdoor_block_reason"].iloc[0])
    assert "active rain at" not in str(out["outdoor_block_reason"].iloc[0])


def test_snow_depth_can_block_existing_ground_snow() -> None:
    from sunstack.opportunity import apply_outdoor_feasibility

    # Falling-snow detection alone does not prove ground cover; snow_depth does.
    no_depth = apply_outdoor_feasibility(_wx_frame())
    assert not bool(no_depth["outdoor_blocked"].iloc[0])
    deep = apply_outdoor_feasibility(_wx_frame(snow_depth=[0.2, 0.0]))
    assert bool(deep["outdoor_blocked"].iloc[0])
    assert "snow-covered ground" in str(deep["outdoor_block_reason"].iloc[0])

def test_sun_warming_heuristic_values_pinned() -> None:
    # Contract §15: dew point 75°F contributes +6°F, 20 mph wind subtracts
    # 6.4°F under the legacy formula. Pinned by test, never prose.
    from sunstack.opportunity import apply_outdoor_feasibility

    frame = _wx_frame(
        temperature_2m=[70.0, 70.0], dew_point_2m=[75.0, 75.0], wind_speed_10m=[20.0, 20.0],
        uv_index=[0.0, 0.0], uv_index_clear_sky=[8.0, 8.0],
        weather_code=[3, 3], rain=[0.0, 0.0], showers=[0.0, 0.0], snowfall=[0.0, 0.0],
        precipitation_probability=[0.0, 0.0], relative_humidity_2m=[50.0, 50.0])
    out = apply_outdoor_feasibility(frame)
    got = float(out["sun_warming_heuristic_f"].iloc[0])
    assert abs(got - (70.0 + 6.0 - 6.4)) < 0.15
    assert "sun_warming_heuristic_f" in out.columns
    assert "comfort_model_version" in out.columns


def test_generic_measured_mmd_rejected() -> None:
    import pytest

    from sunstack.opportunity import attach_personalization

    df = pd.DataFrame({"tan_dose_1h_j_m2": [1000.0]})
    with pytest.raises(ValueError, match="not compatible"):
        _ = attach_personalization(df, personal_mmd_j_m2=5000.0, basis="MEASURED")
    ok = attach_personalization(
        df, personal_mmd_j_m2=5000.0, basis="SUNSTACK_EFFECTIVE_DOSE_MEASURED")
    assert float(ok["personal_mmd_fraction"].iloc[0]) == 0.2


def test_feasibility_reason_codes_name_the_rule() -> None:
    # §14.1: a blocked or unknown row must say which rule fired, so it is
    # explainable without re-deriving it from the raw weather columns.
    from sunstack.opportunity import apply_outdoor_feasibility

    clean = apply_outdoor_feasibility(_wx_frame())
    assert clean["outdoor_feasibility_reason_codes"].tolist() == ["ok", "ok"]

    thunder = apply_outdoor_feasibility(_wx_frame(weather_code=[97, 3]))
    assert "thunderstorm" in str(thunder["outdoor_feasibility_reason_codes"].iloc[0])

    missing = apply_outdoor_feasibility(_wx_frame(temperature_2m=[float("nan"), 70.0]))
    assert "missing_weather" in str(missing["outdoor_feasibility_reason_codes"].iloc[0])

    cold = apply_outdoor_feasibility(_wx_frame(temperature_2m=[10.0, 70.0]))
    assert "too_cold" in str(cold["outdoor_feasibility_reason_codes"].iloc[0])

    snow = apply_outdoor_feasibility(_wx_frame(snow_depth=[0.5, 0.0]))
    assert "ground_snow" in str(snow["outdoor_feasibility_reason_codes"].iloc[0])
