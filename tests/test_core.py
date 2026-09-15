from __future__ import annotations

from datetime import UTC, date, datetime

import numpy as np
import pandas as pd

from sunstack.calibrate import absolute_tan_score, prepare_nasa_training, solar_features
from sunstack.history import _candidate_cams_cycles, normalize_nasa_power
from sunstack.opportunity import _best_contiguous_window
from sunstack.tanscore import (
    _circular_doy_distance,
    add_local_scores,
    build_live_feature_frame,
    predict_uva_uvb,
)


def test_nasa_power_hourly_parser_uses_utc_and_preserves_uv():
    payload = {
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
    assert out["time_utc"].dt.tz is not None
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
            "time_utc": pd.to_datetime(["2026-09-01T16:00Z", "2026-09-01T17:00Z"], utc=True),
            "solar_elevation_deg": [50.0, 50.0],
            "tan_score_absolute_0_100": [20.0, 50.0],
        }
    )
    out = add_local_scores(forecast, ref)
    assert out.loc[1, "local_tan_score_0_100"] > out.loc[0, "local_tan_score_0_100"]
    assert forecast.loc[1, "tan_score_absolute_0_100"] == 50.0

from sunstack.opportunity import (
    apply_outdoor_feasibility,
    attach_fitzpatrick,
    build_30min_forecast,
)


def _opportunity_row(**overrides):
    row = {
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
    overall = out.loc[0, "overall_tan_opportunity_0_100"]
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
    assert out1.loc[0, "overall_tan_opportunity_0_100"] == out6.loc[0, "overall_tan_opportunity_0_100"]
    assert out1.loc[0, "tan_score_absolute_0_100"] == out6.loc[0, "tan_score_absolute_0_100"]
    assert "higher erythema" in out1.loc[0, "personal_uv_risk_context"]


def test_merges_tolerate_mixed_datetime_units():
    # Producers disagree on unit: Open-Meteo strings parse as us, xarray-derived
    # CAMS frames are ns. Neither ruff nor Pyright sees unit mismatches, and
    # merge_asof/merge refuse mixed keys at runtime, so pin the tolerance here.
    stamps = ["2020-01-01 00:00", "2020-01-01 01:00", "2020-01-01 02:00", "2020-01-01 03:00"]
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
            "time": ["2020-01-01T00:00", "2020-01-01T01:00", "2020-01-01T02:00", "2020-01-01T03:00"],
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
                ["2020-01-01 05:00", "2020-01-01 06:00", "2020-01-01 07:00", "2020-01-01 08:00"], utc=True
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
    nasa = pd.DataFrame({
        "time_utc": stamp,
        "ALLSKY_SFC_SW_DWN": [800.0],
        "CLRSKY_SFC_SW_DWN": [1.0],
    })
    train = prepare_nasa_training(nasa, None)
    live = solar_features(pd.Series(stamp))
    assert float(train["clear_ghi"].iloc[0]) > 500.0
    assert float(train["clear_ghi"].iloc[0]) == float(live["clear_ghi"].iloc[0])


def test_best_window_end_is_exclusive_for_hourly_highlight():
    # UI contract: best_window_end is the end of the last 30-min slot, so an
    # hourly row exactly at the end is OUTSIDE the window (its :00 slot was
    # never selected). The UI tints start<=hour<end; keep the data side so.
    dts = pd.date_range("2026-09-15 12:00", periods=6, freq="30min", tz="UTC")
    day = pd.DataFrame({
        "dt": dts,
        "overall_tan_opportunity_0_100": [50.0, 55.0, 60.0, 58.0, 10.0, 5.0],
        "outdoor_blocked": [False] * 6,
    })
    start, end, _ = _best_contiguous_window(day)
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


def test_circular_doy_distance_wraps_year_boundary():
    dist = _circular_doy_distance(pd.Series([1.0, 2.0, 180.0, 364.0, 365.0]), 1)
    assert dist.tolist() == [0.0, 1.0, 179.0, 3.0, 2.0]


def test_cams_cycle_candidates_run_newest_first():
    got = _candidate_cams_cycles(datetime(2026, 9, 14, 3, 20, tzinfo=UTC))
    assert got[0] == (date(2026, 9, 14), "00:00")
    assert got[1] == (date(2026, 9, 13), "12:00")
    assert len(got) == 4
    # A cycle starting exactly now is not published yet.
    got = _candidate_cams_cycles(datetime(2026, 9, 14, 12, 0, tzinfo=UTC))
    assert got[0] == (date(2026, 9, 14), "00:00")


def test_cams_forecast_falls_back_to_older_cycle(monkeypatch, tmp_path):
    from sunstack import history

    calls = []

    def fake_fetch(raw_dir, client, manifest, cycle_date, cycle, force):
        calls.append((cycle_date.isoformat(), cycle))
        if len(calls) == 1:
            manifest.append({"group": "uv", "ok": False, "mode": "group",
                             "cycle": "new", "error": "400"})
            return [], False
        manifest.append({"group": "uv", "ok": True, "mode": "group",
                         "cycle": "old"})
        frame = pd.DataFrame(
            {
                "time_utc": pd.date_range("2026-09-14", periods=3, freq="h", tz="UTC"),
                "source": ["x"] * 3,
                "v": [1.0, 2.0, 3.0],
            }
        )
        return [frame], True

    monkeypatch.setattr(history, "_fetch_cams_cycle", fake_fetch)
    monkeypatch.setattr(history, "cds_credentials_present", lambda: True)
    monkeypatch.setattr(history, "_cds_client", lambda: object())
    out = history.fetch_cams_forecast(tmp_path)
    assert len(out) == 3
    assert len(calls) == 2
    assert out["cams_cycle"].iloc[0] == f"{calls[1][0]}T{calls[1][1]}Z"


def test_predicted_uv_is_zero_below_horizon(tmp_path):
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


def test_cams_retrieve_abandons_stalled_request(tmp_path, monkeypatch):
    from sunstack import history

    monkeypatch.setattr(history.time, "sleep", lambda s: None)

    class Stuck:
        def __init__(self):
            self.reply = {"state": "queued", "request_id": "r1"}
        def update(self):
            pass
        def download(self, target):
            raise AssertionError("must not download a stalled job")

    class Client:
        def retrieve(self, dataset, request):
            return Stuck()

    target = tmp_path / "out.zip"
    try:
        history._retrieve_cams(Client(), "ds", {"data_format": "netcdf_zip"}, target, timeout_s=0)
    except TimeoutError as exc:
        assert "r1" in str(exc)
    else:
        raise AssertionError("stalled request must raise TimeoutError")


def test_cams_retrieve_polls_to_completion(tmp_path, monkeypatch):
    from sunstack import history

    monkeypatch.setattr(history.time, "sleep", lambda s: None)
    seen = []

    class Flowing:
        def __init__(self):
            self.reply = {"state": "accepted", "request_id": "r2"}
            self.states = iter(["queued", "running", "completed"])
        def update(self):
            self.reply = {"state": next(self.states), "request_id": "r2"}
        def download(self, target):
            seen.append(target)
            Path(target).write_bytes(b"ok")

    from pathlib import Path

    class Client:
        def retrieve(self, dataset, request):
            return Flowing()

    target = tmp_path / "out.zip"
    history._retrieve_cams(Client(), "ds", {"data_format": "netcdf_zip"}, target, timeout_s=60)
    assert Path(seen[0]).read_bytes() == b"ok"


def test_cams_retrieve_falls_back_on_format_rejection(tmp_path, monkeypatch):
    from sunstack import history

    monkeypatch.setattr(history.time, "sleep", lambda s: None)
    calls = []

    class Done:
        def __init__(self):
            self.reply = {"state": "completed", "request_id": "r3"}
        def update(self):
            pass
        def download(self, target):
            from pathlib import Path
            Path(target).write_bytes(b"ok")

    class Client:
        def retrieve(self, dataset, request):
            calls.append(dict(request))
            if "data_format" in request:
                raise RuntimeError("400 invalid")
            return Done()

    target = tmp_path / "out.zip"
    history._retrieve_cams(Client(), "ds", {"data_format": "netcdf_zip"}, target, timeout_s=60)
    assert "data_format" in calls[0] and "format" in calls[1]
    assert target.read_bytes() == b"ok"


def test_cams_manifest_records_failed_attempts(tmp_path, monkeypatch):
    import json

    from sunstack import history

    def boom(client, dataset, request, target, timeout_s=None):
        raise RuntimeError("simulated ADS outage")

    monkeypatch.setattr(history, "_retrieve_cams", boom)
    monkeypatch.setattr(history, "cds_credentials_present", lambda: True)
    monkeypatch.setattr(history, "_cds_client", lambda: object())
    out = history.fetch_cams_forecast(tmp_path, force=True)
    assert out.empty
    manifest = json.loads((tmp_path / "raw" / "cams_forecast" / "manifest.json").read_text())
    assert len(manifest["requests"]) > 0
    assert all(not r["ok"] for r in manifest["requests"])


def test_calendar_feed_lists_each_window_once_with_stable_uids():
    from sunstack.ui import build_calendar_ics

    daily = pd.DataFrame([
        {
            "date": "2026-09-15", "best_window_start": "2026-09-15T12:30:00",
            "best_window_end": "2026-09-15T16:30:00", "day_overall_peak_0_100": 51.0,
            "peak_uv_index": 5.4, "peak_predicted_uva_wm2": 42.9,
            "peak_temperature_f": 85.1, "day_confidence_at_peak_0_100": 40.0,
            "day_status": "FAIR",
        },
        {"date": "2026-09-16", "best_window_start": None, "best_window_end": None},
    ])
    first = build_calendar_ics(daily, "20260915_004803")
    second = build_calendar_ics(daily, "20260915_010000")
    assert first.count("BEGIN:VEVENT") == 1
    assert "UID:sunstack-best-2026-09-15@sunstack" in first
    # 12:30 PM Indiana daylight time is 16:30 UTC.
    assert "DTSTART:20260915T163000Z" in first
    assert "DTEND:20260915T203000Z" in first
    assert "SEQUENCE:20260915004803" in first
    # Same date UID across reruns: subscribed calendars update in place.
    assert "UID:sunstack-best-2026-09-15@sunstack" in second
    assert "SEQUENCE:20260915010000" in second
    # Hourly-fed descriptions carry per-day UV peaks, not just the score.
    hourly = pd.DataFrame({
        "time": ["2026-09-15T12:00", "2026-09-15T13:00", "2026-09-16T12:00"],
        "uv_index": [5.0, 5.4, 1.0],
        "predicted_uva_wm2": [40.0, 42.9, 10.0],
        "predicted_uvb_wm2": [0.9, 1.0, 0.2],
    })
    rich = build_calendar_ics(daily, "20260915_004803", hourly)
    flat = rich.replace("\r\n ", "")
    assert "Peak UV 5.4 at 1:00 PM" in flat
    assert "UVA 42.9 W/m2" in flat
    assert "UVB 1 W/m2" in flat


def test_30min_handles_fall_back_duplicate_hours():
    # DST fall-back repeats 1:00-2:00am in wall time. If the API returns both
    # instances with identical naive labels, the 30-min resample must not
    # crash the run (night rows never affect windows either way).
    hourly = pd.DataFrame({
        "time": [
            "2026-11-01T00:00", "2026-11-01T01:00", "2026-11-01T01:30",
            "2026-11-01T01:00", "2026-11-01T01:30", "2026-11-01T02:00",
            "2026-11-01T12:00",
        ],
        "temperature_2m": [50.0, 49.0, 49.0, 48.0, 48.0, 48.0, 60.0],
        "overall_tan_opportunity_0_100": [0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 40.0],
        "tan_score_absolute_0_100": [0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 35.0],
    })
    from sunstack.opportunity import build_30min_forecast

    out = build_30min_forecast(hourly, None)
    assert len(out) > 0
    assert bool((out["time"] == "2026-11-01T12:00").any())


def test_export_static_site_publishes_data_and_calendar(tmp_path):
    from sunstack.output import export_static_site

    latest = tmp_path / "latest"
    (latest / "tables").mkdir(parents=True)
    hourly = pd.DataFrame({
        "time": ["2026-09-15T12:00", "2026-09-15T13:00", "2026-09-15T20:00"],
        "temperature_2m": [80.0, 82.0, 70.0],
        "overall_tan_opportunity_0_100": [50.0, 60.0, 5.0],
        "tan_score_absolute_0_100": [40.0, 45.0, 4.0],
        "local_tan_score_0_100": [80.0, 85.0, 10.0],
        "atmospheric_quality_percentile_0_100": [60.0, 65.0, 20.0],
        "tan_forecast_confidence_0_100": [50.0, 55.0, 30.0],
    })
    half = pd.DataFrame({
        "dt": pd.to_datetime(["2026-09-15 12:00", "2026-09-15 12:30", "2026-09-15 13:00", "2026-09-15 13:30"]),
        "time": ["2026-09-15T12:00", "2026-09-15T12:30", "2026-09-15T13:00", "2026-09-15T13:30"],
        "temperature_2m": [80.0, 81.0, 82.0, 81.0],
        "overall_tan_opportunity_0_100": [50.0, 55.0, 60.0, 58.0],
        "tan_score_absolute_0_100": [40.0, 42.0, 45.0, 44.0],
        "local_tan_score_0_100": [80.0, 82.0, 85.0, 84.0],
        "atmospheric_quality_percentile_0_100": [60.0, 62.0, 65.0, 64.0],
        "tan_forecast_confidence_0_100": [50.0, 52.0, 55.0, 54.0],
    })
    hourly.to_parquet(latest / "tables" / "tan_forecast_hourly.parquet", index=False)
    half.to_parquet(latest / "tables" / "tan_forecast_30min.parquet", index=False)
    (latest / "summary.json").write_text('{"run": "test123", "created_at": "2026-09-15T00:00:00-04:00"}')
    import json as _json

    info = export_static_site(tmp_path, tmp_path / "site")
    assert info["days"] == 1 and info["events"] == 1
    payload = _json.loads((tmp_path / "site" / "data.json").read_text())
    assert set(payload) == {"run", "daily", "hourly", "half_hour", "summary"}
    assert len(payload["daily"]) == 1
    html = (tmp_path / "site" / "index.html").read_text()
    assert "./data.json" in html and "/api/data" not in html
    ics = (tmp_path / "site" / "calendar.ics").read_text()
    assert ics.count("BEGIN:VEVENT") == 1
    assert "UID:sunstack-best-2026-09-15@sunstack" in ics


def test_30min_kills_pre_sunrise_ghost_light():
    # Linear blends invent sunlight before sunrise (Sep 15 sunup ~7:14am
    # local). The geometry-aware interpolator must report exactly zero.
    from sunstack.opportunity import build_30min_forecast

    hourly = pd.DataFrame({
        "time": ["2026-09-15T06:00", "2026-09-15T07:00", "2026-09-15T08:00"],
        "temperature_2m": [60.0, 61.0, 63.0],
        "shortwave_radiation_instant": [0.0, 250.0, 500.0],
        "predicted_uva_wm2": [0.0, 25.0, 45.0],
        "uv_index": [0.0, 2.0, 4.0],
        "overall_tan_opportunity_0_100": [0.0, 20.0, 35.0],
        "tan_score_absolute_0_100": [0.0, 18.0, 32.0],
    })
    out = build_30min_forecast(hourly, None)
    slot = out.loc[out["time"] == "2026-09-15T06:30"].iloc[0]
    assert float(slot["shortwave_radiation_instant"]) == 0.0
    assert float(slot["predicted_uva_wm2"]) == 0.0


def test_30min_uses_clear_sky_index_not_linear_blend(monkeypatch):
    # With TOA mocked nonlinear in wall time, constant-kt input must come
    # back exact; a linear GHI blend would give 250.0 instead of 312.5.
    import numpy as np

    import sunstack.opportunity as opp

    def fake_toa(times_utc):
        minute = pd.to_datetime(times_utc).dt.minute.to_numpy()
        return np.where(minute == 0, 100.0, 250.0)

    monkeypatch.setattr(opp, "_toa_wm2", fake_toa)
    hourly = pd.DataFrame({
        "time": ["2026-09-15T06:00", "2026-09-15T07:00", "2026-09-15T08:00"],
        "temperature_2m": [70.0, 72.0, 74.0],
        "shortwave_radiation_instant": [100.0, 400.0, 700.0],
        "predicted_uva_wm2": [10.0, 40.0, 70.0],
        "uv_index": [1.0, 3.0, 5.0],
        "overall_tan_opportunity_0_100": [10.0, 30.0, 50.0],
        "tan_score_absolute_0_100": [9.0, 28.0, 48.0],
    })
    out = opp.build_30min_forecast(hourly, None)
    slot = out.loc[out["time"] == "2026-09-15T06:30"].iloc[0]
    assert float(slot["shortwave_radiation_instant"]) == 312.5
    assert float(slot["predicted_uva_wm2"]) == 31.25


def test_30min_survives_non_numeric_ghi_dtype():
    # Some feeds deliver radiation as strings/None (object dtype), which the
    # numeric-only resample silently drops. The kt block must coerce, never
    # assume the interpolated frame carries the column (CI KeyError).
    from sunstack.opportunity import build_30min_forecast

    hourly = pd.DataFrame({
        "time": ["2026-09-15T12:00", "2026-09-15T13:00", "2026-09-15T14:00"],
        "temperature_2m": [80.0, 82.0, 83.0],
        "shortwave_radiation_instant": ["400.0", None, "600.0"],
        "predicted_uva_wm2": [30.0, 40.0, 42.0],
        "uv_index": [4.0, 5.0, 5.2],
        "overall_tan_opportunity_0_100": [30.0, 40.0, 42.0],
        "tan_score_absolute_0_100": [28.0, 38.0, 40.0],
    })
    assert not pd.api.types.is_numeric_dtype(hourly["shortwave_radiation_instant"])
    out = build_30min_forecast(hourly, None)
    slot = out.loc[out["time"] == "2026-09-15T12:30"].iloc[0]
    assert float(slot["shortwave_radiation_instant"]) > 0.0


def test_30min_keeps_string_dtype_uv_index():
    # uv_index can arrive as strings (dropped by the numeric-only resample,
    # leaving the UI on a different product via fallback). It must survive
    # with the interpolated value.
    from sunstack.opportunity import build_30min_forecast

    hourly = pd.DataFrame({
        "time": ["2026-09-15T12:00", "2026-09-15T13:00", "2026-09-15T14:00"],
        "temperature_2m": [80.0, 82.0, 83.0],
        "shortwave_radiation_instant": [400.0, 500.0, 600.0],
        "uv_index": ["4.0", "5.0", "5.2"],
        "predicted_uva_wm2": [30.0, 40.0, 42.0],
        "overall_tan_opportunity_0_100": [30.0, 40.0, 42.0],
        "tan_score_absolute_0_100": [28.0, 38.0, 40.0],
    })
    out = build_30min_forecast(hourly, None)
    slot = out.loc[out["time"] == "2026-09-15T12:30"].iloc[0]
    # Linear would give 4.5; the bounded geometry correction stays near it.
    assert 3.0 < float(slot["uv_index"]) < 6.0
