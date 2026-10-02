from __future__ import annotations

import threading
import webbrowser
from collections.abc import Callable
from pathlib import Path

import numpy as np
from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import HTMLResponse, Response

from . import build_sha as _build_sha_mod
from . import config
from .build_sha import build_sha

__getattr__ = _build_sha_mod.__getattr__
from . import serving as _serving_mod

_daylight_payload_rows = _serving_mod._daylight_payload_rows
_filtered_payload = _serving_mod._filtered_payload
_latest_dir = _serving_mod._latest_dir
_read_table = _serving_mod._read_table
_records = _serving_mod._records
_resolve_site = _serving_mod._resolve_site
build_calendar_ics = _serving_mod.build_calendar_ics
build_interval_ics = _serving_mod.build_interval_ics
_daily_uv_peaks = _serving_mod._daily_uv_peaks
_parse_personal_mmd = _serving_mod._parse_personal_mmd


def _parse_surface(surface: object, extent: object) -> tuple[str, str]:
    from .surface import SURFACE_EXTENT_MODES, resolve_surface

    slug = str(surface or "unknown").strip() or "unknown"
    mode = str(extent or "local").strip() or "local"
    try:
        prof = resolve_surface(slug)
    except ValueError as exc:
        raise ValueError(str(exc)) from exc
    if mode not in SURFACE_EXTENT_MODES:
        raise ValueError(
            f"surface_extent must be one of {list(SURFACE_EXTENT_MODES)}, got {mode!r}")
    return prof.slug, mode

def _parse_skin_plane(
    tilt: object, azimuth: object
) -> tuple[float | None, float | None]:
    """Parse optional request geometry without replacing configured defaults."""
    def _value(raw: object, name: str, high: float, wrap360: bool = False) -> float | None:
        text = "" if raw is None else str(raw).strip()
        if not text:
            return None
        try:
            value = float(text)
        except (TypeError, ValueError):
            raise ValueError(
                f"{name} must be a finite number in [0, {high:g}], got {text!r}"
            ) from None
        if not np.isfinite(value) or not 0 <= value <= high:
            raise ValueError(
                f"{name} must be a finite number in [0, {high:g}], got {text!r}"
            )
        return 0.0 if wrap360 and value == high else value

    return _value(tilt, "skin_tilt_deg", 180), _value(
        azimuth, "skin_azimuth_deg", 360, wrap360=True
    )


from . import serving as _serving_template_mod

HTML = _serving_template_mod.HTML
_site_nav = _serving_template_mod._site_nav


RunLiveFn = Callable[..., Path]


def create_app(root: Path, run_live_fn: RunLiveFn | None = None) -> FastAPI:
    app = FastAPI(title="SunStack TanScore")

    @app.get("/", response_class=HTMLResponse)
    def home():
        return HTML

    @app.get("/api/data")
    def data(
        skin_type: str = Query(default=""),
        min_temp: float | None = Query(default=None),
        location: str = Query(default=""),
        personal_mmd: str = Query(default=""),
        personal_mmd_basis: str = Query(default=""),
        surface: str = Query(default="unknown"),
        surface_extent: str = Query(default="local"),
        skin_tilt_deg: str = Query(default=""),
        skin_azimuth_deg: str = Query(default=""),
    ):
        try:
            mmd, basis = _parse_personal_mmd(personal_mmd, personal_mmd_basis)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        try:
            surf, extent = _parse_surface(surface, surface_extent)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        try:
            tilt, azimuth = _parse_skin_plane(skin_tilt_deg, skin_azimuth_deg)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        try:
            try:
                st = int(skin_type) if skin_type else None
            except (TypeError, ValueError):
                raise HTTPException(status_code=400, detail=f"invalid skin_type: {skin_type!r}")
            try:
                site = _resolve_site(location or None)
            except FileNotFoundError as exc:
                raise HTTPException(status_code=404, detail=str(exc))
            run, hourly, half, daily, summary = _filtered_payload(
                root, st, min_temp, site, mmd, basis, surf, extent, tilt, azimuth
            )
            # Source tables retain all rows; payload rows use astronomical daylight.
            hourly_ui = _daylight_payload_rows(hourly)
            half_ui = _daylight_payload_rows(half)
            return {
                "run": str(run),
                "daily": _records(daily),
                "hourly": _records(hourly_ui),
                "half_hour": _records(half_ui),
                "summary": summary,
                "location": site.slug,
                "build_sha": build_sha(),
            }
        except Exception as exc:
            raise HTTPException(status_code=500, detail=str(exc)) from exc

    @app.get("/api/locations")
    def locations():
        return {
            "locations": [
                {k: e[k] for k in ("slug", "name", "lat", "lon", "timezone", "default")}
                for e in _site_nav()
            ]
        }

    @app.post("/api/refresh")
    def refresh(
        skin_type: str = Query(default=""),
        min_temp: float | None = Query(default=None),
        location: str = Query(default=""),
        personal_mmd: str = Query(default=""),
        personal_mmd_basis: str = Query(default=""),
        surface: str = Query(default="unknown"),
        surface_extent: str = Query(default="local"),
        skin_tilt_deg: str = Query(default=""),
        skin_azimuth_deg: str = Query(default=""),
    ):
        try:
            mmd, basis = _parse_personal_mmd(personal_mmd, personal_mmd_basis)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        try:
            _ = _parse_surface(surface, surface_extent)
            _ = _parse_skin_plane(skin_tilt_deg, skin_azimuth_deg)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        try:
            _run = run_live_fn
            if _run is None:
                raise HTTPException(status_code=503, detail="live refresh unavailable: server started without a runner")
            try:
                st = int(skin_type) if skin_type else None
            except (TypeError, ValueError):
                raise HTTPException(status_code=400, detail=f"invalid skin_type: {skin_type!r}")
            try:
                site = _resolve_site(location or None)
            except FileNotFoundError as exc:
                raise HTTPException(status_code=404, detail=str(exc))
            # Surface and pose are UI context only; live runs stay horizontal-environmental.
            assert callable(_run)
            result = _run(
                root,
                auto_calibrate=True,
                force_cams=True,
                strict=True,
                skin_type=st,
                min_temp_f=min_temp,
                personal_mmd_j_m2=mmd,
                personal_mmd_basis=basis,
                fresh=True,
                site=site,
            )
            return {"ok": True, "run": str(result)}
        except Exception as exc:
            raise HTTPException(
                status_code=500, detail=f"LIVE REFRESH FAILED: {exc}"
            ) from exc

    @app.get("/api/calendar.ics")
    def calendar(
        skin_type: str = Query(default=""),
        min_temp: float | None = Query(default=None),
        location: str = Query(default=""),
        surface: str = Query(default="unknown"),
        surface_extent: str = Query(default="local"),
        skin_tilt_deg: str = Query(default=""),
        skin_azimuth_deg: str = Query(default=""),
    ):
        try:
            _ = _parse_surface(surface, surface_extent)
            _ = _parse_skin_plane(skin_tilt_deg, skin_azimuth_deg)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        try:
            try:
                st = int(skin_type) if skin_type else None
            except (TypeError, ValueError):
                raise HTTPException(status_code=400, detail=f"invalid skin_type: {skin_type!r}")
            try:
                site = _resolve_site(location or None)
            except FileNotFoundError as exc:
                raise HTTPException(status_code=404, detail=str(exc))
            # Calendar ranking is environmental-horizontal; validated UI context is ignored.
            _, hourly, _, daily, summary = _filtered_payload(root, st, min_temp, site)
            ics = build_calendar_ics(
                daily,
                str(summary.get("run", "")),
                hourly,
                site_slug=site.slug,
                tz_name=site.timezone,
            )
            return Response(content=ics, media_type="text/calendar; charset=utf-8")
        except Exception as exc:
            raise HTTPException(status_code=500, detail=str(exc)) from exc

    return app


def serve(
    root: Path,
    host: str | None = None,
    port: int | None = None,
    open_browser: bool = True,
    run_live_fn: RunLiveFn | None = None,
) -> None:
    import uvicorn

    host = host or config.UI_HOST
    port = int(port or config.UI_PORT)
    if open_browser:
        threading.Timer(0.8, lambda: webbrowser.open(f"http://{host}:{port}")).start()
    uvicorn.run(create_app(root, run_live_fn), host=host, port=port, log_level="info")

