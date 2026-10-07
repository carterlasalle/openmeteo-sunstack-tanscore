"""Serving-layer payload builders shared by the API and static export (v5).

`ui` owns the FastAPI routes + HTML; `output` (static export) needs the same
payload/calendar helpers. They used to live in `ui`, which forced
`output -> ui -> cli` edges into the `cli -> output` path (import cycle).
This leaf module depends only on opportunity/spectral/tanscore/config, so
both `ui` and `output` import from here without cycling.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import cast
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd

from . import config
from .frame import scol
from .opportunity import (
    ClassBlocks,
    apply_outdoor_feasibility,
    attach_fitzpatrick,
    attach_personalization,
    build_daily_summary,
)
from .tanscore import fnum


def resolve_site(slug: str | None) -> config.Site:
    """Empty slug keeps the South Bend default so old URLs never break."""
    sites = config.active_sites()
    if not slug:
        return config.default_site()
    for s in sites:
        if s.slug == slug:
            return s
    raise FileNotFoundError(f"unknown location: {slug}")


def latest_dir(root: Path, site: config.Site | None = None) -> Path:
    base = (
        root
        if site is None or site.slug == config.default_site().slug
        else root / "sites" / site.slug
    )
    latest = base / "latest"
    if latest.exists() and latest.is_dir():
        return latest
    marker = base / "LATEST"
    if marker.exists():
        p = Path(marker.read_text().strip())
        if p.exists():
            return p
    raise FileNotFoundError(
        "No SunStack run found. Click Refresh or run `uv run sunstack run`."
    )


def read_table(run: Path, name: str) -> pd.DataFrame:
    p = run / "tables" / f"{name}.parquet"
    if p.exists():
        return pd.read_parquet(p)
    p = run / "tables" / f"{name}.csv"
    if p.exists():
        return pd.read_csv(p)
    return pd.DataFrame()


def records(df: pd.DataFrame, limit: int | None = None) -> list[dict[str, object]]:
    """Rows as JSON-safe dicts.

    The shape is a cast, not a guess: `to_json(orient="records")` is specified to
    emit an array of flat objects, and `json.loads` is only annotated `Any`.
    """
    if limit is not None:
        df = df.head(limit)
    clean = df.copy()
    # Numeric-only: tuple columns (uvi_source_values/weights) hold
    # array-likes that frame-wide replace() chokes on (live audit
    # 2026-10-05: ambiguous-truth ValueError killed the export).
    num_cols = clean.select_dtypes(include=[np.number]).columns
    clean[num_cols] = clean[num_cols].replace([np.inf, -np.inf], np.nan)
    # Widened so the guard stays reachable: `to_json` is annotated as returning
    # str, and a non-str here is exactly the failure this check exists to name.
    text = cast(object, clean.to_json(orient="records", date_format="iso"))
    if not isinstance(text, str):
        raise TypeError("records JSON serialization must produce text")
    return cast("list[dict[str, object]]", json.loads(text))


def filtered_payload(
    root: Path,
    skin_type: int | None,
    min_temp: float | None,
    site: config.Site | None = None,
    personal_mmd_j_m2: float | None = None,
    personal_mmd_basis: str | None = None,
    surface: str = "unknown",
    surface_extent: str = "local",
    skin_tilt_deg: float | None = None,
    skin_azimuth_deg: float | None = None,
    class_blocks: ClassBlocks | None = None,
) -> tuple[Path, pd.DataFrame, pd.DataFrame, pd.DataFrame, dict[str, object]]:
    from .spectral import apply_skin_plane as _apply_plane

    run = latest_dir(root, site)
    hourly = read_table(run, "tan_forecast_hourly")
    half = read_table(run, "tan_forecast_30min")
    if hourly.empty or half.empty:
        raise RuntimeError(
            "Latest run is missing TanScore output tables; refresh the data."
        )
    if min_temp is not None:
        hourly = apply_outdoor_feasibility(hourly, min_temp)
        half = apply_outdoor_feasibility(half, min_temp)
    hourly = attach_fitzpatrick(hourly, skin_type)
    half = attach_fitzpatrick(half, skin_type)
    # Surface and pose are per-request skin-plane context (local mode never
    # mutates horizontal environmental fields; §12.11 bit-identical guarantee).
    hourly = _apply_plane(
        hourly, skin_tilt_deg, skin_azimuth_deg, surface, surface_extent
    )
    half = _apply_plane(
        half, skin_tilt_deg, skin_azimuth_deg, surface, surface_extent
    )
    # Personalization is per-request only (audit: run tables no longer carry
    # personal columns, so always compute fresh — None yields clean NaN).
    hourly = attach_personalization(
        hourly, personal_mmd_j_m2=personal_mmd_j_m2, basis=personal_mmd_basis)
    half = attach_personalization(
        half, personal_mmd_j_m2=personal_mmd_j_m2, basis=personal_mmd_basis,
        dose_col="tan_dose_30m_j_m2")
    daily = build_daily_summary(half, class_blocks=class_blocks)
    # v5 canonical endpoint names (contract §2.1.B): every published frame
    # carries exact delayed_pigmentation_dose_* twins of its tan_dose_*
    # columns. Frames scored by the current pipeline already have them; this
    # backfills pre-migration run tables and never overwrites a pipeline twin.
    for frame in (hourly, half, daily):
        for col in [c for c in frame.columns if "tan_dose" in str(c)]:
            twin = str(col).replace("tan_dose", "delayed_pigmentation_dose")
            if twin not in frame.columns:
                frame[twin] = frame[col]
    summary_path = run / "summary.json"
    # `json.loads` is only annotated `Any`; the summary is the run's JSON object,
    # so narrow it once here rather than letting it erase the payload's type.
    summary: dict[str, object] = {}
    if summary_path.exists():
        loaded = cast(object, json.loads(summary_path.read_text()))
        if isinstance(loaded, dict):
            summary = cast("dict[str, object]", loaded)
    return run, hourly, half, daily, summary


def daylight_payload_rows(frame: pd.DataFrame) -> pd.DataFrame:
    """Keep astronomical daylight for display without altering source tables."""
    if frame.empty:
        return frame.copy()

    def _numeric(name: str) -> pd.Series:
        if name not in frame:
            return pd.Series(np.nan, index=frame.index, dtype=float)
        numeric = pd.to_numeric(frame[name], errors="coerce")
        if isinstance(numeric, pd.Series):
            return numeric
        return pd.Series(numeric, index=frame.index)

    is_day = _numeric("is_day")
    if bool(is_day.notna().any()):
        return frame.loc[is_day.fillna(0) > 0].copy()
    elevation = _numeric("solar_elevation_deg")
    if bool(elevation.notna().any()):
        return frame.loc[elevation.fillna(-90) > 0].copy()
    return frame.copy()



def _ics_text(value: object) -> str:
    return (
        str(value)
        .replace("\\", "\\\\")
        .replace(";", "\\;")
        .replace(",", "\\,")
        .replace("\n", "\\n")
    )


def _ics_fold(line: str) -> str:
    parts = [line[:75]]
    rest = line[75:]
    while rest:
        parts.append(" " + rest[:74])
        rest = rest[74:]
    return "\r\n".join(parts)


def _ics_stamp(value: str, tz_name: str | None = None) -> str:
    """Local naive wall time to a UTC basic-format ICS stamp."""
    local = datetime.fromisoformat(str(value)).replace(
        tzinfo=ZoneInfo(tz_name or config.TIMEZONE)
    )
    return local.astimezone(UTC).strftime("%Y%m%dT%H%M%SZ")


def _ics_hhmm(value: str, tz_name: str | None = None) -> str:
    local = datetime.fromisoformat(str(value)).replace(
        tzinfo=ZoneInfo(tz_name or config.TIMEZONE)
    )
    return local.strftime("%-I:%M %p")


def _day_col(sub: pd.DataFrame, name: str) -> np.ndarray:
    if name not in sub:
        return np.array([], dtype=float)
    return np.asarray(pd.to_numeric(scol(sub, name), errors="coerce"), dtype=float)


def daily_uv_peaks(hourly: pd.DataFrame) -> dict[str, dict[str, str]]:
    """Per-day UV peaks from the hourly table: UVI value and time, UVB, UVA.

    Consensus UVI when present (it resists one bad source); raw OM UVI only
    as the pre-consensus fallback.
    """
    peaks: dict[str, dict[str, str]] = {}
    if hourly.empty or "time" not in hourly:
        return peaks
    uvi_col = "uvi_consensus" if "uvi_consensus" in hourly.columns else "uv_index"
    dates = np.asarray(scol(hourly, "time").astype(str).str.slice(0, 10))
    for date in sorted(set(dates.tolist())):
        sub = hourly.loc[dates == date]
        entry: dict[str, str] = {}
        uvi = _day_col(sub, uvi_col)
        if uvi.size and bool(np.isfinite(uvi).any()):
            i = int(np.nanargmax(uvi))
            entry["uvi"] = f"{uvi[i]:g}"
            entry["uvi_time"] = _ics_hhmm(
                str(np.asarray(scol(sub, "time").astype(str))[i])
            )
        for key, col in (("uvb", "predicted_uvb_wm2"), ("uva", "predicted_uva_wm2")):
            vals = _day_col(sub, col)
            if vals.size and bool(np.isfinite(vals).any()):
                entry[key] = f"{np.nanmax(vals):g}"
        peaks[str(date)] = entry
    return peaks


def _fmt_opt(value: object, fmt: str = "g", suffix: str = "") -> str | None:
    if not isinstance(value, (int, float, str)):
        return None
    try:
        f = float(value)
    except (TypeError, ValueError):
        return None
    if not np.isfinite(f):
        return None
    return f"{f:{fmt}}{suffix}"


def _partial_marker(row, flag_col: str | None) -> str:
    """' (partial)' when a complete flag is explicitly false.

    Pre-v4 rows lack the flag keys entirely and must render unchanged, so
    only an explicit false (bool False / 0, never missing/NaN) marks.
    """
    if not flag_col:
        return ""
    fv = row.get(flag_col)
    if fv is None:
        return ""
    try:
        if bool(pd.isna(fv)):
            return ""
        return "" if bool(fv) else " (partial)"
    except (TypeError, ValueError):
        return ""


def build_interval_ics(
    half_hour: pd.DataFrame,
    run_tag: str,
    site_slug: str | None = None,
    tz_name: str | None = None,
) -> str:
    """Optional per-30-minute VEVENTs with interval doses (native vs interpolated labeled)."""
    # SEQUENCE:0 — events are immutable per run (audit: run-tag digits
    # overflowed 32-bit SEQUENCE). Recurrence identity lives in UID.
    sequence = 0
    now = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    events = []
    for _, row in half_hour.iterrows():
        start = row.get("time") or row.get("dt")
        if start is None or (isinstance(start, float) and pd.isna(start)):
            continue
        try:
            end = (pd.to_datetime(str(start)) + pd.Timedelta(minutes=30)).isoformat()
        except (ValueError, TypeError):
            continue
        bits = []
        for label, col, fmt, suf, flag in (
            ("Abs", "tan_score_absolute_0_100", ".0f", "/100", None),
            ("Overall", "overall_tan_opportunity_0_100", ".0f", "/100", None),
            ("Local", "local_tan_score_0_100", ".0f", "/100", None),
            ("TanDose30", "tan_dose_30m_j_m2", "g", " J/m2 mel",
             "tan_dose_30m_complete"),
            ("SED30", "sed_30m", "g", "", "sed_30m_complete"),
            ("UVA30", "uva_dose_30m_j_m2", "g", " J/m2", None),
            ("UVB30", "uvb_dose_30m_j_m2", "g", " J/m2", None),
            ("Conf", "tan_forecast_confidence_0_100", ".0f", "", None),
        ):
            v = _fmt_opt(row.get(col), fmt, suf)
            if v is not None:
                bits.append(f"{label} {v}{_partial_marker(row, flag)}")
        src = str(row.get("subhour_source") or "")
        if src:
            bits.append("native HRRR" if src.startswith("native_HRRR") else "interpolated hourly")
        tier = str(row.get("spectral_tier") or row.get("spectral_backend") or "")
        if tier:
            bits.append(f"tier {tier}")
        feas = str(row.get("outdoor_block_reason") or row.get("outdoor_flags") or "")
        if feas:
            bits.append(feas)
        uid_scope = site_slug or "sunstack"
        stamp = str(start).replace("-", "").replace(":", "").replace("T", "T")[:15]
        events.append("\r\n".join([
            _ics_fold("BEGIN:VEVENT"),
            _ics_fold(f"UID:sunstack-30m-{uid_scope}-{stamp}@{uid_scope}"),
            _ics_fold(f"DTSTAMP:{now}"),
            _ics_fold(f"SEQUENCE:{sequence}"),
            _ics_fold(f"DTSTART:{_ics_stamp(str(start), tz_name)}"),
            _ics_fold(f"DTEND:{_ics_stamp(end, tz_name)}"),
            _ics_fold(f"SUMMARY:{_ics_text('Sun ' + str(start)[11:16] + ' (' + (bits[0] if bits else 'update') + ')')}"),
            _ics_fold(f"DESCRIPTION:{_ics_text('. '.join(bits))}"),
            _ics_fold("END:VEVENT"),
        ]))
    body = "\r\n".join(events)
    head = ("BEGIN:VCALENDAR\r\nVERSION:2.0\r\nPRODID:-//SunStack//TanScore//EN\r\n"
            "CALSCALE:GREGORIAN\r\nMETHOD:PUBLISH\r\nX-WR-CALNAME:SunStack 30-min doses")
    return head + ("\r\n" + body if body else "") + "\r\nEND:VCALENDAR\r\n"


def _calendar_window(
    row: pd.Series, start_col: str, end_col: str, dose_col: str
) -> tuple[str, str, object] | None:
    start, end = row.get(start_col), row.get(end_col)
    if start is None or end is None or pd.isna(start) or pd.isna(end):
        return None
    start_text, end_text = str(start), str(end)
    if not start_text or not end_text:
        return None
    return start_text, end_text, row.get(dose_col)


def build_calendar_ics(
    daily: pd.DataFrame,
    run_tag: str,
    hourly: pd.DataFrame | None = None,
    site_slug: str | None = None,
    tz_name: str | None = None,
) -> str:
    """Best-window VEVENTs, one per day with a window.

    UIDs are stable per date, so every rerun updates the same events in
    place instead of duplicating them in subscribed calendars. Pass the
    hourly table for per-day UV peaks in the descriptions. Descriptions carry
    Absolute/Overall, window TanDose, daily TanDose/SED, UVA/UVB doses,
    confidence, feasibility, and model tier (never an interpolated spectral
    value presented as native resolution).
    """
    # SEQUENCE:0 — events are immutable per run (audit: run-tag digits
    # overflowed 32-bit SEQUENCE). Recurrence identity lives in UID.
    sequence = 0
    now = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    peaks = daily_uv_peaks(hourly) if hourly is not None else {}
    events = []
    for _, row in daily.iterrows():
        usable = _calendar_window(
            row, "best_usable_30m_start", "best_usable_30m_end",
            "best_usable_30m_dose_j_m2")
        strongest = _calendar_window(
            row, "strongest_30m_start", "strongest_30m_end",
            "strongest_30m_dose_j_m2")
        legacy = _calendar_window(
            row, "best_window_start", "best_window_end",
            "tan_dose_best_window_j_m2")
        usable_dose = _fmt_opt(usable[2]) if usable is not None else None
        strongest_dose = _fmt_opt(strongest[2]) if strongest is not None else None
        if usable is not None and usable_dose is not None:
            start, end = usable[0], usable[1]
            dose = usable_dose
        elif strongest is not None and strongest_dose is not None:
            start, end = strongest[0], strongest[1]
            dose = strongest_dose
        elif legacy is not None:
            start, end = legacy[0], legacy[1]
            dose = _fmt_opt(legacy[2])
        else:
            continue
        date = str(row.get("date", ""))
        parts: list[str] = []
        # F-18: a calendar entry is a glance, not the table. This used to emit up
        # to fourteen lines carrying `J/m2`, an unexpanded `SED`, an unexpanded
        # `E_mel`, and the LEGACY Overall beside the absolute scale. Now: the
        # answer, the scale it sits on, the day totals, and one caveat.
        if usable is not None:
            window = f"{_ics_hhmm(usable[0], tz_name)}-{_ics_hhmm(usable[1], tz_name)}"
            parts.append(
                f"Best usable sun {window} - {usable_dose} J/m² pigment-weighted dose"
                if usable_dose else f"Best usable sun {window}"
            )
        elif strongest is not None:
            window = f"{_ics_hhmm(strongest[0], tz_name)}-{_ics_hhmm(strongest[1], tz_name)}"
            parts.append(
                f"Strongest 30 min {window} - {strongest_dose} J/m² pigment-weighted dose"
                if strongest_dose else f"Strongest 30 min {window}"
            )
        elif legacy is not None:
            window = f"{_ics_hhmm(legacy[0], tz_name)}-{_ics_hhmm(legacy[1], tz_name)}"
            legacy_text = _fmt_opt(legacy[2])
            parts.append(
                f"Best sun {window} - {legacy_text} J/m² pigment-weighted dose"
                if legacy_text else f"Best sun {window}"
            )
        absp = _fmt_opt(row.get("day_absolute_peak_0_100"), ".0f", "/100")
        locp = _fmt_opt(row.get("day_local_peak_0_100"), ".0f", "/100")
        scale = " · ".join(
            text for text in (
                f"Absolute {absp} (worldwide scale)" if absp else "",
                f"Local {locp} (percentile within this location)" if locp else "",
            ) if text
        )
        if scale:
            parts.append(scale)
        # Peak UV is a real calendar datapoint, not table detail: it is the one
        # number a sun-seeker checks before deciding whether the day matters.
        uv = peaks.get(date, {})
        if uv.get("uvi"):
            when = f" at {uv['uvi_time']}" if uv.get("uvi_time") else ""
            parts.append(f"Peak UV {uv['uvi']}{when}")
        else:
            _uv_peak = fnum(row, "peak_uv_index")
            if pd.notna(_uv_peak):
                parts.append(f"Peak UV {_uv_peak:g}")
        day_dose = _fmt_opt(row.get("tan_dose_day_j_m2"), "g", " J/m² pigment-weighted")
        if day_dose:
            parts.append(f"Day total {day_dose}{_partial_marker(row, 'tan_dose_complete')}")
        sed_day = _fmt_opt(row.get("sed_day_total"), "g", "")
        if sed_day:
            parts.append(f"SED {sed_day} (standard erythema dose){_partial_marker(row, 'sed_complete')}")
        if usable is not None and strongest is not None and usable[:2] != strongest[:2]:
            parts.append("strongest window is blocked by outdoor constraints")
        status = str(row.get("day_status") or "").strip()
        if status and status.lower() != "nan":
            parts.append(status)
        parts.append("Times refresh with each SunStack run.")
        desc = ". ".join(parts)
        # F-18: SUMMARY is what a lock screen shows, so it stays one line: the
        # window and the dose that ranks it, with units and no bare abbreviation.
        _peak_uvi = fnum(row, "peak_uv_index")
        summary = f"Best sun {_ics_hhmm(start, tz_name)}-{_ics_hhmm(end, tz_name)}"
        if dose is not None:
            summary += f" - {dose} J/m² pigment-weighted dose"
        elif pd.notna(_peak_uvi):
            summary += f" - peak UV {_peak_uvi:g}"
        uid_scope = site_slug or "sunstack"
        events.append(
            "\r\n".join(
                [
                    _ics_fold("BEGIN:VEVENT"),
                    _ics_fold(f"UID:sunstack-best-{uid_scope}-{date}@{uid_scope}"),
                    _ics_fold(f"DTSTAMP:{now}"),
                    _ics_fold(f"SEQUENCE:{sequence}"),
                    _ics_fold(f"DTSTART:{_ics_stamp(start, tz_name)}"),
                    _ics_fold(f"DTEND:{_ics_stamp(end, tz_name)}"),
                    _ics_fold(f"SUMMARY:{_ics_text(summary)}"),
                    _ics_fold(f"DESCRIPTION:{_ics_text(desc)}"),
                    _ics_fold("END:VEVENT"),
                ]
            )
        )
    body = "\r\n".join(events)
    head = (
        "BEGIN:VCALENDAR\r\nVERSION:2.0\r\nPRODID:-//SunStack//TanScore//EN\r\n"
        "CALSCALE:GREGORIAN\r\nMETHOD:PUBLISH\r\nX-WR-CALNAME:SunStack best sun windows"
    )
    return head + ("\r\n" + body if body else "") + "\r\nEND:VCALENDAR\r\n"


_PERSONAL_MMD_BASES = ("SUNSTACK_EFFECTIVE_DOSE_MEASURED", "SOURCE_SPECTRUM_MEASURED",
                       "OBJECTIVE_ESTIMATE", "COARSE_ESTIMATE")


def parse_personal_mmd(personal_mmd: object,
                        basis: object) -> tuple[float | None, str | None]:
    """Validate dashboard/API personal-MMD inputs. Loud on misuse.

    Returns (mmd_j_m2_or_None, basis_or_None). An MMD without an explicit
    basis is rejected: an unlabeled personal fraction would imply more
    provenance than the user supplied.
    """
    mmd_text = str(personal_mmd or "").strip()
    basis_text = str(basis or "").strip()
    if not mmd_text:
        return None, None
    try:
        value = float(mmd_text)
    except (TypeError, ValueError):
        raise ValueError(
            f"personal_mmd must be a number in melanogenic-effective J/m^2, "
            f"got {mmd_text!r}") from None
    if not np.isfinite(value) or value <= 0:
        raise ValueError(
            f"personal_mmd must be a positive finite dose, got {mmd_text!r}")
    if basis_text not in _PERSONAL_MMD_BASES:
        raise ValueError(
            f"personal_mmd_basis must be one of {list(_PERSONAL_MMD_BASES)} "
            f"when personal_mmd is given, got {basis_text!r}")
    return value, basis_text


HTML = r"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Sunlight hours — SunStack</title>
<link rel="icon" href="data:,">
<style>
:root{--paper:#eef1ee;--surface:#ffffff;--surface2:#f7f9f7;--head:#e4e9e4;--headtxt:#4e5754;--track:#dfe4df;--ink:#151a18;--muted:#5b6461;--line:#d2d8d3;--sun:#a85500;--sunwash:#fdeed0;--ok:#2c7a45;--mid:#8a6200;--low:#b3450f;--poor:#646c69;--uv1:#1a9641;--uv2:#ffd500;--uv3:#f57c00;--uv4:#d7191c;--uv5:#7b2fbe;--q1:#151a18;--q2:#3f4a45;--q3:#6b736e;--q4:#8b938e}
/* Hazard (UV index) and quality (0-100 score) must not share a hue. The old
   build painted --mid (#8a6200, "mediocre score") and the UVI 3-5 dot with the
   same hex. UV now uses the conventional five bands; score is a neutral
   lightness ramp so "quality" reads as magnitude, not as a safety colour. */
.uvdot{display:inline-block;width:9px;height:9px;border-radius:50%;margin-right:6px;vertical-align:baseline;outline:1px solid rgba(21,26,24,.35);outline-offset:0}
button:hover,a.btn:hover,select:hover,input:hover{filter:brightness(.94)}
.daycell:hover{border-color:var(--ink)}
details>summary:hover{color:var(--ink)}
.data-stale #hero,.data-stale #strip,.data-stale #doses,.data-stale #charts{opacity:.5}
.data-stale #msg.error{font-weight:600}
*{box-sizing:border-box}body{margin:0;background:var(--paper);color:var(--ink);font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Helvetica,Arial,sans-serif;-webkit-tap-highlight-color:transparent}
::selection{background:var(--sunwash);color:var(--ink)}html{scrollbar-color:var(--line) transparent}
.wrap{max-width:1120px;margin:0 auto;padding:28px 22px 60px;text-align:left}
.top{display:flex;gap:16px;align-items:flex-end;justify-content:space-between;flex-wrap:wrap;border-bottom:2px solid var(--ink);padding-bottom:16px}
h1{font-family:Georgia,"Times New Roman",serif;font-weight:600;font-size:34px;margin:0}
.sub{color:var(--muted);font-size:13px;margin-top:4px}
.controls{display:flex;gap:8px;align-items:center;flex-wrap:wrap;font-size:13px;color:var(--muted)}
select,input,button{font:inherit;background:var(--surface);color:var(--ink);border:1px solid var(--line);border-radius:8px;padding:8px 10px}
.controls a.btn{font:inherit;background:var(--surface);color:var(--ink);border:1px solid var(--line);border-radius:8px;padding:8px 10px;text-decoration:none;font-weight:600}
button{cursor:pointer;font-weight:600}button:hover{border-color:var(--sun)}
button.primary{background:var(--sun);border-color:var(--sun);color:#fff}
.hero{font-family:Georgia,serif;font-size:26px;line-height:1.35;margin:26px 0 4px;max-width:34em}
.hero b{font-weight:700}
.legend{color:var(--muted);font-size:13px;margin:0 0 6px;max-width:70em}
.strip{display:flex;gap:10px;overflow-x:auto;padding:14px 2px;margin:8px 0 4px}
.daycell{min-width:118px;text-align:left;background:var(--surface);border:1px solid var(--line);border-radius:12px;padding:10px 12px;cursor:pointer}
.daycell .dow{font-weight:700;font-size:14px}
.daycell .dt{color:var(--muted);font-size:12px}
.daycell .pk{font-family:Georgia,serif;font-size:24px;margin-top:6px}
.daycell .uv{font-size:12px;color:var(--muted)}
.daycell .bar{height:5px;border-radius:3px;margin-top:8px;background:var(--track)}
.daycell .bar i{display:block;height:100%;border-radius:3px}
.daycell[aria-selected="true"]{border:2px solid var(--sun);background:var(--sunwash)}
.daydetail{margin-top:22px}
.daydetail h2{font-family:Georgia,serif;font-weight:600;font-size:24px;margin:0 0 2px}
.daydetail h2.sec{font-family:inherit;font-size:14px;font-weight:600;color:var(--muted);margin:22px 0 8px;letter-spacing:.01em}
.bestline{font-size:15px;margin:0 0 14px}
.bestline b{color:var(--sun)}
h3{font-size:14px;margin:22px 0 8px;color:var(--muted);font-weight:600}
.tablewrap{overflow:auto;border:1px solid var(--line);border-radius:12px;background:var(--surface)}
table{border-collapse:collapse;width:100%;font-size:13px;font-variant-numeric:tabular-nums}
th,td{padding:8px 10px;border-bottom:1px solid var(--line);text-align:right;white-space:nowrap}
th:first-child,td:first-child{text-align:left;position:sticky;left:0;background:var(--surface)}
thead th{background:var(--head);color:var(--headtxt);font-weight:600}
tr.inwindow td{background:var(--sunwash)}
tr.inwindow td:first-child{font-weight:700}
.uvdot{display:inline-block;width:9px;height:9px;border-radius:50%;margin-right:6px;vertical-align:baseline}
.note{color:var(--muted);font-size:12px}
.status{padding:10px 12px;border-radius:9px;margin:12px 0;display:none;font-size:14px}
.status.show{display:block}.error{background:#f7dfe0;color:#7c2327}.info{background:#eef0e4;color:#4c5540}
details.debug{margin-top:26px;color:var(--muted);font-size:12px}
details.debug pre{background:var(--head);padding:12px;border-radius:8px;overflow:auto}
:focus-visible{outline:2px solid var(--sun);outline-offset:2px}
body.show-nerd .nerd{display:table-cell}th.nerd,td.nerd{display:none}
tr.inclass td{background:#ece4f4}
tr.inclass td:first-child{font-weight:700}
body.hide-class tr.inclass td{background:transparent}
.hide-class .daycell .cls{display:none}
/* Class and window are independent facts and must both show on a row that is
   both. The old builder used a ternary, so `inwindow` shadowed `inclass` and
   the in-class marker was unreachable for exactly the rows the legend told
   users to plan around. */
tr.inclass td:first-child{border-left:3px solid var(--uv5);padding-left:6px}
body.hide-class tr.inclass td:first-child{border-left:none}
.daycell .cls{font-size:11px;color:#5b4a8a;font-weight:700}
.classrow{display:flex;gap:8px;align-items:center;flex-wrap:wrap;font-size:12px;color:var(--muted);margin:8px 0 0}
.note.cls{color:#5b4a8a}
.chartnav{display:flex;gap:6px;align-items:center;margin:0 0 6px;font-size:12px;color:var(--muted)}
.daycell .win{font-size:12px;color:var(--sun);font-weight:700}
.daycell .txt{font-size:11px;color:var(--muted);font-weight:400}
.gloss{font-size:12px;color:var(--muted);margin:6px 0 0}
.gloss b{color:var(--ink)}
.sunfig{display:flex;gap:18px;align-items:flex-start;flex-wrap:wrap;background:var(--surface);border:1px solid var(--line);border-radius:12px;padding:14px 16px;margin:0 0 14px}
.sunfig svg{flex:0 1 auto;max-width:100%;height:auto;background:var(--surface2);border-radius:8px}
.sunfig .cap{font-size:13px;max-width:34em}
.sunfig .cap b{color:var(--sun)}
details>summary{padding:5px 0;cursor:pointer}
details>summary:focus-visible{outline:2px solid var(--sun);outline-offset:2px}
label>input[type=checkbox]{width:16px;height:16px;vertical-align:-3px}
.sunfig select{margin-top:8px}
@media(max-width:640px){h1{font-size:26px}.hero{font-size:21px}.wrap{padding:18px 12px 50px}}
</style></head><body><div class="wrap">
<div class="top"><div><h1>Sunlight hours</h1><div class="sub" id="runline">Loading forecast…</div></div>
<div class="controls settings" role="group" aria-label="Display settings"><label>Location <select id="locsel"><option value="">Loading…</option></select></label><label>Skin <select id="skin"><option value="">None</option><option value="1">I</option><option value="2">II</option><option value="3">III</option><option value="4">IV</option><option value="5">V</option><option value="6">VI</option></select></label><details class="mmd" style="display:inline-block"><summary title="Only if you have a measured or estimated personal MMD">I have my MMD</summary><span id="mmdwrap"><label>My MMD <input id="mmd" type="number" min="1" step="1" placeholder="J/m²" title="Measured/estimated personal MMD in melanogenic-effective J/m² — leave blank unless you know yours" style="width:80px"></label><label>basis <select id="mmdbasis" title="How much to trust your MMD number. It changes how the dose is expressed relative to your own threshold; it never changes the environmental dose."><option value="">—</option><option value="SUNSTACK_EFFECTIVE_DOSE_MEASURED">Measured with SunStack's dose basis</option><option value="SOURCE_SPECTRUM_MEASURED">Measured from the source spectrum</option><option value="OBJECTIVE_ESTIMATE">Estimate from another app</option><option value="COARSE_ESTIMATE">Rough guess</option></select></label></span></details>
<label>Min °F <input id="mintemp" type="number" min="32" max="80" step="1" value="50" style="width:64px"></label><label>Surface <select id="surface" title="Ground around you: changes reflected skin-plane exposure only, never horizontal environment"><option value="unknown">Unknown</option><option value="grass_summer">Summer grass</option><option value="grass_winter">Winter grass</option><option value="dry_beach_sand">Dry sand</option><option value="wet_beach_sand">Wet sand</option><option value="light_concrete">Light concrete</option><option value="aged_concrete">Aged concrete</option><option value="fresh_asphalt">Fresh asphalt</option><option value="aged_asphalt">Aged asphalt</option><option value="weathered_wood_deck">Wood deck</option><option value="open_water">Open water</option><option value="sea_foam">Sea foam</option><option value="fresh_snow">Fresh snow</option><option value="aged_snow">Aged snow</option></select></label><label>Tilt <input id="skintilt" type="number" min="0" max="180" step="1" value="0" style="width:64px"></label><label>Azimuth <input id="skinaz" type="number" min="0" max="360" step="1" value="180" style="width:64px"></label><span class="note" id="invariant">Surface, tilt and skin type change your <b>skin-plane</b> exposure and your risk context. They never change the headline environmental dose above, which is this location's horizontal reference. With tilt 0 over an unknown surface the plane and the reference are the same number, so nothing moves — that is the geometry, not a failure.</span>
<button onclick="loadData()">Apply</button></div><div class="controls actions" role="group" aria-label="Actions"><button class="primary livereq" onclick="refreshData()">Refresh forecast</button><a id="cal" class="btn" href="/api/calendar.ics" title="Subscribe to the best-window calendar">Calendar</a><button onclick="exportVisibleCsv()" title="All days in this run, regardless of the day selected below">Download all (CSV)</button><button onclick="exportDayCsv()" title="Only the day selected below, 30-minute rows with dose and confidence">Download this day (CSV)</button></div></div>
<div id="msg" class="status"></div>
<p class="hero" id="hero">Finding the best light…</p>
<p class="legend">Ranking is maximum expected 30-minute delayed-pigmentation dose (fixed-duration-dose-v2). Overall is a LEGACY composite (deprecated product heuristic); UV∘ is headline UVI fusion, while TanDose comes from the UVA/UVB model.</p>
<p class="gloss" id="skinctx" hidden></p>
<div class="strip" id="strip" role="listbox" aria-label="Days" aria-orientation="horizontal"></div>
<div class="daydetail" id="doses"><h2 class="sec">Doses — intensity vs accumulated exposure</h2><div id="doserow" class="note">Loading doses…</div><details class="debug" id="advphoto"><summary>Advanced / Photobiology</summary><div id="advrow" class="note"></div><div id="provenance" class="note"></div></details></div>
<div class="daydetail" id="charts"><h2 class="sec">Day charts (separate panels — SED is exposure, never “good”)</h2><div class="chartnav" role="group" aria-label="Chart panels"><button id="chartPrev" type="button" aria-label="Previous chart">‹</button><button id="chartNext" type="button" aria-label="Next chart">›</button><span id="chartName" aria-live="polite"></span></div><div id="charttip" class="note" aria-live="polite"></div><canvas id="chartScore" role="img" aria-label="TanScore 0 to 100 over the day, instantaneous intensity. The shaded band is the recommended window. The 30-minute table below lists the same day's dose and confidence." title="TanScore 0–100 — instantaneous intensity, best window shaded" width="640" height="150" style="width:100%;border:1px solid var(--line);border-radius:8px;background:var(--surface)"></canvas><canvas id="chartDose" role="img" aria-label="Cumulative pigment-weighted dose through the day. Higher is more accumulated exposure, not a better outcome. The 30-minute table below lists the per-interval dose." title="Cumulative TanDose — exposure odometer, higher is more dose not better" width="640" height="120" style="width:100%;border:1px solid var(--line);border-radius:8px;background:var(--surface);margin-top:8px"></canvas><canvas id="chartSed" role="img" aria-label="Cumulative sunburn-weighted exposure (SED) through the day. This is a burn load, never a good outcome." title="Cumulative SED — sunburn load, never good" width="640" height="120" style="width:100%;border:1px solid var(--line);border-radius:8px;background:var(--surface);margin-top:8px"></canvas><div class="note">TanScore fixed 0–100 (top, instantaneous intensity); cumulative TanDose melanogenic J/m² (middle, exposure odometer); cumulative SED (bottom, sunburn-weighted exposure, never “good”). Shaded band = best window. Pigment-darkening lives in tables under Advanced, never merged into TanScore.</div></div>
<div class="sunfig" id="sunfigwrap"><svg id="sunfig" width="300" height="190" viewBox="0 0 300 190" role="img" aria-label="Sun position and recline figure"></svg><div class="cap"><div id="suncap">Pick a time to see the sun position and posture.</div><label>Time <select id="sunsel"></select></label><div class="note">Legs stay flat, parallel to the ground — only the torso lifts. Click any table row to inspect that time. Guidance is geometry context, not a score. Headline TanScore/TanDose is the horizontal environmental reference; facing the sun is not modeled.</div></div></div><details class="glossbox"><summary>Column glossary</summary><p class="gloss"><b>UV∘</b> consensus UVI (headline) · <b>OM/CAMS/EPA</b> per-source UVI · <b>Clear</b> cloud-free UVI · <b>ΔUV</b> max source spread (flag ≥1.0, strong ≥2.0) · <b>UVA/UVB</b> predicted W/m² · <b>Temp</b> °F + feels-like · <b>Wind</b> mph + gust · <b>Cloud</b> % · <b>Rain</b> % (≥40 wet) · <b>DNI</b> direct beam W/m² · <b>Overall</b> LEGACY composite 0–100 (deprecated product heuristic) · <b>Abs</b> worldwide strength · <b>Local</b> location percentile · <b>Atm</b> geometry-conditioned transmission percentile · <b>Conf</b> confidence (cut when sources disagree).</p></details><div class="daydetail" id="detail"></div>
<details class="debug"><summary>Run metadata (JSON)</summary><div id="debugsummary" class="note"></div><details><summary>Full JSON</summary><pre id="debugtext">Loading…</pre></details></details>
</div><script>
function dayLo(list,key){key=key||'temperature_2m';let m=null;for(const x of list||[]){const v=+x[key];if(!Number.isNaN(v)&&(m==null||v<m))m=v;}return m;}function dayHi(list,key){key=key||'temperature_2m';let m=null;for(const x of list||[]){const v=+x[key];if(!Number.isNaN(v)&&(m==null||v>m))m=v;}return m;}function peakOf(list,key){let m=null;for(const x of list||[]){const v=+x[key];if(!Number.isNaN(v)&&(m==null||v>m))m=v;}return m;}
function fmtTime(s){if(!s)return 'unknown time';const d=new Date(s);return Number.isNaN(d)?s:d.toLocaleString([],{weekday:'short',month:'short',day:'numeric',hour:'numeric',minute:'2-digit'});}
const f0=n=>n==null||Number.isNaN(+n)?'—':Math.round(+n);
const f1=n=>n==null||Number.isNaN(+n)?'—':(+n).toFixed(1);
const f2=n=>n==null||Number.isNaN(+n)?'—':(+n).toFixed(2);
const esc=s=>String(s==null?'':s).replace(/[&<>"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));
const uvColor=v=>v==null||Number.isNaN(+v)?'var(--line)':+v<3?'var(--uv1)':+v<6?'var(--uv2)':+v<8?'var(--uv3)':+v<11?'var(--uv4)':'var(--uv5)';
const scoreColor=v=>+v>=65?'var(--q1)':+v>=40?'var(--q2)':+v>=20?'var(--q3)':'var(--q4)';
function hhmm(s){const m=/T(\d\d):(\d\d)/.exec(s||'');if(!m)return '—';let h=+m[1];const ap=h<12?'AM':'PM';h=h%12||12;return m[2]==='00'?`${h} ${ap}`:`${h}:${m[2]} ${ap}`;}
function dayName(ds){const d=new Date(ds+'T12:00:00');return Number.isNaN(d)?ds:d.toLocaleDateString([],{weekday:'long',month:'long',day:'numeric'});}
function shortDay(ds){const d=new Date(ds+'T12:00:00');return Number.isNaN(d)?ds:d.toLocaleDateString([],{weekday:'short'})+', '+d.toLocaleDateString([],{month:'numeric',day:'numeric'});}
function winStr(a,b){return a?`${hhmm(a)} – ${b?hhmm(b):'…'}`:'—';}
let DATA=null,SEL=null,LOC="";
async function loadLocs(){try{let j=null;for(const u of ['./locations.json','/api/locations']){try{const r=await fetch(u);if(r.ok){j=await r.json();break;}}catch(e){}}const dd=document.getElementById("locsel");if(!dd||!j)return;dd.innerHTML=(j.locations||[]).map(l=>`<option value="${esc(l.slug)}"${(l.current||(!l.url&&l.default))?" selected":""}${l.url?` data-url="${esc(l.url)}"`:''}>${esc(l.name)}</option>`).join("");LOC=dd.value;dd.addEventListener("change",()=>{const o=dd.selectedOptions[0];if(o&&o.dataset.url){location.href=o.dataset.url;return;}LOC=dd.value;SEL=null;syncUrl(true);loadData();});const want=window.__sunstackWantedLocation;if(want&&[...dd.options].some(o=>o.value===want))dd.value=want;LOC=dd.value;const wd=window.__sunstackWantedDate;if(wd)SEL=wd;}catch(e){}}
function restorePlane(){try{for(const [id,key] of [['surface','sunstack_surface'],['skintilt','sunstack_skin_tilt_deg'],['skinaz','sunstack_skin_azimuth_deg']]){const el=document.getElementById(id),v=localStorage.getItem(key);if(el&&v!==null)el.value=v;}const ct=document.getElementById('classText');if(ct){const v=localStorage.getItem('sunstack_classes');if(v!==null)ct.value=v;}const loc=localStorage.getItem('sunstack_location');if(loc)window.__sunstackWantedLocation=loc;const p=new URLSearchParams(location.search);const ul=p.get('location');if(ul)window.__sunstackWantedLocation=ul;window.__sunstackWantedDate=p.get('date')||'';}catch(e){}}
function urlState(){const p=new URLSearchParams(location.search);return {location:p.get('location')||'',date:p.get('date')||''};}
function syncUrl(push){try{const p=new URLSearchParams(location.search);p.delete('v');if(LOC)p.set('location',LOC);else p.delete('location');if(SEL)p.set('date',SEL);else p.delete('date');const q=p.toString();const u=location.pathname+(q?('?'+q):'');const st={location:LOC,date:SEL};if(push)history.pushState(st,'',u);else history.replaceState(st,'',u);}catch(e){}}
async function init(){restorePlane();await loadLocs();await loadData();syncUrl(false);if(!window.__sunstackPop){window.__sunstackPop=true;window.addEventListener('popstate',()=>{const u=urlState();const dd=document.getElementById('locsel');if(u.location&&dd&&[...dd.options].some(o=>o.value===u.location))dd.value=u.location;LOC=(dd&&dd.value)||LOC;SEL=u.date||null;loadData();});}}
let _gen=0;
function classesJson(){const r=classRanges();return r.length?JSON.stringify(r):'';}
function numOrNull(id){const el=document.getElementById(id);const v=el?String(el.value||'').trim():'';return v===''?null:v;}
function detailText(j,status){const d=j&&j.detail;if(typeof d==='string')return d;if(Array.isArray(d)&&d.length){const f=d[0]||{};const loc=(f.loc||[]).slice(-1)[0];return (loc?loc+': ':'')+(f.msg||'invalid value');}if(d&&typeof d==='object')return String(d.msg||JSON.stringify(d));return 'request failed ('+status+')';}
function markStale(msg){const s=(DATA&&DATA.summary)||{};const when=s.created_at?(' Still showing the '+fmtTime(s.created_at)+' run.'):'';show('Could not load that view: '+msg+'.'+when,'error');document.body.classList.add('data-stale');}
function apiUrl(qs){return '/api/data?'+qs;}
function calUrl(qs){return 'webcal://'+location.host+'/api/calendar.ics?'+qs;}
function checkNumericFields(){const fields=[['mintemp','Min °F'],['skintilt','Skin tilt'],['skinaz','Skin azimuth'],['mmd','Personal MMD']];const bad=[];fields.forEach(function(pair){const el=document.getElementById(pair[0]);if(!el)return;const raw=String(el.value||'').trim();const invalid=raw!==''&&Number.isNaN(Number(raw));el.setAttribute('aria-invalid',invalid?'true':'false');if(invalid)bad.push(pair[1]);});return bad;}
async function loadData(){const gen=++_gen;const applyBtn=document.querySelector('.controls.actions button:not(.livereq)');if(applyBtn)applyBtn.disabled=true;show('Loading…','info');try{const _bad=checkNumericFields();if(_bad.length){show(_bad.join(', ')+': enter a number, or leave blank.','error');return;}const s=document.getElementById('skin').value,p=document.getElementById('mmd').value,b=document.getElementById('mmdbasis').value,sf=(document.getElementById('surface')||{}).value||'unknown',t=numOrNull('skintilt'),a=numOrNull('skinaz'),mt=numOrNull('mintemp');const qp=new URLSearchParams();qp.set('location',LOC||'');if(s)qp.set('skin_type',s);if(mt!==null)qp.set('min_temp',mt);if(p)qp.set('personal_mmd',p);if(b)qp.set('personal_mmd_basis',b);qp.set('surface',sf);if(t!==null)qp.set('skin_tilt_deg',t);if(a!==null)qp.set('skin_azimuth_deg',a);const cls=classesJson();if(cls)qp.set('classes',cls);try{localStorage.setItem('sunstack_surface',sf);if(t!==null)localStorage.setItem('sunstack_skin_tilt_deg',t);if(a!==null)localStorage.setItem('sunstack_skin_azimuth_deg',a);localStorage.setItem('sunstack_location',LOC||'');}catch(e){}const r=await fetch(apiUrl(qp.toString()));const j=await r.json();if(gen!==_gen)return;if(!r.ok)throw new Error(detailText(j,r.status));DATA=j;document.body.classList.remove('data-stale');hide();render();}catch(e){if(gen!==_gen)return;markStale(e.message);}finally{if(gen===_gen&&applyBtn)applyBtn.disabled=false;}}
async function refreshData(){const _b=document.querySelector('.livereq');if(_b&&_b.disabled)return;if(_b)_b.disabled=true;show('Fetching live Open-Meteo and CAMS, rebuilding scores — this takes minutes.','info');try{const s=document.getElementById('skin').value,p=document.getElementById('mmd').value,b=document.getElementById('mmdbasis').value,sf=(document.getElementById('surface')||{}).value||'unknown',t=numOrNull('skintilt'),a=numOrNull('skinaz'),mt=numOrNull('mintemp');const qp=new URLSearchParams();qp.set('location',LOC||'');if(s)qp.set('skin_type',s);if(mt!==null)qp.set('min_temp',mt);if(p)qp.set('personal_mmd',p);if(b)qp.set('personal_mmd_basis',b);qp.set('surface',sf);if(t!==null)qp.set('skin_tilt_deg',t);if(a!==null)qp.set('skin_azimuth_deg',a);const cls=classesJson();if(cls)qp.set('classes',cls);const r=await fetch('/api/refresh?'+qp.toString(),{method:'POST'});const j=await r.json();if(!r.ok)throw new Error(detailText(j,r.status));show('Live run complete.','info');await loadData();if(_b)_b.disabled=false;}catch(e){if(_b)_b.disabled=false;show('Live refresh failed: '+e.message,'error');}}
function exportDayCsv(){if(!DATA||!DATA.daily||!DATA.daily.length){show('No forecast data yet.','error');return;}const q=v=>(/[,"\n]/.test(String(v??''))?'"'+String(v??'').replace(/"/g,'""')+'"':String(v??''));const dl=(name,rows)=>{const csv=rows.map(r=>r.map(q).join(',')).join('\n');const b=new Blob([csv],{type:'text/csv'});const a=document.createElement('a');a.href=URL.createObjectURL(b);a.download=name;document.body.appendChild(a);a.click();setTimeout(()=>{URL.revokeObjectURL(a.href);a.remove();},500);};const head=['time','uv_index','uvi_consensus','predicted_uva_wm2','predicted_uvb_wm2','tan_dose_30m_j_m2','tan_dose_30m_complete','tan_forecast_confidence_0_100','temperature_2m','overall_tan_opportunity_0_100','local_tan_score_0_100','subhour_source','outdoor_block_reason'];const rows=rowsFor(DATA.half_hour,SEL);dl((LOC||'site')+'-'+SEL+'-sunstack-day-30min.csv',[head].concat(rows.map(x=>head.map(k=>x[k]))));show('Downloaded '+rows.length+' 30-minute rows for '+SEL+' (the ranking unit, with dose and confidence).','info');}
function exportVisibleCsv(){if(!DATA||!DATA.daily||!DATA.daily.length){show('No forecast data yet.','error');return;}const q=v=>(/[,"\n]/.test(String(v??''))?'"'+String(v??'').replace(/"/g,'""')+'"':String(v??''));const dl=(name,rows)=>{const csv=rows.map(r=>r.map(q).join(',')).join('\n');const b=new Blob([csv],{type:'text/csv'});const a=document.createElement('a');a.href=URL.createObjectURL(b);a.download=name;document.body.appendChild(a);a.click();setTimeout(()=>{URL.revokeObjectURL(a.href);a.remove();},500);};const hours=DATA.hourly||[],half=DATA.half_hour||[];const hHead=['time','uv_index','uv_index_clear_sky','predicted_uva_wm2','predicted_uvb_wm2','melanogenic_effective_irradiance_wm2','erythemal_irradiance_wm2','pigment_darkening_effective_irradiance','temperature_2m','apparent_temperature','wind_speed_10m','wind_gusts_10m','cloud_cover','precipitation_probability','direct_normal_irradiance_instant','overall_tan_opportunity_0_100','tan_score_absolute_0_100','legacy_absolute_tan_score_55_30_15','local_tan_score_0_100','atmospheric_quality_percentile_0_100','tan_forecast_confidence_0_100','tan_dose_1h_j_m2','tan_dose_1h_complete','tan_dose_1h_coverage_fraction','sed_1h','sed_1h_complete','sed_1h_coverage_fraction','uva_dose_1h_j_m2','uvb_dose_1h_j_m2','pigment_darkening_dose_1h_j_m2','uvi_openmeteo','uvi_cams','uvi_epa','uvi_consensus','uvi_consensus_sources','uvi_source_spread','uvi_difference_percent','spectral_tier','tan_score_model_version','solar_elevation_deg','sun_compass','outdoor_block_reason'];dl((LOC||'site')+'-'+'sunstack-all-hourly.csv',[hHead].concat(hours.map(x=>hHead.map(k=>x[k]))));const qHead=['time','uv_index','uvi_consensus','uvi_epa','uvi_cams','uvi_source_spread','predicted_uva_wm2','melanogenic_effective_irradiance_wm2','tan_dose_30m_j_m2','tan_dose_30m_complete','tan_dose_30m_coverage_fraction','sed_30m','sed_30m_complete','sed_30m_coverage_fraction','pigment_darkening_dose_30m_j_m2','overall_tan_opportunity_0_100','local_tan_score_0_100','subhour_source','spectral_tier'];dl((LOC||'site')+'-'+'sunstack-all-30min.csv',[qHead].concat(half.map(x=>qHead.map(k=>x[k]))));const dall=DATA.daily;if(dall.length){const dHead=['date','day_status','day_overall_peak_0_100','peak_uv_index','peak_temperature_f','day_low_temperature_f','day_high_temperature_f','day_low_feels_like_f','day_high_feels_like_f','day_peak_wind_mph','day_peak_gust_mph','day_absolute_peak_0_100','day_local_peak_0_100','best_window_start','best_window_end','best_hour_start','best_hour_score_0_100','tan_dose_best_window_j_m2','tan_dose_best_window_complete','tan_dose_best_window_coverage_fraction','sed_best_window','sed_best_window_complete','sed_best_window_coverage_fraction','tan_dose_day_j_m2','sed_day_total','uva_dose_day_j_m2','uvb_dose_day_j_m2','blocked_half_hours'];dl((LOC||'site')+'-'+'sunstack-all-days.csv',[dHead].concat(dall.map(d=>dHead.map(k=>d[k]))));}show(`Downloaded all ${dall.length} days (${hours.length} hourly + ${half.length} 30-min rows) for ${esc(LOC||'this site')}.`,'info');}
function sortTableBy(th){const table=th.closest('table');if(!table)return;const tbody=table.querySelector('tbody');if(!tbody)return;const idx=Array.prototype.indexOf.call(th.parentNode.children,th);const rows=Array.prototype.slice.call(tbody.querySelectorAll('tr'));const cur=th.getAttribute('aria-sort');const dir=(cur==='ascending')?'descending':'ascending';const val=r=>{const td=r.children[idx];return td?td.textContent.trim():'';};const num=s=>{const n=parseFloat(String(s).replace(/[^0-9.eE+-]/g,''));return Number.isFinite(n)?n:null;};rows.sort((a,b)=>{const x=val(a),y=val(b),nx=num(x),ny=num(y);const c=(nx!==null&&ny!==null)?(nx-ny):String(x).localeCompare(String(y));return dir==='ascending'?c:-c;});rows.forEach(r=>tbody.appendChild(r));Array.prototype.forEach.call(table.querySelectorAll('th'),o=>o.removeAttribute('aria-sort'));th.setAttribute('aria-sort',dir);}
function show(t,c){const m=document.getElementById('msg');m.textContent=t;m.className='status show '+c;}function hide(){document.getElementById('msg').className='status';}
function renderDoses(){const d=DATA.daily.find(x=>x.date===SEL);const el=document.getElementById('doserow');if(!el||!d){return;}const pc=v=>v===false?' (partial)':'';const half=rowsFor(DATA.half_hour,SEL);const myFVals=half.map(x=>x.personal_mmd_fraction).filter(v=>v!==null&&v!==undefined&&v!==''&&Number.isFinite(+v)).map(Number);const myBest=myFVals.length?Math.max.apply(null,myFVals):null;const myBasis=(half.map(x=>x.personalization_basis).find(v=>v&&v!=='not personalized'))||'';let mmdBit='';{const _mmdEl=document.getElementById('mmd'),_basisEl=document.getElementById('mmdbasis');const _mmd=_mmdEl&&_mmdEl.value!==''&&Number.isFinite(+_mmdEl.value)&&+_mmdEl.value>0?+_mmdEl.value:NaN;if(Number.isFinite(_mmd)){const _dose=+d.best_30m_tan_dose_j_m2,_day=+d.tan_dose_day_j_m2;const _b=_basisEl?_basisEl.value:'';mmdBit=' &nbsp;|&nbsp; Your MMD: <b>'+(_dose/_mmd).toFixed(2)+'×</b> (30-min, client-side'+(_b?' · '+esc(_b):'')+')'+(Number.isFinite(_day)?' · day: <b>'+(_day/_mmd).toFixed(2)+'×</b>':'');}else if(myBest!=null&&Number.isFinite(+myBest)&&+myBest>0){const peakDose=+d.best_30m_tan_dose_j_m2,dayDose=+d.tan_dose_day_j_m2;const mmd=Number.isFinite(peakDose)?peakDose/(+myBest):NaN;const dayRatio=(Number.isFinite(dayDose)&&Number.isFinite(mmd)&&mmd>0)?dayDose/mmd:NaN;mmdBit=' &nbsp;|&nbsp; Peak 30-min MMD fraction: <b>'+(+myBest).toFixed(2)+'×</b>'+(myBasis?' ('+esc(myBasis)+')':'')+(Number.isFinite(dayRatio)?' · Daily TanDose / MMD: <b>'+dayRatio.toFixed(2)+'×</b>':'');}}el.innerHTML=`TanDose peak 30 min <b>${f1(d.best_30m_tan_dose_j_m2)} J/m² mel</b> (${d.best_30m_start?hhmm(d.best_30m_start):'—'}) · best hour <b>${f1(d.best_hour_tan_dose_j_m2)} J/m²</b> (${d.best_hour_start?hhmm(d.best_hour_start):'—'})${pc(d.best_hour_tan_dose_complete)} · best window <b>${f1(d.tan_dose_best_window_j_m2)} J/m²</b>${pc(d.tan_dose_best_window_complete)} · today <b>${f1(d.tan_dose_day_j_m2)} J/m²</b> (<span title="Equivalent minutes at the fixed global-reference melanogenic irradiance. Not safe minutes, minutes-until-tan, minutes-until-burn, or exposure advice.">Normalized reference exposure: ${(d.tan_dose_day_reference_minutes/60).toFixed(1)} ref-hours (model normalization, not a recommended exposure duration)</span>)${pc(d.tan_dose_complete)} &nbsp;|&nbsp; SED peak 30m ${f2(d.best_30m_sed)} · window ${f2(d.sed_best_window)}${pc(d.sed_best_window_complete)} · today ${f2(d.sed_day_total)}${pc(d.sed_complete)}${mmdBit}`;const adv=document.getElementById('advrow');if(adv){const pkIpVals=half.map(x=>x.pigment_darkening_dose_30m_j_m2).filter(v=>v!==null&&v!==undefined&&v!==''&&Number.isFinite(+v)).map(Number);const pkIp=pkIpVals.length?Math.max.apply(null,pkIpVals):null;const h0=(DATA.hourly||[])[0]||{},sm=DATA.summary||{};const specTier=h0.spectral_tier||sm.photobiology_action_spectrum_tier||'—',specBack=h0.spectral_backend||sm.spectral_backend||'—';const specName=sm.action_spectrum_name||h0.action_spectrum_name||'—';const specSum=sm.action_spectrum_sha256||h0.action_spectrum_sha256||'';const disag=h0.uvi_difference_percent;adv.innerHTML=`UVA day ${f1(d.uva_dose_day_j_m2)} J/m² · UVB day ${f2(d.uvb_dose_day_j_m2)} J/m² &nbsp;|&nbsp; Visible-Darkening Potential (peak 30m) ${f1(pkIp)} J/m² existing-pigment (not new melanin) &nbsp;|&nbsp; spectral tier ${esc(specTier)} (${esc(specBack)}) · action spectrum ${esc(specName)}${specSum?` <span title="${esc(specSum)}">checksum ✓</span>`:''} · global ref ${esc(sm.global_reference_version||'—')}${sm.global_reference_e_mel_wm2!=null?` (${sm.global_reference_e_mel_wm2} W/m²)`:''} · UVI disagreement ${disag==null||Number.isNaN(+disag)?'—':f1(disag)+'%'} (moves confidence, not physics)`;}const pv=document.getElementById('provenance');if(pv){const s=DATA.summary||{};const _rh=rowsFor(DATA.hourly,SEL);const _r0=_rh.length?_rh[Math.floor(_rh.length/2)]:((DATA.hourly||[])[0]||{});pv.textContent=`Model ${s.tan_score_model_version||'legacy-55-30-15 (pre-v4 data)'} · action spectrum tier ${s.photobiology_action_spectrum_tier||_r0.photobiology_action_spectrum_tier||'pre-v4 legacy'} · global ref ${s.global_reference_version||'pre-v4 provisional'} (${s.global_reference_e_mel_wm2!=null?s.global_reference_e_mel_wm2+' W/m²':'n/a'}) · CAMS ${s.cams_cycle||'?'} · UVI agree ${f1(_r0.uvi_difference_percent)}% · calib ${_r0.tan_calibration_tier||s.calibration_tier||'?'} · UVA model error: 0.33 W/m² on same-domain data, ~5.8 on live NWP — a train/serve gap, so treat the UVA channel as the least-validated number here.`;}}
const renderDosesBase=renderDoses;
renderDoses=function(){renderDosesBase();if(window.__staticSurface){showSurface();return;}const pv=document.getElementById('provenance');if(!pv)return;const summary=DATA.summary||{},hours=rowsFor(DATA.hourly,SEL),row=hours[0]||((DATA.hourly||[])[0]||{}),surface=document.getElementById('surface'),surfaceName=row.surface_display_name||(surface&&surface.selectedOptions[0]?surface.selectedOptions[0].textContent:'Unknown surface'),proxy=row.surface_uva_reflectance??row.surface_uvb_reflectance,reflected=row.skin_plane_ground_reflected_delayed_pigmentation_wm2,tilt=(document.getElementById('skintilt')||{}).value||'0',azimuth=(document.getElementById('skinaz')||{}).value||'180';const context=`Surface ${surfaceName} · proxy ${Number.isFinite(+proxy)?(+proxy*100).toFixed(2)+'%':'—'} · reflected E_mel ${f2(reflected)} W/m² · tilt ${tilt}° azimuth ${azimuth}° · fusion ${summary.fusion_version||'—'} · confidence ${summary.confidence_version||'—'} · rank ${summary.window_rank_version||'—'}`;
if(typeof surfaceBox==='function'){const s=surfaceBox();if(s){s.textContent=context;return;}}
pv.innerHTML=`<span id="surfacecontext">${esc(context)}</span> · ${esc(pv.textContent||'')}`;}
function drawCharts(){const hours=rowsFor(DATA.hourly,SEL);CHARTTIMES=hours.map(z=>z.time);if(!hours.length)return;const d=DATA.daily.find(x=>x.date===SEL);const times=hours.map(z=>hhmm(z.time));const inB=hours.map(z=>inWin(z.time,d?d.best_window_start:null,d?d.best_window_end:null));const panel=(id,vals,color,fill,opt)=>{const c=document.getElementById(id);if(!c)return;const x=c.getContext('2d');const W=c.width,H=c.height;const padL=36,padB=14,padT=10;const iw=W-padL-4,ih=H-padT-padB;x.clearRect(0,0,W,H);const v=vals.map(z=>+z);const vmax=opt.fixedMax!=null?opt.fixedMax:Math.max(...v.filter(Number.isFinite),1e-9);x.fillStyle='rgba(178,94,0,0.10)';v.forEach((_,n)=>{if(!inB[n])return;const px=padL+n/(Math.max(v.length-1,1))*iw,pw=iw/Math.max(v.length-1,1);x.fillRect(px-pw/2,padT,pw,ih);});x.font='9px sans-serif';x.lineWidth=1;(opt.ticks||[0,vmax]).forEach(t=>{const py=padT+ih-(t/vmax)*ih;x.strokeStyle='#d2d8d3';x.beginPath();x.moveTo(padL,py);x.lineTo(W-2,py);x.stroke();x.fillStyle='#5b6461';x.fillText(opt.fmt?opt.fmt(t):String(Math.round(t)),2,py+3);});const step=Math.max(1,Math.floor(times.length/6));x.fillStyle='#5b6461';for(let n=0;n<times.length;n+=step){const px=padL+n/(Math.max(v.length-1,1))*iw;x.fillText(times[n],px-10,H-3);}x.strokeStyle=color;x.lineWidth=2;x.beginPath();let _pen=false;v.forEach((z,n)=>{if(!Number.isFinite(z)){_pen=false;return;}const px=padL+n/(Math.max(v.length-1,1))*iw;const py=padT+ih-Math.min(z,vmax)/vmax*ih;if(_pen)x.lineTo(px,py);else x.moveTo(px,py);_pen=true;});x.stroke();if(fill){x.lineTo(padL+iw,padT+ih);x.lineTo(padL,padT+ih);x.closePath();x.globalAlpha=0.15;x.fillStyle=color;x.fill();x.globalAlpha=1;}const last=[...v].reverse().find(Number.isFinite);if(last!=null){x.fillStyle=color;x.font='bold 10px sans-serif';x.fillText((opt.fmt?opt.fmt(last):String(last))+(opt.unit||''),W-52,padT+10);}};panel('chartScore',hours.map(z=>z.tan_score_absolute_0_100),'#a85500',true,{fixedMax:100,ticks:[0,20,40,60,80,100],fmt:t=>String(Math.round(t))});let acc=0;const cumDose=hours.map(z=>{const t=+z.tan_dose_1h_j_m2;acc+=Number.isFinite(t)?t:0;return acc;});panel('chartDose',cumDose,'#2c7a45',true,{fmt:t=>t>=1000?(t/1000).toFixed(1)+'k':String(Math.round(t)),unit:' J/m²'});let accS=0;const cumSed=hours.map(z=>{const t=+z.sed_1h;accS+=Number.isFinite(t)?t:0;return accS;});panel('chartSed',cumSed,'#7b4bd6',true,{fmt:t=>String(Math.round(t*10)/10),unit:' SED'});chartTip();chartToggle();}
let CHARTI=0;const CHARTS=[["chartScore","TanScore 0–100 (instantaneous intensity)"],["chartDose","TanDose J/m² (cumulative exposure)"],["chartSed","SED (cumulative sunburn load)"]];
function chartToggle(){const cs=CHARTS.map(c=>document.getElementById(c[0])).filter(Boolean);if(!cs.length)return;CHARTI=Math.max(0,Math.min(CHARTI,cs.length-1));cs.forEach((c,n)=>{c.style.display=n===CHARTI?"":"none";});const nm=document.getElementById("chartName");if(nm)nm.textContent=(CHARTI+1)+" of "+cs.length+" — "+CHARTS[CHARTI][1];}
function chartStep(d){CHARTI=(CHARTI+d+3)%3;chartToggle();}
function chartTip(){["chartPrev","chartNext"].forEach((id,n)=>{const b=document.getElementById(id);if(b&&!b.dataset.wired){b.dataset.wired="1";b.addEventListener("click",()=>chartStep(n?1:-1));}});["chartScore","chartDose","chartSed"].forEach(id=>{const c=document.getElementById(id);if(!c||c.dataset.tip)return;c.dataset.tip="1";c.addEventListener("mousemove",ev=>{const r=c.getBoundingClientRect();const n=Math.round((ev.clientX-r.left)/Math.max(1,r.width)*(Math.max(1,CHARTTIMES.length)-1));const tip=document.getElementById("charttip");if(tip&&CHARTTIMES[n])tip.textContent=hhmm(CHARTTIMES[n])+" — "+c.id.replace("chart","")+" #"+(n+1);});});}
let CHARTTIMES=[];
function bestDay(){const d=(DATA.daily||[]).slice(),dose=x=>{for(const k of ['best_usable_30m_dose_j_m2','strongest_30m_dose_j_m2','best_30m_tan_dose_j_m2']){const v=+x[k];if(Number.isFinite(v))return v;}return -1;};d.sort((a,b)=>dose(b)-dose(a));return d[0]||null;}
function render(){if(!DATA||!DATA.daily||!DATA.daily.length){show('No forecast data yet.','error');return;}
(function(){const s=DATA.summary||{};const fc=s.forecast_code_sha||DATA.build_sha||'?';const rc=s.renderer_code_sha||fc;let tag='Updated '+fmtTime(s.created_at)+' · '+(DATA.hourly||[]).length+' hourly rows · forecast '+fc;if(rc!==fc)tag+=' (page '+rc+')';tag+=' · absolute is provisional global scale, local is this location\u0027s percentile';document.getElementById('runline').textContent=tag;})();
(function(){const el=document.getElementById('skinctx');if(!el)return;const rows=DATA.half_hour&&DATA.half_hour.length?DATA.half_hour:(DATA.hourly||[]);const r=rows.find(x=>x&&x.fitzpatrick_label)||null;if(!r){el.hidden=true;el.textContent='';return;}el.hidden=false;el.innerHTML='<b>'+esc(r.fitzpatrick_label)+'</b> — '+esc(r.skin_response_note||'');})();
console.log('[sunstack] build=%s run=%s updated=%s',DATA.build_sha,DATA.run,(DATA.summary||{}).created_at);
const _calQp=new URLSearchParams();_calQp.set('location',LOC||'');const _skin=document.getElementById('skin').value,_mt=numOrNull('mintemp');if(_skin)_calQp.set('skin_type',_skin);if(_mt!==null)_calQp.set('min_temp',_mt);const _cls=classesJson();if(_cls)_calQp.set('classes',_cls);const _cal=document.getElementById('cal');_cal.href=calUrl(_calQp.toString());_cal.title='Subscribe to the best usable window for each day (same window as this page, including your schedule if set). Surface, tilt and skin type do not change the calendar.';
if(!SEL||!DATA.daily.some(d=>d.date===SEL)){const today=new Date();const pad2=n=>String(n).padStart(2,'0');const tstr=`${today.getFullYear()}-${pad2(today.getMonth()+1)}-${pad2(today.getDate())}`;const tb=DATA.daily.find(d=>d.date===tstr)||bestDay();SEL=tb?tb.date:DATA.daily[0].date;}
const b=bestDay();
document.getElementById('strip').innerHTML=DATA.daily.map(d=>{const pk=+d.day_overall_peak_0_100||0;const ppRaw2=d.peak_precip_probability_pct;const pp=(ppRaw2===null||ppRaw2===undefined||ppRaw2===""||!Number.isFinite(+ppRaw2))?NaN:+ppRaw2;const wet=pp>=40;return `<button class="daycell" role="option" id="dayopt-${d.date}" tabindex="${d.date===SEL?0:-1}" aria-selected="${d.date===SEL}" data-date="${d.date}"${wet?' style="border-color:#c0392b"':''}><div class="dow">${esc(shortDay(d.date))}</div><div class="dt">${esc(d.day_status||'')}${wet?` · <b style="color:#c0392b">${f0(pp)}% rain</b> <span class="txt">· wet</span>`:''}</div><div class="win">${winStr(d.best_window_start,d.best_window_end)}</div>${(()=>{const cs=classSpans(d.date,LOC);return cs?`<div class="cls">🎓 ${cs} ET</div>`:``;})()}<div class="pk" title="Legacy composite (deprecated product heuristic) peak for this day — not the ranking key" style="color:${wet?'#c0392b':scoreColor(pk)}">${f0(pk)}</div><div class="uv" title="Outdoor fit: share of daylight half-hours not hard-blocked">Fit ${f0(100*(1-(+d.blocked_half_hours||0)/Math.max(1,rowsFor(DATA.half_hour,d.date).length)))}%</div><div class="uv" title="Forecast agreement at the peak hour">Conf ${f0(d.day_confidence_at_peak_0_100)}</div><div class="uv">UV ${f1(d.peak_uv_index??peakOf(rowsFor(DATA.hourly,d.date),'uvi_consensus'))} · ${f1(d.day_low_temperature_f??dayLo(rowsFor(DATA.hourly,d.date)))}–${f1(d.day_high_temperature_f??dayHi(rowsFor(DATA.hourly,d.date)))}\u00b0</div><div class="uv">Feels ${f1(d.day_low_feels_like_f??dayLo(rowsFor(DATA.hourly,d.date),'apparent_temperature'))}–${f1(d.day_high_feels_like_f??dayHi(rowsFor(DATA.hourly,d.date),'apparent_temperature'))}\u00b0</div><div class="uv">Gust ${f0(d.day_peak_gust_mph??dayHi(rowsFor(DATA.hourly,d.date),'wind_gusts_10m'))}${(+d.day_peak_wind_mph>=25||+dayHi(rowsFor(DATA.hourly,d.date),'wind_speed_10m')>=25)?` <b style="color:#c0392b">windy</b>`:''}</div><div class="uv">Abs ${f0(d.day_absolute_peak_0_100)} · Loc ${f0(d.day_local_peak_0_100)}</div><div class="bar"><i style="width:${Math.max(3,Math.min(100,pk))}%;background:${wet?'#c0392b':scoreColor(pk)}"></i></div></button>`;}).join('');{const _s=document.getElementById('strip');if(_s)_s.setAttribute('aria-activedescendant','dayopt-'+SEL);}
const heroHours=b?rowsFor(DATA.hourly,b.date):[],heroHalf=b?rowsFor(DATA.half_hour,b.date):[],strongStart=b?(b.strongest_30m_start??b.best_30m_start):null,strongEnd=b?(b.strongest_30m_end??null):null,usableStart=b?(b.best_usable_30m_start??strongStart):null,usableEnd=b?(b.best_usable_30m_end??strongEnd):null,usableRow=heroHalf.find(x=>String(x.time).slice(0,16)===String(usableStart||'').slice(0,16))||heroHours[0]||{},surfaceEl=document.getElementById('surface'),surfaceName=surfaceEl&&surfaceEl.selectedOptions[0]?surfaceEl.selectedOptions[0].textContent:'Unknown surface',backend=usableRow.spectral_backend||(DATA.summary||{}).spectral_backend||'—',tier=usableRow.spectral_tier||(DATA.summary||{}).photobiology_action_spectrum_tier||'—';
const _winState=(()=>{if(!usableStart)return '';const now=new Date();const s=new Date(String(usableStart).slice(0,16)),e=usableEnd?new Date(String(usableEnd).slice(0,16)):null;if(e&&now>e)return 'this window has passed';if(now>=s)return 'happening now';return '';})();
const _sameWin=String(strongStart||'').slice(0,16)===String(usableStart||'').slice(0,16);
const _doseOf=o=>f0(o.best_usable_30m_dose_j_m2??o.strongest_30m_dose_j_m2??o.best_30m_tan_dose_j_m2);
document.getElementById('hero').innerHTML=b?`<b>${dayName(b.date)}</b> is the best day in this run. Best window ${winStr(usableStart,usableEnd)} — ${_doseOf(b)} J/m² pigment-weighted dose, confidence <span title="0-100, how much to trust this row. It is cut when the UVI sources disagree - a spread of 1.0 or more starts reducing it. Not a probability, and not a quality judgement about the weather.">${f0(usableRow.tan_forecast_confidence_0_100)}</span>${_winState?', '+_winState:''}.${_sameWin?'':' Strongest window is '+winStr(strongStart,strongEnd)+' ('+f1(b.strongest_30m_dose_j_m2??b.best_30m_tan_dose_j_m2)+' J/m²) before schedule and comfort are applied.'}`:'No usable light in this run.';
document.querySelectorAll('.daycell').forEach(el=>el.addEventListener('click',()=>{SEL=el.dataset.date;syncUrl(true);render();}));
renderDay();{const rh=rowsFor(DATA.hourly,SEL),rq=rowsFor(DATA.half_hour,SEL);renderSunFig(rh,rq);}try{renderDoses();}catch(e){console.error('[sunstack] doses failed',e);show('Dose panel failed to render — see console.','error');}try{drawCharts();}catch(e){console.error('[sunstack] charts failed',e);show('Charts failed to render — see console.','error');}{const nb=document.getElementById('nerdBtn');if(nb){const on=document.body.classList.contains('show-nerd');nb.textContent=on?'Hide extra columns':'Show all columns';nb.setAttribute('aria-pressed',on?'true':'false');}}document.getElementById('debugtext').textContent=JSON.stringify(DATA.summary||{},null,2);
{const ds=document.getElementById('debugsummary');if(ds){const s=DATA.summary||{};const keys=['site','location','site_name','generated','created_at','run_tag','build_sha','day','date','hourly_rows','half_hour_rows','rows','surface','surface_slug','spectral_backend','spectral_tier','fusion_version','confidence_version','window_rank_version','photobiology_action_spectrum_tier','calibration_dir','data_source'];const li=[];for(const k of keys){const v=s[k];if(v===undefined||v===null||v==='')continue;if(typeof v==='object')continue;li.push('<b>'+esc(String(k))+'</b> '+esc(String(v)));}ds.innerHTML=li.length?li.join(' · ')+'<br><span class="note">The full run summary is under Full JSON. This is provenance, not the observations the forecast came from.</span>':'<span class="note">No summary keys to show. The full run summary is under Full JSON.</span>';}}}
function sunFigState(){return {sel:null};}
function compassDeg(c){const pts={N:0,NNE:22.5,NE:45,ENE:67.5,E:90,ESE:112.5,SE:135,SSE:157.5,S:180,SSW:202.5,SW:225,WSW:247.5,W:270,WNW:292.5,NW:315,NNW:337.5};return pts[String(c||'').toUpperCase()]??null;}
function figXY(cx,cy,r,degUp,degFromNorth){const a=(degFromNorth-90)*Math.PI/180;const el=degUp*Math.PI/180;const rr=r*Math.cos(el);return [cx+rr*Math.cos(a),cy-rr*Math.sin(a)];}
function stickFigure(x,y,s,liftDeg,faceDir){
 // Thin side-view recliner, outline style: hip pivot at (x,y) on the ground.
 // Legs flat along the ground, torso rising at liftDeg above horizontal,
 // head as an OUTLINE ring on a short neck gap (paper fill, so it never
 // merges into the orange sun disc), resting arm, foot tick.
 const dir=faceDir<0?-1:1;
 const lift=(liftDeg==null?0:liftDeg)*Math.PI/180;
 const legL=s*1.08,torL=s*0.66,headR=s*0.115;
 const ankX=x-dir*legL,ankY=y;
 const shX=x+dir*torL*Math.cos(lift),shY=y-torL*Math.sin(lift);
 const hdX=shX+dir*(headR+1.5)*Math.cos(lift),hdY=shY-(headR+1.5)*Math.sin(lift);
 const elX=shX-dir*4*Math.cos(lift),elY=shY+torL*0.3*Math.sin(lift)+4;
 let o='';
 o+=`<ellipse cx="${(x-dir*legL*0.4).toFixed(1)}" cy="${(y+5).toFixed(1)}" rx="${(legL*0.55).toFixed(1)}" ry="2.5" fill="currentColor" opacity="0.12"/>`;
 o+=`<line x1="${x}" y1="${y}" x2="${ankX.toFixed(1)}" y2="${ankY}" stroke="currentColor" stroke-width="3.2" stroke-linecap="round"/>`;
 o+=`<line x1="${ankX.toFixed(1)}" y1="${ankY}" x2="${(ankX+dir*6).toFixed(1)}" y2="${(ankY-2).toFixed(1)}" stroke="currentColor" stroke-width="2.4" stroke-linecap="round"/>`;
 o+=`<line x1="${x}" y1="${(y-1).toFixed(1)}" x2="${shX.toFixed(1)}" y2="${shY.toFixed(1)}" stroke="currentColor" stroke-width="3.6" stroke-linecap="round"/>`;
 o+=`<line x1="${shX.toFixed(1)}" y1="${shY.toFixed(1)}" x2="${elX.toFixed(1)}" y2="${elY.toFixed(1)}" stroke="currentColor" stroke-width="2" stroke-linecap="round"/>`;
 o+=`<line x1="${shX.toFixed(1)}" y1="${shY.toFixed(1)}" x2="${hdX.toFixed(1)}" y2="${hdY.toFixed(1)}" stroke="currentColor" stroke-width="3.2" stroke-linecap="round"/>`;
 o+=`<circle cx="${hdX.toFixed(1)}" cy="${hdY.toFixed(1)}" r="${headR.toFixed(1)}" fill="#f7f9f7" stroke="currentColor" stroke-width="2.2"/>`;
 return o;}
function drawSunFig(row){const svg=document.getElementById('sunfig');if(!svg||!row)return;const cx=150,cy=154,r=106;const NS='http://www.w3.org/2000/svg';while(svg.firstChild)svg.removeChild(svg.firstChild);const mk=(t,a)=>{const e=document.createElementNS(NS,t);for(const k in a)e.setAttribute(k,a[k]);svg.appendChild(e);return e;};mk('line',{x1:16,y1:cy-4,x2:284,y2:cy-4,stroke:'#c3cac5','stroke-width':1.5});mk('text',{x:248,y:cy-18,'font-size':10,fill:'#5b6461'}).textContent='ground';const elev=+row.solar_elevation_deg,az=+row.solar_azimuth_deg;const lift=+(row.torso_lift_deg||0);if(!(elev>0)){mk('text',{x:cx,y:64,'text-anchor':'middle','font-size':13,fill:'#5b6461'}).textContent='sun below horizon';mk('text',{x:cx,y:82,'text-anchor':'middle','font-size':11,fill:'#5b6461'}).textContent='no direct-sun posture';const g=document.createElementNS(NS,'g');g.setAttribute('transform',`translate(${cx+8},${cy-4})`);g.setAttribute('color','#646c69');g.innerHTML=stickFigure(0,0,56,0,1);svg.appendChild(g);return;}const cdeg=compassDeg(row.sun_compass);const azUse=cdeg==null?(Number.isNaN(az)?180:az):cdeg;const[sx,sy]=figXY(cx,cy-4,r,elev,azUse);const sun=mk('circle',{cx:sx,cy:sy,r:9.5,fill:'#e8a100',stroke:'#a85500','stroke-width':2});sun.appendChild(document.createElementNS(NS,'title')).textContent=`sun ${elev.toFixed(0)}° up, ${row.sun_compass||''}`;const dir=sx>=cx?1:-1;const lr=lift*Math.PI/180,tL=56*0.66,chX=cx+dir*tL*0.5*Math.cos(lr),chY=(cy-4)-tL*0.5*Math.sin(lr);const rdx=sx-chX,rdy=sy-chY,rlen=Math.hypot(rdx,rdy)||1,rex=sx-rdx/rlen*12.5,rey=sy-rdy/rlen*12.5;mk('line',{x1:chX.toFixed(1),y1:chY.toFixed(1),x2:rex.toFixed(1),y2:rey.toFixed(1),stroke:'#a85500','stroke-width':1.2,'stroke-dasharray':'4 3',opacity:0.7});const g=document.createElementNS(NS,'g');g.setAttribute('transform',`translate(${cx},${cy-4})`);g.setAttribute('color','#151a18');g.innerHTML=stickFigure(0,0,56,lift,dir);svg.appendChild(g);mk('text',{x:cx,y:cy+22,'text-anchor':'middle','font-size':10,fill:'#5b6461'}).textContent=`face ${row.sun_compass||'—'} · torso ~${Math.round(lift)}°`;const cap=document.getElementById('suncap');if(cap)cap.innerHTML=`<b>${hhmm(row.time)}</b> — ${esc(row.sun_posture_guidance||'')} (UV ${f1(row.uv_index)}, overall ${f0(row.overall_tan_opportunity_0_100)})`;}
function pickSunRow(hours,half){const all=(half||[]).concat(hours||[]).filter(x=>+x.solar_elevation_deg>0);if(!all.length)return (hours||[])[0]||null;let best=null,bs=-1;for(const x of all){const v=+x.overall_tan_opportunity_0_100;if(!Number.isNaN(v)&&v>bs){bs=v;best=x;}}return best;}
function renderSunFig(hours,half){const sel=FIG.sel;const list=(half||[]).concat(hours||[]);let row=list.find(x=>x.time===sel)||pickSunRow(hours,half);if(!row)return;FIG.sel=row.time;drawSunFig(row);const opts=list.filter(x=>+x.solar_elevation_deg>0);const dd=document.getElementById('sunsel');if(dd){const cur=dd.value;dd.innerHTML=opts.map(x=>`<option value="${esc(x.time)}"${x.time===row.time?' selected':''}>${hhmm(x.time)} — sun ${f0(x.solar_elevation_deg)}° ${esc(x.sun_compass||'')}</option>`).join('');if(![...dd.options].some(o=>o.value===cur))dd.value=row.time;}}
function rowsFor(list,date){return (list||[]).filter(x=>(x.time||'').slice(0,10)===date).sort((a,b)=>String(a.time).localeCompare(String(b.time)));}
function inWin(t,a,c){t=String(t||'').slice(0,16);a=String(a||'').slice(0,16);c=String(c||'').slice(0,16);return a&&(!c||t<c)&&t>=a?true:false;}
function parseSchedule(text){const out=[];const days={mon:0,tue:1,wed:2,thu:3,fri:4};for(const raw of String(text||'').split('\n')){const line=raw.trim();if(!line)continue;const m=/^([a-z]{3})[a-z]*\s+(\d{1,2}):(\d{2})\s*-\s*(\d{1,2}):(\d{2})$/i.exec(line);if(!m)continue;const d=days[m[1].toLowerCase()];if(d===undefined)continue;const s=(+m[2])*60+(+m[3]),e=(+m[4])*60+(+m[5]);if(s<e)out.push({dow:d,start_min:s,end_min:e});}return out;}
function classRanges(){try{return parseSchedule(localStorage.getItem('sunstack_classes')||'');}catch(e){return [];}}
function classAt(time){const r=classRanges();if(!r.length)return "";const d=new Date(time);if(Number.isNaN(d))return "";const wd=(d.getDay()+6)%7;if(wd>4)return "";const mins=d.getHours()*60+d.getMinutes();for(const iv of r){if(iv.dow===wd&&mins>=iv.start_min&&mins<iv.end_min)return "in class";}return "";}
function classSpans(date){const r=classRanges();if(!r.length)return "";const wd=(new Date(date+"T12:00:00").getDay()+6)%7;const f=m=>`${Math.floor(m/60)}:${String(m%60).padStart(2,'0')}`;return r.filter(iv=>iv.dow===wd).map(iv=>f(iv.start_min)+"-"+f(iv.end_min)).join(", ");}
function availWin(date,a,b){if(document.body.classList.contains('hide-class'))return "";if(!classRanges().length)return "";try{const A=String(a||"").slice(0,16),B=String(b||"").slice(0,16);if(!A)return "";const rows=rowsFor(DATA.half_hour,date);const free=rows.filter(x=>!classAt(x.time)&&String(x.time).slice(0,16)>=A&&(!B||String(x.time).slice(0,16)<B));if(!free.length)return `<span class="note cls">all of it in class</span>`;const f0s=free[0].time,f1s=free[free.length-1].time;return `<span class="note cls">free for you: ${hhmm(f0s)}–${hhmm(f1s)}</span>`;}catch(e){return "";}}
function uviRange(x){const fin=v=>(v!==null&&v!==undefined&&v!==""&&Number.isFinite(+v));const vs=[x.uv_index,x.uvi_cams,x.uvi_epa].filter(fin).map(Number);if(!(vs.length>=2)||!Number.isFinite(+x.uvi_source_spread)||+x.uvi_source_spread<1)return "";const lo=Math.min(...vs),hi=Math.max(...vs);return `<br><span class="note" title="Source range ${hi.toFixed(1)} vs ${lo.toFixed(1)} across UVI sources — min/max of visible sources, not a modeled sunny/cloudy scenario">${lo.toFixed(1)}–${hi.toFixed(1)}</span>`;}
function disagreeNote(x){return [x.outdoor_block_reason,x.uv_input_disagree?'UV/broadband inputs disagree on cloud':'',x.uvi_source_disagree?'UVI sources disagree':''].filter(Boolean).join(' · ');}
let FIG=sunFigState();
function renderDay(){const d=DATA.daily.find(x=>x.date===SEL);if(!d)return;const el=document.getElementById('detail');
const hours=rowsFor(DATA.hourly,SEL),half=rowsFor(DATA.half_hour,SEL);
const uvRows=hours.filter(x=>+x.uv_index>0);
const hHtml=hours.map(x=>{const w=inWin(x.time,d.best_window_start,d.best_window_end);const cl=classAt(x.time);const note=[disagreeNote(x),cl].filter(Boolean).join(' · ');const ppRaw=x.precipitation_probability;const pp=(ppRaw===null||ppRaw===undefined||ppRaw===''||!Number.isFinite(+ppRaw))?NaN:+ppRaw;const wet=pp>=40;const sun=(+x.solar_elevation_deg>0)?` <span class="note">&#9728;&#xFE0E; ${f0(x.solar_elevation_deg)}° ${esc(x.sun_compass||'')}</span>`:'';const rainCell=Number.isNaN(pp)?'<span class="note">—</span>':(wet?`<b style="color:#c0392b">${f0(pp)}%</b>`:`${f0(pp)}%`);return `<tr data-time="${esc(x.time)}" class="${w?'inwindow ':''}${cl?'inclass':''}"><td>${w?'★ ':''}${hhmm(x.time)}</td><td><span class="uvdot" style="background:${uvColor(x.uvi_consensus ?? x.uv_index)}"></span><b>${f1(x.uvi_consensus ?? x.uv_index)}</b>${uviRange(x)}</td><td class="nerd">${f1(x.uv_index)}</td><td class="nerd">${f1(x.uvi_cams)}</td><td class="nerd">${f1(x.uvi_epa)}</td><td class="nerd">${f1(x.uv_index_clear_sky)}</td><td><span title="Disagree flag at spread ≥1.0 UVI, strong at ≥2.0">${x.uvi_source_spread==null||Number.isNaN(+x.uvi_source_spread)?"—":(+x.uvi_source_spread).toFixed(2)}</span></td><td class="nerd">${f1(x.predicted_uva_wm2)}</td><td class="nerd">${f2(x.predicted_uvb_wm2)}</td><td>${f1(x.temperature_2m)}°${(+x.apparent_temperature!=null&&!Number.isNaN(+x.apparent_temperature)&&Number.isFinite(+x.apparent_temperature)&&Number.isFinite(+x.temperature_2m)&&Math.abs(+x.apparent_temperature-+x.temperature_2m)>=2)?` <span class="note">fl ${f1(x.apparent_temperature)}°</span>`:''}${Number.isFinite(+x.sun_adjusted_feels_like_f)?` <span class="note">sun-feels ${f1(x.sun_adjusted_feels_like_f)}°</span>`:''}${x.comfort_band&&x.comfort_band!=='perfect'?` <span class="note">${esc(x.comfort_band)}</span>`:''}</td><td>${(+x.wind_speed_10m>=25||+x.wind_gusts_10m>=25)?`<b style="color:#c0392b">`:''}${f0(x.wind_speed_10m)}${(+x.wind_gusts_10m!=null&&!Number.isNaN(+x.wind_gusts_10m)&&+x.wind_gusts_10m>+x.wind_speed_10m+3)?` g${f0(x.wind_gusts_10m)}`:''}${(+x.wind_speed_10m>=25||+x.wind_gusts_10m>=25)?`</b>`:''}</td><td class="nerd">${f0(x.cloud_cover)}%</td><td class="nerd">${rainCell}</td><td class="nerd">${f0(x.direct_normal_irradiance_instant)}</td><td>${f0(x.overall_tan_opportunity_0_100)}</td><td class="nerd">${f0(x.tan_score_absolute_0_100)}</td><td class="nerd">${f0(x.local_tan_score_0_100)}</td><td class="nerd">${f0(x.atmospheric_quality_percentile_0_100)}</td><td>${f0(x.tan_forecast_confidence_0_100)}</td><td class="note">${esc(note)}${sun}</td></tr>`;}).join('');
const qHtml=half.map(x=>{const w=inWin(x.time,d.best_window_start,d.best_window_end);const cl=classAt(x.time);const uv=(x.uvi_consensus!=null?x.uvi_consensus:x.uv_index)!=null?(x.uvi_consensus!=null?x.uvi_consensus:x.uv_index):x.air__uv_index;return `<tr data-time="${esc(x.time)}" class="${w?'inwindow ':''}${cl?'inclass':''}"><td>${w?'★ ':''}${hhmm(x.time)}</td><td><span class="uvdot" style="background:${uvColor(uv)}"></span><b>${f1(uv)}</b>${uviRange(x)}</td><td>${f1(x.predicted_uva_wm2)}</td><td><b>${f0(x.delayed_pigmentation_dose_30m_j_m2??x.tan_dose_30m_j_m2)}</b></td><td>${f0(x.tan_forecast_confidence_0_100)}</td><td>${f0(x.overall_tan_opportunity_0_100)}</td><td>${f0(x.local_tan_score_0_100)}</td><td class="note">${esc(x.subhour_source==='native_HRRR_radiation_weather_plus_interpolated_UV'?'HRRR wx/rad + interp UV':(x.subhour_source==='interpolated_hourly'?'hourly split':(x.subhour_source||'hourly split')))}</td><td class="note">${esc([disagreeNote(x),cl].filter(Boolean).join(' · '))}</td></tr>`;}).join('');
el.innerHTML=`<h2>${dayName(d.date)} <span class="note">Abs ${f0(d.day_absolute_peak_0_100)} (worldwide scale) · Local ${f0(d.day_local_peak_0_100)} (percentile within this location)</span> <span class="note" title="Day verdict word, derived from the peak Overall composite (the LEGACY 0-100 heuristic, see Research notes): 0 = NO OUTDOOR WINDOW, 1-34 = POOR, 35-49 = FAIR, 50-64 = GOOD, 65-79 = VERY GOOD, 80+ = EXCELLENT; UNKNOWN when the weather is missing for the day.">status: ${esc(d.day_status||'')}</span></h2>
<p class="bestline">Good window (longest near-peak) <b>${winStr(d.best_window_start,d.best_window_end)}</b> · best hour ${hhmm(d.best_hour_start)} (legacy score <span title="overall_tan_opportunity_0_100 — the deprecated composite, not the ranking key">${f0(d.best_hour_score_0_100)}</span>) · peak 30-min dose ${f0(d.peak_30m_tan_dose_j_m2??d.best_30m_tan_dose_j_m2)} J/m² · peak UV ${f1(d.peak_uv_index??peakOf(hours,'uvi_consensus'))} · ${f1(d.peak_temperature_f??peakOf(hours,'temperature_2m'))}°F · ${f0(d.blocked_half_hours)} blocked half-hours. Rows tinted below fall inside the good window. ${classRanges().length?availWin(d.date,d.best_window_start,d.best_window_end):""}</p>
<details class="classrow" id="classbox"><summary>My schedule (optional)</summary><p class="note">One block per line — <b>Mon 11:00-12:15</b>. Kept in this browser only; it is never part of the published forecast. With no schedule entered, nothing is filtered and no class rows are marked.</p><textarea id="classText" rows="3" spellcheck="false" aria-label="Your weekly class or busy blocks, one per line, for example Mon 11:00-12:15"></textarea><div class="note"><label><input type="checkbox" id="classTgl" checked> Show class rows in the tables</label> <span id="classState"></span></div><p class="note">Rows inside a class block get a purple left border; the amber tint marks the recommended window. A row can be both — that is the collision worth seeing.</p></details><h3>Every hour — Headline UVI first <button id="nerdBtn" type="button" aria-pressed="false" title="Show all 20 columns">Show all columns</button></h3><p class="gloss">UV∘ Headline UVI (bias-corrected inverse-error fusion of OM Best Match + CAMS + EPA) · ΔUV source-range spread flags disagreement · Ranking is maximum expected 30-minute delayed-pigmentation dose (fixed-duration-dose-v2); Overall is a LEGACY composite (deprecated product heuristic) · <b>All columns stay in the page</b> — hidden ones are one tap away and always in Export CSV.</p><div class="tablewrap"><table><thead><tr><th title="Local hour">Time</th><th title="Headline UVI (bias-corrected inverse-error fusion) — drives the SED channel">UV∘</th><th class="nerd" title="OM = Open-Meteo Best Match UVI (not GFS-only)">OM</th><th class="nerd" title="CAMS = Copernicus spectral UVI">CAMS</th><th class="nerd" title="EPA = NWS operational UVI by ZIP">EPA</th><th class="nerd" title="Clear-sky UVI — cloud-free value, compare with UV∘ for cloud suppression">Clear</th><th title="Max UVI spread across sources — disagree flag at ≥1.0, strong at ≥2.0">ΔUV</th><th class="nerd" title="Predicted UVA irradiance W/m²">UVA</th><th class="nerd" title="Predicted UVB irradiance W/m²">UVB</th><th title="Air temperature and feels-like, both °F">Temp °F</th><th title="Wind speed and gust, both mph">Wind mph</th><th class="nerd" title="Total cloud cover %">Cloud</th><th class="nerd" title="Precipitation probability % — bold red at ≥40">Rain</th><th class="nerd" title="Direct normal irradiance, instantaneous W/m²">DNI</th><th title="Overall tanning opportunity 0–100 — LEGACY composite (deprecated product heuristic)">Overall (legacy)</th><th class="nerd" title="Absolute melanogenic strength — worldwide scale">Abs</th><th class="nerd" title="Local percentile — how rare this is for this location">Local</th><th class="nerd" title="Atmospheric quality percentile — air clarity">Atm</th><th title="Forecast confidence 0–100 — discounted when sources disagree">Conf</th><th>Note</th></tr></thead><tbody>${hHtml||'<tr><td colspan="19">No hourly rows for this day.</td></tr>'}</tbody></table></div>
<h3>Every 30 minutes</h3><div class="tablewrap"><table><thead><tr><th title="Local hour">Time</th><th title="Headline UVI (bias-corrected inverse-error fusion) — drives the SED channel">UV∘</th><th title="Predicted UVA irradiance W/m²">UVA</th><th title="Expected 30-minute pigment-weighted dose J/m² — this is the ranking objective">Dose J/m²</th><th title="Forecast agreement — how much to trust this row">Conf</th><th title="LEGACY composite (deprecated product heuristic) — not the ranking key">Overall (legacy)</th><th title="Percentile within this location's own history — not comparable across sites">Local</th><th title="How this row's radiation was produced">Source</th><th>Note</th></tr></thead><tbody>${qHtml||'<tr><td colspan="9">No 30-minute rows for this day.</td></tr>'}</tbody></table></div>`;
 if(!window.__sunstackWired){window.__sunstackWired=true;document.addEventListener('change',e=>{if(e.target&&e.target.id==='classTgl'){document.body.classList.toggle('hide-class',!e.target.checked);render();}});const syncClass=()=>{const n=classRanges().length;const st=document.getElementById('classState');if(st)st.textContent=n?('using '+n+' block'+(n===1?'':'s')):'no schedule set';};document.addEventListener('input',e=>{if(e.target&&e.target.id==='classText'){try{localStorage.setItem('sunstack_classes',e.target.value);}catch(err){}syncClass();}});document.addEventListener('change',e=>{if(e.target&&e.target.id==='classText'){syncClass();loadData();}});document.addEventListener('click',e=>{const _th=(e.target&&e.target.closest)?e.target.closest('#detail th'):null;if(_th){sortTableBy(_th);return;}if(e.target&&e.target.id==='nerdBtn'){document.body.classList.toggle('show-nerd');const on=document.body.classList.contains('show-nerd');e.target.textContent=on?'Hide extra columns':'Show all columns';e.target.title=on?'Show only the headline columns':'Show all '+((document.querySelector('#detail table thead tr')||{children:[]}).children.length)+' columns';e.target.setAttribute('aria-pressed',on?'true':'false');}});fetch('/api/locations').then(r=>{if(!r.ok)throw 0;}).catch(()=>{const b=document.querySelector('.controls.actions .livereq');if(b)b.style.display='none';});const _strip=document.getElementById('strip');if(_strip&&!_strip.dataset.keys){_strip.dataset.keys='1';_strip.addEventListener('keydown',e=>{const cells=Array.prototype.slice.call(_strip.querySelectorAll('.daycell'));if(!cells.length)return;const i=cells.indexOf(document.activeElement);let j=-1;if(e.key==='ArrowRight'||e.key==='ArrowDown')j=Math.min(cells.length-1,i+1);else if(e.key==='ArrowLeft'||e.key==='ArrowUp')j=Math.max(0,i-1);else if(e.key==='Home')j=0;else if(e.key==='End')j=cells.length-1;if(j<0)return;e.preventDefault();SEL=cells[j].dataset.date;syncUrl(true);render();const nx=document.querySelector('#strip .daycell[data-date="'+SEL+'"]');if(nx)nx.focus();});}window.__sunstackSyncClass=syncClass;}document.querySelectorAll('#detail tr[data-time]').forEach(tr=>tr.addEventListener('click',()=>{FIG.sel=tr.dataset.time;const hours=rowsFor(DATA.hourly,SEL),half=rowsFor(DATA.half_hour,SEL);renderSunFig(hours,half);}));
 const dd=document.getElementById('sunsel');if(dd&&!dd.dataset.wired){dd.dataset.wired='1';dd.addEventListener('change',()=>{FIG.sel=dd.value;const hours=rowsFor(DATA.hourly,SEL),half=rowsFor(DATA.half_hour,SEL);renderSunFig(hours,half);});}
}
const renderDayBase=renderDay;
renderDay=function(){renderDayBase();const gloss=document.querySelector('#detail .gloss');if(gloss)gloss.textContent='Ranking is maximum expected 30-minute delayed-pigmentation dose (fixed-duration-dose-v2). Overall is a LEGACY composite (deprecated product heuristic).';};
init();
</script></body></html>"""


def site_nav(current_slug: str | None = None) -> list[dict[str, object]]:
    """Picker entries with per-page relative URLs for the static export.

    The live API picker switches data in place; static pages each hold one
    site's data.json, so the picker is a nav menu. URLs are relative to the
    current page: root serves docs/, site pages serve docs/sites/<slug>/.
    """
    sites = config.active_sites()
    current = current_slug or config.default_site().slug
    nav: list[dict[str, object]] = []
    for s in sites:
        if s.slug == current:
            url = None
        elif current == config.default_site().slug:
            url = f"sites/{s.slug}/"
        elif s.slug == config.default_site().slug:
            url = "../../"
        else:
            url = f"../{s.slug}/"
        nav.append(
            {
                "slug": s.slug,
                "name": s.name,
                "lat": s.lat,
                "lon": s.lon,
                "timezone": s.timezone,
                "default": s.default,
                "current": s.slug == current,
                "url": url,
            }
        )
    return nav
