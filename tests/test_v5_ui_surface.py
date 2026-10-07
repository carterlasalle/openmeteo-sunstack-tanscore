import csv
import json
from collections.abc import Mapping
from importlib import import_module
from pathlib import Path
from typing import Protocol, cast

import pytest


class _Response(Protocol):
    status_code: int
    text: str

    def json(self) -> object: ...


class _Client(Protocol):
    def get(
        self, url: str, *, params: Mapping[str, str] | None = None
    ) -> _Response: ...

    def post(
        self, url: str, *, params: Mapping[str, str] | None = None
    ) -> _Response: ...


class _ClientFactory(Protocol):
    def __call__(self, app: object) -> _Client: ...

class _AppFactory(Protocol):
    def __call__(self, root: Path) -> object: ...


def _write_rows(path: Path, rows: list[dict[str, object]]) -> None:
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def _api_fixture(tmp_path: Path) -> Path:
    latest = tmp_path / "latest"
    tables = latest / "tables"
    tables.mkdir(parents=True)
    hourly: list[dict[str, object]] = [
        {
            "time": "2026-09-15T11:00",
            "is_day": 1,
            "solar_elevation_deg": 28.0,
            "solar_azimuth_deg": 145.0,
            "shortwave_radiation": 440.0,
            "direct_radiation": 320.0,
            "diffuse_radiation": 120.0,
            "temperature_2m": 80.0,
            "overall_tan_opportunity_0_100": 40.0,
            "tan_score_absolute_0_100": 35.0,
            "local_tan_score_0_100": 80.0,
            "atmospheric_quality_percentile_0_100": 60.0,
            "tan_forecast_confidence_0_100": 50.0,
            "tan_dose_1h_j_m2": 1000.0,
            "melanogenic_effective_irradiance_wm2": 0.4,
        },
        {
            "time": "2026-09-15T12:00",
            "is_day": 1,
            "solar_elevation_deg": 48.0,
            "solar_azimuth_deg": 180.0,
            "shortwave_radiation": 720.0,
            "direct_radiation": 560.0,
            "diffuse_radiation": 160.0,
            "temperature_2m": 82.0,
            "overall_tan_opportunity_0_100": 60.0,
            "tan_score_absolute_0_100": 45.0,
            "local_tan_score_0_100": 85.0,
            "atmospheric_quality_percentile_0_100": 65.0,
            "tan_forecast_confidence_0_100": 55.0,
            "tan_dose_1h_j_m2": 2000.0,
            "melanogenic_effective_irradiance_wm2": 0.5,
        },
        {
            "time": "2026-09-15T13:00",
            "is_day": 1,
            "solar_elevation_deg": 35.0,
            "solar_azimuth_deg": 215.0,
            "shortwave_radiation": 530.0,
            "direct_radiation": 390.0,
            "diffuse_radiation": 140.0,
            "temperature_2m": 81.0,
            "overall_tan_opportunity_0_100": 50.0,
            "tan_score_absolute_0_100": 40.0,
            "local_tan_score_0_100": 82.0,
            "atmospheric_quality_percentile_0_100": 62.0,
            "tan_forecast_confidence_0_100": 52.0,
            "tan_dose_1h_j_m2": 1500.0,
            "melanogenic_effective_irradiance_wm2": 0.45,
        },
    ]
    _write_rows(tables / "tan_forecast_hourly.csv", hourly)
    half: list[dict[str, object]] = []
    for time, elevation, azimuth, ghi, direct, diffuse, score, dose, blocked in (
        ("2026-09-15T11:00", 28.0, 145.0, 440.0, 320.0, 120.0, 40.0, 500.0, 1),
        ("2026-09-15T11:30", 38.0, 162.0, 600.0, 460.0, 140.0, 45.0, 800.0, 1),
        ("2026-09-15T12:00", 48.0, 180.0, 720.0, 560.0, 160.0, 60.0, 1000.0, 0),
        ("2026-09-15T12:30", 45.0, 195.0, 670.0, 510.0, 160.0, 58.0, 900.0, 0),
        ("2026-09-15T13:00", 40.0, 205.0, 600.0, 450.0, 150.0, 50.0, 700.0, 0),
        ("2026-09-15T13:30", 35.0, 215.0, 530.0, 390.0, 140.0, 48.0, 600.0, 0),
    ):
        half.append(
            {
                "dt": time,
                "time": time,
                "is_day": 1,
                "solar_elevation_deg": elevation,
                "solar_azimuth_deg": azimuth,
                "shortwave_radiation": ghi,
                "direct_radiation": direct,
                "diffuse_radiation": diffuse,
                "temperature_2m": 80.0,
                "overall_tan_opportunity_0_100": score,
                "tan_score_absolute_0_100": score - 5,
                "local_tan_score_0_100": 80.0,
                "atmospheric_quality_percentile_0_100": 60.0,
                "tan_forecast_confidence_0_100": 50.0,
                "tan_dose_30m_j_m2": dose,
                "melanogenic_effective_irradiance_wm2": 0.4,
                "apparent_temperature": 80.0,
                "wind_speed_10m": 5.0,
                "wind_gusts_10m": 6.0,
                "outdoor_blocked": blocked,
            }
        )
    _write_rows(tables / "tan_forecast_30min.csv", half)
    _ = (latest / "summary.json").write_text(
        json.dumps(
            {
                "run": "apitest",
                "created_at": "2026-09-15T00:00:00-04:00",
                "fusion_version": "test-fusion",
                "confidence_version": "test-confidence",
                "window_rank_version": "fixed-duration-dose-v2",
            }
        )
    )
    return tmp_path


def _client(root: Path) -> _Client:
    try:
        testclient_module = import_module("fastapi.testclient")
        ui_module = import_module("sunstack.ui")
        factory = cast(_ClientFactory, testclient_module.__dict__["TestClient"])
        app_factory = cast(_AppFactory, ui_module.__dict__["create_app"])
        return factory(app_factory(root))
    except (ImportError, RuntimeError):
        pytest.skip("httpx/TestClient not installed")


def _detail(response: _Response) -> str:
    body = response.json()
    assert isinstance(body, dict)
    return str(cast(dict[str, object], body)["detail"])


def _payload(response: _Response) -> dict[str, object]:
    body = response.json()
    assert isinstance(body, dict)
    return cast(dict[str, object], body)


def _rows(payload: dict[str, object], key: str) -> list[dict[str, object]]:
    rows = payload[key]
    assert isinstance(rows, list)
    typed_rows = cast(list[object], rows)
    result: list[dict[str, object]] = []
    for row in typed_rows:
        assert isinstance(row, dict)
        result.append(cast(dict[str, object], row))
    return result


def _number(row: dict[str, object], column: str) -> float:
    value = row[column]
    assert isinstance(value, int | float | str)
    return float(value)


def _stable_calendar_lines(text: str) -> list[str]:
    return [line for line in text.splitlines() if not line.startswith("DTSTAMP:")]


def test_data_rejects_bad_surface_extent_and_skin_plane(tmp_path: Path):
    client = _client(_api_fixture(tmp_path))

    bad_surface = client.get("/api/data", params={"surface": "nope"})
    assert bad_surface.status_code == 400
    assert "grass_summer" in _detail(bad_surface)

    bad_extent = client.get("/api/data", params={"surface_extent": "planet"})
    assert bad_extent.status_code == 400
    assert "surface_extent" in _detail(bad_extent)

    bad_tilt = client.get("/api/data", params={"skin_tilt_deg": "200"})
    assert bad_tilt.status_code == 400
    assert "[0, 180]" in _detail(bad_tilt)

    broad = client.get("/api/data", params={"surface_extent": "broad"})
    assert broad.status_code == 200, broad.text


def test_surface_context_preserves_horizontal_values(tmp_path: Path):
    client = _client(_api_fixture(tmp_path))
    params = {"skin_tilt_deg": "60", "skin_azimuth_deg": "180"}
    grass = client.get("/api/data", params={**params, "surface": "grass_summer"})
    sand = client.get("/api/data", params={**params, "surface": "dry_beach_sand"})
    assert grass.status_code == sand.status_code == 200
    grass_data, sand_data = _payload(grass), _payload(sand)

    for key in ("hourly", "half_hour"):
        for grass_row, sand_row in zip(
            _rows(grass_data, key), _rows(sand_data, key), strict=True
        ):
            for col in (
                "melanogenic_effective_irradiance_wm2",
                "tan_score_absolute_0_100",
                "overall_tan_opportunity_0_100",
                "tan_forecast_confidence_0_100",
            ):
                assert grass_row[col] == sand_row[col], col
    assert _rows(grass_data, "daily") == _rows(sand_data, "daily")

    reflected = "skin_plane_ground_reflected_delayed_pigmentation_wm2"
    grass_hourly, sand_hourly = _rows(grass_data, "hourly"), _rows(sand_data, "hourly")
    assert _number(sand_hourly[0], reflected) > _number(grass_hourly[0], reflected) > 0

    flat_grass = client.get(
        "/api/data", params={"surface": "grass_summer", "skin_tilt_deg": "0"}
    )
    flat_sand = client.get(
        "/api/data", params={"surface": "dry_beach_sand", "skin_tilt_deg": "0"}
    )
    assert flat_grass.status_code == flat_sand.status_code == 200
    assert _number(_rows(_payload(flat_grass), "hourly")[0], reflected) == 0
    assert _number(_rows(_payload(flat_sand), "hourly")[0], reflected) == 0


def test_refresh_and_calendar_validate_surface_without_reordering_environment(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    root = _api_fixture(tmp_path)
    client = _client(root)
    calls: list[dict[str, object]] = []

    def fake_run_live(*args: object, **kwargs: object) -> Path:
        _ = args
        calls.append(dict(kwargs))
        return root / "latest"

    monkeypatch.setattr("sunstack.cli.run_live", fake_run_live)
    before = client.get("/api/data")
    assert before.status_code == 200
    surface_params = {
        "surface": "dry_beach_sand",
        "surface_extent": "broad",
        "skin_tilt_deg": "60",
        "skin_azimuth_deg": "180",
    }
    refreshed = client.post("/api/refresh", params=surface_params)
    assert refreshed.status_code == 200, refreshed.text
    context_keys = {"surface", "surface_extent", "skin_tilt_deg", "skin_azimuth_deg"}
    assert calls and not context_keys & calls[0].keys()

    after = client.get("/api/data")
    assert after.status_code == 200
    assert _rows(_payload(before), "daily") == _rows(_payload(after), "daily")

    baseline = client.get("/api/calendar.ics")
    surfaced = client.get("/api/calendar.ics", params=surface_params)
    assert baseline.status_code == surfaced.status_code == 200
    assert _stable_calendar_lines(baseline.text) == _stable_calendar_lines(surfaced.text)


def test_min_temp_is_bounded_to_the_advertised_range(tmp_path: Path) -> None:
    """F-19: tilt and azimuth were range-checked while min_temp accepted -100
    and 120. The page's own input advertises 32-80, so the API enforces the same
    window instead of leaving one control inconsistent with its siblings."""
    client = _client(_api_fixture(tmp_path))

    for bad in ("-100", "120", "10", "95"):
        r = client.get("/api/data", params={"min_temp": bad})
        assert r.status_code == 400, (bad, r.status_code)
        assert "between 32 and 80" in _detail(r), _detail(r)

    # NaN keeps its own message: it is a different failure from out-of-range.
    nan = client.get("/api/data", params={"min_temp": "nan"})
    assert nan.status_code == 400
    assert "finite" in _detail(nan), _detail(nan)

    for ok in ("32", "50", "80"):
        assert client.get("/api/data", params={"min_temp": ok}).status_code == 200, ok


def test_summary_names_the_requested_skin_type(tmp_path: Path) -> None:
    """F-21: summary.skin_type stayed null when skin_type=3 was requested, while
    every row already carried fitzpatrick_type: 3."""
    client = _client(_api_fixture(tmp_path))

    asked = client.get("/api/data", params={"skin_type": "3"})
    assert asked.status_code == 200
    asked_summary = _payload(asked).get("summary")
    assert isinstance(asked_summary, dict)
    assert cast("dict[str, object]", asked_summary).get("skin_type") == 3

    # Not requested stays null: the run's own summary has no request context.
    plain = client.get("/api/data")
    assert plain.status_code == 200
    plain_summary = _payload(plain).get("summary")
    assert isinstance(plain_summary, dict)
    assert cast("dict[str, object]", plain_summary).get("skin_type") is None
