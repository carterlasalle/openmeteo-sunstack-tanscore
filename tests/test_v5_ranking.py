"""Fixed-duration physical ranking tests (v5 contract §16, §24.7).

The primary ranking is maximum expected delayed-pigmentation dose over a
fixed window — never Local/Atmo/confidence blending, never Overall.
"""

from __future__ import annotations

from typing import cast

import pandas as pd


def _cell_text(row: pd.Series, name: str) -> str:
    return cast("str", row[name])


def _day() -> pd.DataFrame:
    return pd.DataFrame({
        "dt": pd.to_datetime([
            "2026-06-21T10:00", "2026-06-21T10:30",
            "2026-06-21T11:00", "2026-06-21T11:30"]),
        "melanogenic_effective_irradiance_wm2": [0.5, 0.6, 0.4, 0.1],
        "tan_forecast_confidence_0_100": [70.0, 70.0, 70.0, 70.0],
        "outdoor_blocked": [False, False, False, True],
        "is_day": [1, 1, 1, 1],
        "overall_tan_opportunity_0_100": [10.0, 90.0, 20.0, 5.0],
        "tan_score_absolute_0_100": [30.0, 35.0, 25.0, 10.0],
        "local_tan_score_0_100": [50.0, 99.0, 5.0, 50.0],
        "atmospheric_quality_percentile_0_100": [50.0] * 4,
        "temperature_2m": [75.0] * 4,
        "uvi_consensus": [5.0] * 4,
        "uv_index": [5.0] * 4,
        "predicted_uva_wm2": [40.0] * 4,
        "precipitation_probability": [0.0] * 4,
        "wind_speed_10m": [5.0] * 4,
        "wind_gusts_10m": [6.0] * 4,
        "apparent_temperature": [75.0] * 4,
        "comfort_band": ["perfect"] * 4,
    })


def test_fixed_30m_rank_equals_independent_interval_integration() -> None:
    from sunstack.opportunity import best_fixed_dose_window

    win = best_fixed_dose_window(_day(), 30, usable_only=True)
    assert win is not None
    # Independent rectangular integration over interval means (contract
    # §5.4): stamps label interval ENDS, so window [t_i, t_i+30m) holds the
    # single interval ending at t_{i+1}: [10:00]=0.6×1800=1080,
    # [10:30]=0.4×1800=720, [11:00]=0.1×1800=180 J/m².
    assert str(win[0]) == "2026-06-21 10:00:00"
    assert abs(win[2] - 1080.0) < 1e-9


def test_lower_local_percentile_cannot_make_weaker_dose_win() -> None:
    from sunstack.opportunity import best_fixed_dose_window

    day = _day()
    # 10:30 carries the max Local percentile (99) but the winning pair is
    # [10:00,10:30) on physics (990 > 900): Local never enters the objective.
    win = best_fixed_dose_window(day, 30, usable_only=False)
    assert win is not None
    assert str(win[0]) == "2026-06-21 10:00:00"


def test_hard_blocked_strongest_excluded_from_usable_but_retained() -> None:
    from sunstack.opportunity import best_fixed_dose_window

    day = _day()
    day.loc[0, "outdoor_blocked"] = True  # block the strongest slot
    usable = best_fixed_dose_window(day, 30, usable_only=True)
    strongest = best_fixed_dose_window(day, 30, usable_only=False)
    assert usable is not None and strongest is not None
    assert str(usable[0]) != str(strongest[0])
    assert str(strongest[0]) == "2026-06-21 10:00:00"


def test_comfortable_window_excludes_hard_blocked_and_warm_slots() -> None:
    from sunstack.opportunity import best_fixed_dose_window, build_daily_summary

    day = _day()
    day["melanogenic_effective_irradiance_wm2"] = [1.0, 0.8, 0.6, 0.4]
    day["outdoor_blocked"] = [True, False, False, False]
    day["comfort_band"] = ["too hot", "warm", "perfect", "sun-warmed"]
    strongest = best_fixed_dose_window(day, 30, usable_only=False)
    usable = best_fixed_dose_window(day, 30, usable_only=True)
    comfortable = best_fixed_dose_window(day, 30, usable_only=True, comfort_min=2)
    assert strongest is not None and usable is not None and comfortable is not None
    assert [str(window[0]) for window in (strongest, usable, comfortable)] == [
        "2026-06-21 10:00:00",
        "2026-06-21 10:30:00",
        "2026-06-21 11:00:00",
    ]
    row = build_daily_summary(day).iloc[0]
    assert _cell_text(row, "best_comfortable_usable_30m_start") == "2026-06-21T11:00:00"
    assert _cell_text(row, "best_comfortable_usable_30m_end") == "2026-06-21T11:30:00"
    assert row["best_comfortable_usable_30m_dose_j_m2"] == 720.0


def test_comfort_min_breaks_equal_dose_ties() -> None:
    from sunstack.opportunity import best_fixed_dose_window

    day = _day()
    day["melanogenic_effective_irradiance_wm2"] = [0.5] * 4
    day["outdoor_blocked"] = [False] * 4
    day["comfort_band"] = ["cool", "warm", "sun-warmed", "perfect"]
    cool_or_better = best_fixed_dose_window(day, 30, comfort_min=1)
    sun_warmed_or_better = best_fixed_dose_window(day, 30, comfort_min=2)
    assert cool_or_better is not None and sun_warmed_or_better is not None
    assert str(cool_or_better[0]) == "2026-06-21 10:00:00"
    assert str(sun_warmed_or_better[0]) == "2026-06-21 11:00:00"

def test_confidence_only_breaks_defined_ties() -> None:
    from sunstack.opportunity import best_fixed_dose_window

    day = _day()
    day["melanogenic_effective_irradiance_wm2"] = [0.4, 0.5, 0.5, 0.1]
    day["tan_forecast_confidence_0_100"] = [50.0, 90.0, 50.0, 50.0]
    day["outdoor_blocked"] = [False, False, False, False]
    win = best_fixed_dose_window(day, 30, usable_only=True, dose_tolerance_frac=0.01)
    # Rectangular: [10:00]=[10:30]=900 tie within tolerance; error tiebreak
    # ties too (30 vs 30), so earliest start wins outright.
    assert win is not None
    assert str(win[0]) == "2026-06-21 10:00:00"


def test_confidence_breaks_exact_ties() -> None:
    from sunstack.opportunity import best_fixed_dose_window

    day = _day()
    day["melanogenic_effective_irradiance_wm2"] = [0.5, 0.5, 0.5, 0.5]
    day["tan_forecast_confidence_0_100"] = [50.0, 50.0, 90.0, 50.0]
    day["outdoor_blocked"] = [False, False, False, False]
    win = best_fixed_dose_window(day, 30, usable_only=True, dose_tolerance_frac=0.01)
    # All doses exactly tied (900 each): [10:30] window (conf 50+90) beats
    # [10:00] (50+50); [11:00] ties [10:30] on err, earliest wins.
    assert win is not None
    assert str(win[0]) == "2026-06-21 10:30:00"


def test_daily_summary_carries_both_rankings() -> None:
    from sunstack.opportunity import build_daily_summary

    daily = build_daily_summary(_day())
    assert len(daily) == 1
    row = daily.iloc[0]
    assert row["window_rank_version"] == "fixed-duration-dose-v2"
    assert row["exposure_basis"] == "environmental_horizontal"
    assert _cell_text(row, "strongest_30m_start") == "2026-06-21T10:00:00"
    assert _cell_text(row, "best_usable_30m_start") == "2026-06-21T10:00:00"
    assert _cell_text(row, "best_comfortable_usable_30m_start") == "2026-06-21T10:00:00"
