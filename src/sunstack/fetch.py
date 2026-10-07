from __future__ import annotations

import json
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Protocol

import requests
import requests_cache

try:
    from retry_requests import retry
except ImportError:

    def retry(
        session: requests.Session | None = None,
        retries: int = 10,
        backoff_factor: float = 0.1,
        status_to_retry: tuple[int, ...] = (),
        prefixes: tuple[str, ...] = (),
        **_kwargs: object,
    ) -> requests.Session:
        # Mirrors retry_requests' signature so both branches of this try/except
        # declare the same call surface; with the package absent the session is
        # returned unwrapped rather than raising.
        assert session is not None
        return session


from . import config

FORECAST_URL = "https://api.open-meteo.com/v1/forecast"
ENSEMBLE_URL = "https://ensemble-api.open-meteo.com/v1/ensemble"
AIR_QUALITY_URL = "https://air-quality-api.open-meteo.com/v1/air-quality"

# Query-parameter values the Open-Meteo APIs accept. Kept narrow (not Any) so
# the param builders and the session Protocol keep their real types.
QueryParams = dict[str, str | int | float]


@dataclass(slots=True)
class FetchResult:
    name: str
    endpoint: str
    params: QueryParams
    # Raw decoded JSON body. The upstream shape is only known after parsing
    # (mapping for forecast payloads, list for multi-model ones), so it is
    # carried as object and narrowed by consumers.
    payload: object
    error: str | None = None
    from_cache: bool = False
    elapsed_ms: float | None = None
    status_code: int | None = None


def build_session(
    cache_dir: Path, expire_after: int = 900, fresh: bool = False
) -> requests.Session:
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


class HttpResponse(Protocol):
    """The slice of an HTTP response the diagnostics touch.

    Declared as read-only properties, not mutable attributes: requests exposes
    them as properties, and a mutable attribute in a Protocol is invariant, so
    a real Response would not satisfy it.
    """

    @property
    def status_code(self) -> int: ...
    @property
    def content(self) -> bytes | None: ...
    @property
    def text(self) -> str: ...

    def raise_for_status(self) -> None: ...
    def json(self) -> Any: ...


class HttpSession(Protocol):
    """The slice of a requests session: one GET, as requests/httpx provide it."""

    def get(
        self, url: str, /, *, params: dict[str, Any], timeout: int
    ) -> HttpResponse: ...


def request(
    session: HttpSession, name: str, endpoint: str, params: dict[str, Any],
    timeout: int = 120,
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
        res = request(session, name, endpoint, params)
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
        return request(requests.Session(), name, endpoint, params, timeout=timeout)

    with ThreadPoolExecutor(max_workers=3) as pool:
        return list(pool.map(_one, probes))


_FEED_USE = {
    # Core scoring inputs (actually consumed at runtime).
    "deterministic__best_match": "scoring core (weather/radiation/UVI)",
    "profile__best_match": "scoring core (profiles)",
    "hrrr_15min": "subhour radiation/weather correction",
    "air_quality": "AOD550 + UV fallback/context",
    "ensemble_members__ncep_gefs025": "confidence (support)",
    "ensemble_members__ncep_aigefs025": "confidence (support)",
    "ensemble_members__ecmwf_ifs025_ensemble": "confidence (support)",
    "ensemble_members__ecmwf_aifs025_ensemble": "confidence (support)",
}
_FEED_USE_PREFIX = (
    ("deterministic__", "confidence (deterministic agreement)"),
    ("profile__", "diagnostic-only (persisted, unscored)"),
    ("ensemble_members__", "confidence (support)"),
    ("ensemble_mean__", "diagnostic-only (persisted, unscored)"),
)


def _feed_use(name: str) -> str:
    if name in _FEED_USE:
        return _FEED_USE[name]
    for prefix, use in _FEED_USE_PREFIX:
        if name.startswith(prefix):
            return use
    if name in ("air_quality",):
        return _FEED_USE["air_quality"]
    return "diagnostic-only (persisted, unscored)"


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
        entry["consumed_by"] = _feed_use(result.name)
        manifest.append(entry)
        if result.payload is not None:
            _raw_text = json.dumps(result.payload, indent=2, allow_nan=True)
            (raw_dir / f"{result.name}.json").write_text(_raw_text, encoding="utf-8")
            import hashlib as _hashlib

            entry["sha256"] = _hashlib.sha256(_raw_text.encode("utf-8")).hexdigest()[:16]
            entry["retrieved_at"] = datetime.now(UTC).isoformat()
    (raw_dir / "manifest.json").write_text(
        json.dumps(manifest, indent=2), encoding="utf-8"
    )
