from __future__ import annotations

import json
import os
import re
import shutil
import time
import zipfile
from collections.abc import Iterable
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import requests

try:
    from retry_requests import retry
except ImportError:  # Lightweight fallback; uv sync installs retry-requests normally.
    def retry(session, **_kwargs):
        return session
import requests_cache

from . import config

NASA_POWER_URL = "https://power.larc.nasa.gov/api/temporal/hourly/point"
HISTORICAL_FORECAST_URL = "https://historical-forecast-api.open-meteo.com/v1/forecast"
PREVIOUS_RUNS_URL = "https://previous-runs-api.open-meteo.com/v1/forecast"
CAMS_FORECAST_DATASET = "cams-global-atmospheric-composition-forecasts"
CAMS_EAC4_DATASET = "cams-global-reanalysis-eac4"


def _session(cache_dir: Path, expire_after: int = 86400 * 30, fresh: bool = False):
    if fresh:
        return retry(requests.Session(), retries=5, backoff_factor=0.6)
    cache_dir.mkdir(parents=True, exist_ok=True)
    cached = requests_cache.CachedSession(
        str(cache_dir / "history_http"),
        expire_after=expire_after,
        stale_if_error=True,
        allowable_methods=("GET",),
    )
    return retry(cached, retries=5, backoff_factor=0.6)


def _write_table(df: pd.DataFrame, path_no_suffix: Path) -> None:
    if df.empty:
        return
    path_no_suffix.parent.mkdir(parents=True, exist_ok=True)
    df.to_parquet(path_no_suffix.with_suffix(".parquet"), index=False)
    df.to_csv(path_no_suffix.with_suffix(".csv"), index=False)


def _chunks(start: date, end: date, days: int) -> Iterable[tuple[date, date]]:
    cur = start
    while cur <= end:
        stop = min(end, cur + timedelta(days=days - 1))
        yield cur, stop
        cur = stop + timedelta(days=1)


def _json_get(session, url: str, params: dict[str, Any], timeout: int = 180) -> dict[str, Any]:
    r = session.get(url, params=params, timeout=timeout)
    r.raise_for_status()
    payload = r.json()
    if isinstance(payload, dict) and payload.get("error"):
        raise RuntimeError(str(payload.get("reason", payload)))
    return payload


# ---------------------------------------------------------------------------
# NASA POWER — historical UVA/UVB calibration target
# ---------------------------------------------------------------------------


def normalize_nasa_power(payload: dict[str, Any]) -> pd.DataFrame:
    params = payload.get("properties", {}).get("parameter", {})
    if not isinstance(params, dict) or not params:
        return pd.DataFrame()
    all_times: set[str] = set()
    for values in params.values():
        if isinstance(values, dict):
            all_times.update(values)
    if not all_times:
        return pd.DataFrame()
    ordered = sorted(all_times)
    out = pd.DataFrame({"time_utc": pd.to_datetime(ordered, format="%Y%m%d%H", utc=True)})
    for name, values in params.items():
        if not isinstance(values, dict):
            continue
        series = pd.Series([values.get(k, np.nan) for k in ordered], dtype="float64")
        series = series.replace(-999.0, np.nan).replace(-999, np.nan)
        out[name] = series
    return out


def fetch_nasa_power_history(
    out_dir: Path,
    cache_dir: Path,
    start: date | None = None,
    end: date | None = None,
    force: bool = False,
) -> pd.DataFrame:
    start = start or config.NASA_POWER_START
    end = min(end or config.NASA_POWER_END, date.today())
    raw_dir = out_dir / "raw" / "nasa_power"
    table_dir = out_dir / "tables" / "nasa_power"
    raw_dir.mkdir(parents=True, exist_ok=True)
    table_dir.mkdir(parents=True, exist_ok=True)
    session = _session(cache_dir, fresh=force)
    frames: list[pd.DataFrame] = []

    for year in range(start.year, end.year + 1):
        ys = max(start, date(year, 1, 1))
        ye = min(end, date(year, 12, 31))
        parquet = table_dir / f"power_{year}.parquet"
        raw = raw_dir / f"power_{year}.json"
        if parquet.exists() and not force:
            frames.append(pd.read_parquet(parquet))
            continue
        params = {
            "parameters": ",".join(config.NASA_POWER_PARAMETERS),
            "community": "RE",
            "longitude": config.LONGITUDE,
            "latitude": config.LATITUDE,
            "start": ys.strftime("%Y%m%d"),
            "end": ye.strftime("%Y%m%d"),
            "format": "JSON",
            "time-standard": "UTC",
        }
        try:
            payload = _json_get(session, NASA_POWER_URL, params, timeout=240)
        except requests.RequestException as exc:
            print(f"WARN NASA POWER {year}: {exc}")
            continue
        raw.write_text(json.dumps(payload), encoding="utf-8")
        frame = normalize_nasa_power(payload)
        if frame.empty:
            print(f"WARN NASA POWER {year}: empty response")
            continue
        frame["source"] = "nasa_power_ceres_merra2"
        frame["latitude_request"] = config.LATITUDE
        frame["longitude_request"] = config.LONGITUDE
        frame.to_parquet(parquet, index=False)
        frame.to_csv(table_dir / f"power_{year}.csv", index=False)
        frames.append(frame)

    result = pd.concat(frames, ignore_index=True).sort_values("time_utc") if frames else pd.DataFrame()
    if not result.empty:
        _write_table(result, out_dir / "tables" / "nasa_power_hourly")
    return result


# ---------------------------------------------------------------------------
# Open-Meteo historical forecast + previous runs
# ---------------------------------------------------------------------------


def _openmeteo_hourly_frame(payload: dict[str, Any], source: str, model: str) -> pd.DataFrame:
    block = payload.get("hourly")
    if not isinstance(block, dict) or "time" not in block:
        return pd.DataFrame()
    n = len(block["time"])
    data: dict[str, Any] = {"time": block["time"]}
    for k, v in block.items():
        if k != "time" and isinstance(v, list) and len(v) == n:
            data[k] = v
    df = pd.DataFrame(data)
    df["time_utc"] = pd.to_datetime(df.pop("time"), utc=True)
    df.insert(1, "source", source)
    df.insert(2, "model", model)
    df["latitude_grid"] = payload.get("latitude")
    df["longitude_grid"] = payload.get("longitude")
    df["elevation_m"] = payload.get("elevation")
    return df


def fetch_openmeteo_historical_forecast(
    out_dir: Path,
    cache_dir: Path,
    start: date | None = None,
    end: date | None = None,
    force: bool = False,
) -> pd.DataFrame:
    start = start or config.OPENMETEO_HISTORY_START
    end = end or config.OPENMETEO_HISTORY_END
    raw_dir = out_dir / "raw" / "openmeteo_historical_forecast"
    table_dir = out_dir / "tables" / "openmeteo_historical_forecast"
    raw_dir.mkdir(parents=True, exist_ok=True)
    table_dir.mkdir(parents=True, exist_ok=True)
    session = _session(cache_dir, fresh=force)
    frames: list[pd.DataFrame] = []

    # Three-month chunks are small enough to be resilient and large enough not to
    # hammer the public archive endpoint.
    for cs, ce in _chunks(start, end, 92):
        key = f"{cs:%Y%m%d}_{ce:%Y%m%d}"
        parquet = table_dir / f"historical_{key}.parquet"
        raw = raw_dir / f"historical_{key}.json"
        if parquet.exists() and not force:
            frames.append(pd.read_parquet(parquet))
            continue
        params = {
            "latitude": config.LATITUDE,
            "longitude": config.LONGITUDE,
            "timezone": "UTC",
            "start_date": cs.isoformat(),
            "end_date": ce.isoformat(),
            "models": "best_match",
            "temperature_unit": "celsius",
            "wind_speed_unit": "ms",
            "precipitation_unit": "mm",
            "hourly": ",".join(config.OPENMETEO_HISTORY_VARIABLES),
        }
        try:
            payload = _json_get(session, HISTORICAL_FORECAST_URL, params, timeout=240)
        except requests.RequestException as exc:
            print(f"WARN Open-Meteo historical {key}: {exc}")
            continue
        raw.write_text(json.dumps(payload), encoding="utf-8")
        frame = _openmeteo_hourly_frame(payload, "openmeteo_historical_forecast", "best_match")
        if frame.empty:
            continue
        frame.to_parquet(parquet, index=False)
        frames.append(frame)

    result = pd.concat(frames, ignore_index=True).drop_duplicates("time_utc").sort_values("time_utc") if frames else pd.DataFrame()
    if not result.empty:
        _write_table(result, out_dir / "tables" / "openmeteo_historical_hourly")
    return result


def _previous_run_variables() -> list[str]:
    variables: list[str] = []
    for base in config.PREVIOUS_RUN_BASE_VARIABLES:
        variables.append(base)
        for lead in config.PREVIOUS_RUN_LEADS[1:]:
            variables.append(f"{base}_previous_day{lead}")
    return variables


def fetch_openmeteo_previous_runs(
    out_dir: Path,
    cache_dir: Path,
    force: bool = False,
) -> pd.DataFrame:
    raw_dir = out_dir / "raw" / "openmeteo_previous_runs"
    table_dir = out_dir / "tables" / "openmeteo_previous_runs"
    raw_dir.mkdir(parents=True, exist_ok=True)
    table_dir.mkdir(parents=True, exist_ok=True)
    session = _session(cache_dir, fresh=force)
    frames: list[pd.DataFrame] = []

    variables = _previous_run_variables()
    fallback_days = []
    for d in [config.OPENMETEO_PREVIOUS_RUNS_DAYS, 730, 365, 92]:
        if d not in fallback_days:
            fallback_days.append(d)

    for model in config.PREVIOUS_RUN_MODELS:
        parquet = table_dir / f"previous_runs__{model}.parquet"
        if parquet.exists() and not force:
            frames.append(pd.read_parquet(parquet))
            continue
        payload = None
        used_days = None
        last_error: Exception | None = None
        for days in fallback_days:
            params = {
                "latitude": config.LATITUDE,
                "longitude": config.LONGITUDE,
                "timezone": "UTC",
                "past_days": days,
                "forecast_days": 1,
                "models": model,
                "temperature_unit": "celsius",
                "wind_speed_unit": "ms",
                "precipitation_unit": "mm",
                "hourly": ",".join(variables),
            }
            try:
                payload = _json_get(session, PREVIOUS_RUNS_URL, params, timeout=300)
                used_days = days
                break
            except requests.RequestException as exc:
                last_error = exc
        if payload is None:
            print(f"WARN Previous Runs {model}: {last_error}")
            continue
        (raw_dir / f"previous_runs__{model}.json").write_text(json.dumps(payload), encoding="utf-8")
        frame = _openmeteo_hourly_frame(payload, "openmeteo_previous_runs", model)
        if frame.empty:
            continue
        frame["requested_past_days"] = used_days
        frame.to_parquet(parquet, index=False)
        frames.append(frame)

    result = pd.concat(frames, ignore_index=True, sort=False) if frames else pd.DataFrame()
    if not result.empty:
        _write_table(result, out_dir / "tables" / "openmeteo_previous_runs_all")
    return result


# ---------------------------------------------------------------------------
# EPA/NWS operational UVI (US ZIP sites only; opportunistic third UVI source)
# ---------------------------------------------------------------------------

EPA_UV_HOURLY_URL = "https://enviro.epa.gov/enviro/efservice/getEnvirofactsUVHOURLY/ZIP/{zip}/JSON"
EPA_UV_DAILY_URL = "https://enviro.epa.gov/enviro/efservice/getEnvirofactsUVDAILY/ZIP/{zip}/JSON"


def normalize_epa_hourly(payload: object) -> pd.DataFrame:
    """EPA hourly UVI rows to a site-local hourly frame (time, uvi_epa).

    DATE_TIME looks like "Sep/23/2026 06 AM" in the ZIP's local time, which
    matches the site-local wall clock the forecast tables use. Unparseable
    rows are dropped; an empty frame means degrade, never fabricate.
    """
    if not isinstance(payload, list) or not payload:
        return pd.DataFrame()
    recs = []
    for row in payload:
        if not isinstance(row, dict):
            continue
        try:
            # Wall-clock parse is intentional: EPA DATE_TIME is already the
            # ZIP's local time, matching the site-local wall clock join key.
            dt = datetime.strptime(  # noqa: DTZ007
                str(row.get("DATE_TIME", "")).strip(), "%b/%d/%Y %I %p")
            val = float(row.get("UV_VALUE"))  # type: ignore[arg-type]
        except (ValueError, TypeError):
            continue
        if not np.isfinite(val):
            continue
        recs.append({"time": dt.strftime("%Y-%m-%dT%H:%M"), "uvi_epa": val})
    if not recs:
        return pd.DataFrame()
    out = pd.DataFrame(recs).sort_values("time").drop_duplicates("time")
    out["source"] = "epa_nws_operational_hourly"
    return out


def normalize_epa_daily(payload: object) -> pd.DataFrame:
    """EPA daily UVI peaks to (date, uvi_epa_daily_peak). Display reference only."""
    if not isinstance(payload, list) or not payload:
        return pd.DataFrame()
    recs = []
    for row in payload:
        if not isinstance(row, dict):
            continue
        try:
            # Date-only parse is intentional: EPA DATE is a calendar-day label.
            day = datetime.strptime(  # noqa: DTZ007
                str(row.get("DATE", "")).strip(), "%b/%d/%Y").date().isoformat()
            val = float(row.get("UV_INDEX"))  # type: ignore[arg-type]
        except (ValueError, TypeError):
            continue
        if not np.isfinite(val):
            continue
        recs.append({"date": day, "uvi_epa_daily_peak": val})
    if not recs:
        return pd.DataFrame()
    out = pd.DataFrame(recs).sort_values("date").drop_duplicates("date")
    out["source"] = "epa_nws_operational_daily"
    return out


def fetch_epa_uv_forecast(out_dir: Path, zip_code: str, timeout: int = 30) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Live EPA/NWS operational UVI for a US ZIP. Degrades to empty frames.

    Writes raw JSON + tables for provenance when non-empty. Never raises on
    upstream failure: EPA is an opportunistic third UVI source, not a gate.
    """
    hourly = pd.DataFrame()
    daily = pd.DataFrame()
    raw_dir = out_dir / "raw" / "epa_uv"
    table_dir = out_dir / "tables"
    try:
        resp = requests.get(EPA_UV_HOURLY_URL.format(zip=zip_code), timeout=timeout)
        resp.raise_for_status()
        raw_dir.mkdir(parents=True, exist_ok=True)
        raw_dir.joinpath(f"epa_hourly_{zip_code}.json").write_text(resp.text, encoding="utf-8")
        hourly = normalize_epa_hourly(resp.json())
    except (requests.RequestException, ValueError) as exc:
        print(f"WARN EPA hourly UVI {zip_code}: {exc}")
    try:
        resp = requests.get(EPA_UV_DAILY_URL.format(zip=zip_code), timeout=timeout)
        resp.raise_for_status()
        raw_dir.mkdir(parents=True, exist_ok=True)
        raw_dir.joinpath(f"epa_daily_{zip_code}.json").write_text(resp.text, encoding="utf-8")
        daily = normalize_epa_daily(resp.json())
    except (requests.RequestException, ValueError) as exc:
        print(f"WARN EPA daily UVI {zip_code}: {exc}")
    if not hourly.empty:
        _write_table(hourly, table_dir / "epa_uv_hourly")
    if not daily.empty:
        _write_table(daily, table_dir / "epa_uv_daily")
    return hourly, daily

# ---------------------------------------------------------------------------
# Direct CAMS via Copernicus ADS
# ---------------------------------------------------------------------------


def cds_credentials_present() -> bool:
    if os.getenv("CDSAPI_KEY"):
        return True
    home = Path.home()
    return (home / ".cdsapirc").exists() or (home / ".cdsapi").exists()

def _cds_client():
    import cdsapi

    url = os.getenv("CDSAPI_URL")
    key = os.getenv("CDSAPI_KEY")
    kwargs: dict[str, Any] = {"quiet": False, "wait_until_complete": False}
    if url and key:
        return cdsapi.Client(url=url, key=key, **kwargs)
    return cdsapi.Client(**kwargs)


def _sanitize(text: str) -> str:
    s = text.strip().lower()
    s = s.replace("µ", "u").replace("μ", "u")
    s = re.sub(r"[^a-z0-9]+", "_", s).strip("_")
    return s


def _extract_nc_zip(path: Path, extract_dir: Path) -> list[Path]:
    if extract_dir.exists():
        shutil.rmtree(extract_dir)
    extract_dir.mkdir(parents=True, exist_ok=True)
    if zipfile.is_zipfile(path):
        with zipfile.ZipFile(path) as z:
            z.extractall(extract_dir)
        return sorted(extract_dir.rglob("*.nc"))
    if path.suffix == ".nc":
        return [path]
    return []


def _point_from_dataset(ds, lat: float, lon: float):
    # Coordinate names are stable for CAMS netCDF, but keep this tolerant.
    lat_name = next((x for x in ("latitude", "lat") if x in ds.coords), None)
    lon_name = next((x for x in ("longitude", "lon") if x in ds.coords), None)
    if lat_name is not None:
        ds = ds.sel({lat_name: lat}, method="nearest")
    if lon_name is not None:
        lvals = ds[lon_name].values
        lon_sel = lon
        try:
            if np.nanmin(lvals) >= 0 and lon < 0:
                lon_sel = lon % 360
        except (TypeError, ValueError) as exc:
            print(f"WARN CAMS longitude axis non-numeric; keeping requested lon ({exc})")
        ds = ds.sel({lon_name: lon_sel}, method="nearest")
    return ds


def _dataset_time_column(df: pd.DataFrame) -> pd.Series:
    for name in ("valid_time", "validity_time"):
        if name in df:
            return pd.to_datetime(df[name], utc=True)
    if "forecast_reference_time" in df and "step" in df:
        return pd.to_datetime(df["forecast_reference_time"], utc=True) + _cams_step_delta(df)
    if "time" in df and "step" in df:
        base = pd.to_datetime(df["time"], utc=True)
        try:
            return base + _cams_step_delta(df)
        except (TypeError, ValueError):
            return base
    if "time" in df:
        return pd.to_datetime(df["time"], utc=True)
    raise ValueError("No recognizable time coordinate in CAMS netCDF")


def _cams_step_delta(df: pd.DataFrame) -> pd.Series:
    """Forecast-step column as a timedelta.

    xarray usually decodes CF steps to timedelta64 already. A bare numeric
    step is interpreted as hours (the CAMS request uses leadtime_hour), never
    as nanoseconds: ``pd.to_timedelta`` on integers defaults to ns, which
    would collapse the whole forecast onto the reference time.
    """
    step = df.loc[:, "step"]
    if pd.api.types.is_timedelta64_dtype(step):
        return pd.to_timedelta(step)
    numeric = pd.to_numeric(step, errors="coerce")
    if numeric.notna().any():
        return pd.to_timedelta(numeric.fillna(0), unit="h")
    return pd.to_timedelta(step)


def normalize_cams_netcdf_zip(path: Path, extract_dir: Path, source: str) -> pd.DataFrame:
    import xarray as xr

    frames: list[pd.DataFrame] = []
    for nc in _extract_nc_zip(path, extract_dir):
        try:
            ds = xr.open_dataset(nc)
            ds = _point_from_dataset(ds, config.LATITUDE, config.LONGITUDE)
            raw = ds.to_dataframe().reset_index()
            raw["time_utc"] = _dataset_time_column(raw)
            keep: dict[str, Any] = {"time_utc": raw["time_utc"]}
            for var in ds.data_vars:
                if var not in raw:
                    continue
                attrs = ds[var].attrs
                long_name = attrs.get("long_name") or attrs.get("standard_name") or var
                name = "cams_" + _sanitize(str(long_name))
                # If duplicate long names occur, retain the original short name too.
                if name in keep:
                    name = "cams_" + _sanitize(var)
                keep[name] = pd.to_numeric(raw[var], errors="coerce")
            frame = pd.DataFrame(keep)
            frame["source"] = source
            frames.append(frame)
            ds.close()
        except Exception as exc:
            print(f"WARN CAMS netCDF parse {nc.name}: {exc}")
    if not frames:
        return pd.DataFrame()
    merged = frames[0]
    for frame in frames[1:]:
        merged = merged.merge(frame.drop(columns=["source"], errors="ignore"), on="time_utc", how="outer")
    merged["source"] = source
    return merged.sort_values("time_utc").drop_duplicates("time_utc")


def _cams_area(pad: float = 0.45) -> list[float]:
    return [
        config.LATITUDE + pad,
        config.LONGITUDE - pad,
        config.LATITUDE - pad,
        config.LONGITUDE + pad,
    ]

def _retrieve_cams(
    client,
    dataset: str,
    request: dict[str, Any],
    target: Path,
    timeout_s: int | None = None,
) -> None:
    """Submit a CAMS request and poll it with a hard deadline.

    cdsapi otherwise polls a queued job forever. Waiting is bounded so one
    stalled request can never hang a run; callers treat expiry like any other
    per-unit failure (warn/skip/fall back) instead of hanging silently.
    """
    limit = config.CAMS_REQUEST_TIMEOUT_S if timeout_s is None else timeout_s
    target.parent.mkdir(parents=True, exist_ok=True)
    # New ADS uses data_format. A fallback keeps compatibility with older dataset
    # schema snapshots that still expect format.
    req = dict(request)
    try:
        result = client.retrieve(dataset, req)
    except Exception:
        if "data_format" not in req:
            raise
        req["format"] = req.pop("data_format")
        result = client.retrieve(dataset, req)
    rid = result.reply.get("request_id", "unknown")
    print(f"Request ID is {rid}")
    start = time.monotonic()
    last_state: str | None = None
    last_beat = start
    while True:
        result.update()
        state = result.reply.get("state")
        if state != last_state:
            print(f"status has been updated to {state}")
            last_state = state
        if state == "completed":
            result.download(str(target))
            return
        if state == "failed":
            err = result.reply.get("error", {})
            raise RuntimeError(f"{err.get('message')}. {err.get('reason')}.")
        elapsed = time.monotonic() - start
        if elapsed > limit:
            raise TimeoutError(
                f"CAMS ADS request {rid} for {dataset} still '{state}' after {int(elapsed)}s."
            )
        if elapsed - last_beat >= 120:
            print(f"CAMS request {rid} still '{state}' after {int(elapsed)}s...")
            last_beat = elapsed
        if state not in ("accepted", "queued", "running"):
            raise RuntimeError(f"CAMS ADS request {rid} in unexpected state '{state}'.")
        time.sleep(10)


def _latest_safe_cams_cycle(now: datetime | None = None) -> tuple[date, str]:
    now = now or datetime.now(UTC)
    # Leave enough time for the operational run to finish and reach ADS.
    if now.hour >= 18:
        return now.date(), "12:00"
    if now.hour >= 6:
        return now.date(), "00:00"
    return (now - timedelta(days=1)).date(), "12:00"


def _candidate_cams_cycles(now: datetime | None = None) -> list[tuple[date, str]]:
    """Newest-first CAMS run cycles that have already started.

    The newest cycle is not always published yet (ADS then rejects the
    request); callers fall back to older cycles, reusing downloaded files.
    """
    now = now or datetime.now(UTC)
    out: list[tuple[date, str]] = []
    for back in range(3):
        day = now.date() - timedelta(days=back)
        for hh in ("12:00", "00:00"):
            run = datetime(day.year, day.month, day.day, int(hh[:2]), tzinfo=UTC)
            if run < now:
                out.append((day, hh))
            if len(out) >= 4:
                return out
    return out


def fetch_cams_forecast(out_dir: Path, force: bool = False, raw_root: Path | None = None) -> pd.DataFrame:
    """Fetch direct CAMS NRT spectral fields from ADS.

    Group requests are efficient. If ADS rejects a group, SunStack retries each
    variable independently so the debug manifest names the exact failing field
    instead of silently dropping the whole spectral layer.

    Downloads are cached by cycle under ``raw_root`` (shared across runs) so a
    rerun does not re-download an unchanged forecast; per-run tables stay in
    ``out_dir``.
    """
    if not cds_credentials_present():
        print("ERROR Direct CAMS unavailable: no ADS/CDS API credentials found.")
        return pd.DataFrame()
    raw_dir = (raw_root if raw_root is not None else out_dir) / "raw" / "cams_forecast"
    table_dir = out_dir / "tables"
    raw_dir.mkdir(parents=True, exist_ok=True)
    client = _cds_client()
    manifest: list[dict[str, Any]] = []
    cycle_date, cycle = _latest_safe_cams_cycle()
    won: tuple[date, str] | None = None
    frames: list[pd.DataFrame] = []
    fallback: tuple[tuple[date, str], list[pd.DataFrame]] | None = None
    for cand_date, cand_cycle in _candidate_cams_cycles():
        print(f"CAMS forecast trying cycle {cand_date.isoformat()}T{cand_cycle}Z...", flush=True)
        got, complete = _fetch_cams_cycle(raw_dir, client, manifest, cand_date, cand_cycle, force)
        if got and complete:
            won, frames = (cand_date, cand_cycle), got
            break
        if fallback is None and got:
            fallback = ((cand_date, cand_cycle), got)
    if won is not None:
        cycle_date, cycle = won
    if won is None and fallback is not None:
        (cycle_date, cycle), frames = fallback
        print(f"WARN direct CAMS using partial {cycle_date.isoformat()}T{cycle}Z data.", flush=True)

    (raw_dir / "manifest.json").write_text(json.dumps({
        "dataset": CAMS_FORECAST_DATASET,
        "cycle": f"{cycle_date.isoformat()}T{cycle}Z",
        "requests": manifest,
    }, indent=2), encoding="utf-8")

    if not frames:
        return pd.DataFrame()
    result = frames[0]
    for frame in frames[1:]:
        result = result.merge(frame.drop(columns=["source"], errors="ignore"), on="time_utc", how="outer")
    # Merge can create duplicate columns when different files carry shared coords;
    # retain the first non-null version.
    duplicate_bases = {}
    for c in list(result.columns):
        if c.endswith(("_x", "_y")):
            duplicate_bases.setdefault(c[:-2], []).append(c)
    for base, cols in duplicate_bases.items():
        if base not in result:
            result[base] = result[cols].bfill(axis=1).iloc[:, 0]
        result = result.drop(columns=cols, errors="ignore")
    result["source"] = "cams_direct_forecast"
    result["cams_cycle"] = f"{cycle_date.isoformat()}T{cycle}Z"
    result = result.sort_values("time_utc").drop_duplicates("time_utc")
    _write_table(result, table_dir / "cams_direct_forecast")
    return result


def _fetch_cams_cycle(
    raw_dir: Path,
    client,
    manifest: list[dict[str, Any]],
    cycle_date: date,
    cycle: str,
    force: bool,
) -> tuple[list[pd.DataFrame], bool]:
    """One cycle attempt: group requests with per-variable fallback.

    Returns (frames, complete); complete means every group yielded data
    (already-downloaded files count). Manifest entries get a cycle tag.
    """
    frames: list[pd.DataFrame] = []
    entries: list[dict[str, Any]] = []
    complete = True

    def request_for(variables: list[str]) -> dict[str, Any]:
        return {
            "variable": variables,
            "date": [f"{cycle_date:%Y-%m-%d}/{cycle_date:%Y-%m-%d}"],
            "time": [cycle],
            "leadtime_hour": [str(x) for x in range(121)],
            "type": ["forecast"],
            "data_format": "netcdf_zip",
            "area": _cams_area(),
        }

    for group, variables in config.CAMS_FORECAST_VARIABLE_GROUPS.items():
        target = raw_dir / f"cams_{cycle_date:%Y%m%d}_{cycle[:2]}z__{group}.netcdf_zip"
        extract = raw_dir / f"extract__{group}"
        group_ok = target.exists() and not force
        yielded = False
        if not group_ok:
            try:
                _retrieve_cams(client, CAMS_FORECAST_DATASET, request_for(variables), target)
                group_ok = True
                entries.append({"group": group, "variables": variables, "ok": True, "mode": "group"})
            except Exception as exc:
                entries.append({"group": group, "variables": variables, "ok": False, "mode": "group", "error": str(exc)})
                print(f"WARN direct CAMS group {group} failed; retrying variables individually: {exc}")
        if group_ok:
            frame = normalize_cams_netcdf_zip(target, extract, "cams_direct_forecast")
            if not frame.empty:
                frames.append(frame)
                yielded = True
            complete = complete and yielded
            continue
        for variable in variables:
            vtarget = raw_dir / f"cams_{cycle_date:%Y%m%d}_{cycle[:2]}z__{group}__{_sanitize(variable)}.netcdf_zip"
            vextract = raw_dir / f"extract__{group}__{_sanitize(variable)}"
            try:
                if not vtarget.exists() or force:
                    _retrieve_cams(client, CAMS_FORECAST_DATASET, request_for([variable]), vtarget)
                frame = normalize_cams_netcdf_zip(vtarget, vextract, "cams_direct_forecast")
                if frame.empty:
                    raise RuntimeError("download parsed to an empty table")
                frames.append(frame)
                entries.append({"group": group, "variable": variable, "ok": True, "mode": "single-variable"})
                yielded = True
            except Exception as exc:
                entries.append({"group": group, "variable": variable, "ok": False, "mode": "single-variable", "error": str(exc)})
                print(f"ERROR direct CAMS variable {variable}: {exc}")
        complete = complete and yielded
    tag = f"{cycle_date.isoformat()}T{cycle}Z"
    for entry in entries:
        entry["cycle"] = tag
    manifest.extend(entries)
    return frames, complete


def fetch_cams_eac4_history(out_dir: Path, force: bool = False) -> pd.DataFrame:
    if not cds_credentials_present():
        print("INFO CAMS EAC4 skipped: no ADS/CDS API credentials found.")
        return pd.DataFrame()
    raw_dir = out_dir / "raw" / "cams_eac4"
    table_dir = out_dir / "tables" / "cams_eac4"
    raw_dir.mkdir(parents=True, exist_ok=True)
    table_dir.mkdir(parents=True, exist_ok=True)
    frames: list[pd.DataFrame] = []
    times = [f"{h:02d}:00" for h in range(0, 24, 3)]
    missing: list[int] = []
    for year in range(config.CAMS_EAC4_START_YEAR, config.CAMS_EAC4_END_YEAR + 1):
        parquet = table_dir / f"eac4_{year}.parquet"
        if parquet.exists() and not force:
            frames.append(pd.read_parquet(parquet))
        else:
            missing.append(year)

    def _one(year: int) -> pd.DataFrame:
        parquet = table_dir / f"eac4_{year}.parquet"
        target = raw_dir / f"eac4_{year}.netcdf_zip"
        extract = raw_dir / f"extract_{year}"
        if not target.exists() or force:
            request = {
                "variable": config.CAMS_EAC4_VARIABLES,
                "date": [f"{year}-01-01/{year}-12-31"],
                "time": times,
                "data_format": "netcdf_zip",
                "area": _cams_area(0.8),
            }
            print(f"CAMS EAC4 {year}: requesting...", flush=True)
            try:
                _retrieve_cams(_cds_client(), CAMS_EAC4_DATASET, request, target)
            except Exception as exc:
                print(f"WARN CAMS EAC4 {year}: {exc}", flush=True)
                return pd.DataFrame()
        try:
            frame = normalize_cams_netcdf_zip(target, extract, "cams_eac4")
        except Exception as exc:
            print(f"WARN CAMS EAC4 {year}: normalize failed: {exc}", flush=True)
            return pd.DataFrame()
        if frame.empty:
            return frame
        frame.to_parquet(parquet, index=False)
        print(f"CAMS EAC4 {year}: done ({len(frame)} rows)", flush=True)
        return frame

    if missing:
        with ThreadPoolExecutor(max_workers=config.CAMS_EAC4_WORKERS) as pool:
            frames.extend(f for f in pool.map(_one, sorted(missing)) if not f.empty)

    result = pd.concat(frames, ignore_index=True, sort=False).drop_duplicates("time_utc").sort_values("time_utc") if frames else pd.DataFrame()
    if not result.empty:
        _write_table(result, out_dir / "tables" / "cams_eac4_hourly3")
    return result
