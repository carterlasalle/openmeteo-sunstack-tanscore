from __future__ import annotations

import json
from pathlib import Path

import pandas as pd


def _swap_once(text: str, old: str, new: str) -> str:
    found = text.count(old)
    if found != 1:
        raise RuntimeError(f"static export anchor drifted ({found}x): {old[:70]!r}")
    return text.replace(old, new)


def render_static_html(run_tag: object = "", min_temp_f: float = 50.0) -> str:
    """Static index.html from the live template. Pure HTML: needs no run data.

    site-refresh renders UI-only updates from committed docs/ with this, so a
    fresh checkout without data/latest can still republish the page.
    """
    from .ui import HTML

    html = HTML
    html = _swap_once(
        html,
        "fetch(`/api/data?skin_type=${s}&min_temp=${m}&location=${encodeURIComponent(LOC)}`)",
        "fetch('./data.json')",
    )
    try:
        html = _swap_once(html, "init();\n</script>", "init();initSkin();\n</script>")
    except RuntimeError:
        html = _swap_once(
            html, "loadData();\n</script>", "loadData();initSkin();\n</script>"
        )
    run_stamp = "".join(c for c in str(run_tag) if c.isdigit()) or "0"
    html = _swap_once(
        html,
        '<label>Min °F <input id="mintemp" type="number" min="32" max="80" step="1" value="50" style="width:64px"></label>\n',
        "",
    )
    html = _swap_once(
        html,
        '<button onclick="loadData()">Apply</button><button class="primary" onclick="refreshData()">Refresh forecast</button>',
        f'<span class="note">Static export · min {min_temp_f:g}°F · reruns publish fresh data</span>',
    )
    html = _swap_once(
        html,
        '<div class="daydetail" id="detail"></div>',
        '<p class="legend" id="skinnote" style="display:none"></p><div class="daydetail" id="detail"></div>',
    )
    html = _swap_once(
        html,
        "async function loadData(){",
        "let SKIN=null;async function initSkin(){try{const r=await fetch('./skin.json');SKIN=await r.json();}catch(e){SKIN=null;}const el=document.getElementById('skin');if(el){el.addEventListener('change',showSkin);showSkin();}}function showSkin(){const el=document.getElementById('skin');const box=document.getElementById('skinnote');if(!el||!box||!SKIN)return;const info=SKIN[el.value||''];if(!info){box.style.display='none';return;}box.textContent=info.fitzpatrick_label+': '+info.skin_response_note;box.style.display='';}async function loadData(){",
    )
    html = _swap_once(
        html,
        "const s=document.getElementById('skin').value,m=document.getElementById('mintemp').value;const r=await fetch('./data.json');",
        f"const s=document.getElementById('skin').value,m='50';const r=await fetch('./data.json?v={run_stamp}');",
    )
    html = _swap_once(
        html,
        "document.getElementById('cal').href='webcal://'+location.host+'/api/calendar.ics"
        "?skin_type='+document.getElementById('skin').value+'&min_temp='+document.getElementById('mintemp').value+'&location='+encodeURIComponent(LOC);",
        "var calEl=document.getElementById('cal');if(calEl){var p=location.pathname;"
        "p=p.slice(0,p.lastIndexOf('/')+1);calEl.href='webcal://'+location.host+p+'calendar.ics';}",
    )
    return html


def reskin_static_dir(
    page_dir: Path | str, site_slug: str | None = None
) -> dict[str, object]:
    """Re-render a committed static page dir in place. No run data needed.

    Reads the committed data.json payload (run tag + rows already in docs/),
    rewrites index.html from the current template, stamps data.json build_sha,
    and refreshes locations.json + skin.json. calendar.ics is data-derived so
    it is left alone — rebuilding it from the daylight-filtered payload rows
    would degrade the UV peaks vs the full-hourly build in export_static_site.
    """
    from .opportunity import fitzpatrick_context
    from .ui import _resolve_site, _site_nav, build_sha

    page = Path(page_dir)
    payload: dict[str, object] = json.loads(
        (page / "data.json").read_text(encoding="utf-8")
    )
    summary = payload.get("summary")
    run_tag = summary.get("run", "") if isinstance(summary, dict) else ""
    site = _resolve_site(site_slug)
    (page / "index.html").write_text(render_static_html(run_tag), encoding="utf-8")
    payload["build_sha"] = build_sha()
    (page / "data.json").write_text(json.dumps(payload), encoding="utf-8")
    (page / "locations.json").write_text(
        json.dumps({"locations": _site_nav(site.slug)}), encoding="utf-8"
    )
    (page / "skin.json").write_text(
        json.dumps({str(i): fitzpatrick_context(i) for i in range(1, 7)}),
        encoding="utf-8",
    )
    return {"page": str(page), "run": run_tag, "build_sha": payload["build_sha"]}


def export_static_site(
    root: Path,
    out_dir: Path,
    skin_type: int | None = None,
    min_temp_f: float = 50.0,
    site_slug: str | None = None,
) -> dict[str, object]:
    """Publish the latest run as a static site: index + data + calendar.

    template replacement asserts a unique anchor, so live-UI drift fails
    loudly here instead of shipping a subtly broken page.
    """
    from . import config
    from .calibrate import scol
    from .opportunity import fitzpatrick_context
    from .ui import (
        _filtered_payload,
        _records,
        _resolve_site,
        _site_nav,
        build_calendar_ics,
        build_sha,
    )

    site = _resolve_site(site_slug)
    entered = config.use_site(site)
    entered.__enter__()
    try:
        run, hourly, half, daily, summary = _filtered_payload(
            root, skin_type, min_temp_f, site
        )
    finally:
        entered.__exit__(None, None, None)
    ht = pd.to_datetime(scol(hourly, "time"))
    hourly_ui = hourly.loc[(ht.dt.hour >= 7) & (ht.dt.hour <= 20)].copy()
    qt = pd.to_datetime(scol(half, "time"))
    half_ui = half.loc[(qt.dt.hour >= 7) & (qt.dt.hour <= 20)].copy()
    payload: dict[str, object] = {
        "run": str(run),
        "daily": _records(daily),
        "hourly": _records(hourly_ui),
        "half_hour": _records(half_ui),
        "summary": summary,
        "build_sha": build_sha(),
    }
    html = render_static_html(summary.get("run", ""), min_temp_f)
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "index.html").write_text(html, encoding="utf-8")
    (out_dir / "data.json").write_text(json.dumps(payload), encoding="utf-8")
    (out_dir / "locations.json").write_text(
        json.dumps({"locations": _site_nav(site.slug)}), encoding="utf-8"
    )
    (out_dir / "skin.json").write_text(
        json.dumps({str(i): fitzpatrick_context(i) for i in range(1, 7)}),
        encoding="utf-8",
    )
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
