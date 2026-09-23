"""Regression tests for CAMS netCDF time decoding.

The decoded time_utc grid anchors every CAMS-gated product (spectral AOD
merge, UVBED closure, UVI-agreement confidence). A 2026-09 validation noted
a ~4-5 h CAMS-vs-Open-Meteo diurnal phase offset under investigation; these
tests lock each _dataset_time_column branch so the decoder itself cannot
silently shift, collapse, or double-count the time axis.
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
import pytest

xr = pytest.importorskip("xarray")

from sunstack import history


def _write_ds(path: Path, coords: dict, var_name: str = "uvbed") -> Path:
    lat = np.array([41.5, 42.0])
    lon = np.array([-86.5, -86.0])
    dims = tuple(coords) + ("latitude", "longitude")
    shape = tuple(len(np.atleast_1d(v)) for v in coords.values()) + (len(lat), len(lon))
    rng = np.random.default_rng(7)
    ds = xr.Dataset(
        {var_name: (dims, rng.random(shape),
                    {"long_name": "UV biologically effective dose"})},
        coords={**coords, "latitude": lat, "longitude": lon},
    )
    ds.to_netcdf(path)
    return path


def test_valid_time_passes_through(tmp_path):
    times = pd.date_range("2026-09-22 12:00", periods=5, freq="h", tz="UTC")
    p = _write_ds(tmp_path / "a.nc", {"valid_time": times.tz_convert(None).to_numpy()})
    out = history.normalize_cams_netcdf_zip(p, tmp_path / "x1", "test")
    assert len(out) == 5
    assert out["time_utc"].tolist() == list(times)


def test_reference_plus_timedelta_step(tmp_path):
    ref = np.array(["2026-09-22T12:00"], dtype="datetime64[ns]")
    steps = np.array([0, 6, 12], dtype="timedelta64[h]")
    p = _write_ds(tmp_path / "b.nc",
                  {"forecast_reference_time": ref, "step": steps})
    out = history.normalize_cams_netcdf_zip(p, tmp_path / "x2", "test")
    assert out["time_utc"].tolist() == list(
        pd.to_datetime(["2026-09-22 12:00", "2026-09-22 18:00",
                        "2026-09-23 00:00"], utc=True))


def test_reference_plus_numeric_hour_step(tmp_path):
    # Bare numeric steps are CAMS leadtime_hours, never nanoseconds: the grid
    # must span hours, not collapse onto the reference time.
    ref = np.array(["2026-09-22T12:00"], dtype="datetime64[ns]")
    p = _write_ds(tmp_path / "c.nc",
                  {"forecast_reference_time": ref, "step": np.array([0, 1, 2])})
    out = history.normalize_cams_netcdf_zip(p, tmp_path / "x3", "test")
    assert out["time_utc"].tolist() == list(
        pd.to_datetime(["2026-09-22 12:00", "2026-09-22 13:00",
                        "2026-09-22 14:00"], utc=True))


def test_time_plus_timedelta_step(tmp_path):
    ref = np.array(["2026-09-22T12:00"], dtype="datetime64[ns]")
    steps = np.array([0, 3], dtype="timedelta64[h]")
    p = _write_ds(tmp_path / "d.nc", {"time": ref, "step": steps})
    out = history.normalize_cams_netcdf_zip(p, tmp_path / "x4", "test")
    assert out["time_utc"].tolist() == list(
        pd.to_datetime(["2026-09-22 12:00", "2026-09-22 15:00"], utc=True))


def test_time_only_falls_back_to_time(tmp_path):
    times = pd.date_range("2026-09-22 12:00", periods=3, freq="h")
    p = _write_ds(tmp_path / "e.nc", {"time": times.to_numpy()})
    out = history.normalize_cams_netcdf_zip(p, tmp_path / "x5", "test")
    assert len(out) == 3


def test_no_time_coordinate_returns_empty_not_crash(tmp_path, capsys):
    ds = xr.Dataset(
        {"uvbed": (("latitude", "longitude"), np.ones((2, 2)))},
        coords={"latitude": [41.5, 42.0], "longitude": [-86.5, -86.0]},
    )
    p = tmp_path / "f.nc"
    ds.to_netcdf(p)
    out = history.normalize_cams_netcdf_zip(p, tmp_path / "x6", "test")
    assert out.empty
