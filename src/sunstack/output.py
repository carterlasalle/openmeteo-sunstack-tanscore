from __future__ import annotations

import json
from pathlib import Path

import pandas as pd


def _swap_once(text: str, old: str, new: str) -> str:
    found = text.count(old)
    if found != 1:
        raise RuntimeError(f"static export anchor drifted ({found}x): {old[:70]!r}")
    return text.replace(old, new)


def export_static_site(
    root: Path, out_dir: Path, skin_type: int | None = None, min_temp_f: float = 50.0
) -> dict[str, object]:
    """Publish the latest run as a static site: index + data + calendar.

    Same payload shape as GET /api/data for the default UI view. Every
    template replacement asserts a unique anchor, so live-UI drift fails
    loudly here instead of shipping a subtly broken page.
    """
    from .calibrate import scol
    from .ui import HTML, _filtered_payload, _records, build_calendar_ics

    run, hourly, half, daily, summary = _filtered_payload(root, skin_type, min_temp_f)
    ht = pd.to_datetime(scol(hourly, "time"))
    hourly_ui = hourly.loc[(ht.dt.hour >= 7) & (ht.dt.hour <= 20)].copy()
    qt = pd.to_datetime(scol(half, "time"))
    half_ui = half.loc[(qt.dt.hour >= 7) & (qt.dt.hour <= 20)].copy()
    payload = {
        "run": str(run),
        "daily": _records(daily),
        "hourly": _records(hourly_ui),
        "half_hour": _records(half_ui),
        "summary": summary,
    }
    html = HTML
    html = _swap_once(html, "fetch(`/api/data?skin_type=${s}&min_temp=${m}`)", "fetch('./data.json')")
    run_stamp = "".join(c for c in str(summary.get("run", "")) if c.isdigit()) or "0"
    start = html.index('<div class="controls">')
    end_marker = "Calendar</a></div></div>"
    if html.count(end_marker) != 1:
        raise RuntimeError("static export anchor drifted: controls block end")
    end = html.index(end_marker) + len(end_marker)
    skin_label = "None" if skin_type is None else str(skin_type)
    html = (
        html[:start]
        + f'<div class="controls"><span class="note">Static export · skin {skin_label} · '
        + f"min {min_temp_f:g}°F · reruns publish fresh data</span>"
        + '<a id="cal" class="btn" href="./calendar.ics" '
        + 'title="Subscribe to the best-window calendar">Calendar</a></div></div>'
        + html[end:]
    )
    html = _swap_once(
        html,
        "const s=document.getElementById('skin').value,m=document.getElementById('mintemp').value;const r=await fetch('./data.json');",
        f"const s='',m='';const r=await fetch('./data.json?v={run_stamp}');",
    )
    html = _swap_once(
        html,
        "document.getElementById('cal').href='webcal://'+location.host+'/api/calendar.ics"
        "?skin_type='+document.getElementById('skin').value+'&min_temp='+document.getElementById('mintemp').value;",
        "var calEl=document.getElementById('cal');if(calEl){var p=location.pathname;"
        "p=p.slice(0,p.lastIndexOf('/')+1);calEl.href='webcal://'+location.host+p+'calendar.ics';}",
    )
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "index.html").write_text(html, encoding="utf-8")
    (out_dir / "data.json").write_text(json.dumps(payload), encoding="utf-8")
    (out_dir / "calendar.ics").write_text(
        build_calendar_ics(daily, str(summary.get("run", "")), hourly), encoding="utf-8"
    )
    starts = daily.get("best_window_start")
    return {
        "out_dir": str(out_dir),
        "hourly_rows": len(hourly_ui),
        "half_rows": len(half_ui),
        "days": len(daily),
        "events": int(starts.notna().sum()) if starts is not None else 0,
    }


def write_frame(frame: pd.DataFrame, out_dir: Path, name: str) -> None:
    if frame.empty:
        return
    out_dir.mkdir(parents=True, exist_ok=True)
    frame.to_parquet(out_dir / f"{name}.parquet", index=False)
    frame.to_csv(out_dir / f"{name}.csv", index=False)


def write_excel(sheets: dict[str, pd.DataFrame], path: Path) -> None:
    usable = {name: df for name, df in sheets.items() if not df.empty}
    if not usable:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    # xlsxwriter is intentionally not a dependency; pandas will use openpyxl if
    # installed. We avoid making XLSX mandatory because CSV+Parquet are lossless and
    # much better for the very wide/member-heavy tables.
    try:
        with pd.ExcelWriter(path) as writer:
            for name, df in usable.items():
                # Excel has a 1,048,576-row limit; cap only the convenience workbook.
                df.head(1_000_000).to_excel(writer, sheet_name=name[:31], index=False)
    except ImportError:
        pass
