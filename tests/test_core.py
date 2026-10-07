from __future__ import annotations

import time
from collections.abc import Iterator
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Required, TypedDict, cast, override

import numpy as np
import pandas as pd
import pytest
import yaml

from sunstack.calibrate import absolute_tan_score, prepare_nasa_training, solar_features
from sunstack.frame import num
from sunstack.history import candidate_cams_cycles, normalize_nasa_power
from sunstack.opportunity import best_contiguous_window
from sunstack.tanscore import (
    add_local_scores,
    build_live_feature_frame,
    circular_doy_distance,
    predict_uva_uvb,
)


def _text(frame: pd.DataFrame, name: str) -> pd.Series[str]:
    """Text-column read.

    The pandas stubs type ``frame[name]`` as ``Any``, which erases the whole
    expression that consumes it; the tests read text columns by contract.
    """
    return cast("pd.Series[str]", frame[name])


# `with` is a Python keyword, so the step document type is declared
# functionally instead of as a class.
_WorkflowStep = TypedDict(
    "_WorkflowStep",
    {
        "name": str,
        "uses": str,
        "run": str,
        "env": dict[str, str],
        "with": dict[str, str],
    },
    total=False,
)


class _WorkflowJob(TypedDict):
    steps: list[_WorkflowStep]


class _WorkflowOn(TypedDict, total=False):
    """Trigger block; only the keys these tests read are modelled."""

    schedule: Required[list[dict[str, str]]]
    push: dict[str, list[str]]
    pull_request: dict[str, list[str]]
    workflow_run: dict[str, list[str]]
    issues: dict[str, list[str]]
    workflow_dispatch: object
    pull_request_target: object


class _Workflow(TypedDict, total=False):
    name: str
    on: Required[_WorkflowOn]
    permissions: dict[str, str]
    jobs: Required[dict[str, _WorkflowJob]]


class _Pyproject(TypedDict):
    project: dict[str, object]
    tool: dict[str, dict[str, object]]


class _IssueChooser(TypedDict):
    blank_issues_enabled: bool


class _IssueFormAttributes(TypedDict, total=False):
    label: str
    options: list[str | dict[str, str]]


class _IssueFormField(TypedDict, total=False):
    type: Required[str]
    id: str
    attributes: Required[_IssueFormAttributes]


class _IssueForm(TypedDict, total=False):
    name: Required[str]
    description: Required[str]
    body: Required[list[_IssueFormField]]
    labels: list[str]


class _SitePayload(TypedDict):
    """The static-export payload (data.json) these tests assert on.

    Every key is written unconditionally by the export and the `/api/data`
    route, so none of them is optional: typing them as optional would let a
    regression drop one and only fail at the assertion, far from the cause.
    """

    run: str
    daily: list[dict[str, object]]
    hourly: list[dict[str, object]]
    half_hour: list[dict[str, object]]
    summary: dict[str, object]
    build_sha: str


class _LocationsDoc(TypedDict):
    locations: list[dict[str, object]]


def _load_yaml(path: Path) -> object:
    """Parsed YAML document.

    ``yaml.safe_load`` is untyped, so the parse is widened to ``object`` here
    and each document is cast to the shape the test actually reads.
    """
    return cast(object, yaml.safe_load(path.read_text(encoding="utf-8")))

def test_nasa_power_hourly_parser_uses_utc_and_preserves_uv():
    payload: dict[str, object] = {
        "properties": {
            "parameter": {
                "ALLSKY_SFC_UVA": {"2026010112": 34.2, "2026010113": 36.1},
                "ALLSKY_SFC_UVB": {"2026010112": 0.41, "2026010113": 0.46},
                "ALLSKY_SFC_UV_INDEX": {"2026010112": 4.1, "2026010113": 4.6},
            }
        }
    }
    out = normalize_nasa_power(payload)
    assert len(out) == 2
    utc = cast("pd.Series[pd.Timestamp]", out["time_utc"])
    assert utc.dt.tz is not None
    assert out.loc[0, "ALLSKY_SFC_UVA"] == 34.2
    assert out.loc[1, "ALLSKY_SFC_UVB"] == 0.46


def test_absolute_tanscore_is_global_and_monotonic():
    scores = absolute_tan_score(
        np.array([0.0, 6.0, 10.0, 20.0]),
        np.array([0.0, 35.0, 45.0, 60.0]),
    )
    assert scores[0] == 0
    assert scores[-1] == 100
    assert np.all(np.diff(scores) > 0)
    # A good UVI~6 / UVA~35 South Bend-like hour must not become ~100/100.
    assert 30 < scores[1] < 60


def test_local_percentile_is_interpretation_not_physics():
    times = pd.date_range("2020-08-20", periods=1000, freq="3h", tz="UTC")
    ref = pd.DataFrame(
        {
            "time_utc": times,
            "day_of_year": np.full(1000, 244),
            "solar_elevation_deg": np.tile(np.linspace(10, 65, 8), 125),
            "absolute_tan_score_0_100": np.linspace(5, 55, 1000),
        }
    )
    forecast = pd.DataFrame(
        {
            "time_utc": pd.to_datetime(
                ["2026-09-01T16:00Z", "2026-09-01T17:00Z"], utc=True
            ),
            "solar_elevation_deg": [50.0, 50.0],
            "tan_score_absolute_0_100": [20.0, 50.0],
        }
    )
    out = add_local_scores(forecast, ref)
    assert out["local_tan_score_0_100"].iloc[1] > out["local_tan_score_0_100"].iloc[0]
    assert forecast.loc[1, "tan_score_absolute_0_100"] == 50.0


from sunstack.opportunity import (
    apply_outdoor_feasibility,
    attach_fitzpatrick,
    build_30min_forecast,
)


def _opportunity_row(**overrides: object) -> pd.DataFrame:
    """One plausible daylight outdoor row; overrides break a single field."""
    row: dict[str, object] = {
        "tan_score_absolute_0_100": 44.0,
        "local_tan_score_0_100": 97.0,
        "atmospheric_quality_percentile_0_100": 94.0,
        "tan_forecast_confidence_0_100": 91.0,
        "temperature_2m": 78.0,
        "apparent_temperature": 80.0,
        "rain": 0.0,
        "showers": 0.0,
        "snowfall": 0.0,
        "precipitation": 0.0,
        "precipitation_probability": 0.0,
        "weather_code": 0,
        "wind_speed_10m": 5.0,
        "relative_humidity_2m": 50.0,
    }
    row.update(overrides)
    return pd.DataFrame([row])


def test_overall_merges_context_without_erasing_absolute_scale():
    out = apply_outdoor_feasibility(_opportunity_row())
    overall = num(out, "overall_tan_opportunity_0_100").iloc[0]
    assert 50 < overall < 65
    assert overall <= 64  # absolute + configured 20-point headroom
    assert out.loc[0, "outdoor_feasibility_0_100"] == 100


def test_rain_snow_and_temperature_hard_block_outdoor_opportunity():
    for kwargs in [
        {"rain": 0.01, "weather_code": 61},
        {"snowfall": 0.1, "weather_code": 71},
        {"temperature_2m": 111.0},
        {"temperature_2m": 45.0},
    ]:
        out = apply_outdoor_feasibility(_opportunity_row(**kwargs))
        assert bool(out.loc[0, "outdoor_blocked"])
        assert out.loc[0, "overall_tan_opportunity_0_100"] == 0
        assert out.loc[0, "tan_score_absolute_0_100"] == 44.0


def test_fitzpatrick_is_context_not_environmental_multiplier():
    base = _opportunity_row()
    scored = apply_outdoor_feasibility(base)
    out1 = attach_fitzpatrick(scored, 1)
    out6 = attach_fitzpatrick(scored, 6)
    assert (
        out1.loc[0, "overall_tan_opportunity_0_100"]
        == out6.loc[0, "overall_tan_opportunity_0_100"]
    )
    assert (
        out1.loc[0, "tan_score_absolute_0_100"]
        == out6.loc[0, "tan_score_absolute_0_100"]
    )
    assert "higher erythema" in str(out1.loc[0, "personal_uv_risk_context"])


def test_merges_tolerate_mixed_datetime_units():
    # Producers disagree on unit: Open-Meteo strings parse as us, xarray-derived
    # CAMS frames are ns. Neither ruff nor Pyright sees unit mismatches, and
    # merge_asof/merge refuse mixed keys at runtime, so pin the tolerance here.
    stamps = [
        "2020-01-01 00:00",
        "2020-01-01 01:00",
        "2020-01-01 02:00",
        "2020-01-01 03:00",
    ]
    nasa = pd.DataFrame(
        {
            "time_utc": pd.to_datetime(stamps, utc=True).astype("datetime64[us, UTC]"),
            "ALLSKY_SFC_UVA": [10.0, 12.0, 14.0, 16.0],
            "ALLSKY_SFC_UVB": [0.2, 0.3, 0.4, 0.5],
            "ALLSKY_SFC_UV_INDEX": [1.0, 2.0, 3.0, 4.0],
        }
    )
    cams_hist = pd.DataFrame(
        {
            "time_utc": pd.to_datetime(stamps, utc=True).astype("datetime64[ns, UTC]"),
            "total_aerosol_optical_depth_469nm": [0.1] * 4,
            "total_aerosol_optical_depth_865nm": [0.05] * 4,
            "total_column_ozone_kgm2": [0.006] * 4,
        }
    )
    out = prepare_nasa_training(nasa, cams_hist)
    assert len(out) == 4
    assert str(out["time_utc"].dtype) == "datetime64[ns, UTC]"
    assert bool(out["ozone_du"].notna().all())
    assert bool(out["aod340"].notna().all())
    best = pd.DataFrame(
        {
            "time": [
                "2020-01-01T00:00",
                "2020-01-01T01:00",
                "2020-01-01T02:00",
                "2020-01-01T03:00",
            ],
            "shortwave_radiation": [0.0, 100.0, 300.0, 500.0],
            "direct_normal_irradiance": [0.0, 200.0, 500.0, 800.0],
            "diffuse_radiation": [0.0, 50.0, 100.0, 120.0],
            "terrestrial_radiation": [0.0, 400.0, 800.0, 1000.0],
            "cloud_cover": [100.0, 80.0, 40.0, 10.0],
            "temperature_2m": [50.0, 55.0, 60.0, 65.0],
            "relative_humidity_2m": [80.0, 70.0, 60.0, 50.0],
            "surface_pressure": [10000.0] * 4,
        }
    )
    cams_live = pd.DataFrame(
        {
            "time_utc": pd.to_datetime(
                [
                    "2020-01-01 05:00",
                    "2020-01-01 06:00",
                    "2020-01-01 07:00",
                    "2020-01-01 08:00",
                ],
                utc=True,
            ).astype("datetime64[ns, UTC]"),
            "total_aerosol_optical_depth_340nm": [0.12] * 4,
            "total_aerosol_optical_depth_380nm": [0.10] * 4,
            "total_column_ozone_dobson": [300.0] * 4,
            "forecast_albedo": [0.2] * 4,
        }
    )
    live = build_live_feature_frame(best, cams_live)
    assert len(live) == 4
    assert str(live["time_utc"].dtype) == "datetime64[ns, UTC]"


def test_train_and_serve_share_clear_sky():
    # Train/serve skew guard: the UVA model must see the same clear-sky
    # algorithm in training (POWER CLRSKY is MERRA-based) and live (Ineichen).
    # The decoy CLRSKY value 1.0 must not survive preparation.
    stamp = pd.to_datetime(["2020-07-01 17:00"], utc=True).astype("datetime64[ns, UTC]")
    nasa = pd.DataFrame(
        {
            "time_utc": stamp,
            "ALLSKY_SFC_SW_DWN": [800.0],
            "CLRSKY_SFC_SW_DWN": [1.0],
        }
    )
    train = prepare_nasa_training(nasa, None)
    live = solar_features(pd.Series(stamp))
    assert float(num(train, "clear_ghi").iloc[0]) > 500.0
    assert float(num(train, "clear_ghi").iloc[0]) == float(num(live, "clear_ghi").iloc[0])


def test_best_window_end_is_exclusive_for_hourly_highlight():
    # UI contract: best_window_end is the end of the last 30-min slot, so an
    # hourly row exactly at the end is OUTSIDE the window (its :00 slot was
    # never selected). The UI tints start<=hour<end; keep the data side so.
    dts = pd.date_range("2026-09-15 12:00", periods=6, freq="30min", tz="UTC")
    day = pd.DataFrame(
        {
            "dt": dts,
            "overall_tan_opportunity_0_100": [50.0, 55.0, 60.0, 58.0, 10.0, 5.0],
            "outdoor_blocked": [False] * 6,
        }
    )
    window = best_contiguous_window(day)
    assert window is not None
    start, end, _ = window
    assert start == dts[0] and end == dts[3] + pd.Timedelta(minutes=30)
    hours = ["2026-09-15T12:00", "2026-09-15T13:00", "2026-09-15T14:00"]
    lit = [t for t in hours if start.isoformat()[:16] <= t < end.isoformat()[:16]]
    assert lit == ["2026-09-15T12:00", "2026-09-15T13:00"]


def test_30min_interpolation_forward_fills_boolean_flags():
    # numpy bool cannot hold the NaN gaps reindexing creates (upcasts to object
    # and breaks interpolate(method="time")). Flags must survive the resample
    # without blending; feasibility itself is recomputed at 30min below freezing
    # here, so every slot must end up blocked (pre-fix code raises TypeError).
    hourly = pd.DataFrame(
        {
            "time": ["2020-01-01T00:00", "2020-01-01T01:00", "2020-01-01T02:00"],
            "shortwave_radiation": [0.0, 100.0, 200.0],
            "temperature_2m": [40.0, 40.0, 40.0],
            "outdoor_blocked": [True, True, False],
        }
    )
    out = build_30min_forecast(hourly, None)
    assert len(out) == 5
    assert out["outdoor_blocked"].tolist() == [True] * 5


def test_30min_frame_carries_action_spectrum_row_identity():
    # Carry-out whitelist regression (§3/§28). The final recompute re-derives
    # every row's identity, but build_30min_forecast copies back only the
    # columns it names. The action-spectrum fields were absent from that list,
    # so the published frame could not name the spectrum its scores were
    # convolved against — every other recomputed child shipped, so nothing
    # else noticed.
    from sunstack import config
    from sunstack.opportunity import build_30min_forecast
    from sunstack.photobiology import load_action_spectrum

    hourly = pd.DataFrame(
        {
            "time": ["2026-09-29T12:00", "2026-09-29T13:00"],
            "shortwave_radiation_instant": [700.0, 800.0],
            "uv_index": [6.0, 7.0],
            "temperature_2m": [70.0, 72.0],
            "predicted_uva_wm2": [40.0, 45.0],
            "predicted_uvb_wm2": [1.1, 1.3],
            "tan_score_absolute_0_100": [50.0, 60.0],
        }
    )
    out = build_30min_forecast(hourly, None)
    assert "action_spectrum_version" in out.columns
    assert "action_spectrum_sha256" in out.columns
    assert set(out["action_spectrum_version"]) == {config.ACTION_SPECTRUM_VERSION}
    assert set(out["action_spectrum_sha256"]) == {
        load_action_spectrum(config.ACTION_SPECTRUM_STEM).sha256
    }


def test_30min_keeps_object_typed_radiation_split():
    # The live feed delivers the radiation split as strings/None, exactly like
    # the weather columns. Those were rescued by _SUBHOUR_NUMERIC_COLUMNS; the
    # radiation columns were not, so select_dtypes dropped them and the
    # native-HRRR override then created each one as all-NaN and filled only its
    # own stamps. Production shipped 30-min frames with shortwave/direct/diffuse
    # non-null on 36 of 671 rows (5%), which silently made the whole
    # surface/posture model inert: skin_plane_factor stayed 1.0 and the
    # reflected component stayed 0 on every interpolated daylight row.
    from sunstack.opportunity import build_30min_forecast
    from sunstack.spectral import apply_skin_plane

    hours = pd.date_range("2026-06-21 10:00", periods=6, freq="h")
    hourly = pd.DataFrame({
        "time": hours.strftime("%Y-%m-%dT%H:%M"),
        "shortwave_radiation": [400.0, 600.0, 750.0, 700.0, 500.0, 300.0],
        "direct_radiation": [250.0, 420.0, 560.0, 520.0, 330.0, 180.0],
        "diffuse_radiation": [150.0, 180.0, 190.0, 180.0, 170.0, 120.0],
        "shortwave_radiation_instant": [410.0, 610.0, 760.0, 710.0, 510.0, 310.0],
        "solar_elevation_deg": [45.0, 55.0, 62.0, 58.0, 48.0, 33.0],
        "solar_azimuth_deg": [130.0, 150.0, 180.0, 210.0, 230.0, 250.0],
        "albedo": [0.2] * 6,
        "uv_index": [5.0, 7.0, 8.0, 7.5, 5.5, 3.0],
        "tan_score_absolute_0_100": [40.0, 60.0, 70.0, 65.0, 45.0, 25.0],
    })
    # Native HRRR covers only the 10:00 and 12:00 stamps (minutes 0/30).
    hrrr = pd.DataFrame({
        "time": ["2026-06-21T10:00", "2026-06-21T12:00"],
        "shortwave_radiation": [405.0, 755.0],
        "direct_radiation": [255.0, 565.0],
        "diffuse_radiation": [150.0, 190.0],
    })
    object_typed = hourly.copy()
    for col in ("shortwave_radiation", "direct_radiation", "diffuse_radiation"):
        object_typed[col] = object_typed[col].map(str).astype(object)

    out = build_30min_forecast(object_typed, hrrr)
    for col in ("shortwave_radiation", "direct_radiation", "diffuse_radiation"):
        assert col in out.columns, f"{col} must survive the object-typed feed"
        assert pd.to_numeric(out[col], errors="coerce").notna().all(), (
            f"{col} must be populated on every 30-min row, not just the "
            f"{int(pd.to_numeric(out[col], errors='coerce').notna().sum())} "
            "native-HRRR stamps")

    # And the model that consumes it must actually respond to posture. The
    # factor is a transposition ratio, not "bigger is better": with a high sun
    # a 45 deg plane catches less than horizontal, so assert it MOVES off 1.0
    # rather than that it exceeds it.
    flat = apply_skin_plane(out.copy(), None, None, "unknown", "local")
    tilted = apply_skin_plane(out.copy(), 45.0, 180.0, "dry_beach_sand", "local")
    assert (flat["skin_plane_factor"] == 1.0).all(), "flat plane is the reference"
    factors = num(tilted, "skin_plane_factor")
    assert ((factors - 1.0).abs() > 1e-6).any(), (
        "a 45 deg tilt must move the plane factor off the horizontal reference "
        "once the beam/diffuse split is present")
    assert (tilted["skin_plane_ground_reflected_delayed_pigmentation_wm2"] > 0).any(), (
        "a tilted plane over sand must pick up ground reflection")


def test_30min_keeps_object_typed_weather_and_feasibility_agrees():
    # P0 regression: production feeds deliver temperature/wind/precip as
    # object/string dtype. The transformer must coerce (not drop) them, and
    # exact-hour 30-min Overall must match hourly Overall when no subhour
    # correction applies. Pre-fix: 161/196 exact hours disagreed (avg 4.5pts).
    from sunstack.opportunity import apply_outdoor_feasibility, build_30min_forecast

    hourly = pd.DataFrame(
        {
            "time": ["2026-09-29T08:00", "2026-09-29T09:00", "2026-09-29T10:00"],
            "temperature_2m": ["48.6", "55.0", "60.0"],
            "apparent_temperature": ["47.0", "54.0", "59.0"],
            "precipitation_probability": ["5", "5", "5"],
            "wind_speed_10m": ["9.0", "9.0", "9.0"],
            "wind_gusts_10m": ["16.0", "16.0", "16.0"],
            "weather_code": ["2", "2", "2"],
            "rain": ["0.0", "0.0", "0.0"],
            "showers": ["0.0", "0.0", "0.0"],
            "snowfall": ["0.0", "0.0", "0.0"],
            "relative_humidity_2m": ["63", "60", "58"],
            "shortwave_radiation_instant": [100.0, 300.0, 500.0],
            "uv_index": [1.0, 2.0, 3.0],
            "tan_score_absolute_0_100": [10.0, 40.0, 60.0],
            "local_tan_score_0_100": [10.0, 40.0, 60.0],
            "atmospheric_quality_percentile_0_100": [50.0, 50.0, 50.0],
            "tan_forecast_confidence_0_100": [80.0, 80.0, 80.0],
            "overall_tan_opportunity_0_100": [10.0, 40.0, 60.0],
        }
    )
    out = build_30min_forecast(hourly, None)
    for col in ("temperature_2m", "precipitation_probability",
                "wind_speed_10m", "weather_code"):
        assert col in out.columns, f"{col} must survive hourly->30min"
    ref = apply_outdoor_feasibility(hourly.copy())
    merged = out[out["time"].isin(ref["time"])].merge(
        ref[["time", "overall_tan_opportunity_0_100"]].rename(
            columns={"overall_tan_opportunity_0_100": "hourly_overall"}),
        on="time", how="left",
    )
    assert (merged["temperature_2m"].notna()).all()
    assert abs(num(merged, "overall_tan_opportunity_0_100").iloc[0]
               - num(merged, "hourly_overall").iloc[0]) < 0.5


def test_circular_doy_distance_wraps_year_boundary():
    dist = circular_doy_distance(pd.Series([1.0, 2.0, 180.0, 364.0, 365.0]), 1)
    assert dist.tolist() == [0.0, 1.0, 179.0, 3.0, 2.0]


def test_cams_cycle_candidates_run_newest_first():
    # Candidates start from the latest safe cycle (unpublished newest skipped):
    # at 03:20 the safe cycle is 9/13 12z; at 12:00 exactly, 12z just started
    # so the safe cycle is still 00z.
    got = candidate_cams_cycles(datetime(2026, 9, 14, 3, 20, tzinfo=UTC))
    assert got[0] == (date(2026, 9, 13), "12:00")
    assert got[1] == (date(2026, 9, 13), "00:00")
    assert len(got) == 4
    got = candidate_cams_cycles(datetime(2026, 9, 14, 12, 0, tzinfo=UTC))
    assert got[0] == (date(2026, 9, 14), "00:00")
def test_cams_group_unpublished_skips_single_retries(monkeypatch: pytest.MonkeyPatch):
    # A 400 'not a valid combination' on a group means the cycle isn't
    # published: skip per-variable retries (wasted ADS calls), keep the
    # genuine-failure path (unknown 400 still retries each variable).
    from sunstack import history

    calls: list[str | list[str]] = []

    def fake_retrieve(
        _client: object, _dataset: str, request: dict[str, object], _target: Path
    ) -> None:
        variable = request["variable"]
        # `list[str]` is a parameterized generic and cannot be passed to
        # isinstance; check the container and its members directly.
        assert isinstance(variable, str) or (
            isinstance(variable, list)
            and all(isinstance(v, str) for v in cast("list[object]", variable))
        )
        calls.append(cast("str | list[str]", variable))
        raise RuntimeError(
            "400 Client Error: Request has not produced a valid combination of values"
        )

    monkeypatch.setattr(history, "retrieve_cams", fake_retrieve)
    def _skip_zip_normalize(*_args: object) -> pd.DataFrame:
        """The archive never parses here; the fake returns an empty frame."""
        return pd.DataFrame()

    monkeypatch.setattr(history, "normalize_cams_netcdf_zip", _skip_zip_normalize)
    class InertJob:
        """Structural stand-in for a submitted ADS job (never polled here)."""

        def __init__(self) -> None:
            self.reply: dict[str, object] = {}

        def update(self) -> None:
            raise AssertionError("the inert job is never polled")

        def download(self, target: str) -> None:
            raise AssertionError(f"the inert job is never downloaded: {target}")

    class InertClient:
        """Stand-in ADS client: `retrieve_cams` is patched, so nothing is sent."""

        def retrieve(self, dataset: str, request: dict[str, object]) -> InertJob:
            raise AssertionError(f"unexpected live retrieve: {dataset} {request}")

    manifest: list[dict[str, object]] = []
    frames, complete = history.fetch_cams_cycle(
        Path("/tmp/nonexistent-cams-test"),
        InertClient(), manifest, date(2026, 9, 24), "12:00", True,
    )
    group_calls = [c for c in calls if len(c) > 1]
    single_calls = [c for c in calls if len(c) == 1]
    assert len(group_calls) == len(history.config.CAMS_FORECAST_VARIABLE_GROUPS)
    assert single_calls == []
    assert frames == [] and complete is False


def test_cams_forecast_falls_back_to_older_cycle(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    from sunstack import history

    calls: list[tuple[str, str]] = []

    def fake_fetch(
        _raw_dir: Path, _client: object, manifest: list[dict[str, object]],
        cycle_date: date, cycle: str, _force: bool,
    ) -> tuple[list[pd.DataFrame], bool]:
        calls.append((cycle_date.isoformat(), cycle))
        if len(calls) == 1:
            manifest.append(
                {
                    "group": "uv",
                    "ok": False,
                    "mode": "group",
                    "cycle": "new",
                    "error": "400",
                }
            )
            return [], False
        manifest.append({"group": "uv", "ok": True, "mode": "group", "cycle": "old"})
        frame = pd.DataFrame(
            {
                "time_utc": pd.date_range("2026-09-14", periods=3, freq="h", tz="UTC"),
                "source": ["x"] * 3,
                "v": [1.0, 2.0, 3.0],
            }
        )
        return [frame], True

    monkeypatch.setattr(history, "fetch_cams_cycle", fake_fetch)
    monkeypatch.setattr(history, "cds_credentials_present", lambda: True)
    monkeypatch.setattr(history, "_cds_client", lambda: object())
    out = history.fetch_cams_forecast(tmp_path)
    assert len(out) == 3
    assert len(calls) == 2
    assert out["cams_cycle"].iloc[0] == f"{calls[1][0]}T{calls[1][1]}Z"


def test_predicted_uv_is_zero_below_horizon(tmp_path: Path):
    features = pd.DataFrame(
        {
            "ghi": [100.0, 100.0],
            "uv_index": [5.0, 5.0],
            "is_day": [1, 0],
        }
    )
    uva, uvb, _ = predict_uva_uvb(features, tmp_path)
    assert uva[0] > 0 and uvb[0] > 0
    assert uva[1] == 0 and uvb[1] == 0


def test_cams_retrieve_abandons_stalled_request(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    from sunstack import history

    def _no_sleep(_secs: float) -> None:
        """The fake job state advances on its own; never really wait."""

    monkeypatch.setattr(time, "sleep", _no_sleep)

    class Stuck:
        def __init__(self) -> None:
            self.reply: dict[str, object] = {"state": "queued", "request_id": "r1"}

        def update(self) -> None:
            pass

        def download(self, target: str) -> None:
            raise AssertionError(f"must not download a stalled job to {target}")

    class Client:
        def retrieve(self, dataset: str, request: dict[str, object]) -> Stuck:
            assert dataset == "ds" and "data_format" in request
            return Stuck()

    target = tmp_path / "out.zip"
    try:
        history.retrieve_cams(
            Client(), "ds", {"data_format": "netcdf_zip"}, target, timeout_s=0
        )
    except TimeoutError as exc:
        assert "r1" in str(exc)
    else:
        raise AssertionError("stalled request must raise TimeoutError")


def test_request_diagnoses_empty_and_garbled_bodies():
    from sunstack import fetch

    class Resp:
        status_code: int = 200
        content: bytes = b""
        text: str = ""

        def raise_for_status(self) -> None:
            pass

        def json(self) -> object:
            raise ValueError("no JSON in an empty body")

    class Sess:
        """Stand-in requests session; records what the helper asked for."""

        def __init__(self) -> None:
            self.calls: list[tuple[str, dict[str, object], int]] = []

        def get(self, endpoint: str, params: dict[str, object], timeout: int) -> Resp:
            self.calls.append((endpoint, params, timeout))
            return Resp()

    session = Sess()
    r = fetch.request(session, "x", "https://example.com", {})
    assert session.calls == [("https://example.com", {}, 120)]
    assert r.payload is None and "empty body" in (r.error or "")

    class Garbled(Resp):
        content: bytes = b"<html>maintenance</html>"
        text: str = "<html>maintenance</html>"

        @override
        def json(self) -> object:
            raise ValueError("Expecting value: line 1 column 1 (char 0)")

    class Sess2:
        """Same stand-in, but every response body is unparseable HTML."""

        def __init__(self) -> None:
            self.calls: list[tuple[str, dict[str, object], int]] = []

        def get(self, endpoint: str, params: dict[str, object], timeout: int) -> Resp:
            self.calls.append((endpoint, params, timeout))
            return Garbled()

    session2 = Sess2()
    r2 = fetch.request(session2, "y", "https://example.com", {})
    assert session2.calls == [("https://example.com", {}, 120)]
    assert r2.payload is None
    assert "200" in (r2.error or "") and "maintenance" in (r2.error or "")


def test_cams_retrieve_polls_to_completion(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    from sunstack import history

    def _no_sleep(_secs: float) -> None:
        """The fake job state advances on its own; never really wait."""

    monkeypatch.setattr(time, "sleep", _no_sleep)
    seen: list[str] = []

    class Flowing:
        def __init__(self) -> None:
            self.reply: dict[str, object] = {"state": "accepted", "request_id": "r2"}
            self.states: Iterator[str] = iter(["queued", "running", "completed"])

        def update(self) -> None:
            self.reply = {"state": next(self.states), "request_id": "r2"}

        def download(self, target: str) -> None:
            seen.append(target)
            _ = Path(target).write_bytes(b"ok")

    class Client:
        def retrieve(self, dataset: str, request: dict[str, object]) -> Flowing:
            assert dataset == "ds" and "data_format" in request
            return Flowing()

    target = tmp_path / "out.zip"
    history.retrieve_cams(
        Client(), "ds", {"data_format": "netcdf_zip"}, target, timeout_s=60
    )
    assert Path(seen[0]).read_bytes() == b"ok"


def test_cams_retrieve_falls_back_on_format_rejection(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    from sunstack import history

    def _no_sleep(_secs: float) -> None:
        """The fake job state advances on its own; never really wait."""

    monkeypatch.setattr(time, "sleep", _no_sleep)
    calls: list[dict[str, object]] = []

    class Done:
        def __init__(self) -> None:
            self.reply: dict[str, object] = {"state": "completed", "request_id": "r3"}

        def update(self) -> None:
            pass

        def download(self, target: str) -> None:
            _ = Path(target).write_bytes(b"ok")

    class Client:
        def retrieve(self, dataset: str, request: dict[str, object]) -> Done:
            assert dataset == "ds"
            calls.append(dict(request))
            if "data_format" in request:
                raise RuntimeError("400 invalid")
            return Done()

    target = tmp_path / "out.zip"
    history.retrieve_cams(
        Client(), "ds", {"data_format": "netcdf_zip"}, target, timeout_s=60
    )
    assert "data_format" in calls[0] and "format" in calls[1]
    assert target.read_bytes() == b"ok"


def test_cams_manifest_records_failed_attempts(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    import json

    from sunstack import history

    def boom(
        _client: object, _dataset: str, _request: dict[str, object], _target: Path,
        _timeout_s: int | None = None,
    ) -> None:
        raise RuntimeError("simulated ADS outage")

    monkeypatch.setattr(history, "retrieve_cams", boom)
    monkeypatch.setattr(history, "cds_credentials_present", lambda: True)
    monkeypatch.setattr(history, "_cds_client", lambda: object())
    out = history.fetch_cams_forecast(tmp_path, force=True)
    assert out.empty
    manifest = cast(
        "dict[str, list[dict[str, object]]]",
        json.loads((tmp_path / "raw" / "cams_forecast" / "manifest.json").read_text()),
    )
    assert len(manifest["requests"]) > 0
    assert all(not r["ok"] for r in manifest["requests"])


def test_calendar_feed_lists_each_window_once_with_stable_uids():
    from sunstack.ui import build_calendar_ics

    daily = pd.DataFrame(
        [
            {
                "date": "2026-09-15",
                "best_window_start": "2026-09-15T12:30:00",
                "best_window_end": "2026-09-15T16:30:00",
                "best_usable_30m_start": "2026-09-15T12:30:00",
                "best_usable_30m_end": "2026-09-15T13:00:00",
                "best_usable_30m_dose_j_m2": 800.0,
                "strongest_30m_start": "2026-09-15T13:00:00",
                "strongest_30m_end": "2026-09-15T13:30:00",
                "strongest_30m_dose_j_m2": 1000.0,
                "day_overall_peak_0_100": 51.0,
                "peak_uv_index": 5.4,
                "peak_predicted_uva_wm2": 42.9,
                "peak_temperature_f": 85.1,
                "day_confidence_at_peak_0_100": 40.0,
                "day_status": "FAIR",
            },
            {"date": "2026-09-16", "best_window_start": None, "best_window_end": None},
        ]
    )
    first = build_calendar_ics(daily, "20260915_004803")
    second = build_calendar_ics(daily, "20260915_010000")
    assert first.count("BEGIN:VEVENT") == 1
    assert "UID:sunstack-best-sunstack-2026-09-15@sunstack" in first
    # The usable physical 30-minute window, not the legacy broad window,
    # defines the subscription time.
    assert "DTSTART:20260915T163000Z" in first
    assert "DTEND:20260915T170000Z" in first
    assert "SEQUENCE:0" in first
    # Same date UID across reruns: subscribed calendars update in place.
    # SEQUENCE stays 0 (immutable events; audit: run-tag digits overflowed).
    assert "UID:sunstack-best-sunstack-2026-09-15@sunstack" in second
    assert "SEQUENCE:0" in second
    # Hourly-fed descriptions carry per-day UV peaks, not just the score.
    hourly = pd.DataFrame(
        {
            "time": ["2026-09-15T12:00", "2026-09-15T13:00", "2026-09-16T12:00"],
            "uv_index": [5.0, 5.4, 1.0],
            "predicted_uva_wm2": [40.0, 42.9, 10.0],
            "predicted_uvb_wm2": [0.9, 1.0, 0.2],
        }
    )
    rich = build_calendar_ics(daily, "20260915_004803", hourly)
    flat = rich.replace("\r\n ", "")
    assert "Peak UV 5.4 at 1:00 PM" in flat
    assert "UVA 42.9 W/m2" in flat
    assert "UVB 1 W/m2" in flat
    assert "Best usable sun 12:30 PM-1:00 PM (dose 800 J/m2 E_mel)" in flat
    assert "Strongest 30m 1:00 PM-1:30 PM (dose 1000 J/m2 E_mel) is blocked" in flat


def test_30min_handles_fall_back_duplicate_hours():
    # DST fall-back repeats 1:00-2:00am in wall time. If the API returns both
    # instances with identical naive labels, the 30-min resample must not
    # crash the run (night rows never affect windows either way).
    hourly = pd.DataFrame(
        {
            "time": [
                "2026-11-01T00:00",
                "2026-11-01T01:00",
                "2026-11-01T01:30",
                "2026-11-01T01:00",
                "2026-11-01T01:30",
                "2026-11-01T02:00",
                "2026-11-01T12:00",
            ],
            "temperature_2m": [50.0, 49.0, 49.0, 48.0, 48.0, 48.0, 60.0],
            "overall_tan_opportunity_0_100": [0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 40.0],
            "tan_score_absolute_0_100": [0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 35.0],
        }
    )
    from sunstack.opportunity import build_30min_forecast

    out = build_30min_forecast(hourly, None)
    assert len(out) > 0
    assert bool((out["time"] == "2026-11-01T12:00").any())


def test_export_static_site_publishes_data_and_calendar(tmp_path: Path):
    from sunstack.output import export_static_site

    latest = tmp_path / "latest"
    (latest / "tables").mkdir(parents=True)
    hourly = pd.DataFrame(
        {
            "time": ["2026-09-15T12:00", "2026-09-15T13:00", "2026-09-15T20:00"],
            "is_day": [1, 1, 0],
            "temperature_2m": [80.0, 82.0, 70.0],
            "overall_tan_opportunity_0_100": [50.0, 60.0, 5.0],
            "tan_score_absolute_0_100": [40.0, 45.0, 4.0],
            "local_tan_score_0_100": [80.0, 85.0, 10.0],
            "atmospheric_quality_percentile_0_100": [60.0, 65.0, 20.0],
            "tan_forecast_confidence_0_100": [50.0, 55.0, 30.0],
        }
    )
    half = pd.DataFrame(
        {
            "dt": pd.to_datetime(
                [
                    "2026-09-15 12:00",
                    "2026-09-15 12:30",
                    "2026-09-15 13:00",
                    "2026-09-15 13:30",
                    "2026-09-15 20:00",
                ]
            ),
            "time": [
                "2026-09-15T12:00",
                "2026-09-15T12:30",
                "2026-09-15T13:00",
                "2026-09-15T13:30",
                "2026-09-15T20:00",
            ],
            "is_day": [1, 1, 1, 1, 0],
            "temperature_2m": [80.0, 81.0, 82.0, 81.0, 70.0],
            "overall_tan_opportunity_0_100": [50.0, 55.0, 60.0, 58.0, 5.0],
            "tan_score_absolute_0_100": [40.0, 42.0, 45.0, 44.0, 4.0],
            "local_tan_score_0_100": [80.0, 82.0, 85.0, 84.0, 10.0],
            "atmospheric_quality_percentile_0_100": [60.0, 62.0, 65.0, 64.0, 20.0],
            "tan_forecast_confidence_0_100": [50.0, 52.0, 55.0, 54.0, 30.0],
        }
    )
    hourly.to_parquet(latest / "tables" / "tan_forecast_hourly.parquet", index=False)
    half.to_parquet(latest / "tables" / "tan_forecast_30min.parquet", index=False)
    _ = (latest / "summary.json").write_text(
        '{"run": "test123", "created_at": "2026-09-15T00:00:00-04:00"}'
    )
    import json as _json

    info = export_static_site(tmp_path, tmp_path / "site")
    assert info["days"] == 1 and info["events"] == 1
    html = (tmp_path / "site" / "index.html").read_text()
    assert "./data.json" in html and "/api/data" not in html
    assert "build_sha" in html and "build=" in html, (
        "runline shows SHA and console logs it"
    )
    payload = cast(
        _SitePayload,
        _json.loads((tmp_path / "site" / "data.json").read_text()),
    )
    assert payload["build_sha"], "data.json must carry the code SHA"
    assert [row["time"] for row in payload["hourly"]] == [
        "2026-09-15T12:00",
        "2026-09-15T13:00",
    ]
    assert {row["is_day"] for row in payload["half_hour"]} == {1}
    import subprocess as _sp

    want = _sp.run(
        ["git", "rev-parse", "--short", "HEAD"],
        capture_output=True,
        text=True,
        check=False,
    ).stdout.strip()
    assert payload["build_sha"] == (want or "unknown"), (
        "SHA matches the exporting commit"
    )
    assert 'rel="icon"' in html, "static export must silence the favicon 404"
    assert "locations.json" in html, (
        "static picker must read locations.json before /api/locations"
    )
    locs = cast(
        _LocationsDoc,
        _json.loads((tmp_path / "site" / "locations.json").read_text()),
    )["locations"]
    assert {e["slug"] for e in locs} >= {"south-bend", "pacific-palisades"}
    assert any(e.get("url") for e in locs), "non-current sites need nav urls"
    assert "data-url" in html, "picker options must carry per-page urls"

    skin = cast(
        "dict[str, dict[str, str]]",
        _json.loads((tmp_path / "site" / "skin.json").read_text()),
    )
    assert sorted(skin) == ["1", "2", "3", "4", "5", "6"]
    assert "may burn" in skin["3"]["fitzpatrick_label"]
    surfaces = cast(
        "dict[str, dict[str, object]]",
        _json.loads((tmp_path / "site" / "surfaces.json").read_text()),
    )
    assert set(surfaces["grass_summer"]) == {
        "display_name", "proxy_reflectance", "reflectance_low",
        "reflectance_high", "spectral_quality", "optical_model",
    }
    assert "surfaces.json" in html and "reflected context" in html
    ics = (tmp_path / "site" / "calendar.ics").read_text()
    assert ics.count("BEGIN:VEVENT") == 1
    assert "UID:sunstack-best-south-bend-2026-09-15@south-bend" in ics

def test_fusion_recomputed_after_subhour_correction():
    # P1 regression: 30-min geometry/HRRR corrections must recompute fusion
    # from corrected sources. Interpolating consensus + sources independently
    # leaves consensus outside the visible source range (115/392 rows in prod).
    from sunstack.opportunity import build_30min_forecast

    hourly = pd.DataFrame(
        {
            "time": ["2026-09-24T12:00", "2026-09-24T13:00", "2026-09-24T14:00"],
            "uv_index": [4.0, 5.0, 4.5],
            "uvi_cams": [3.0, 3.2, 3.1],
            "uvi_epa": [4.0, 4.0, 4.0],
            "uvi_consensus": [4.0, 4.0, 4.0],
            "uvi_source_spread": [1.0, 1.8, 1.4],
            "uvi_sunny": [4.0, 5.0, 4.5],
            "uvi_cloudy": [3.0, 3.2, 3.1],
            "uvi_source_disagree": [True, True, True],
            "temperature_2m": [70.0, 72.0, 71.0],
            "precipitation_probability": [0.0, 0.0, 0.0],
            "wind_speed_10m": [5.0, 5.0, 5.0],
            "weather_code": [1, 1, 1],
            "shortwave_radiation_instant": [500.0, 600.0, 550.0],
        }
    )
    out = build_30min_forecast(hourly, None)
    sources = {name: num(out, name) for name in ("uv_index", "uvi_cams", "uvi_epa")}
    consensus = num(out, "uvi_consensus")
    spread = num(out, "uvi_source_spread")
    stamps = _text(out, "time")
    for i in range(len(out)):
        vs = [s.iloc[i] for s in sources.values() if not pd.isna(s.iloc[i])]
        if len(vs) >= 2 and not pd.isna(consensus.iloc[i]):
            assert min(vs) - 0.01 <= consensus.iloc[i] <= max(vs) + 0.01, (
                f"consensus {consensus.iloc[i]} outside sources {vs} at {stamps.iloc[i]}")
        if not pd.isna(spread.iloc[i]) and len(vs) >= 2:
            assert abs(spread.iloc[i] - (max(vs) - min(vs))) < 0.02, (
                f"spread {spread.iloc[i]} != range at {stamps.iloc[i]}")


def test_reskin_never_rewrites_forecast_identity(tmp_path: Path):
    # P0 regression: reskin_static_dir must update renderer identity only.
    # Pre-fix it overwrote build_sha, stamping new code onto old rows.
    import json as _json

    from sunstack.output import export_static_site, reskin_static_dir

    latest = tmp_path / "latest"
    (latest / "tables").mkdir(parents=True)
    hourly = pd.DataFrame(
        {
            "time": ["2026-09-15T12:00"],
            "temperature_2m": [80.0],
            "overall_tan_opportunity_0_100": [50.0],
            "tan_score_absolute_0_100": [40.0],
            "local_tan_score_0_100": [80.0],
            "atmospheric_quality_percentile_0_100": [60.0],
            "tan_forecast_confidence_0_100": [50.0],
        }
    )
    half = pd.DataFrame(
        {
            "dt": pd.to_datetime(["2026-09-15 12:00"]),
            "time": ["2026-09-15T12:00"],
            "temperature_2m": [80.0],
            "overall_tan_opportunity_0_100": [50.0],
            "tan_score_absolute_0_100": [40.0],
            "local_tan_score_0_100": [80.0],
            "atmospheric_quality_percentile_0_100": [60.0],
            "tan_forecast_confidence_0_100": [50.0],
        }
    )
    hourly.to_parquet(latest / "tables" / "tan_forecast_hourly.parquet", index=False)
    half.to_parquet(latest / "tables" / "tan_forecast_30min.parquet", index=False)
    _ = (latest / "summary.json").write_text(
        '{"run": "oldrun", "created_at": "2026-09-15T00:00:00-04:00",'
        + ' "forecast_code_sha": "aaa1111"}'
    )
    _ = export_static_site(tmp_path, tmp_path / "site")
    before = cast(
        _SitePayload, _json.loads((tmp_path / "site" / "data.json").read_text())
    )
    assert before["summary"]["forecast_code_sha"] == "aaa1111"
    _ = reskin_static_dir(tmp_path / "site")
    after = cast(
        _SitePayload, _json.loads((tmp_path / "site" / "data.json").read_text())
    )
    assert after["summary"]["forecast_code_sha"] == "aaa1111", (
        "reskin must never rewrite forecast identity")
    assert after["summary"].get("renderer_code_sha"), "reskin stamps renderer"
    assert after["build_sha"] == "aaa1111", "top-level SHA tracks forecast"



def test_reskin_static_dir_needs_no_run_data(tmp_path: Path):
    import json as _json

    from sunstack.output import reskin_static_dir

    page = tmp_path / "page"
    page.mkdir()
    _ = (page / "data.json").write_text(
        _json.dumps(
            {
                "run": "data/latest",
                "summary": {
                    "run": "20260922_173542",
                    "created_at": "2026-09-22T00:00:00+00:00",
                },
                "daily": [],
                "hourly": [],
                "half_hour": [],
            }
        ),
        encoding="utf-8",
    )
    _ = (page / "index.html").write_text("STALE", encoding="utf-8")
    _ = (page / "locations.json").write_text("{}", encoding="utf-8")
    _ = (page / "skin.json").write_text("{}", encoding="utf-8")
    info = reskin_static_dir(page)
    assert info["run"] == "20260922_173542", "reskin keeps the committed run tag"
    assert info["build_sha"], "reskin stamps the current code SHA"
    html = (page / "index.html").read_text()
    assert html != "STALE" and "./data.json" in html, (
        "index.html re-rendered from template"
    )
    assert (
        _json.loads((page / "data.json").read_text())["build_sha"] == info["build_sha"]
    )
    assert "dry_beach_sand" in _json.loads((page / "surfaces.json").read_text())


def test_daily_summary_keeps_status_and_wind_peaks():
    from sunstack.opportunity import build_daily_summary

    df = pd.DataFrame(
        {
            "dt": pd.to_datetime(["2026-09-24 12:00", "2026-09-24 12:30"]),
            "overall_tan_opportunity_0_100": [10.0, 40.0],
            "temperature_2m": [70.0, 72.0],
            "apparent_temperature": [71.0, 74.0],
            "wind_speed_10m": [9.0, 26.0],
            "wind_gusts_10m": [12.0, 34.0],
            "outdoor_blocked": [False, False],
        }
    )
    out = build_daily_summary(df)
    row = out.iloc[0]
    assert row["day_status"] == "FAIR", "status column must survive field additions"
    assert row["blocked_half_hours"] == 0
    assert row["day_peak_wind_mph"] == 26.0
    assert row["day_peak_gust_mph"] == 34.0
    assert row["day_high_feels_like_f"] == 74.0
    ui = Path("src/sunstack/serving.py").read_text(encoding="utf-8")
    assert "<th>Temp</th><th>Wind</th>" in ui, "hourly table needs a Wind column"
    assert "wind_gusts_10m" in ui and "windy" in ui, "gusty days/cells call out wind"


def test_calendar_uids_are_namespaced_per_location():
    from sunstack.ui import build_calendar_ics

    daily = pd.DataFrame(
        [
            {
                "date": "2026-09-15",
                "best_window_start": "2026-09-15T12:30:00",
                "best_window_end": "2026-09-15T16:30:00",
                "day_overall_peak_0_100": 51.0,
                "day_status": "FAIR",
            }
        ]
    )
    sb = build_calendar_ics(daily, "20260915_004803")
    pal = build_calendar_ics(daily, "20260915_004803", site_slug="pacific-palisades")
    assert "UID:sunstack-best-sunstack-2026-09-15@sunstack" in sb
    assert "UID:sunstack-best-pacific-palisades-2026-09-15@pacific-palisades" in pal


def test_30min_kills_pre_sunrise_ghost_light():
    # Linear blends invent sunlight before sunrise (Sep 15 sunup ~7:14am
    # local). The geometry-aware interpolator must report exactly zero.
    from sunstack.opportunity import build_30min_forecast

    hourly = pd.DataFrame(
        {
            "time": ["2026-09-15T06:00", "2026-09-15T07:00", "2026-09-15T08:00"],
            "temperature_2m": [60.0, 61.0, 63.0],
            "shortwave_radiation_instant": [0.0, 250.0, 500.0],
            "predicted_uva_wm2": [0.0, 25.0, 45.0],
            "uv_index": [0.0, 2.0, 4.0],
            "overall_tan_opportunity_0_100": [0.0, 20.0, 35.0],
            "tan_score_absolute_0_100": [0.0, 18.0, 32.0],
        }
    )
    out = build_30min_forecast(hourly, None)
    slot = out.loc[_text(out, "time") == "2026-09-15T06:30"]
    assert float(num(slot, "shortwave_radiation_instant").iloc[0]) == 0.0
    assert float(num(slot, "predicted_uva_wm2").iloc[0]) == 0.0


def test_30min_uses_clear_sky_index_not_linear_blend(monkeypatch: pytest.MonkeyPatch):
    # With TOA mocked nonlinear in wall time, constant-kt input must come
    # back exact; a linear GHI blend would give 250.0 instead of 312.5.
    import numpy as np

    import sunstack.opportunity as opp

    def fake_toa(times_utc: pd.Series) -> np.ndarray:
        minutes = pd.to_datetime(times_utc).dt.minute.to_numpy()
        toa = np.full(minutes.shape, 250.0)
        toa[minutes == 0] = 100.0
        return toa

    monkeypatch.setattr(opp, "_toa_wm2", fake_toa)
    hourly = pd.DataFrame(
        {
            "time": ["2026-09-15T06:00", "2026-09-15T07:00", "2026-09-15T08:00"],
            "temperature_2m": [70.0, 72.0, 74.0],
            "shortwave_radiation_instant": [100.0, 400.0, 700.0],
            "predicted_uva_wm2": [10.0, 40.0, 70.0],
            "uv_index": [1.0, 3.0, 5.0],
            "overall_tan_opportunity_0_100": [10.0, 30.0, 50.0],
            "tan_score_absolute_0_100": [9.0, 28.0, 48.0],
        }
    )
    out = opp.build_30min_forecast(hourly, None)
    slot = out.loc[_text(out, "time") == "2026-09-15T06:30"]
    assert float(num(slot, "shortwave_radiation_instant").iloc[0]) == 312.5
    assert float(num(slot, "predicted_uva_wm2").iloc[0]) == 31.25


def test_30min_broadband_corrections_recompute_pigment_channel():
    # Broadband corrections (clear-sky-index / native-HRRR) rescale UVA/UVB
    # after interpolation; the pigment-darkening channel must be recomputed
    # from the corrected bands, or corrected rows would publish pigment doses
    # inconsistent with their own radiation.
    import sunstack.opportunity as opp
    from sunstack.spectral import pigment_darkening_from_broadband

    hourly = pd.DataFrame(
        {
            "time": ["2026-09-15T12:00", "2026-09-15T13:00", "2026-09-15T14:00"],
            "temperature_2m": [80.0, 82.0, 83.0],
            "shortwave_radiation_instant": [500.0, 520.0, 500.0],
            "predicted_uva_wm2": [40.0, 42.0, 40.0],
            "predicted_uvb_wm2": [0.5, 0.52, 0.5],
            "uv_index": [5.0, 5.2, 5.0],
            "overall_tan_opportunity_0_100": [40.0, 42.0, 40.0],
            "tan_score_absolute_0_100": [38.0, 40.0, 38.0],
        }
    )
    # Native HRRR sees much brighter broadband: bounded correction rescales
    # the bands on native rows, so stale pigment would visibly mismatch.
    hrrr15 = pd.DataFrame(
        {
            "time": ["2026-09-15T12:00", "2026-09-15T13:00", "2026-09-15T14:00"],
            "shortwave_radiation_instant": [800.0, 830.0, 800.0],
        }
    )
    out = opp.build_30min_forecast(hourly, hrrr15)
    native = out.loc[
        _text(out, "subhour_source").str.startswith("native_HRRR", na=False)
    ]
    assert len(native) > 0
    uva = num(native, "predicted_uva_wm2").to_numpy(dtype=float)
    assert bool(np.any(np.not_equal(uva, 40.0)))
    expected = np.round(
        pigment_darkening_from_broadband(
            num(native, "predicted_uva_wm2").to_numpy(dtype=float),
            num(native, "predicted_uvb_wm2").to_numpy(dtype=float),
        ),
        5,
    )
    got = num(native, "pigment_darkening_effective_irradiance").to_numpy(dtype=float)
    assert np.allclose(np.asarray(expected, dtype=float), got, rtol=0, atol=1e-9)


def test_30min_survives_non_numeric_ghi_dtype():
    # Some feeds deliver radiation as strings/None (object dtype), which the
    # numeric-only resample silently drops. The kt block must coerce, never
    # assume the interpolated frame carries the column (CI KeyError).
    from sunstack.opportunity import build_30min_forecast

    hourly = pd.DataFrame(
        {
            "time": ["2026-09-15T12:00", "2026-09-15T13:00", "2026-09-15T14:00"],
            "temperature_2m": [80.0, 82.0, 83.0],
            "shortwave_radiation_instant": ["400.0", None, "600.0"],
            "predicted_uva_wm2": [30.0, 40.0, 42.0],
            "uv_index": [4.0, 5.0, 5.2],
            "overall_tan_opportunity_0_100": [30.0, 40.0, 42.0],
            "tan_score_absolute_0_100": [28.0, 38.0, 40.0],
        }
    )
    assert not pd.api.types.is_numeric_dtype(hourly["shortwave_radiation_instant"])
    out = build_30min_forecast(hourly, None)
    slot = out.loc[_text(out, "time") == "2026-09-15T12:30"]
    assert float(num(slot, "shortwave_radiation_instant").iloc[0]) > 0.0


def test_30min_keeps_string_dtype_uv_index():
    # uv_index can arrive as strings (dropped by the numeric-only resample,
    # leaving the UI on a different product via fallback). It must survive
    # with the interpolated value.
    from sunstack.opportunity import build_30min_forecast

    hourly = pd.DataFrame(
        {
            "time": ["2026-09-15T12:00", "2026-09-15T13:00", "2026-09-15T14:00"],
            "temperature_2m": [80.0, 82.0, 83.0],
            "shortwave_radiation_instant": [400.0, 500.0, 600.0],
            "uv_index": ["4.0", "5.0", "5.2"],
            "predicted_uva_wm2": [30.0, 40.0, 42.0],
            "overall_tan_opportunity_0_100": [30.0, 40.0, 42.0],
            "tan_score_absolute_0_100": [28.0, 38.0, 40.0],
        }
    )
    out = build_30min_forecast(hourly, None)
    slot = out.loc[_text(out, "time") == "2026-09-15T12:30"]
    # Linear would give 4.5; the bounded geometry correction stays near it.
    assert 3.0 < float(num(slot, "uv_index").iloc[0]) < 6.0


def test_overnight_rows_score_zero_opportunity_not_residual():
    from sunstack.opportunity import apply_outdoor_feasibility

    df = pd.DataFrame(
        {
            "temperature_2m": [70.0, 65.0],
            "sza": [50.0, 95.0],
            "tan_score_absolute_0_100": [40.0, 30.0],
            "local_tan_score_0_100": [80.0, 70.0],
            "atmospheric_quality_percentile_0_100": [60.0, 50.0],
            "tan_forecast_confidence_0_100": [50.0, 50.0],
        }
    )
    out = apply_outdoor_feasibility(df, None)
    assert out["overall_tan_opportunity_0_100"].iloc[1] == 0.0
    assert out["overall_components_unblocked_0_100"].iloc[1] == 0.0
    # Environmental score is physics, not usability: untouched.
    assert out["tan_score_absolute_0_100"].iloc[1] == 30.0
    assert out["overall_tan_opportunity_0_100"].iloc[0] > 0.0


def test_hrrr_correction_stays_bounded_against_kt_baseline():
    # The HRRR ratio now measures native vs the kt-improved baseline instead
    # of stacking a second independent bound on linear (0.7 x 0.45 = 0.31
    # floor seen in production). Total stays within the composed clip.
    from sunstack.opportunity import build_30min_forecast

    hourly = pd.DataFrame(
        {
            "time": ["2026-09-15T12:00", "2026-09-15T13:00", "2026-09-15T14:00"],
            "temperature_2m": [80.0, 82.0, 83.0],
            "shortwave_radiation_instant": [400.0, 500.0, 600.0],
            "predicted_uva_wm2": [30.0, 40.0, 42.0],
            "uv_index": [4.0, 5.0, 5.2],
            "overall_tan_opportunity_0_100": [30.0, 40.0, 42.0],
            "tan_score_absolute_0_100": [28.0, 38.0, 40.0],
        }
    )
    hrrr = pd.DataFrame(
        {
            "time": ["2026-09-15T12:00", "2026-09-15T12:30", "2026-09-15T13:00"],
            "shortwave_radiation_instant": [450.0, 120.0, 520.0],
        }
    )
    plain = build_30min_forecast(hourly, None)
    fixed = build_30min_forecast(hourly, hrrr)
    for stamp in ("2026-09-15T12:00", "2026-09-15T12:30", "2026-09-15T13:00"):
        a = float(num(plain.loc[_text(plain, "time") == stamp], "predicted_uva_wm2").iloc[0])
        b = float(num(fixed.loc[_text(fixed, "time") == stamp], "predicted_uva_wm2").iloc[0])
        assert 0.3 * a <= b <= 2.1 * a


def test_scheduled_workflow_is_complete_and_wired():
    # Every Actions failure this week was a workflow edit that dropped a
    # step or an env key (missing export step, missing CDSAPI_KEY) and only
    # failed 15 minutes into a CI run. Pin the load-bearing surface here.
    wf = cast(_Workflow, _load_yaml(Path(".github/workflows/run.yml")))
    steps = wf["jobs"]["run"]["steps"]
    by_name = {s.get("uses", s.get("name")): s for s in steps}
    assert "actions/checkout@v7.0.1" in by_name
    assert "astral-sh/setup-uv@v10.1.0" in by_name
    # uv drift rewrote uv.lock mid-run and broke `git pull --rebase` for six
    # straight runs (Sep 17). The workflow pins the exact uv and the publish
    # step discards lock churn; pin both so no edit can silently drop them.
    setup_uv = by_name["astral-sh/setup-uv@v10.1.0"]
    assert setup_uv.get("with", {}).get("version"), (
        "setup-uv must pin an exact uv version"
    )
    names = [s.get("name") for s in steps]
    for required in (
        "Install dependencies",
        "Forecast + export + publish, one site at a time",
        "Bundle run data for download",
        "Upload run data",
    ):
        assert required in names, f"missing workflow step: {required}"
    upload = by_name["actions/upload-artifact@v4"]
    assert "sunstack-data-" in str(upload.get("with", {}).get("name", "")), (
        "artifact name must be per-run downloadable"
    )
    install = by_name["Install dependencies"]
    step = by_name["Forecast + export + publish, one site at a time"]
    assert "uv run sunstack run" in step.get("run", ""), (
        "single step runs, exports, and publishes per site"
    )
    assert "--locked" in install.get("run", ""), (
        "installs must fail loudly on lock drift, not rewrite uv.lock"
    )
    import inspect as _inspect

    from sunstack import cli as _cli

    pub_src = _inspect.getsource(_cli.publish_site)
    assert "uv.lock" in pub_src, "publish must discard uv.lock churn before rebasing"
    assert "theirs" in pub_src, (
        "publish must recover from mid-run local pushes instead of exit 128"
    )
    forecast = by_name["Forecast + export + publish, one site at a time"]
    env = forecast.get("env", {})
    assert "CDSAPI_URL" in env and "CDSAPI_KEY" in env
    schedules = wf["on"]["schedule"]
    assert any("0,9,12,21" in s["cron"] for s in schedules)
    assert all(s.get("timezone") == "America/Indiana/Indianapolis" for s in schedules)
    assert "workflow_dispatch" in wf["on"]
    import tomllib

    with open("pyproject.toml", "rb") as f:
        proj = cast("_Pyproject", cast(object, tomllib.load(f)))
    assert proj["project"].get("requires-python"), (
        "requires-python must survive metadata edits"
    )
    assert proj["tool"]["uv"].get("required-version"), (
        "uv required-version pins the resolver"
    )


def test_location_calibrate_workflow_is_post_merge_only():
    wf = cast(_Workflow, _load_yaml(Path(".github/workflows/location-calibrate.yml")))
    on = wf["on"]
    assert "pull_request_target" not in on, (
        "calibration must never run on unapproved proposals"
    )
    push_paths = (on.get("push", {}) or {}).get("paths", [])
    assert "locations.yaml" in push_paths, "calibration triggers on registry merge"
    perms = wf.get("permissions", {})
    assert "pull-requests" not in perms, "calibrate job needs no PR write scope"
    steps = wf["jobs"]["calibrate"]["steps"]
    runs = " ".join(str(s.get("run", "")) for s in steps)
    assert "calibrate_missing_sites.py" in runs, (
        "calibration bootstraps only missing sites"
    )
    assert "CDSAPI_URL" in runs or any(
        "CDSAPI_URL" in str(s.get("env", "")) for s in steps
    ), "secrets flow to the post-merge job, never to intake"


def test_location_intake_workflow_holds_no_secrets():
    wf = cast(_Workflow, _load_yaml(Path(".github/workflows/location-intake.yml")))
    text = Path(".github/workflows/location-intake.yml").read_text(encoding="utf-8")
    scrubbed = text.replace("nobody gets secrets", "")
    assert "secrets." not in scrubbed, "intake must never read any GitHub secret"
    assert "CDSAPI_URL" not in text and "CDSAPI_KEY" not in text, (
        "intake must never touch CAMS credentials"
    )
    assert "pull_request_target" in wf["on"], (
        "intake validates unapproved proposals"
    )
    perms = wf.get("permissions", {})
    assert perms.get("contents") == "read", "intake stays read-only on code"


def test_location_propose_workflow_is_issue_triggered_and_secret_free():
    text = Path(".github/workflows/location-propose.yml").read_text(encoding="utf-8")
    wf = cast(_Workflow, _load_yaml(Path(".github/workflows/location-propose.yml")))
    on = wf["on"]
    assert "issues" in on, "propose triggers on [Location] issues"
    scrubbed = text.replace("nobody gets secrets", "")
    assert "secrets." not in scrubbed, "propose must never read any GitHub secret"
    assert "CDSAPI_URL" not in text and "CDSAPI_KEY" not in text
    runs = " ".join(str(s.get("run", "")) for s in wf["jobs"]["propose"]["steps"])
    assert "issue_location_to_pr.py" in runs, (
        "propose parses the issue into a registry append"
    )
    assert "reason=duplicate" in text and "reason=invalid" in text, (
        "parse must classify the failure"
    )
    assert "addLabels" in text, "failure comments must label the issue"
    assert "removeLabel" in text, "ready must clear stale duplicate/invalid labels"
    assert text.count("createComment") >= 2, (
        "duplicate/invalid and ready both comment on the issue"
    )
    assert "Closes #" in text, "opened PR must mention the issue so it closes on merge"
    assert "is staged with the one-entry append" in text, (
        "blocked PRs still hand off a staged branch"
    )
    assert "Allow GitHub Actions to create and approve pull requests" in text
    assert "allow_pr" in text, "maintainer can re-run with PR creation enabled"
    ui = Path("src/sunstack/serving.py").read_text(encoding="utf-8")
    assert "peak_precip_probability_pct" in ui and "c0392b" in ui, (
        "rainy days/cells highlight red"
    )
    assert "day_low_temperature_f" in ui and "day_high_temperature_f" in ui, (
        "day cards show temp range"
    )
    assert "day_absolute_peak_0_100" in ui and "day_local_peak_0_100" in ui, (
        "day cards show abs + local"
    )
    assert "getFullYear" in ui, "default day is today, not best day"


def test_issue_location_parser_round_trips_registry_append(tmp_path: Path):
    import subprocess
    import sys

    import yaml

    body = (
        "### Location name\n\nCasa de Campo, Dominican Republic\n\n"
        "### Proposed slug\n\ncasa-de-campo\n\n"
        "### Latitude\n\n18.42\n\n"
        "### Longitude\n\n-68.89\n\n"
        "### Timezone\n\nAmerica/Santo_Domingo\n"
    )
    _ = (tmp_path / "body.md").write_text(body, encoding="utf-8")
    out = tmp_path / "proposed.yaml"
    proc = subprocess.run(
        [
            sys.executable,
            "scripts/issue_location_to_pr.py",
            str(tmp_path / "body.md"),
            "locations.yaml",
            str(out),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 0, proc.stderr or proc.stdout
    proposed = cast("list[dict[str, object]]", yaml.safe_load(out.read_text(encoding="utf-8")))
    base = cast(
        "list[dict[str, object]]",
        yaml.safe_load(Path("locations.yaml").read_text(encoding="utf-8")),
    )
    assert len(proposed) == len(base) + 1, "propose appends exactly one entry"
    assert proposed[-1]["slug"] == "casa-de-campo"
    assert proposed[:-1] == base, "existing entries untouched"


def test_run_one_site_skips_cold_calibration_without_failing(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    import yaml

    from sunstack import cli, config

    _ = (tmp_path / "locations.yaml").write_text(
        yaml.safe_dump(
            [
                {
                    "slug": "south-bend",
                    "name": "SB",
                    "lat": 41.7,
                    "lon": -86.2,
                    "timezone": "America/Indiana/Indianapolis",
                    "default": True,
                },
                {
                    "slug": "cold-site",
                    "name": "Cold",
                    "lat": 10.0,
                    "lon": 10.0,
                    "timezone": "UTC",
                },
            ]
        ),
        encoding="utf-8",
    )
    monkeypatch.chdir(tmp_path)
    (tmp_path / "data").mkdir(exist_ok=True)
    cold = next(
        s
        for s in config.load_sites(tmp_path / "locations.yaml")
        if s.slug == "cold-site"
    )
    import pytest

    with pytest.raises(cli.SiteSkipped):
        _ = cli.run_one_site(tmp_path / "data", cold)
    # South Bend path resolution never touches the cold site.
    sb = next(
        s
        for s in config.load_sites(tmp_path / "locations.yaml")
        if s.slug == "south-bend"
    )
    _, cal_dir, _ = cli.calibration_paths(tmp_path / "data", None)
    assert cal_dir == tmp_path / "data" / "calibration"
    assert sb.slug == "south-bend"


def test_site_refresh_workflow_is_ui_only_and_secret_free():
    text = Path(".github/workflows/site-refresh.yml").read_text(encoding="utf-8")
    wf = cast(_Workflow, _load_yaml(Path(".github/workflows/site-refresh.yml")))
    on = wf["on"]
    assert "workflow_dispatch" in on, "refresh stays manually runnable"
    assert "workflow_run" in on, "refresh fires after each forecast run"
    assert (on.get("workflow_run", {}) or {}).get("workflows") == ["forecast-run"]
    assert "schedule" not in on and "schedule" not in text, (
        "refresh never forecasts on its own"
    )
    push_paths = (on.get("push", {}) or {}).get("paths", []) or []
    assert "src/sunstack/ui.py" in push_paths, "UI fixes publish without a forecast run"
    assert "locations.yaml" in push_paths, "registry changes re-export the picker"
    assert "secrets." not in text and "CDSAPI" not in text, (
        "refresh touches no credentials"
    )
    runs = " ".join(str(s.get("run", "")) for s in wf["jobs"]["refresh"]["steps"])
    assert "sunstack reskin" in runs, (
        "refresh re-renders committed docs, never needs data/latest"
    )
    assert "sunstack run" not in runs, "forecast stays in forecast-run only"
    assert "sunstack export" not in runs, (
        "export needs data/latest, which CI checkouts lack"
    )


def test_run_alternates_publish_per_site():
    import inspect

    from sunstack import cli

    # run→publish per site (not run-all→publish-all): one slow site can never
    # take down the other's fresh data.
    src = inspect.getsource(cli.run_one_site_locked)
    assert "run_live" in src and "export_static_site" in src and "publish_site" in src
    assert "site_lock" in inspect.getsource(cli.run_one_site), (
        "per-site runs serialize under the site lock (audit: globals unsafe)")
    # Cold sites skip without failing: calibrate workflow owns bootstrap.
    assert "SiteSkipped" in inspect.getsource(cli.run_all_sites)
    # Run dirs are ephemeral CI state (artifact carries them); only docs +
    # calibration outputs commit, so git never grows 40MB/run.
    pub = inspect.getsource(cli.publish_site)
    assert "calibration" in pub, "calibration models still publish for fresh clones"
    assert "/latest" not in pub and "/runs" not in pub, "run dirs must not commit"


def test_uv_ghi_disagreement_flags_only_strong_daytime_mismatch():
    from sunstack.tanscore import apply_disagreement_penalty, uv_ghi_disagree

    def flag(**kw: float) -> bool:
        base: dict[str, float] = {
            "ghi": np.nan,
            "terrestrial_radiation": np.nan,
            "uv_index": np.nan,
            "uv_index_clear_sky": np.nan,
            "sza": np.nan,
        }
        base.update(kw)
        return bool(uv_ghi_disagree(pd.DataFrame([base])).iloc[0])

    # Sep-16 case: bright broadband, dark UV, high sun.
    assert flag(
        ghi=641.0,
        terrestrial_radiation=1044.0,
        uv_index=0.65,
        uv_index_clear_sky=5.7,
        sza=35.0,
    )
    # Mirror image: dark broadband, bright UV.
    assert flag(
        ghi=150.0,
        terrestrial_radiation=1000.0,
        uv_index=5.0,
        uv_index_clear_sky=6.0,
        sza=40.0,
    )
    # Consistent skies never flag.
    assert not flag(
        ghi=800.0,
        terrestrial_radiation=1000.0,
        uv_index=6.0,
        uv_index_clear_sky=7.0,
        sza=35.0,
    )
    assert not flag(
        ghi=100.0,
        terrestrial_radiation=900.0,
        uv_index=0.5,
        uv_index_clear_sky=6.0,
        sza=40.0,
    )
    # Twilight angular physics, not contradiction.
    assert not flag(
        ghi=150.0,
        terrestrial_radiation=300.0,
        uv_index=0.8,
        uv_index_clear_sky=2.0,
        sza=80.0,
    )
    # Night and missing inputs never flag.
    assert not flag(
        ghi=0.0,
        terrestrial_radiation=0.0,
        uv_index=0.0,
        uv_index_clear_sky=0.0,
        sza=100.0,
    )
    assert not flag()

    conf = pd.Series([40.0, 30.0, float("nan")])
    out = apply_disagreement_penalty(conf, pd.Series([True, False, True]))
    assert out.tolist()[0] == 20.0
    assert out.tolist()[1] == 30.0
    assert pd.isna(out.tolist()[2])


def test_disagreement_flag_forward_fills_to_half_hours():
    from sunstack.opportunity import build_30min_forecast

    hourly = pd.DataFrame(
        {
            "time": ["2026-09-15T12:00", "2026-09-15T13:00", "2026-09-15T14:00"],
            "temperature_2m": [80.0, 82.0, 83.0],
            "shortwave_radiation_instant": [400.0, 500.0, 600.0],
            "uv_index": [4.0, 5.0, 5.2],
            "predicted_uva_wm2": [30.0, 40.0, 42.0],
            "overall_tan_opportunity_0_100": [30.0, 40.0, 42.0],
            "tan_score_absolute_0_100": [28.0, 38.0, 40.0],
            "uv_input_disagree": [False, True, False],
        }
    )
    out = build_30min_forecast(hourly, None)
    half = out.loc[_text(out, "time") == "2026-09-15T13:30"]
    assert len(half) == 1
    assert bool(num(half, "uv_input_disagree").iloc[0]) is True


def test_sun_posture_guidance_is_geometry_not_scoring():
    from sunstack.tanscore import (
        add_sun_posture,
        sun_compass,
        sun_posture_guidance,
        torso_lift_deg,
    )

    assert sun_compass(164.3) == "SSE"
    assert sun_compass(0.0) == "N"
    assert sun_compass(359.0) == "N"
    assert sun_compass(float("nan")) == "—"
    # Lift closes the zenith gap: 90 - elevation.
    assert torso_lift_deg(50.1) == 39.9
    assert torso_lift_deg(80.0) == 10.0
    assert torso_lift_deg(-5.0) is None
    assert torso_lift_deg(float("nan")) is None
    # Three bands: flat / flat-or-lift / face-and-lift; night never prescribes.
    assert "lay flat on back" in sun_posture_guidance(65.0, 180.0)
    assert "lift torso ~40" in sun_posture_guidance(50.1, 164.3)
    assert "face WSW" in sun_posture_guidance(15.0, 250.0)
    assert sun_posture_guidance(-5.0, 300.0).startswith("sun below horizon")
    # Real Sep-15 1 PM row: elev 50.1, azim 164.3.
    df = pd.DataFrame(
        {
            "solar_elevation_deg": [50.1],
            "solar_azimuth_deg": [164.3],
            "tan_score_absolute_0_100": [39.5],
        }
    )
    out = add_sun_posture(df)
    assert out["sun_compass"].iloc[0] == "SSE"
    assert out["torso_lift_deg"].iloc[0] == 39.9
    assert "SSE" in out["sun_posture_guidance"].iloc[0]
    assert out["tan_score_absolute_0_100"].iloc[0] == 39.5


def test_posture_labels_recomputed_at_half_hours():
    from sunstack.opportunity import build_30min_forecast

    hourly = pd.DataFrame(
        {
            "time": ["2026-09-15T12:00", "2026-09-15T13:00", "2026-09-15T14:00"],
            "temperature_2m": [80.0, 82.0, 83.0],
            "shortwave_radiation_instant": [400.0, 500.0, 600.0],
            "uv_index": [4.0, 5.0, 5.2],
            "predicted_uva_wm2": [30.0, 40.0, 42.0],
            "overall_tan_opportunity_0_100": [30.0, 40.0, 42.0],
            "tan_score_absolute_0_100": [28.0, 38.0, 40.0],
            "solar_elevation_deg": [45.0, 50.1, 48.0],
            "solar_azimuth_deg": [150.0, 164.3, 180.0],
        }
    )
    out = build_30min_forecast(hourly, None)
    half = out.loc[_text(out, "time") == "2026-09-15T13:30"]
    assert len(half) == 1
    # 13:30 geometry is exact pvlib (audit: was interpolated midpoint):
    # elev ~51.0, azim ~172 → S, not SSE; lift = 90 - elev.
    assert _text(half, "sun_compass").iloc[0] == "S"
    assert "S" in _text(half, "sun_posture_guidance").iloc[0]
    assert 38.0 < float(num(half, "torso_lift_deg").iloc[0]) < 42.0


def test_location_registry_loads_south_bend_default(tmp_path: Path):
    from sunstack.config import active_sites, default_site, load_sites

    sites = load_sites()
    assert {s.slug for s in sites} >= {"south-bend", "pacific-palisades"}
    assert default_site().slug == "south-bend"
    assert {s.slug for s in active_sites()} >= {"south-bend", "pacific-palisades"}
    sb = next(s for s in sites if s.slug == "south-bend")
    assert sb.timezone == "America/Indiana/Indianapolis"
    assert load_sites(tmp_path / "nope.yaml")[0].default is True


def test_location_registry_rejects_bad_entries(tmp_path: Path):
    import pytest
    import yaml

    from sunstack.config import load_sites

    def write(rows: list[dict[str, object]]) -> Path:
        p = tmp_path / "loc.yaml"
        _ = p.write_text(yaml.safe_dump(rows), encoding="utf-8")
        return p

    with pytest.raises((TypeError, ValueError)):
        _ = load_sites(
            write(
                [
                    {
                        "slug": "a",
                        "lat": 0,
                        "lon": 0,
                        "timezone": "UTC",
                        "default": True,
                    },
                    {"slug": "a", "lat": 1, "lon": 1, "timezone": "UTC"},
                ]
            )
        )
    with pytest.raises((TypeError, ValueError)):
        _ = load_sites(
            write(
                [{"slug": "x", "lat": 91, "lon": 0, "timezone": "UTC", "default": True}]
            )
        )
    with pytest.raises(ValueError):
        _ = load_sites(
            write(
                [
                    {
                        "slug": "x",
                        "lat": 0,
                        "lon": 0,
                        "timezone": "Mars/Olympus",
                        "default": True,
                    }
                ]
            )
        )
    with pytest.raises((TypeError, ValueError)):
        _ = load_sites(write([{"slug": "x", "lat": 0, "lon": 0, "timezone": "UTC"}]))


def test_use_site_scopes_coordinates_without_leak():
    from sunstack import config

    site = next(s for s in config.load_sites() if s.slug == "pacific-palisades")
    before = (config.LATITUDE, config.LONGITUDE, config.TIMEZONE)
    with config.use_site(site):
        assert (config.LATITUDE, config.LONGITUDE, config.TIMEZONE) == (
            34.04,
            -118.53,
            "America/Los_Angeles",
        )
        assert config.current_site() is site
    assert (config.LATITUDE, config.LONGITUDE, config.TIMEZONE) == before
    assert config.current_site() is None


def test_site_paths_namespace_non_default_only(tmp_path: Path):
    from sunstack.cli import calibration_paths

    default_root, default_cal, _ = calibration_paths(tmp_path)
    assert default_root == tmp_path / "calibration_sources"
    assert default_cal == tmp_path / "calibration"
    pal_root, pal_cal, _ = calibration_paths(tmp_path, "pacific-palisades")
    assert pal_root == tmp_path / "sites" / "pacific-palisades" / "calibration_sources"
    assert pal_cal == tmp_path / "sites" / "pacific-palisades" / "calibration"


def test_issue_forms_are_valid_and_secret_free():
    tpl = Path(".github/ISSUE_TEMPLATE")
    assert not list(tpl.glob("*.md")), "legacy markdown templates must stay retired"
    forms = sorted(tpl.glob("[0-9]-*.yml"))
    assert len(forms) == 3, "bug + feature + location forms, ordered by numeric prefix"
    cfg = cast(_IssueChooser, _load_yaml(tpl / "config.yml"))
    assert cfg.get("blank_issues_enabled") is False, "chooser forces structured forms"

    forbidden = ("password",)
    for form in forms:
        wf = cast(_IssueForm, _load_yaml(form))
        assert len(wf["name"]) > 3 and wf["description"], (
            f"{form.name} needs name + description"
        )
        body = wf["body"]
        assert body, f"{form.name} body cannot be empty"
        assert any(b.get("type") != "markdown" for b in body), (
            f"{form.name} needs an input field"
        )
        ids = [b["id"] for b in body if "id" in b]
        assert len(ids) == len(set(ids)), f"{form.name} ids must be unique"
        labels = [
            b["attributes"].get("label", "")
            for b in body
            if b.get("type") != "markdown"
        ]
        assert len(labels) == len(set(labels)), f"{form.name} labels must be unique"
        for b in body:
            assert b.get("type") in {
                "markdown",
                "textarea",
                "input",
                "dropdown",
                "checkboxes",
                "upload",
            }, f"{form.name}: bad input type"
            for opt in (b.get("attributes", {}) or {}).get("options", []) or []:
                opt = opt if isinstance(opt, str) else opt.get("label", "")
                assert opt.lower() != "none", (
                    f"{form.name}: 'None' is auto-populated, must not be listed"
                )
        assert "labels" in wf, f"{form.name} needs auto-applied labels"
        text = form.read_text(encoding="utf-8")
        scrubbed = text.replace("nobody needs secrets", "").replace(
            "needs no secrets", ""
        )
        assert all(w not in scrubbed.lower() for w in forbidden), (
            f"{form.name} label holds a forbidden word"
        )
        assert "CDSAPI" not in scrubbed and "secrets." not in scrubbed, (
            f"{form.name} must never touch credentials"
        )

    loc = cast(_IssueForm, _load_yaml(tpl / "3-location-request.yml"))
    loc_ids = {b.get("id") for b in loc["body"]}
    assert {"latitude", "longitude", "timezone", "slug", "location-name"} <= loc_ids, (
        "location form must capture registry fields explicitly"
    )


def test_debug_photobiology_reports_full_stack(tmp_path: Path, capsys: pytest.CaptureFixture[str]):
    # --photobiology debug must expose spectra, weights, reference, and the
    # latest hourly v4 columns; a silent or partial dump would hide the
    # internals the loud-failure contract relies on operators seeing.
    from sunstack.cli import debug_photobiology

    tables = tmp_path / "latest" / "tables"
    tables.mkdir(parents=True)
    pd.DataFrame({
        "time": ["2026-09-15T12:00"],
        "melanogenic_effective_irradiance_wm2": [0.5],
        "uv_index": [5.0],
        "uvi_openmeteo": [5.0],
        "uvi_cams": [float("nan")],
        "uvi_difference_percent": [float("nan")],
        "tan_score_absolute_0_100": [30.0],
        "legacy_absolute_tan_score_55_30_15": [28.0],
        "erythemal_irradiance_wm2": [0.125],
        "pigment_darkening_effective_irradiance": [0.08],
        "tan_dose_1h_j_m2": [1800.0],
        "sed_1h": [4.5],
        "uva_dose_1h_j_m2": [100000.0],
        "uvb_dose_1h_j_m2": [3000.0],
        "pigment_darkening_dose_1h_j_m2": [290.0],
        "spectral_backend": ["tierC-broadband-proxy-v2"],
        "spectral_tier": ["C"],
        "tan_score_model_version": ["action-spectrum-v2"],
        "cams_cycle": ["none"],
        "tan_calibration_tier": ["nasa_power_ml"],
        "uv_input_disagree": [False],
        "tan_forecast_confidence_0_100": [60.0],
    }).to_parquet(tables / "tan_forecast_hourly.parquet", index=False)
    debug_photobiology(tmp_path)
    out = capsys.readouterr().out
    for token in ("parrish_fda_3630", "cie_erythema_reference",
                  "ipd_action_spectrum", "Tier-C band weights",
                  "global_reference: global-mel-ref-v2",
                  "pigment_darkening_effective_irradiance",
                  "pigment_darkening_dose_1h_j_m2",
                  "latest hourly photobiology columns present"):
        assert token in out, token
    assert "MISSING columns" not in out


def test_debug_photobiology_without_latest_is_graceful(tmp_path: Path, capsys: pytest.CaptureFixture[str]):
    from sunstack.cli import debug_photobiology

    debug_photobiology(tmp_path)
    assert "no latest hourly table" in capsys.readouterr().out


def test_env_example_documents_every_src_env_var():
    # Operator-facing contract: every env var read in src (hand section or
    # BUGHUNT block) must be documented in .env.example; an undocumented
    # knob is an unusable knob.
    import re
    from pathlib import Path

    env = (Path(".env.example")).read_text(encoding="utf-8")
    seen: set[str] = set()
    for src in Path("src/sunstack").glob("*.py"):
        seen |= set(re.findall(r'os\.getenv\("([A-Z0-9_]+)"', src.read_text()))
    assert seen, "no env vars found — scanner broken"
    missing = sorted(v for v in seen if v not in env)
    assert not missing, missing


def test_dose_row_marks_partial_window_and_day_doses():
    # Cumulative doses can be partial (gap-split windows, incomplete days);
    # the dashboard dose row must surface that via the complete flags with
    # an explicit-false check, so pre-v4 rows without the keys render clean.
    from sunstack.ui import HTML

    assert "constpc=v=>v===false?'(partial)':''" in HTML.replace(" ", "")
    for flag in ("tan_dose_best_window_complete", "tan_dose_complete",
                 "best_hour_tan_dose_complete",
                 "sed_best_window_complete", "sed_complete"):
        assert "pc(d." + flag + ")" in HTML.replace(" ", ""), flag


def test_show_config_exposes_photobiology_model(capsys: pytest.CaptureFixture[str]):
    # Operators must see which model/reference/tier scoring uses; a config
    # dump without the v4 block hides the most consequential settings.
    from sunstack.cli import print_config

    print_config()
    out = capsys.readouterr().out
    for token in ("Photobiology model", "tan_score_model=action-spectrum-v2",
                  "global-mel-ref-v2", "tierC-broadband-proxy-v2",
                  "tandose_max_gap_s=", "skin_tilt_deg=",
                  "uvi_disagree_warn/strong="):
        assert token in out, token


def test_swap_once_fails_loudly_on_anchor_drift():
    # Static-export template replacement must fail loudly (not ship a subtly
    # broken page) when an anchor is missing or ambiguous.
    import pytest

    from sunstack.output import swap_once

    assert swap_once("ab", "b", "c") == "ac"
    with pytest.raises(RuntimeError, match="anchor drifted"):
        _ = swap_once("ab", "z", "c")
    with pytest.raises(RuntimeError, match="anchor drifted"):
        _ = swap_once("bb", "b", "c")


def test_scol_rejects_duplicate_columns_loudly():
    import pytest

    from sunstack.frame import scol

    dup = pd.DataFrame([[1.0, 2.0]], columns=["uva", "uva"])
    with pytest.raises(TypeError, match="unique Series"):
        _ = scol(dup, "uva")
    assert scol(pd.DataFrame({"uva": [1.0]}), "uva").tolist() == [1.0]


def test_num_missing_column_is_nan_not_crash():
    from sunstack.frame import num

    frame = pd.DataFrame({"a": [1.0, 2.0]})
    out = num(frame, "nope")
    assert out.isna().all()
    assert len(out) == 2


def test_build_local_reference_empty_is_empty(tmp_path: Path):
    from sunstack.calibrate import build_local_reference

    assert build_local_reference(pd.DataFrame(), tmp_path).empty


def test_train_uv_models_empty_raises_loudly(tmp_path: Path):
    import pytest

    from sunstack.calibrate import train_uv_models

    with pytest.raises(RuntimeError, match="empty"):
        _ = train_uv_models(pd.DataFrame(), tmp_path)


def test_build_local_reference_without_uvb_uses_uvi_fallback(tmp_path: Path):
    # No measured UVB band: the uvi*0.15 fallback keeps E_mel defined and
    # version-stamped instead of failing the rebuild.
    from sunstack.calibrate import build_local_reference

    training = pd.DataFrame({
        "time_utc": pd.date_range("2024-06-21 10:00", periods=6, freq="h", tz="UTC"),
        "uva": [30.0] * 6,
        "uvi": [5.0] * 6,
        "sza": [40.0] * 6,
        "ghi": [600.0] * 6,
    })
    ref = build_local_reference(training, tmp_path)
    assert len(ref) == 6
    assert ref["melanogenic_effective_irradiance_wm2"].notna().all()
    assert (ref["tan_score_model_version"] == "action-spectrum-v2").all()


def test_output_helpers_fail_loud_or_noop(tmp_path: Path):
    # Unknown locations and missing runs must fail with actionable errors
    # (never the wrong site or a bare crash); empty frames are no-ops.
    import importlib.util

    import pytest

    from sunstack.output import write_excel, write_frame
    from sunstack.ui import latest_dir, resolve_site

    assert resolve_site(None).slug == "south-bend"  # old URLs keep working
    with pytest.raises(FileNotFoundError, match="unknown location"):
        _ = resolve_site("no-such-place")
    with pytest.raises(FileNotFoundError, match="No SunStack run found"):
        _ = latest_dir(tmp_path)
    write_frame(pd.DataFrame(), tmp_path / "out", "x")
    assert not (tmp_path / "out").exists()
    write_excel({}, tmp_path / "empty.xlsx")
    assert not (tmp_path / "empty.xlsx").exists()
    if importlib.util.find_spec("openpyxl") is None:
        write_excel({"a": pd.DataFrame({"x": [1.0]})}, tmp_path / "w.xlsx")
        assert not (tmp_path / "w.xlsx").exists()


def test_day_status_thresholds():
    # User-facing day verdicts shown in the dashboard and day export; pin the
    # boundaries so a threshold edit is deliberate, never incidental.
    from sunstack.opportunity import day_status

    assert day_status(float("nan")) == "UNKNOWN"
    assert day_status(95.0) == "EXCELLENT"
    assert day_status(80.0) == "EXCELLENT"
    assert day_status(79.9) == "VERY GOOD"
    assert day_status(65.0) == "VERY GOOD"
    assert day_status(50.0) == "GOOD"
    assert day_status(35.0) == "FAIR"
    assert day_status(34.9) == "POOR"
    assert day_status(0.0) == "NO OUTDOOR WINDOW"


def test_30min_nearest_fills_discrete_weather_codes():
    # WMO codes / day flags must never be numerically interpolated: 12:30
    # between codes 61 and 3 must read nearest (61), not a 32.0 blend.
    from sunstack.opportunity import build_30min_forecast

    hourly = pd.DataFrame(
        {
            "time": ["2026-09-15T12:00", "2026-09-15T13:00", "2026-09-15T14:00"],
            "temperature_2m": [80.0, 81.0, 82.0],
            "shortwave_radiation_instant": [500.0, 510.0, 520.0],
            "predicted_uva_wm2": [40.0, 41.0, 42.0],
            "uv_index": [5.0, 5.1, 5.2],
            "overall_tan_opportunity_0_100": [40.0, 41.0, 42.0],
            "tan_score_absolute_0_100": [38.0, 39.0, 40.0],
            "weather_code": [61, 3, 3],
            "is_day": [1, 1, 1],
        }
    )
    out = build_30min_forecast(hourly, None)
    slot = out.loc[_text(out, "time") == "2026-09-15T12:30"]
    assert float(num(slot, "weather_code").iloc[0]) == 61.0


def test_read_table_falls_back_to_csv(tmp_path: Path):
    from sunstack.ui import latest_dir, read_table

    tables = tmp_path / "tables"
    tables.mkdir(parents=True)
    pd.DataFrame({"a": [1.0]}).to_csv(tables / "m.csv", index=False)
    assert read_table(tmp_path, "m")["a"].tolist() == [1.0]
    assert read_table(tmp_path, "missing").empty
    target = tmp_path / "run1"
    target.mkdir()
    _ = (tmp_path / "LATEST").write_text(str(target), encoding="utf-8")
    assert latest_dir(tmp_path) == target


def test_site_nav_relative_urls_cover_both_pages():
    # Static export picker: root page links down to sites, site pages link
    # back up; the current page never links to itself.
    from sunstack.ui import site_nav

    root = {e["slug"]: e for e in site_nav(None)}
    assert root["south-bend"]["url"] is None
    assert root["pacific-palisades"]["url"] == "sites/pacific-palisades/"
    site = {e["slug"]: e for e in site_nav("pacific-palisades")}
    assert site["pacific-palisades"]["url"] is None
    assert site["south-bend"]["url"] == "../../"


def test_build_sha_unknown_off_git(monkeypatch: pytest.MonkeyPatch):
    import subprocess

    import sunstack.ui as _ui
    from sunstack.build_sha import build_sha

    def _boom(*_args: object, **_kwargs: object) -> None:
        raise OSError("no git here")

    monkeypatch.setattr(_ui, "BUILD_SHA", None)
    monkeypatch.setattr(subprocess, "run", _boom)
    assert build_sha() == "unknown"


def test_calendar_builders_skip_ragged_rows():
    # Calendar builders must survive ragged frames: empty tables, missing
    # time columns, and unparseable stamps degrade to fewer events, never
    # a crash that blocks the whole export.
    from sunstack.ui import build_interval_ics, daily_uv_peaks

    assert daily_uv_peaks(pd.DataFrame()) == {}
    assert daily_uv_peaks(pd.DataFrame({"uv_index": [5.0]})) == {}
    half = pd.DataFrame([
        {"time": "2026-09-15T12:00", "tan_score_absolute_0_100": 40.0},
        {"time": None, "tan_score_absolute_0_100": 42.0},
        {"time": "not-a-time", "tan_score_absolute_0_100": 43.0},
    ])
    ics = build_interval_ics(half, "20260915_004803")
    assert ics.count("BEGIN:VEVENT") == 1
    assert ics.count("END:VEVENT") == 1


def test_location_registry_rejects_malformed_shapes(tmp_path: Path):
    # Every malformed registry shape must fail loudly at load (never a
    # half-parsed location silently scoring the wrong coordinates).
    import pytest
    import yaml

    from sunstack.config import load_sites

    def write(obj: object) -> Path:
        p = tmp_path / "loc.yaml"
        _ = p.write_text(yaml.safe_dump(obj), encoding="utf-8")
        return p

    def good(**kw: object) -> dict[str, object]:
        base: dict[str, object] = {"slug": "a", "lat": 0, "lon": 0, "timezone": "UTC",
                                   "default": True}
        base.update(kw)
        return base

    with pytest.raises(TypeError, match="must be a list"):
        _ = load_sites(write({"slug": "a"}))
    with pytest.raises(TypeError, match="must be a mapping"):
        _ = load_sites(write(["nope"]))
    with pytest.raises(TypeError, match="keys must be strings"):
        _ = load_sites(write([{123: "x", "slug": "a", "lat": 0, "lon": 0,
                           "timezone": "UTC"}]))
    with pytest.raises(TypeError, match="missing slug"):
        _ = load_sites(write([{"lat": 0, "lon": 0, "timezone": "UTC"}]))
    with pytest.raises(TypeError, match="must be a number"):
        _ = load_sites(write([good(lat="x")]))
    with pytest.raises(TypeError, match="must be a number"):
        _ = load_sites(write([good(lat=True)]))
    with pytest.raises(TypeError, match="must be a number"):
        _ = load_sites(write([good(lon="x")]))
    with pytest.raises(TypeError, match="must be a number"):
        _ = load_sites(write([good(lon=False)]))
    with pytest.raises(TypeError, match="must be a string"):
        _ = load_sites(write([good(timezone="")]))
    with pytest.raises(ValueError, match="empty"):
        _ = load_sites(write([]))
    assert load_sites(write(None)) == []
    with pytest.raises(ValueError, match="default"):
        _ = load_sites(write([good(default=False)]))


def test_render_static_html_falls_back_to_loaddata_anchor(monkeypatch: pytest.MonkeyPatch):
    # Template variants without the init() anchor must still get skin
    # wiring via the legacy loadData() anchor, never a half-swapped page.
    import sunstack.serving as _serving
    from sunstack.output import render_static_html

    variant = _serving.HTML.replace("init();\n</script>", "loadData();\n</script>")
    assert "loadData();\n</script>" in variant
    monkeypatch.setattr(_serving, "HTML", variant)
    monkeypatch.setattr("sunstack.ui.HTML", variant)
    html = render_static_html("20260923_000000")
    assert "loadData().then(initSkin);\n</script>" in html


def test_percentile_helpers_reject_non_series_loudly():
    import pytest

    from sunstack.tanscore import circular_doy_distance, fnum, percentile

    # The test's whole point is that a non-Series is rejected. The value stays a
    # list at runtime; this helper declares the type the caller is *claiming* to
    # hold, so the guard under test is still the thing that raises.
    def _as_declared(value: object) -> pd.Series:
        return cast("pd.Series", value)

    with pytest.raises(TypeError, match="must be a Series"):
        _ = percentile(_as_declared([1.0, 2.0]), 1.5)
    with pytest.raises(TypeError, match="must be a Series"):
        _ = circular_doy_distance(_as_declared([200, 210]), 205)
    row = pd.Series({"a": 5.0, "b": None, "c": "junk"})
    assert fnum(row, "a") == 5.0
    assert pd.isna(fnum(row, "missing"))
    assert pd.isna(fnum(row, "b"))
    assert pd.isna(fnum(row, "c"))
    assert fnum(row, "c", default=-1.0) == -1.0


def test_grade_ladders_cover_full_range():
    from sunstack.tanscore import grade_absolute, grade_local

    assert grade_absolute(float("nan")) == "unknown"
    assert grade_absolute(85.0) == "extreme natural tanning intensity"
    assert grade_absolute(0.0) == "low"
    assert grade_local(float("nan")) == "unknown"
    assert grade_local(99.0) == "exceptional locally"
    assert grade_local(91.8) == "excellent locally"
    assert grade_local(0.0) == "poor locally"


def test_local_scores_widen_on_thin_reference():
    # A tiny climatology (< 250 seasonal / < 100 geometry rows) must widen
    # to the full reference and still score, never NaN everything out.
    from sunstack.tanscore import add_local_scores

    forecast = pd.DataFrame({
        "time_utc": pd.to_datetime(["2026-06-21T12:00Z"]),
        "tan_score_absolute_0_100": [30.0],
        "solar_elevation_deg": [60.0],
    })
    ref = pd.DataFrame({
        "time_utc": pd.to_datetime(["2026-06-21T12:00Z"] * 3),
        "day_of_year": [172, 172, 172],
        "solar_elevation_deg": [60.0, 61.0, 59.0],
        "absolute_tan_score_0_100": [10.0, 20.0, 30.0],
    })
    out = add_local_scores(forecast, ref)
    assert out["local_tan_score_0_100"].notna().all()
    assert out["atmospheric_quality_percentile_0_100"].notna().all()


def test_class_aware_window_excludes_class_blocks():
    # Server-side class window: same ranking minus Mon-Fri class blocks.
    import pandas as pd

    from sunstack.opportunity import build_daily_summary

    rows: list[dict[str, object]] = []
    for h in range(9, 17):
        for m in (0, 30):
            rows.append({
                "dt": pd.Timestamp(f"2026-09-28 {h:02d}:{m:02d}"),
                "time": f"2026-09-28T{h:02d}:{m:02d}",
                "overall_tan_opportunity_0_100": 60.0,
                "is_day": 1,
                "outdoor_blocked": False,
                "temperature_2m": 70.0,
                "apparent_temperature": 70.0,
                "wind_speed_10m": 5.0,
                "wind_gusts_10m": 8.0,
                "precipitation_probability": 0.0,
            })
    daily = build_daily_summary(pd.DataFrame(rows))
    assert len(daily) == 1
    row = daily.iloc[0]
    # Monday 11:00-12:15 is class: available window must not start inside it.
    assert row["best_available_window_start"] is not None
    assert not ("11:00" <= row["best_available_window_start"][11:16] < "12:15"), (
        f"available window starts in class: {row['best_available_window_start']}")


def test_sun_adjusted_comfort_rewards_calm_sun_punishes_wind():
    # Bare-skin lying still: calm sun feels warmer than windy sun; muggy adds more.
    import pandas as pd

    from sunstack.opportunity import apply_outdoor_feasibility

    def row(temp: float, uvi: float, wind: float, dew: float) -> pd.DataFrame:
        return pd.DataFrame({
            'temperature_2m': [temp], 'apparent_temperature': [temp],
            'uv_index': [uvi], 'uvi_consensus': [uvi], 'uv_index_clear_sky': [5.5],
            'wind_speed_10m': [wind], 'wind_gusts_10m': [wind + 5],
            'precipitation_probability': [0.0], 'dew_point_2m': [dew],
            'relative_humidity_2m': [60.0], 'rain': [0.0], 'showers': [0.0],
            'snowfall': [0.0], 'weather_code': [1],
            'tan_score_absolute_0_100': [80.0], 'local_tan_score_0_100': [96.0],
            'atmospheric_quality_percentile_0_100': [80.0],
            'tan_forecast_confidence_0_100': [80.0]})

    calm = apply_outdoor_feasibility(row(68.0, 5.0, 2, 55)).iloc[0]
    windy = apply_outdoor_feasibility(row(68.0, 5.0, 20, 55)).iloc[0]
    muggy = apply_outdoor_feasibility(row(68.0, 5.0, 2, 74)).iloc[0]
    assert calm['sun_adjusted_feels_like_f'] > windy['sun_adjusted_feels_like_f'] + 3
    assert muggy['sun_adjusted_feels_like_f'] > calm['sun_adjusted_feels_like_f'] + 3
    # 65F scorcher-sun stays GOOD, never shitted on by mild air.
    hot = apply_outdoor_feasibility(row(65.0, 5.5, 3, 55)).iloc[0]
    assert hot['overall_tan_opportunity_0_100'] >= 65, (
        f"65F sun must stay GOOD, got {hot['overall_tan_opportunity_0_100']}")
