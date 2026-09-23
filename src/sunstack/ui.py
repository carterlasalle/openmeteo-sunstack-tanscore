from __future__ import annotations

import json
import threading
import webbrowser
from datetime import UTC, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd
from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import HTMLResponse, Response

from . import config
from .calibrate import scol
from .opportunity import (
    apply_outdoor_feasibility,
    attach_fitzpatrick,
    attach_personalization,
    build_daily_summary,
)
from .tanscore import fnum

BUILD_SHA: str | None = None


def build_sha() -> str:
    """Short git SHA of the code serving this page. Cached; 'unknown' off-git."""
    global BUILD_SHA
    if BUILD_SHA is None:
        try:
            import subprocess

            out = subprocess.run(
                ["git", "rev-parse", "--short", "HEAD"],
                capture_output=True,
                text=True,
                check=False,
                timeout=10,
            )
            BUILD_SHA = out.stdout.strip() or "unknown"
        except (OSError, subprocess.SubprocessError):
            BUILD_SHA = "unknown"
    return BUILD_SHA


def _site_nav(current_slug: str | None = None) -> list[dict[str, object]]:
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


def _resolve_site(slug: str | None) -> config.Site:
    """Empty slug keeps the South Bend default so old URLs never break."""
    sites = config.active_sites()
    if not slug:
        return config.default_site()
    for s in sites:
        if s.slug == slug:
            return s
    raise FileNotFoundError(f"unknown location: {slug}")


def _latest_dir(root: Path, site: config.Site | None = None) -> Path:
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


def _read_table(run: Path, name: str) -> pd.DataFrame:
    p = run / "tables" / f"{name}.parquet"
    if p.exists():
        return pd.read_parquet(p)
    p = run / "tables" / f"{name}.csv"
    if p.exists():
        return pd.read_csv(p)
    return pd.DataFrame()


def _records(df: pd.DataFrame, limit: int | None = None):
    if limit is not None:
        df = df.head(limit)
    clean = df.replace([np.inf, -np.inf], np.nan).copy()
    text = clean.to_json(orient="records", date_format="iso")
    if not isinstance(text, str):
        raise TypeError("records JSON serialization must produce text")
    return json.loads(text)


def _filtered_payload(
    root: Path,
    skin_type: int | None,
    min_temp: float | None,
    site: config.Site | None = None,
    personal_mmd_j_m2: float | None = None,
    personal_mmd_basis: str | None = None,
):
    run = _latest_dir(root, site)
    hourly = _read_table(run, "tan_forecast_hourly")
    half = _read_table(run, "tan_forecast_30min")
    if hourly.empty or half.empty:
        raise RuntimeError(
            "Latest run is missing TanScore output tables; refresh the data."
        )
    if min_temp is not None:
        hourly = apply_outdoor_feasibility(hourly, min_temp)
        half = apply_outdoor_feasibility(half, min_temp)
    hourly = attach_fitzpatrick(hourly, skin_type)
    half = attach_fitzpatrick(half, skin_type)
    hourly = attach_personalization(
        hourly, personal_mmd_j_m2=personal_mmd_j_m2, basis=personal_mmd_basis)
    half = attach_personalization(
        half, personal_mmd_j_m2=personal_mmd_j_m2, basis=personal_mmd_basis,
        dose_col="tan_dose_30m_j_m2")
    daily = build_daily_summary(half)
    summary_path = run / "summary.json"
    summary = json.loads(summary_path.read_text()) if summary_path.exists() else {}
    return run, hourly, half, daily, summary


_PERSONAL_MMD_BASES = ("MEASURED", "OBJECTIVE_ESTIMATE", "COARSE_ESTIMATE")


def _parse_personal_mmd(personal_mmd: object,
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


def _daily_uv_peaks(hourly: pd.DataFrame) -> dict[str, dict[str, str]]:
    """Per-day UV peaks from the hourly table: UVI value and time, UVB, UVA."""
    peaks: dict[str, dict[str, str]] = {}
    if hourly.empty or "time" not in hourly:
        return peaks
    dates = np.asarray(scol(hourly, "time").astype(str).str.slice(0, 10))
    for date in sorted(set(dates.tolist())):
        sub = hourly.loc[dates == date]
        entry: dict[str, str] = {}
        uvi = _day_col(sub, "uv_index")
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
    try:
        f = float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None
    if not np.isfinite(f):
        return None
    return f"{f:{fmt}}{suffix}"


def build_interval_ics(
    half_hour: pd.DataFrame,
    run_tag: str,
    site_slug: str | None = None,
    tz_name: str | None = None,
) -> str:
    """Optional per-30-minute VEVENTs with interval doses (native vs interpolated labeled)."""
    digits = "".join(c for c in run_tag if c.isdigit())
    sequence = int(digits) if digits else 0
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
        for label, col, fmt, suf in (
            ("Abs", "tan_score_absolute_0_100", ".0f", "/100"),
            ("Overall", "overall_tan_opportunity_0_100", ".0f", "/100"),
            ("TanDose30", "tan_dose_30m_j_m2", "g", " J/m2 mel"),
            ("SED30", "sed_30m", "g", ""),
            ("UVA30", "uva_dose_30m_j_m2", "g", " J/m2"),
            ("UVB30", "uvb_dose_30m_j_m2", "g", " J/m2"),
            ("Conf", "tan_forecast_confidence_0_100", ".0f", ""),
        ):
            v = _fmt_opt(row.get(col), fmt, suf)
            if v is not None:
                bits.append(f"{label} {v}")
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
    digits = "".join(c for c in run_tag if c.isdigit())
    sequence = int(digits) if digits else 0
    now = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    peaks = _daily_uv_peaks(hourly) if hourly is not None else {}
    events = []
    for _, row in daily.iterrows():
        start, end = row.get("best_window_start"), row.get("best_window_end")
        if not start or not end or pd.isna(start) or pd.isna(end):
            continue
        date = str(row.get("date", ""))
        peak = fnum(row, "day_overall_peak_0_100")
        peak_s = str(int(peak)) if pd.notna(peak) else "?"
        parts = [f"Overall {peak_s}/100"]
        absp = _fmt_opt(row.get("day_absolute_peak_0_100"), ".0f", "/100")
        if absp:
            parts.append(f"Abs {absp}")
        uv = peaks.get(date, {})
        if uv.get("uvi"):
            when = f" at {uv['uvi_time']}" if uv.get("uvi_time") else ""
            parts.append(f"Peak UV {uv['uvi']}{when}")
            if uv.get("uva"):
                parts.append(f"UVA {uv['uva']} W/m2")
            if uv.get("uvb"):
                parts.append(f"UVB {uv['uvb']} W/m2")
        else:
            uvi = fnum(row, "peak_uv_index")
            if pd.notna(uvi):
                parts.append(f"UV index {uvi:g}")
            uva = fnum(row, "peak_predicted_uva_wm2")
            if pd.notna(uva):
                parts.append(f"UVA {uva:g} W/m2")
        for label, col, fmt, suf in (
            ("TanDose window", "tan_dose_best_window_j_m2", "g", " J/m2 mel"),
            ("TanDose day", "tan_dose_day_j_m2", "g", " J/m2 mel"),
            ("SED window", "sed_best_window", "g", ""),
            ("SED day", "sed_day_total", "g", ""),
            ("UVA day", "uva_dose_day_j_m2", "g", " J/m2"),
            ("UVB day", "uvb_dose_day_j_m2", "g", " J/m2"),
            ("Confidence", "day_confidence_at_peak_0_100", ".0f", ""),
        ):
            v = _fmt_opt(row.get(col), fmt, suf)
            if v is not None:
                parts.append(f"{label} {v}")
        status = str(row.get("day_status") or "").strip()
        if status and status.lower() != "nan":
            parts.append(status)
        parts.append("Times refresh with each SunStack run.")
        desc = ". ".join(parts)
        if uv.get("uvi"):
            summary = f"Best sun {_ics_hhmm(start, tz_name)}-{_ics_hhmm(end, tz_name)} (UV {uv['uvi']}, overall {peak_s})"
        else:
            summary = f"Best sun {_ics_hhmm(start, tz_name)}-{_ics_hhmm(end, tz_name)} (overall {peak_s})"
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


HTML = r"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Sunlight hours — SunStack</title>
<link rel="icon" href="data:,">
<style>
:root{--paper:#faf6ee;--ink:#211c12;--muted:#6f6553;--line:#e2d7bf;--sun:#b25e00;--sunwash:#f6e3bd;--ok:#2e7d46;--mid:#b07d00;--low:#c25a1e;--poor:#9a938a}
*{box-sizing:border-box}body{margin:0;background:var(--paper);color:var(--ink);font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Helvetica,Arial,sans-serif}
.wrap{max-width:1120px;margin:0 auto;padding:28px 22px 60px;text-align:left}
.top{display:flex;gap:16px;align-items:flex-end;justify-content:space-between;flex-wrap:wrap;border-bottom:2px solid var(--ink);padding-bottom:16px}
h1{font-family:Georgia,"Times New Roman",serif;font-weight:600;font-size:34px;margin:0}
.sub{color:var(--muted);font-size:13px;margin-top:4px}
.controls{display:flex;gap:8px;align-items:center;flex-wrap:wrap;font-size:13px;color:var(--muted)}
select,input,button{font:inherit;background:#fffdf7;color:var(--ink);border:1px solid var(--line);border-radius:8px;padding:8px 10px}
.controls a.btn{font:inherit;background:#fffdf7;color:var(--ink);border:1px solid var(--line);border-radius:8px;padding:8px 10px;text-decoration:none;font-weight:600}
button{cursor:pointer;font-weight:600}button:hover{border-color:var(--sun)}
button.primary{background:var(--sun);border-color:var(--sun);color:#fff}
.hero{font-family:Georgia,serif;font-size:26px;line-height:1.35;margin:26px 0 4px;max-width:34em}
.hero b{font-weight:700}
.legend{color:var(--muted);font-size:13px;margin:0 0 6px;max-width:70em}
.strip{display:flex;gap:10px;overflow-x:auto;padding:14px 2px;margin:8px 0 4px}
.daycell{min-width:118px;text-align:left;background:#fffdf7;border:1px solid var(--line);border-radius:12px;padding:10px 12px;cursor:pointer}
.daycell .dow{font-weight:700;font-size:14px}
.daycell .dt{color:var(--muted);font-size:12px}
.daycell .pk{font-family:Georgia,serif;font-size:24px;margin-top:6px}
.daycell .uv{font-size:12px;color:var(--muted)}
.daycell .bar{height:5px;border-radius:3px;margin-top:8px;background:#eee5cf}
.daycell .bar i{display:block;height:100%;border-radius:3px}
.daycell[aria-selected="true"]{border:2px solid var(--sun);background:#fff8e8}
.daydetail{margin-top:22px}
.daydetail h2{font-family:Georgia,serif;font-weight:600;font-size:24px;margin:0 0 2px}
.bestline{font-size:15px;margin:0 0 14px}
.bestline b{color:var(--sun)}
h3{font-size:14px;margin:22px 0 8px;color:var(--muted);font-weight:600}
.tablewrap{overflow:auto;border:1px solid var(--line);border-radius:12px;background:#fffdf7}
table{border-collapse:collapse;width:100%;font-size:13px;font-variant-numeric:tabular-nums}
th,td{padding:8px 10px;border-bottom:1px solid var(--line);text-align:right;white-space:nowrap}
th:first-child,td:first-child{text-align:left;position:sticky;left:0;background:#fffdf7}
thead th{background:#f3ecdb;color:#5c5342;font-weight:600}
tr.inwindow td{background:var(--sunwash)}
tr.inwindow td:first-child{font-weight:700}
.uvdot{display:inline-block;width:9px;height:9px;border-radius:50%;margin-right:6px;vertical-align:baseline}
.note{color:var(--muted);font-size:12px}
.status{padding:10px 12px;border-radius:9px;margin:12px 0;display:none;font-size:14px}
.status.show{display:block}.error{background:#f7dfe0;color:#7c2327}.info{background:#eef0e4;color:#4c5540}
details.debug{margin-top:26px;color:var(--muted);font-size:12px}
details.debug pre{background:#f3ecdb;padding:12px;border-radius:8px;overflow:auto}
:focus-visible{outline:2px solid var(--sun);outline-offset:2px}
.sunfig{display:flex;gap:18px;align-items:flex-start;flex-wrap:wrap;background:#fffdf7;border:1px solid var(--line);border-radius:12px;padding:14px 16px;margin:0 0 14px}
.sunfig svg{flex:0 0 auto;background:#fbf7ec;border-radius:8px}
.sunfig .cap{font-size:13px;max-width:34em}
.sunfig .cap b{color:var(--sun)}
.sunfig select{margin-top:8px}
@media(max-width:640px){h1{font-size:26px}.hero{font-size:21px}.wrap{padding:18px 12px 50px}}
</style></head><body><div class="wrap">
<div class="top"><div><h1>Sunlight hours</h1><div class="sub" id="runline">Loading forecast…</div></div>
<div class="controls"><label>Location <select id="locsel"><option value="">Loading…</option></select></label><label>Skin <select id="skin"><option value="">None</option><option value="1">I</option><option value="2">II</option><option value="3">III</option><option value="4">IV</option><option value="5">V</option><option value="6">VI</option></select></label><label>My MMD <input id="mmd" type="number" min="1" step="1" placeholder="J/m²" title="Measured/estimated personal MMD in melanogenic-effective J/m²" style="width:80px"></label><label>basis <select id="mmdbasis" title="Provenance of the MMD value"><option value="">—</option><option value="MEASURED">MEASURED</option><option value="OBJECTIVE_ESTIMATE">OBJECTIVE_ESTIMATE</option><option value="COARSE_ESTIMATE">COARSE_ESTIMATE</option></select></label>
<label>Min °F <input id="mintemp" type="number" min="32" max="80" step="1" value="50" style="width:64px"></label>
<button onclick="loadData()">Apply</button><button class="primary" onclick="refreshData()">Refresh forecast</button><a id="cal" class="btn" href="/api/calendar.ics" title="Subscribe to the best-window calendar">Calendar</a><button onclick="exportVisibleCsv()">Export CSV</button></div></div>
<div id="msg" class="status"></div>
<p class="hero" id="hero">Finding the best light…</p>
<p class="legend">Overall blends four readings: absolute strength worldwide, how rare it is for this location, air clarity, and forecast confidence. UV is the raw index; clear is the cloud-free value.</p>
<div class="strip" id="strip" role="tablist" aria-label="Days"></div>
<div class="daydetail" id="doses"><h3>Doses — intensity vs accumulated exposure</h3><div id="doserow" class="note">Loading doses…</div><div id="provenance" class="note"></div></div>
<div class="daydetail" id="charts"><h3>Day charts (separate panels — SED is exposure, never “good”)</h3><canvas id="chartScore" width="640" height="150" style="width:100%;border:1px solid var(--line);border-radius:8px;background:#fffdf7"></canvas><canvas id="chartDose" width="640" height="120" style="width:100%;border:1px solid var(--line);border-radius:8px;background:#fffdf7;margin-top:8px"></canvas><canvas id="chartSed" width="640" height="120" style="width:100%;border:1px solid var(--line);border-radius:8px;background:#fffdf7;margin-top:8px"></canvas><div class="note">Instantaneous TanScore (top), cumulative TanDose melanogenic J/m² (middle), cumulative SED (bottom). Optional pigment-darkening shown in tables, not merged into TanScore.</div></div>
<div class="sunfig" id="sunfigwrap"><svg id="sunfig" width="300" height="190" role="img" aria-label="Sun position and recline figure"></svg><div class="cap"><div id="suncap">Pick a time to see the sun position and posture.</div><label>Time <select id="sunsel"></select></label><div class="note">Legs stay flat, parallel to the ground — only the torso lifts. Click any table row to inspect that time. Guidance is geometry context, not a score.</div></div></div><div class="daydetail" id="detail"></div>
<details class="debug"><summary>Source data</summary><pre id="debugtext">Loading…</pre></details>
</div><script>
function dayLo(list,key){key=key||'temperature_2m';let m=null;for(const x of list||[]){const v=+x[key];if(!Number.isNaN(v)&&(m==null||v<m))m=v;}return m;}function dayHi(list,key){key=key||'temperature_2m';let m=null;for(const x of list||[]){const v=+x[key];if(!Number.isNaN(v)&&(m==null||v>m))m=v;}return m;}function peakOf(list,key){let m=null;for(const x of list||[]){const v=+x[key];if(!Number.isNaN(v)&&(m==null||v>m))m=v;}return m;}
function fmtTime(s){if(!s)return 'unknown time';const d=new Date(s);return Number.isNaN(d)?s:d.toLocaleString([],{weekday:'short',month:'short',day:'numeric',hour:'numeric',minute:'2-digit'});}
const f0=n=>n==null||Number.isNaN(+n)?'—':Math.round(+n);
const f1=n=>n==null||Number.isNaN(+n)?'—':(+n).toFixed(1);
const f2=n=>n==null||Number.isNaN(+n)?'—':(+n).toFixed(2);
const esc=s=>String(s==null?'':s).replace(/[&<>"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));
const uvColor=v=>v==null||Number.isNaN(+v)?'#c9c0ab':+v<3?'#4d9e5f':+v<6?'#dfa700':+v<8?'#e07b00':+v<11?'#d33f27':'#7b4bd6';
const scoreColor=v=>+v>=65?'var(--ok)':+v>=40?'var(--mid)':+v>=20?'var(--low)':'var(--poor)';
function hhmm(s){const m=/T(\d\d):(\d\d)/.exec(s||'');if(!m)return '—';let h=+m[1];const ap=h<12?'AM':'PM';h=h%12||12;return m[2]==='00'?`${h} ${ap}`:`${h}:${m[2]} ${ap}`;}
function dayName(ds){const d=new Date(ds+'T12:00:00');return Number.isNaN(d)?ds:d.toLocaleDateString([],{weekday:'long',month:'long',day:'numeric'});}
function shortDay(ds){const d=new Date(ds+'T12:00:00');return Number.isNaN(d)?ds:d.toLocaleDateString([],{weekday:'short'})+', '+d.toLocaleDateString([],{month:'numeric',day:'numeric'});}
function winStr(a,b){return a?`${hhmm(a)} – ${b?hhmm(b):'…'}`:'—';}
let DATA=null,SEL=null,LOC="";
async function loadLocs(){try{let j=null;for(const u of ['./locations.json','/api/locations']){try{const r=await fetch(u);if(r.ok){j=await r.json();break;}}catch(e){}}const dd=document.getElementById("locsel");if(!dd||!j)return;dd.innerHTML=(j.locations||[]).map(l=>`<option value="${esc(l.slug)}"${(l.current||(!l.url&&l.default))?" selected":""}${l.url?` data-url="${esc(l.url)}"`:''}>${esc(l.name)}</option>`).join("");LOC=dd.value;dd.addEventListener("change",()=>{const o=dd.selectedOptions[0];if(o&&o.dataset.url){location.href=o.dataset.url;return;}LOC=dd.value;SEL=null;loadData();});}catch(e){}}
async function init(){await loadLocs();await loadData();}
async function loadData(){show('Loading…','info');try{const s=document.getElementById('skin').value,m=document.getElementById('mintemp').value,p=document.getElementById('mmd').value,b=document.getElementById('mmdbasis').value;const r=await fetch(`/api/data?skin_type=${s}&min_temp=${m}&personal_mmd=${p}&personal_mmd_basis=${b}&location=${encodeURIComponent(LOC)}`);const j=await r.json();if(!r.ok)throw new Error(j.detail||'Request failed');DATA=j;hide();render();}catch(e){show('Could not load forecast: '+e.message+'. Check the server log, then Refresh.','error');}}
async function refreshData(){show('Calling live Open-Meteo and CAMS, rebuilding scores (takes minutes)…','info');try{const s=document.getElementById('skin').value,m=document.getElementById('mintemp').value,p=document.getElementById('mmd').value,b=document.getElementById('mmdbasis').value;const r=await fetch(`/api/refresh?skin_type=${s}&min_temp=${m}&personal_mmd=${p}&personal_mmd_basis=${b}&location=${encodeURIComponent(LOC)}`,{method:'POST'});const j=await r.json();if(!r.ok)throw new Error(j.detail||'Refresh failed');show('Refresh complete.','info');await loadData();}catch(e){show('Refresh failed: '+e.message,'error');}}
function exportVisibleCsv(){if(!DATA||!DATA.daily||!DATA.daily.length){show('No forecast data yet.','error');return;}const q=v=>(/[,"\n]/.test(String(v??''))?'"'+String(v??'').replace(/"/g,'""')+'"':String(v??''));const dl=(name,rows)=>{const csv=rows.map(r=>r.map(q).join(',')).join('\n');const b=new Blob([csv],{type:'text/csv'});const a=document.createElement('a');a.href=URL.createObjectURL(b);a.download=name;document.body.appendChild(a);a.click();setTimeout(()=>{URL.revokeObjectURL(a.href);a.remove();},500);};const hours=DATA.hourly||[],half=DATA.half_hour||[];const hHead=['time','uv_index','uv_index_clear_sky','predicted_uva_wm2','predicted_uvb_wm2','melanogenic_effective_irradiance_wm2','erythemal_irradiance_wm2','pigment_darkening_effective_irradiance','temperature_2m','apparent_temperature','wind_speed_10m','wind_gusts_10m','cloud_cover','precipitation_probability','direct_normal_irradiance_instant','overall_tan_opportunity_0_100','tan_score_absolute_0_100','legacy_absolute_tan_score_55_30_15','local_tan_score_0_100','atmospheric_quality_percentile_0_100','tan_forecast_confidence_0_100','tan_dose_1h_j_m2','sed_1h','uva_dose_1h_j_m2','uvb_dose_1h_j_m2','pigment_darkening_dose_1h_j_m2','uvi_openmeteo','uvi_cams','uvi_difference_percent','spectral_tier','tan_score_model_version','solar_elevation_deg','sun_compass','outdoor_block_reason'];dl(`sunstack-all-hourly.csv`,[hHead].concat(hours.map(x=>hHead.map(k=>x[k]))));const qHead=['time','uv_index','predicted_uva_wm2','melanogenic_effective_irradiance_wm2','tan_dose_30m_j_m2','sed_30m','pigment_darkening_dose_30m_j_m2','overall_tan_opportunity_0_100','subhour_source','spectral_tier'];dl(`sunstack-all-30min.csv`,[qHead].concat(half.map(x=>qHead.map(k=>x[k]))));const dall=DATA.daily;if(dall.length){const dHead=['date','day_status','day_overall_peak_0_100','peak_uv_index','peak_temperature_f','day_low_temperature_f','day_high_temperature_f','day_low_feels_like_f','day_high_feels_like_f','day_peak_wind_mph','day_peak_gust_mph','day_absolute_peak_0_100','day_local_peak_0_100','best_window_start','best_window_end','best_hour_start','best_hour_score_0_100','tan_dose_best_window_j_m2','sed_best_window','tan_dose_day_j_m2','sed_day_total','uva_dose_day_j_m2','uvb_dose_day_j_m2','blocked_half_hours'];dl(`sunstack-all-days.csv`,[dHead].concat(dall.map(d=>dHead.map(k=>d[k]))));}show(`Exported all ${dall.length} days (${hours.length} hourly + ${half.length} 30-min rows).`,'info');}
function show(t,c){const m=document.getElementById('msg');m.textContent=t;m.className='status show '+c;}function hide(){document.getElementById('msg').className='status';}
function renderDoses(){const d=DATA.daily.find(x=>x.date===SEL);const el=document.getElementById('doserow');if(!el||!d){return;}const half=rowsFor(DATA.half_hour,SEL);const pkIpVals=half.map(x=>x.pigment_darkening_dose_30m_j_m2).filter(v=>v!==null&&v!==undefined&&v!==''&&Number.isFinite(+v)).map(Number);const pkIp=pkIpVals.length?Math.max.apply(null,pkIpVals):null;const myFVals=half.map(x=>x.personal_mmd_fraction).filter(v=>v!==null&&v!==undefined&&v!==''&&Number.isFinite(+v)).map(Number);const myBest=myFVals.length?Math.max.apply(null,myFVals):null;const myBasis=(half.map(x=>x.personalization_basis).find(v=>v&&v!=='not personalized'))||'';el.innerHTML=`TanDose peak 30 min <b>${f1(d.best_30m_tan_dose_j_m2)} J/m² mel</b> (${d.best_30m_start?hhmm(d.best_30m_start):'—'}) · best hour <b>${f1(d.best_hour_tan_dose_j_m2)} J/m²</b> (${d.best_hour_start?hhmm(d.best_hour_start):'—'}) · best window <b>${f1(d.tan_dose_best_window_j_m2)} J/m²</b> · today <b>${f1(d.tan_dose_day_j_m2)} J/m²</b> (${f1(d.tan_dose_day_reference_minutes)} ref-min) &nbsp;|&nbsp; SED peak 30m ${f2(d.best_30m_sed)} · window ${f2(d.sed_best_window)} · today ${f2(d.sed_day_total)} &nbsp;|&nbsp; UVA day ${f1(d.uva_dose_day_j_m2)} J/m² · UVB day ${f2(d.uvb_dose_day_j_m2)} J/m² &nbsp;|&nbsp; Visible-Darkening Potential (peak 30m) ${f1(pkIp)} J/m² existing-pigment (not new melanin)${myBest==null?'':' &nbsp;|&nbsp; My MMD fraction (day max) <b>'+myBest.toFixed(2)+'</b>'+(myBasis?' ('+esc(myBasis)+')':'')}`;const pv=document.getElementById('provenance');if(pv){const s=DATA.summary||{};pv.textContent=`Model ${s.tan_score_model_version||'legacy-55-30-15 (pre-v4 data)'} · spectrum tier ${s.photobiology_action_spectrum_tier||(DATA.hourly[0]||{}).photobiology_action_spectrum_tier||'pre-v4 legacy'} · spectral ${(DATA.hourly[0]||{}).spectral_backend||s.spectral_backend||'pre-v4 broadband'} (${(DATA.hourly[0]||{}).spectral_tier||'pre-v4'}) · global ref ${s.global_reference_version||'pre-v4'} (${s.global_reference_e_mel_wm2!=null?s.global_reference_e_mel_wm2+' W/m²':'n/a'}) · CAMS ${s.cams_cycle||'?'} · UVI agree ${f1((DATA.hourly[0]||{}).uvi_difference_percent)} · calib ${(DATA.hourly[0]||{}).tan_calibration_tier||s.calibration_tier||'?'}`;}}
function drawCharts(){const hours=rowsFor(DATA.hourly,SEL);if(!hours.length)return;const line=(id,vals,color,fill)=>{const c=document.getElementById(id);if(!c)return;const x=c.getContext('2d');const W=c.width,H=c.height;x.clearRect(0,0,W,H);const v=vals.map(z=>+z);const m=Math.max(...v.filter(Number.isFinite),1e-9);x.strokeStyle='#e2d7bf';x.beginPath();x.moveTo(0,H-1);x.lineTo(W,H-1);x.stroke();x.strokeStyle=color;x.lineWidth=2;x.beginPath();v.forEach((z,i)=>{const px=i/(Math.max(v.length-1,1))*W,py=H-4-(Number.isFinite(z)?z/m:0)*(H-10);i?x.lineTo(px,py):x.moveTo(px,py);});x.stroke();if(fill){x.lineTo(W,H);x.lineTo(0,H);x.closePath();x.globalAlpha=0.15;x.fillStyle=color;x.fill();x.globalAlpha=1;}};line('chartScore',hours.map(z=>z.tan_score_absolute_0_100),'#b25e00',true);let acc=0;const cumDose=hours.map(z=>{const t=+z.tan_dose_1h_j_m2;acc+=Number.isFinite(t)?t:0;return acc;});line('chartDose',cumDose,'#2e7d46',true);let accS=0;const cumSed=hours.map(z=>{const t=+z.sed_1h;accS+=Number.isFinite(t)?t:0;return accS;});line('chartSed',cumSed,'#7b4bd6',true);}
function bestDay(){const d=(DATA.daily||[]).filter(x=>+x.day_overall_peak_0_100>0);d.sort((a,b)=>b.day_overall_peak_0_100-a.day_overall_peak_0_100);return d[0]||DATA.daily[0];}
function render(){if(!DATA||!DATA.daily||!DATA.daily.length){show('No forecast data yet. Press Refresh forecast.','error');return;}
document.getElementById('runline').textContent='Updated '+fmtTime((DATA.summary||{}).created_at)+' · '+(DATA.hourly||[]).length+' hourly rows · build '+(DATA.build_sha||'?')+' · absolute is worldwide scale, local is this location\u0027s percentile';
console.log('[sunstack] build=%s run=%s updated=%s',DATA.build_sha,DATA.run,(DATA.summary||{}).created_at);
document.getElementById('cal').href='webcal://'+location.host+'/api/calendar.ics?skin_type='+document.getElementById('skin').value+'&min_temp='+document.getElementById('mintemp').value+'&location='+encodeURIComponent(LOC);
if(!SEL||!DATA.daily.some(d=>d.date===SEL)){const today=new Date();const pad2=n=>String(n).padStart(2,'0');const tstr=`${today.getFullYear()}-${pad2(today.getMonth()+1)}-${pad2(today.getDate())}`;const tb=DATA.daily.find(d=>d.date===tstr)||bestDay();SEL=tb?tb.date:DATA.daily[0].date;}
const b=bestDay();
document.getElementById('strip').innerHTML=DATA.daily.map(d=>{const pk=+d.day_overall_peak_0_100||0;const pp=+d.peak_precip_probability_pct||0;const wet=pp>=40;return `<button class="daycell" role="tab" aria-selected="${d.date===SEL}" data-date="${d.date}"${wet?' style="border-color:#c0392b"':''}><div class="dow">${esc(shortDay(d.date))}</div><div class="dt">${esc(d.day_status||'')}${wet?` · <b style="color:#c0392b">${f0(pp)}% rain</b>`:''}</div><div class="pk" style="color:${wet?'#c0392b':scoreColor(pk)}">${f0(pk)}</div><div class="uv">UV ${f1(d.peak_uv_index??peakOf(rowsFor(DATA.hourly,d.date),'uv_index'))} · ${f1(d.day_low_temperature_f??dayLo(rowsFor(DATA.hourly,d.date)))}–${f1(d.day_high_temperature_f??dayHi(rowsFor(DATA.hourly,d.date)))}\u00b0</div><div class="uv">Feels ${f1(d.day_low_feels_like_f??dayLo(rowsFor(DATA.hourly,d.date),'apparent_temperature'))}–${f1(d.day_high_feels_like_f??dayHi(rowsFor(DATA.hourly,d.date),'apparent_temperature'))}\u00b0</div><div class="uv">Gust ${f0(d.day_peak_gust_mph??dayHi(rowsFor(DATA.hourly,d.date),'wind_gusts_10m'))}${(+d.day_peak_gust_mph>=25||+dayHi(rowsFor(DATA.hourly,d.date),'wind_gusts_10m')>=25)?` <b style="color:#c0392b">windy</b>`:''}</div><div class="uv">Abs ${f0(d.day_absolute_peak_0_100)} · Loc ${f0(d.day_local_peak_0_100)}</div><div class="bar"><i style="width:${Math.max(3,Math.min(100,pk))}%;background:${wet?'#c0392b':scoreColor(pk)}"></i></div></button>`;}).join('');
document.getElementById('hero').innerHTML=b?`Best light <b>${dayName(b.date)} ${winStr(b.best_window_start,b.best_window_end)}</b> — overall ${f0(b.day_overall_peak_0_100)}, UV ${f1(b.peak_uv_index??peakOf(rowsFor(DATA.hourly,b.date),'uv_index'))}.`:'No usable light in this run.';
document.querySelectorAll('.daycell').forEach(el=>el.addEventListener('click',()=>{SEL=el.dataset.date;render();}));
renderDay();{const rh=rowsFor(DATA.hourly,SEL),rq=rowsFor(DATA.half_hour,SEL);renderSunFig(rh,rq);}try{renderDoses();drawCharts();}catch(e){}document.getElementById('debugtext').textContent=JSON.stringify(DATA.summary||{},null,2);}
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
 o+=`<circle cx="${hdX.toFixed(1)}" cy="${hdY.toFixed(1)}" r="${headR.toFixed(1)}" fill="#fbf7ec" stroke="currentColor" stroke-width="2.2"/>`;
 return o;}
function drawSunFig(row){const svg=document.getElementById('sunfig');if(!svg||!row)return;const cx=150,cy=154,r=106;const NS='http://www.w3.org/2000/svg';while(svg.firstChild)svg.removeChild(svg.firstChild);const mk=(t,a)=>{const e=document.createElementNS(NS,t);for(const k in a)e.setAttribute(k,a[k]);svg.appendChild(e);return e;};mk('line',{x1:16,y1:cy-4,x2:284,y2:cy-4,stroke:'#c9bfa8','stroke-width':1.5});mk('text',{x:248,y:cy-18,'font-size':10,fill:'#6f6553'}).textContent='ground';const elev=+row.solar_elevation_deg,az=+row.solar_azimuth_deg;const lift=+(row.torso_lift_deg||0);if(!(elev>0)){mk('text',{x:cx,y:64,'text-anchor':'middle','font-size':13,fill:'#6f6553'}).textContent='sun below horizon';mk('text',{x:cx,y:82,'text-anchor':'middle','font-size':11,fill:'#6f6553'}).textContent='no direct-sun posture';const g=document.createElementNS(NS,'g');g.setAttribute('transform',`translate(${cx+8},${cy-4})`);g.setAttribute('color','#9a938a');g.innerHTML=stickFigure(0,0,56,0,1);svg.appendChild(g);return;}const cdeg=compassDeg(row.sun_compass);const azUse=cdeg==null?(Number.isNaN(az)?180:az):cdeg;const[sx,sy]=figXY(cx,cy-4,r,elev,azUse);const sun=mk('circle',{cx:sx,cy:sy,r:9.5,fill:'#e8a100',stroke:'#b25e00','stroke-width':2});sun.appendChild(document.createElementNS(NS,'title')).textContent=`sun ${elev.toFixed(0)}° up, ${row.sun_compass||''}`;const dir=sx>=cx?1:-1;const lr=lift*Math.PI/180,tL=56*0.66,chX=cx+dir*tL*0.5*Math.cos(lr),chY=(cy-4)-tL*0.5*Math.sin(lr);const rdx=sx-chX,rdy=sy-chY,rlen=Math.hypot(rdx,rdy)||1,rex=sx-rdx/rlen*12.5,rey=sy-rdy/rlen*12.5;mk('line',{x1:chX.toFixed(1),y1:chY.toFixed(1),x2:rex.toFixed(1),y2:rey.toFixed(1),stroke:'#b25e00','stroke-width':1.2,'stroke-dasharray':'4 3',opacity:0.7});const g=document.createElementNS(NS,'g');g.setAttribute('transform',`translate(${cx},${cy-4})`);g.setAttribute('color','#211c12');g.innerHTML=stickFigure(0,0,56,lift,dir);svg.appendChild(g);mk('text',{x:cx,y:cy+22,'text-anchor':'middle','font-size':10,fill:'#6f6553'}).textContent=`face ${row.sun_compass||'—'} · torso ~${Math.round(lift)}°`;const cap=document.getElementById('suncap');if(cap)cap.innerHTML=`<b>${hhmm(row.time)}</b> — ${esc(row.sun_posture_guidance||'')} (UV ${f1(row.uv_index)}, overall ${f0(row.overall_tan_opportunity_0_100)})`;}
function pickSunRow(hours,half){const all=(half||[]).concat(hours||[]).filter(x=>+x.solar_elevation_deg>0);if(!all.length)return (hours||[])[0]||null;let best=null,bs=-1;for(const x of all){const v=+x.overall_tan_opportunity_0_100;if(!Number.isNaN(v)&&v>bs){bs=v;best=x;}}return best;}
function renderSunFig(hours,half){const sel=FIG.sel;const list=(half||[]).concat(hours||[]);let row=list.find(x=>x.time===sel)||pickSunRow(hours,half);if(!row)return;FIG.sel=row.time;drawSunFig(row);const opts=list.filter(x=>+x.solar_elevation_deg>0);const dd=document.getElementById('sunsel');if(dd){const cur=dd.value;dd.innerHTML=opts.map(x=>`<option value="${esc(x.time)}"${x.time===row.time?' selected':''}>${hhmm(x.time)} — sun ${f0(x.solar_elevation_deg)}° ${esc(x.sun_compass||'')}</option>`).join('');if(![...dd.options].some(o=>o.value===cur))dd.value=row.time;}}
function rowsFor(list,date){return (list||[]).filter(x=>(x.time||'').slice(0,10)===date).sort((a,b)=>String(a.time).localeCompare(String(b.time)));}
function inWin(t,a,c){t=String(t||'').slice(0,16);a=String(a||'').slice(0,16);c=String(c||'').slice(0,16);return a&&(!c||t<c)&&t>=a?true:false;}
function disagreeNote(x){return [x.outdoor_block_reason,x.uv_input_disagree?'UV/broadband inputs disagree on cloud':''].filter(Boolean).join(' · ');}
let FIG=sunFigState();
function renderDay(){const d=DATA.daily.find(x=>x.date===SEL);if(!d)return;const el=document.getElementById('detail');
const hours=rowsFor(DATA.hourly,SEL),half=rowsFor(DATA.half_hour,SEL);
const uvRows=hours.filter(x=>+x.uv_index>0);
const hHtml=hours.map(x=>{const w=inWin(x.time,d.best_window_start,d.best_window_end);const note=disagreeNote(x);const pp=+x.precipitation_probability||0;const wet=pp>=40;const sun=(+x.solar_elevation_deg>0)?` <span class=\"note\">&#9728;&#xFE0E; ${f0(x.solar_elevation_deg)}° ${esc(x.sun_compass||'')}</span>`:'';const rainCell=wet?`<b style="color:#c0392b">${f0(pp)}%</b>`:`${f0(pp)}%`;return `<tr data-time="${esc(x.time)}" ${w?' class="inwindow"':''}><td>${hhmm(x.time)}</td><td><span class="uvdot" style="background:${uvColor(x.uv_index)}"></span><b>${f1(x.uv_index)}</b></td><td>${f1(x.uv_index_clear_sky)}</td><td>${f1(x.predicted_uva_wm2)}</td><td>${f2(x.predicted_uvb_wm2)}</td><td>${f1(x.temperature_2m)}°${(+x.apparent_temperature!=null&&!Number.isNaN(+x.apparent_temperature)&&Math.abs(+x.apparent_temperature-+x.temperature_2m)>=2)?` <span class="note">fl ${f1(x.apparent_temperature)}°</span>`:''}</td><td>${(+x.wind_speed_10m>=25||+x.wind_gusts_10m>=25)?`<b style="color:#c0392b">`:''}${f0(x.wind_speed_10m)}${(+x.wind_gusts_10m!=null&&!Number.isNaN(+x.wind_gusts_10m)&&+x.wind_gusts_10m>+x.wind_speed_10m+3)?` g${f0(x.wind_gusts_10m)}`:''}${(+x.wind_speed_10m>=25||+x.wind_gusts_10m>=25)?`</b>`:''}</td><td>${f0(x.cloud_cover)}%</td><td>${rainCell}</td><td>${f0(x.direct_normal_irradiance_instant)}</td><td><b>${f0(x.overall_tan_opportunity_0_100)}</b></td><td>${f0(x.tan_score_absolute_0_100)}</td><td>${f0(x.local_tan_score_0_100)}</td><td>${f0(x.atmospheric_quality_percentile_0_100)}</td><td>${f0(x.tan_forecast_confidence_0_100)}</td><td class="note">${esc(note)}${sun}</td></tr>`;}).join('');
const qHtml=half.map(x=>{const w=inWin(x.time,d.best_window_start,d.best_window_end);const uv=x.uv_index!=null?x.uv_index:x.air__uv_index;return `<tr data-time="${esc(x.time)}" ${w?' class="inwindow"':''}><td>${hhmm(x.time)}</td><td><span class="uvdot" style="background:${uvColor(uv)}"></span><b>${f1(uv)}</b></td><td>${f1(x.predicted_uva_wm2)}</td><td><b>${f0(x.overall_tan_opportunity_0_100)}</b></td><td class="note">${esc(x.subhour_source==='native_HRRR_radiation_weather_plus_interpolated_UV'?'HRRR 15-min':(x.subhour_source||'').slice(0,24)||'hourly split')}</td><td class="note">${esc(disagreeNote(x))}</td></tr>`;}).join('');
el.innerHTML=`<h2>${dayName(d.date)} <span style="color:${scoreColor(d.day_overall_peak_0_100)}">· ${f0(d.day_overall_peak_0_100)}</span> <span class="note">${esc(d.day_status||'')}</span></h2>
<p class="bestline">Best window <b>${winStr(d.best_window_start,d.best_window_end)}</b> · best hour ${hhmm(d.best_hour_start)} (${f0(d.best_hour_score_0_100)}) · peak UV ${f1(d.peak_uv_index??peakOf(hours,'uv_index'))} · ${f1(d.peak_temperature_f??peakOf(hours,'temperature_2m'))}°F · ${f0(d.blocked_half_hours)} blocked half-hours. Rows tinted below fall inside the best window.</p>
<h3>Every hour — raw UV first</h3><div class="tablewrap"><table><thead><tr><th>Time</th><th>UV</th><th>Clear</th><th>UVA</th><th>UVB</th><th>Temp</th><th>Wind</th><th>Cloud</th><th>Rain</th><th>DNI</th><th>Overall</th><th>Abs</th><th>Local</th><th>Atm</th><th>Conf</th><th>Note</th></tr></thead><tbody>${hHtml||'<tr><td colspan="16">No hourly rows for this day.</td></tr>'}</tbody></table></div>
<h3>Every 30 minutes</h3><div class="tablewrap"><table><thead><tr><th>Time</th><th>UV</th><th>UVA</th><th>Overall</th><th>Source</th><th>Note</th></tr></thead><tbody>${qHtml||'<tr><td colspan="6">No 30-minute rows for this day.</td></tr>'}</tbody></table></div>`;
 document.querySelectorAll('#detail tr[data-time]').forEach(tr=>tr.addEventListener('click',()=>{FIG.sel=tr.dataset.time;const hours=rowsFor(DATA.hourly,SEL),half=rowsFor(DATA.half_hour,SEL);renderSunFig(hours,half);}));
 const dd=document.getElementById('sunsel');if(dd&&!dd.dataset.wired){dd.dataset.wired='1';dd.addEventListener('change',()=>{FIG.sel=dd.value;const hours=rowsFor(DATA.hourly,SEL),half=rowsFor(DATA.half_hour,SEL);renderSunFig(hours,half);});}
}
init();
</script></body></html>"""


def create_app(root: Path) -> FastAPI:
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
    ):
        try:
            mmd, basis = _parse_personal_mmd(personal_mmd, personal_mmd_basis)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        try:
            st = int(skin_type) if skin_type else None
            site = _resolve_site(location or None)
            run, hourly, half, daily, summary = _filtered_payload(
                root, st, min_temp, site, mmd, basis
            )
            # Keep the UI useful: daylight-ish hours only, but source files retain everything.
            ht = pd.to_datetime(scol(hourly, "time"))
            hourly_ui = hourly.loc[(ht.dt.hour >= 7) & (ht.dt.hour <= 20)].copy()
            qt = pd.to_datetime(scol(half, "time"))
            half_ui = half.loc[(qt.dt.hour >= 7) & (qt.dt.hour <= 20)].copy()
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
    ):
        try:
            mmd, basis = _parse_personal_mmd(personal_mmd, personal_mmd_basis)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        try:
            from .cli import run_live

            st = int(skin_type) if skin_type else None
            site = _resolve_site(location or None)
            result = run_live(
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
    ):
        try:
            st = int(skin_type) if skin_type else None
            site = _resolve_site(location or None)
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
) -> None:
    import uvicorn

    host = host or config.UI_HOST
    port = int(port or config.UI_PORT)
    if open_browser:
        threading.Timer(0.8, lambda: webbrowser.open(f"http://{host}:{port}")).start()
    uvicorn.run(create_app(root), host=host, port=port, log_level="info")
