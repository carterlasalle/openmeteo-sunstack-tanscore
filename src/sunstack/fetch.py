from __future__ import annotations

import json
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import requests
import requests_cache

try:
    from retry_requests import retry
except ImportError:

    def retry(session, **_kwargs):
        return session


from . import config

FORECAST_URL = "https://api.open-meteo.com/v1/forecast"
ENSEMBLE_URL = "https://ensemble-api.open-meteo.com/v1/ensemble"
AIR_QUALITY_URL = "https://air-quality-api.open-meteo.com/v1/air-quality"


@dataclass(slots=True)
class FetchResult:
    name: str
    endpoint: str
    params: dict[str, Any]
    payload: dict[str, Any] | list[dict[str, Any]] | None
    error: str | None = None
    from_cache: bool = False
    elapsed_ms: float | None = None
    status_code: int | None = None


def build_session(cache_dir: Path, expire_after: int = 900, fresh: bool = False):
    if fresh:
        return retry(requests.Session(), retries=5, backoff_factor=0.35)
    cache_dir.mkdir(parents=True, exist_ok=True)
    cached = requests_cache.CachedSession(
        str(cache_dir / "http_cache"),
        expire_after=expire_after,
        allowable_methods=("GET",),
        stale_if_error=True,
    )
    return retry(cached, retries=5, backoff_factor=0.35)


def _request(
    session, name: str, endpoint: str, params: dict[str, Any], timeout: int = 120
) -> FetchResult:
    started = time.perf_counter()
    try:
        response = session.get(endpoint, params=params, timeout=timeout)
        elapsed = (time.perf_counter() - started) * 1000.0
        response.raise_for_status()
        body_len = len(response.content or b"")
        if body_len == 0:
            return FetchResult(
                name=name,
                endpoint=endpoint,
                params=params,
                payload=None,
                error=f"empty body: HTTP {response.status_code}, 0 bytes (upstream returned nothing to parse)",
                elapsed_ms=round((time.perf_counter() - started) * 1000.0, 1),
                status_code=response.status_code,
            )
        try:
            payload = response.json()
        except ValueError as exc:
            preview = (response.text or "")[:200].replace("\n", " ")
            return FetchResult(
                name=name,
                endpoint=endpoint,
                params=params,
                payload=None,
                error=f"unparseable body: HTTP {response.status_code}, {body_len} bytes, {exc} :: {preview!r}",
                elapsed_ms=round((time.perf_counter() - started) * 1000.0, 1),
                status_code=response.status_code,
            )
        if isinstance(payload, dict) and payload.get("error"):
            return FetchResult(
                name=name,
                endpoint=endpoint,
                params=params,
                payload=None,
                error=str(payload.get("reason", "Open-Meteo error")),
                elapsed_ms=round((time.perf_counter() - started) * 1000.0, 1),
                status_code=response.status_code,
            )
        return FetchResult(
            name=name,
            endpoint=endpoint,
            params=params,
            payload=payload,
            from_cache=bool(getattr(response, "from_cache", False)),
            elapsed_ms=round(elapsed, 1),
            status_code=response.status_code,
        )
    except requests.RequestException as exc:
        return FetchResult(
            name=name,
            endpoint=endpoint,
            params=params,
            payload=None,
            error=str(exc),
            elapsed_ms=round((time.perf_counter() - started) * 1000.0, 1),
            status_code=getattr(locals().get("response", None), "status_code", None),
        )


def _common() -> dict[str, Any]:
    return {
        "latitude": config.LATITUDE,
        "longitude": config.LONGITUDE,
        "timezone": config.TIMEZONE,
        "temperature_unit": "fahrenheit",
        "wind_speed_unit": "mph",
        "precipitation_unit": "inch",
        "cell_selection": "land",
    }


def deterministic_params(model: str) -> dict[str, Any]:
    params = {
        **_common(),
        "forecast_days": config.FORECAST_DAYS,
        "models": model,
        "hourly": ",".join(config.HOURLY_VARIABLES),
        "daily": ",".join(config.DAILY_VARIABLES),
    }
    if model == "best_match":
        params["current"] = ",".join(config.CURRENT_VARIABLES)
    return params


def profile_params(model: str) -> dict[str, Any]:
    return {
        **_common(),
        "forecast_days": min(config.FORECAST_DAYS, 10),
        "models": model,
        "hourly": ",".join(config.PROFILE_VARIABLES),
    }


def hrrr_15min_params() -> dict[str, Any]:
    return {
        **_common(),
        "models": "ncep_hrrr_conus",
        "forecast_minutely_15": config.HRRR_15MIN_STEPS,
        "minutely_15": ",".join(config.HRRR_15MIN_VARIABLES),
    }


def ensemble_params(model: str) -> dict[str, Any]:
    return {
        **_common(),
        "forecast_days": config.FORECAST_DAYS,
        "temporal_resolution": "hourly",
        "models": model,
        "hourly": ",".join(config.ENSEMBLE_VARIABLES),
    }


def ensemble_mean_params(model: str) -> dict[str, Any]:
    return {
        **_common(),
        "forecast_days": config.FORECAST_DAYS,
        "models": model,
        "hourly": ",".join(config.ENSEMBLE_MEAN_VARIABLES),
    }


def air_quality_params() -> dict[str, Any]:
    return {
        "latitude": config.LATITUDE,
        "longitude": config.LONGITUDE,
        "timezone": config.TIMEZONE,
        "forecast_days": config.AIR_QUALITY_DAYS,
        "domains": "cams_global",
        "hourly": ",".join(config.AIR_QUALITY_VARIABLES),
    }


def fetch_all(cache_dir: Path, fresh: bool = True) -> list[FetchResult]:
    """Fetch every live source. Live runs bypass cache by default.

    Historical/calibration endpoints have their own durable caching because they are
    immutable/slow; current forecasts should represent a real request on every run.
    """
    import logging

    log = logging.getLogger("sunstack.fetch")
    session = build_session(cache_dir, fresh=fresh)
    results: list[FetchResult] = []

    def _get(name: str, endpoint: str, params: dict[str, Any]) -> FetchResult:
        res = _request(session, name, endpoint, params)
        status = "OK" if res.payload is not None else f"FAIL: {res.error}"
        log.info("[%s] %s (%s ms)", name, status, res.elapsed_ms)
        results.append(res)
        return res

    for model in config.DETERMINISTIC_MODELS:
        _get(f"deterministic__{model}", FORECAST_URL, deterministic_params(model))
    for model in config.PROFILE_MODELS:
        _get(f"profile__{model}", FORECAST_URL, profile_params(model))
    _get("hrrr_15min", FORECAST_URL, hrrr_15min_params())
    for model in config.ENSEMBLE_MEMBER_MODELS:
        _get(f"ensemble_members__{model}", ENSEMBLE_URL, ensemble_params(model))
    for model in config.ENSEMBLE_MEAN_MODELS:
        _get(f"ensemble_mean__{model}", ENSEMBLE_URL, ensemble_mean_params(model))
    _get("air_quality", AIR_QUALITY_URL, air_quality_params())
    return results


def probe_live(timeout: int = 20) -> list[FetchResult]:
    """Fast connectivity check: one tiny request per Open-Meteo endpoint family."""
    probes = [
        (
            "forecast__best_match",
            FORECAST_URL,
            {
                **_common(),
                "forecast_days": 1,
                "models": "best_match",
                "hourly": "temperature_2m",
            },
        ),
        (
            "ensemble__ncep_gefs025",
            ENSEMBLE_URL,
            {
                **_common(),
                "forecast_days": 1,
                "models": "ncep_gefs025",
                "hourly": "temperature_2m",
            },
        ),
        ("air_quality", AIR_QUALITY_URL, {**air_quality_params(), "forecast_days": 1}),
    ]

    def _one(item: tuple[str, str, dict[str, Any]]) -> FetchResult:
        name, endpoint, params = item
        return _request(requests.Session(), name, endpoint, params, timeout=timeout)

    with ThreadPoolExecutor(max_workers=3) as pool:
        return list(pool.map(_one, probes))


def write_raw(results: list[FetchResult], raw_dir: Path) -> None:
    raw_dir.mkdir(parents=True, exist_ok=True)
    manifest = []
    for result in results:
        entry = {
            "name": result.name,
            "endpoint": result.endpoint,
            "params": result.params,
            "error": result.error,
            "from_cache": result.from_cache,
            "elapsed_ms": result.elapsed_ms,
            "status_code": result.status_code,
            "ok": result.payload is not None,
        }
        manifest.append(entry)
        if result.payload is not None:
            (raw_dir / f"{result.name}.json").write_text(
                json.dumps(result.payload, indent=2, allow_nan=True), encoding="utf-8"
            )
    (raw_dir / "manifest.json").write_text(
        json.dumps(manifest, indent=2), encoding="utf-8"
    )
