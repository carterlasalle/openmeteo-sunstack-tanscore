from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path
from typing import cast

import pandas as pd


def swap_once(text: str, old: str, new: str) -> str:
    found = text.count(old)
    if found != 1:
        raise RuntimeError(f"static export anchor drifted ({found}x): {old[:70]!r}")
    return text.replace(old, new)


def _surface_payload() -> dict[str, dict[str, object]]:
    from .surface import PRESETS

    fields = (
        "display_name",
        "proxy_reflectance",
        "reflectance_low",
        "reflectance_high",
        "spectral_quality",
        "optical_model",
    )
    return {
        slug: {field: getattr(profile, field) for field in fields}
        for slug, profile in PRESETS.items()
    }


def render_static_html(run_tag: object = "", min_temp_f: float = 50.0) -> str:
    """Static index.html from the live template. Pure HTML: needs no run data.

    site-refresh renders UI-only updates from committed docs/ with this, so a
    fresh checkout without data/latest can still republish the page.
    """
    from . import serving as _serving_mod

    html = _serving_mod.HTML
    # Anchor on the one-line url helper rather than the query string: the live
    # page builds its query with URLSearchParams, so there is no literal URL to
    # match, and this stays stable as query parameters come and go.
    html = swap_once(
        html,
        "function apiUrl(qs){return '/api/data?'+qs;}",
        "function apiUrl(qs){return './data.json';}",
    )
    try:
        html = swap_once(
            html, "init();\n</script>", "init().then(initSkin);\n</script>"
        )
    except RuntimeError:
        html = swap_once(
            html,
            "loadData();\n</script>",
            "loadData().then(initSkin);\n</script>",
        )
    run_stamp = "".join(c for c in str(run_tag) if c.isdigit()) or "0"
    # Run-stamped fetch: a republished page must not serve a cached data.json.
    # The stamp rides the swapped helper, since every fetch goes through it.
    html = swap_once(
        html, "return './data.json';", f"return './data.json?v={run_stamp}';"
    )
    html = swap_once(
        html,
        '<label>Min °F <input id="mintemp" type="number" min="32" max="80" step="1" value="50" style="width:64px"></label>',
        f'<input id="mintemp" type="hidden" value="{min_temp_f:g}">',
    )
    html = swap_once(
        html,
        '<button onclick="loadData()">Apply</button></div><div class="controls actions" role="group" aria-label="Actions"><button class="primary livereq" onclick="refreshData()">Refresh forecast</button>',
        f'</div><div class="controls actions" role="group" aria-label="Actions"><span class="note">Static export · min {min_temp_f:g}°F · reruns publish fresh data</span>',
    )
    html = swap_once(
        html,
        '<div class="daydetail" id="detail"></div>',
        '<p class="legend" id="skinnote" style="display:none"></p><div class="daydetail" id="detail"></div>',
    )
    html = swap_once(
        html,
        "async function loadData(){",
        (
            "let SKIN=null,SURFACES=null;"
            "async function initSkin(){try{const r=await fetch('./skin.json');SKIN=await r.json();}catch(e){SKIN=null;}"
            "try{const r=await fetch('./surfaces.json');SURFACES=await r.json();}catch(e){SURFACES=null;}"
            "if(SURFACES)window.__staticSurface=true;"
            "const skin=document.getElementById('skin');if(skin)skin.addEventListener('change',showSkin);"
            "const surfaceSel=document.getElementById('surface');if(surfaceSel)surfaceSel.title=(surfaceSel.title||'')+' Static page: local client-side reflection only; broad/homogeneous extent needs backend RT.';"
            "for(const id of ['surface','skintilt','skinaz']){const el=document.getElementById(id);if(el)el.addEventListener('change',showSurface);}"
            "showSkin();showSurface();}"
            "function showSkin(){const el=document.getElementById('skin'),box=document.getElementById('skinnote');if(!el||!box||!SKIN)return;"
            "const info=SKIN[el.value||''];if(!info){box.style.display='none';return;}"
            "box.textContent=info.fitzpatrick_label+': '+info.skin_response_note;box.style.display='';}"
            "function surfaceBox(){const pv=document.getElementById('provenance');if(!pv)return null;let s=document.getElementById('surfacecontext');"
            "if(!s){s=document.createElement('span');s.id='surfacecontext';pv.insertBefore(document.createTextNode(' · '),pv.firstChild);pv.insertBefore(s,pv.firstChild);}return s;}"
            "function showSurface(){const box=surfaceBox(),el=document.getElementById('surface');if(!box||!el||!SURFACES||!DATA)return;"
            "const info=SURFACES[el.value||''];if(!info)return;const row=rowsFor(DATA.hourly,SEL)[0]||((DATA.hourly||[])[0]||{}),name=info.display_name||el.value,s=DATA.summary||{};"
            "const tail=' · spectral '+esc(row.spectral_backend||s.spectral_backend||'—')+' (tier '+esc(row.spectral_tier||s.photobiology_action_spectrum_tier||'—')+') · fusion '+esc(s.fusion_version||'—')+' · confidence '+esc(s.confidence_version||'—')+' · rank '+esc(s.window_rank_version||'—');"
            "if(row.surface_extent_mode==='broad'){box.textContent='Surface '+name+' · broad extent requires backend RT'+tail;return;}"
            "const rawTilt=+((document.getElementById('skintilt')||{}).value||0),tilt=Number.isFinite(rawTilt)?Math.max(0,Math.min(180,rawTilt)):0,azimuth=(document.getElementById('skinaz')||{}).value||'180';"
            "let ghi=+row.shortwave_radiation;if(!Number.isFinite(ghi)){const direct=+row.direct_radiation,diffuse=+row.diffuse_radiation;ghi=(Number.isFinite(direct)?direct:0)+(Number.isFinite(diffuse)?diffuse:0);}"
            "const reflected=ghi*(+info.proxy_reflectance)*((1-Math.cos(tilt*Math.PI/180))/2);"
            "box.textContent='Surface '+name+' (client-side) · proxy '+((+info.proxy_reflectance)*100).toFixed(2)+'% · reflected context '+f2(reflected)+' W/m² broadband proxy · tilt '+tilt+'° azimuth '+azimuth+'°'+tail;}"
            "async function loadData(){"
        ),
    )
    # Static export keeps the live fetch shape (./data.json via the first
    # anchor above); the surface selector stays visible and recomputes
    # skin-plane reflection client-side from serialized components.
    # Static surface controls only update the reflected-context provenance;
    # broad homogeneous surfaces require backend radiative transfer.
    html = swap_once(
        html,
        "function calUrl(qs){return 'webcal://'+location.host+'/api/calendar.ics?'+qs;}",
        "function calUrl(qs){var p=location.pathname;"
        + "p=p.slice(0,p.lastIndexOf('/')+1);return 'webcal://'+location.host+p+'calendar.ics';}",
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
    from .build_sha import build_sha
    from .opportunity import fitzpatrick_context
    from .serving import resolve_site, site_nav

    page = Path(page_dir)
    payload = cast("dict[str, object]", json.loads((page / "data.json").read_text(encoding="utf-8")))
    # The committed payload's summary is only known to be a mapping at runtime;
    # widen once so the guards below stay reachable for the checker.
    raw_summary: object = payload.get("summary")
    summary = (
        cast("dict[str, object]", raw_summary) if isinstance(raw_summary, dict) else None
    )
    run_tag = summary.get("run", "") if summary is not None else ""
    site = resolve_site(site_slug)
    _ = (page / "index.html").write_text(render_static_html(run_tag), encoding="utf-8")
    # Provenance guard: a reskin renders UI only. It must NEVER rewrite the
    # forecast identity stamped at generation time. The old code overwrote
    # build_sha here, letting a page claim a code revision that never
    # generated its rows (shipped bug: ed14cad stamp on old-median rows).
    if summary is not None:
        summary["renderer_code_sha"] = build_sha()
        if "forecast_code_sha" not in summary:
            summary["forecast_code_sha"] = summary.get(
                "forecast_generated_by", "unknown")
    payload["build_sha"] = (summary.get("forecast_code_sha")
                            if summary is not None else build_sha())
    _ = (page / "data.json").write_text(json.dumps(payload), encoding="utf-8")
    _ = (page / "locations.json").write_text(
        json.dumps({"locations": site_nav(site.slug)}), encoding="utf-8"
    )
    _ = (page / "skin.json").write_text(
        json.dumps({str(i): fitzpatrick_context(i) for i in range(1, 7)}),
        encoding="utf-8",
    )
    _ = (page / "surfaces.json").write_text(
        json.dumps(_surface_payload()), encoding="utf-8"
    )
    return {"page": str(page), "run": run_tag, "build_sha": payload["build_sha"]}


def export_static_site(
    root: Path,
    out_dir: Path,
    skin_type: int | None = None,
    min_temp_f: float = 50.0,
    site_slug: str | None = None,
    personal_mmd_j_m2: float | None = None,
    personal_mmd_basis: str | None = None,
) -> dict[str, object]:
    """Publish the latest run as a static site: index + data + calendar.

    template replacement asserts a unique anchor, so live-UI drift fails
    loudly here instead of shipping a subtly broken page.

    Personal MMD is baked only when explicitly supplied (like skin_type);
    the default export carries no personal data.
    """
    from . import config
    from .build_sha import build_sha
    from .opportunity import fitzpatrick_context
    from .serving import (
        build_calendar_ics,
        build_interval_ics,
        daylight_payload_rows,
        filtered_payload,
        records,
        resolve_site,
        site_nav,
    )
    site = resolve_site(site_slug)
    entered = config.use_site(site)
    _ = entered.__enter__()
    try:
        run, hourly, half, daily, summary = filtered_payload(
            root, skin_type, min_temp_f, site,
            personal_mmd_j_m2, personal_mmd_basis,
        )
    finally:
        _ = entered.__exit__(None, None, None)
    hourly_ui = daylight_payload_rows(hourly)
    half_ui = daylight_payload_rows(half)
    # filtered_payload returns a summary mapping; the runtime check stays (a
    # mocked/stale caller could hand back something else) via a widened cast.
    raw_summary = cast(object, summary)
    summary_map = (
        cast("dict[str, object]", raw_summary) if isinstance(raw_summary, dict) else None
    )
    if summary_map is not None:
        if "forecast_code_sha" not in summary_map:
            summary_map["forecast_code_sha"] = build_sha()
        summary_map["renderer_code_sha"] = build_sha()
    payload: dict[str, object] = {
        "run": str(run),
        "daily": records(daily),
        "hourly": records(hourly_ui),
        "half_hour": records(half_ui),
        "summary": summary,
        "build_sha": (summary_map.get("forecast_code_sha")
                      if summary_map is not None else build_sha()),
    }
    html = render_static_html(summary.get("run", ""), min_temp_f)
    out_dir.mkdir(parents=True, exist_ok=True)
    _ = (out_dir / "index.html").write_text(html, encoding="utf-8")
    _ = (out_dir / "data.json").write_text(json.dumps(payload), encoding="utf-8")
    _ = (out_dir / "locations.json").write_text(
        json.dumps({"locations": site_nav(site.slug)}), encoding="utf-8"
    )
    _ = (out_dir / "skin.json").write_text(
        json.dumps({str(i): fitzpatrick_context(i) for i in range(1, 7)}),
        encoding="utf-8",
    )
    _ = (out_dir / "surfaces.json").write_text(
        json.dumps(_surface_payload()), encoding="utf-8"
    )
    _ = (out_dir / "calendar.ics").write_text(
        build_calendar_ics(daily, str(summary.get("run", "")), hourly,
                           site_slug=site.slug, tz_name=site.timezone),
        encoding="utf-8",
    )
    # Per-30-minute interval events (doses, tier, native-HRRR vs interpolated
    # labeling). Night rows carry no usable sun: emit daylight intervals only
    # (is_day when present, else any positive UV/E_mel signal). Columns absent
    # entirely mean an old table: keep all rows rather than emit nothing.
    daylight = half
    try:
        def _col(name: str) -> pd.Series:
            if name not in half.columns:
                return pd.Series(0.0, index=half.index, dtype="float64")
            col = pd.to_numeric(half[name], errors="coerce")
            assert isinstance(col, pd.Series)
            return col.fillna(0)

        if {"is_day", "uv_index", "melanogenic_effective_irradiance_wm2"}.isdisjoint(half.columns):
            pass
        else:
            _mask = (_col("is_day") > 0) | (_col("uv_index") > 0) | (
                _col("melanogenic_effective_irradiance_wm2") > 0)
            daylight = half.loc[_mask]
    except (KeyError, ValueError, TypeError):
        pass
    _ = (out_dir / "calendar-30min.ics").write_text(
        build_interval_ics(daylight, str(summary.get("run", "")),
                           site_slug=site.slug, tz_name=site.timezone),
        encoding="utf-8",
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
        writer = cast("pd.ExcelWriter[object]", pd.ExcelWriter(path))
        with writer:
            for name, df in usable.items():
                # Excel has a 1,048,576-row limit; cap only the convenience workbook.
                to_excel = cast("Callable[..., None]", df.head(1_000_000).to_excel)
                to_excel(writer, sheet_name=name[:31], index=False)
    except ImportError:
        pass
