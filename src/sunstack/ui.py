from __future__ import annotations

import importlib
import threading
import webbrowser
from collections.abc import Callable
from pathlib import Path
from typing import cast

import numpy as np
from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import HTMLResponse, Response

from . import build_sha as _build_sha_mod
from . import config
from .build_sha import build_sha

__getattr__ = _build_sha_mod.__getattr__
from . import serving as _serving_mod

daylight_payload_rows = _serving_mod.daylight_payload_rows
filtered_payload = _serving_mod.filtered_payload
latest_dir = _serving_mod.latest_dir
read_table = _serving_mod.read_table
records = _serving_mod.records
resolve_site = _serving_mod.resolve_site
build_calendar_ics = _serving_mod.build_calendar_ics
build_interval_ics = _serving_mod.build_interval_ics
daily_uv_peaks = _serving_mod.daily_uv_peaks
parse_personal_mmd = _serving_mod.parse_personal_mmd

from .opportunity import ClassBlocks


def _parse_classes(raw: object) -> ClassBlocks:
    """Parse the optional per-request class schedule.

    This is user context, not product data. It used to be a hardcoded personal
    timetable shipped in the client and the server (gated to the South Bend
    slug), so a public page rendered one person's week as if it were the
    visitor's. An empty parameter means "no schedule": nothing is filtered,
    no class rows are marked, and no "free for you" line is produced.
    """
    from .opportunity import parse_class_blocks

    return parse_class_blocks(raw)


def _parse_skin_type(raw: object) -> int | None:
    """Parse the Fitzpatrick selector, rejecting anything outside 1-6.

    The range check used to live only inside `attach_fitzpatrick`, which raises
    ValueError; that escaped the endpoint's generic handler and surfaced as
    `500 {"detail": "Fitzpatrick skin type must be an integer from 1 to 6"}` —
    a client error reported as a server error.
    """
    text = "" if raw is None else str(raw).strip()
    if not text:
        return None
    try:
        value = int(text)
    except (TypeError, ValueError):
        raise HTTPException(status_code=400, detail=f"invalid skin_type: {raw!r}") from None
    if not 1 <= value <= 6:
        raise HTTPException(
            status_code=400,
            detail=f"skin_type must be an integer from 1 to 6, got {value}",
        )
    return value


# The cold-floor window the page's own input advertises (32-80 °F). It lives in
# the FastAPI Query declaration so /openapi.json describes the accepted domain
# and out-of-range or non-finite values are rejected before a handler runs
# (F-19 enforced the same window in the handler with a 400; the schema is the
# contract clients and generated SDKs actually read, so it owns the bound now).
_MIN_TEMP_F_LOW, _MIN_TEMP_F_HIGH = 32.0, 80.0

# `classes` is a JSON array of [day, start, end] blocks; empty means "no
# schedule". The wire shape belongs in the schema, so an obvious non-array is a
# 422 before a handler runs instead of a 400 from the parser.
_CLASSES_PATTERN = r"^$|^\[.*\]$"
_CLASSES_DESC = (
    'JSON array of {"dow": 0-4, "start": "HH:MM", "end": "HH:MM"} blocks '
    "(empty string = no schedule)"
)

# Fitzpatrick selector: the page's <select> offers empty (unset) or 1-6, and the
# handler rejects anything else, so the schema states the same closed domain.
_SKIN_TYPE_PATTERN = r"^$|^[1-6]$"

# Status codes every read endpoint can deliberately return. 503 is the fresh
# install: no run has been published yet, which the message tells the user to
# fix by running one - it is not a server fault.
_READ_RESPONSES: dict[int | str, dict[str, object]] = {
    400: {"description": "invalid query parameter (schedule JSON, surface, tilt, MMD)"},
    404: {"description": "unknown location"},
    503: {"description": "no forecast run published yet"},
}


def _parse_surface(surface: object, extent: object) -> tuple[str, str]:
    from .surface import PRESETS, resolve_surface, validate_surface_extent

    slug = str(surface or "unknown").strip() or "unknown"
    mode = str(extent or "local").strip() or "local"
    # F-20: `custom` is a CLI capability - it needs both reflectance flags, which
    # this endpoint does not accept - so listing it as an allowed slug here
    # advertised an option that could never work.
    if slug == "custom":
        raise ValueError(
            "surface=custom needs explicit reflectances and is CLI-only: pass --surface-uva-reflectance and --surface-uvb-reflectance to `sunstack run`"
        )
    try:
        prof = resolve_surface(slug)
    except ValueError as exc:
        allowed = sorted(s for s in PRESETS if s != "custom")
        raise ValueError(f"unknown surface {slug!r}; allowed: {allowed}") from exc
    mode = validate_surface_extent(mode)
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
site_nav = _serving_template_mod.site_nav


RunLiveFn = Callable[..., Path]


def _resolve_run_live() -> RunLiveFn | None:
    """The live runner, resolved at call time rather than at wiring time.

    Resolved by name for two reasons: `sunstack.cli` imports this module, so a
    static `from . import cli` would close a real import cycle; and a reference
    captured at startup would pin the original function, so patching
    `sunstack.cli.run_live` (a test, an embedder) would silently keep running the
    unpatched one.
    """
    cli = importlib.import_module("sunstack.cli")
    return cast("RunLiveFn | None", getattr(cli, "run_live", None))


def create_app(root: Path, run_live_fn: RunLiveFn | None = None) -> FastAPI:
    app = FastAPI(title="SunStack TanScore")

    @app.get("/", response_class=HTMLResponse)
    def home():
        return HTML

    @app.get("/api/data", responses=_READ_RESPONSES)
    def data(
        skin_type: str = Query(default="", pattern=_SKIN_TYPE_PATTERN),
        min_temp: float | None = Query(
            default=None, ge=_MIN_TEMP_F_LOW, le=_MIN_TEMP_F_HIGH
        ),
        location: str = Query(default=""),
        personal_mmd: str = Query(default=""),
        personal_mmd_basis: str = Query(default=""),
        surface: str = Query(default="unknown"),
        surface_extent: str = Query(default="local"),
        skin_tilt_deg: str = Query(default=""),
        skin_azimuth_deg: str = Query(default=""),
        classes: str = Query(default="", pattern=_CLASSES_PATTERN, description=_CLASSES_DESC),
    ):
        try:
            class_blocks = _parse_classes(classes)
        except (TypeError, ValueError) as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        try:
            mmd, basis = parse_personal_mmd(personal_mmd, personal_mmd_basis)
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
            st = _parse_skin_type(skin_type)
            try:
                site = resolve_site(location or None)
            except FileNotFoundError as exc:
                raise HTTPException(status_code=404, detail=str(exc))
            run, hourly, half, daily, summary = filtered_payload(
                root, st, min_temp, site, mmd, basis, surf, extent, tilt, azimuth,
                class_blocks,
            )
            # Source tables retain all rows; payload rows use astronomical daylight.
            hourly_ui = daylight_payload_rows(hourly)
            half_ui = daylight_payload_rows(half)
            # F-21: the run's own summary has no request context, so its
            # skin_type is null, while every row carries fitzpatrick_type. The
            # served summary must name the skin type it was rendered for.
            summary["skin_type"] = st
            return {
                "run": str(run),
                "daily": records(daily),
                "hourly": records(hourly_ui),
                "half_hour": records(half_ui),
                "summary": summary,
                "location": site.slug,
                "build_sha": build_sha(),
            }
        except HTTPException:
            # A deliberate 4xx from the inner guards must not be re-wrapped as
            # a 500. `raise HTTPException(404, "unknown location: atlantis")`
            # inside this try used to surface as
            # `500 {"detail": "404: unknown location: atlantis"}` — a client
            # error reported as a server error, which breaks monitoring and
            # sends the user looking for a server log.
            raise
        except FileNotFoundError as exc:
            # No run published yet. That is the documented fresh-install state
            # (the message says how to fix it), so it is 503 + retry, not a 500
            # that reads as a server crash. `latest_dir` is the only thing below
            # that raises it - an unknown location is already a 404 above.
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        except Exception as exc:
            raise HTTPException(status_code=500, detail=str(exc)) from exc

    @app.get("/api/locations")
    @app.get("/locations.json")
    def locations():
        # Both paths on purpose: the client tries the static ./locations.json
        # first (that is what the exported site serves) and falls back to the
        # API. Serving the same payload here means the live UI does not emit a
        # 404 into the console on every load.
        return {
            "locations": [
                {k: e[k] for k in ("slug", "name", "lat", "lon", "timezone", "default")}
                for e in site_nav()
            ]
        }

    @app.post("/api/refresh")
    def refresh(
        skin_type: str = Query(default="", pattern=_SKIN_TYPE_PATTERN),
        min_temp: float | None = Query(
            default=None, ge=_MIN_TEMP_F_LOW, le=_MIN_TEMP_F_HIGH
        ),
        location: str = Query(default=""),
        personal_mmd: str = Query(default=""),
        personal_mmd_basis: str = Query(default=""),
        surface: str = Query(default="unknown"),
        surface_extent: str = Query(default="local"),
        skin_tilt_deg: str = Query(default=""),
        skin_azimuth_deg: str = Query(default=""),
    ):
        try:
            mmd, basis = parse_personal_mmd(personal_mmd, personal_mmd_basis)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        try:
            _ = _parse_surface(surface, surface_extent)
            _ = _parse_skin_plane(skin_tilt_deg, skin_azimuth_deg)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        try:
            _run = run_live_fn if run_live_fn is not None else _resolve_run_live()
            if _run is None:
                raise HTTPException(status_code=503, detail="live refresh unavailable: this install has no live runner")
            st = _parse_skin_type(skin_type)
            try:
                site = resolve_site(location or None)
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
        except HTTPException:
            raise
        except Exception as exc:
            raise HTTPException(
                status_code=500, detail=f"LIVE REFRESH FAILED: {exc}"
            ) from exc

    @app.get(
        "/api/calendar.ics",
        response_class=Response,
        responses={
            **_READ_RESPONSES,
            200: {"content": {"text/calendar": {}}, "description": "iCalendar feed"},
        },
    )
    def calendar(
        skin_type: str = Query(default="", pattern=_SKIN_TYPE_PATTERN),
        min_temp: float | None = Query(
            default=None, ge=_MIN_TEMP_F_LOW, le=_MIN_TEMP_F_HIGH
        ),
        location: str = Query(default=""),
        surface: str = Query(default="unknown"),
        surface_extent: str = Query(default="local"),
        skin_tilt_deg: str = Query(default=""),
        skin_azimuth_deg: str = Query(default=""),
        classes: str = Query(default="", pattern=_CLASSES_PATTERN, description=_CLASSES_DESC),
    ):
        try:
            class_blocks = _parse_classes(classes)
        except (TypeError, ValueError) as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        try:
            _ = _parse_surface(surface, surface_extent)
            _ = _parse_skin_plane(skin_tilt_deg, skin_azimuth_deg)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        try:
            st = _parse_skin_type(skin_type)
            try:
                site = resolve_site(location or None)
            except FileNotFoundError as exc:
                raise HTTPException(status_code=404, detail=str(exc))
            # Calendar ranking is environmental-horizontal; validated UI context is ignored.
            _, hourly, _, daily, _ = filtered_payload(
                root, st, min_temp, site, class_blocks=class_blocks)
            ics = build_calendar_ics(
                daily,
                hourly,
                site_slug=site.slug,
                tz_name=site.timezone,
            )
            return Response(content=ics, media_type="text/calendar; charset=utf-8")
        except HTTPException:
            raise
        except FileNotFoundError as exc:
            # Same fresh-install state as /api/data; see there.
            raise HTTPException(status_code=503, detail=str(exc)) from exc
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

