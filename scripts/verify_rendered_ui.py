#!/usr/bin/env python3
"""Rendered-UI verification for the published page (Phase 2 acceptance).

Three closure-matrix rows were left PARTIAL pending *rendered* proof: material ->
plane -> window -> hero, the flat-pose invariant, and the schedule/MMD honesty
notes. `node`-driven tests execute the page's functions but never build a DOM,
run `render()` or click a control, so they cannot see any of it. This drives real
Chromium over the committed `docs/` artifact and records what it observed.

Playwright is deliberately not a project dependency (the browsers are a large
download and CI does not need them), so the import is local and the script says
so instead of failing obscurely.

Usage:
  uv run --with playwright python -m playwright install chromium   # once
  uv run python scripts/verify_rendered_ui.py [--site-dir docs]
Writes docs/validation/rendered_ui_verification.md (not committed by CI).
Exits 1 if any check fails, so it is usable as a gate.
"""

from __future__ import annotations

import argparse
import functools
import http.server
import importlib
import json
import re
import socketserver
import threading
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[1]

# Each check returns (name, ok, observed). The observed value is what makes the
# report reviewable: a future regression shows the before/after difference.
CHECKS: list[tuple[str, bool, str]] = []


_viewport_label = ""


def record(name: str, ok: bool, observed: object) -> None:
    """Record one check. LABEL names the viewport the check ran in."""
    CHECKS.append((f"{_viewport_label}{name}", bool(ok), str(observed)[:400]))
    print(
        f"{'PASS' if ok else 'FAIL'}  {_viewport_label}{name}  {str(observed)[:150]}"
    )


class _Handler(http.server.SimpleHTTPRequestHandler):
    """Serve the site dir quietly: one log line per request drowns the output."""

    def log_message(self, format: str, *args: object) -> None:
        return


def _serve(site_dir: Path) -> tuple[socketserver.ThreadingTCPServer, str]:
    handler = functools.partial(_Handler, directory=str(site_dir))
    httpd = socketserver.ThreadingTCPServer(("127.0.0.1", 0), handler)
    httpd.daemon_threads = True
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    return httpd, f"http://127.0.0.1:{httpd.server_address[1]}/"


def _module_factor(row: dict[str, object], surface: str, tilt: float) -> float:
    import pandas as pd

    from sunstack.spectral import apply_skin_plane

    plane = apply_skin_plane(
        pd.DataFrame([row]), tilt_deg=tilt, azimuth_deg=180.0, surface_slug=surface
    )
    return float(plane.iloc[0]["skin_plane_factor"])


VIEWPORTS = ((1350, 900, "desktop"), (390, 844, "mobile"))


def _checks(
    page: Any,  # playwright is an optional dependency: its types are not installed
    payload: dict[str, Any],
    site_dir: Path,
    url: str,
    errors: list[str],
) -> None:
    """The behaviour checks, run once per viewport."""
    errors: list[str] = []
    page.on("pageerror", lambda e: errors.append(str(e)))
    page.on("console", lambda m: errors.append(m.text) if m.type == "error" else None)
    page.goto(url, wait_until="networkidle")
    page.wait_for_timeout(2500)

    hero = page.evaluate("() => document.getElementById('hero').textContent.replace(/\\s+/g,' ')")
    record("page loads with a payload and no console/page errors", bool(hero) and not errors, errors or hero[:120])

    # 1. flat pose over an unknown surface: the invariant must be stated
    page.select_option("#surface", "unknown")
    page.fill("#skintilt", "0")
    page.press("#skintilt", "Tab")
    page.wait_for_timeout(1200)
    flat_hero = page.evaluate(
        "() => document.getElementById('hero').textContent.replace(/\\s+/g,' ')"
    )
    record(
        "flat/unknown pose states the horizontal-reference invariant",
        "horizontal reference" in flat_hero and "in your plane" not in flat_hero,
        flat_hero[-140:],
    )

    # 2. material -> plane -> hero, and the module agrees
    page.select_option("#surface", "dry_beach_sand")
    page.fill("#skintilt", "45")
    page.press("#skintilt", "Tab")
    page.wait_for_timeout(1500)
    hero45 = page.evaluate(
        "() => document.getElementById('hero').textContent.replace(/\\s+/g,' ')"
    )
    panel = page.evaluate("() => document.getElementById('surfacecontext').textContent")
    record(
        "material+tilt reach the hero above the fold",
        "Dry beach sand" in hero45 and "tilted 45" in hero45 and "+" in hero45,
        [c for c in hero45.split(". ") if "plane" in c][:1],
    )
    row_time = page.evaluate(
        "() => (activeRow()||{}).time",
    )
    row = next(
        (r for r in payload["half_hour"] if str(r["time"]).startswith(str(row_time)[:16])),
        None,
    )
    if row is None:
        record("panel row resolves to a published row", False, row_time)
    else:
        want = _module_factor(row, "dry_beach_sand", 45.0)
        panel_factor = page.evaluate("() => planeForRow(activeRow()).factor")
        record(
            "panel plane factor equals the physics module (4-dp round)",
            abs(float(panel_factor) - want) < 5e-5,
            f"page={panel_factor:.6f} module={want:.6f} row={row_time}",
        )
        # The panel prints the row as "YYYY-MM-DD HH:MM" (space, not the
        # ISO "T"): compare against what a reader actually sees.
        shown_row = str(row_time)[:16].replace("T", " ")
        record(
            "panel names its row and reports the gain",
            "plane gain" in panel and shown_row in panel,
            panel[:160],
        )

    # 2b. switching material moves the plane, and the module agrees again -
    # "grass -> sand -> snow" is the audit's Phase 2 interaction list, not just
    # one material spot check.
    sand_factor = float(page.evaluate("() => planeForRow(activeRow()).factor"))
    page.select_option("#surface", "fresh_snow")
    page.wait_for_timeout(1400)
    snow_hero = page.evaluate(
        "() => document.getElementById('hero').textContent.replace(/\\s+/g,' ')"
    )
    snow_time = page.evaluate("() => (activeRow()||{}).time")
    snow_row = next(
        (r for r in payload["half_hour"] if str(r["time"]).startswith(str(snow_time)[:16])), None
    )
    if snow_row is None:
        record("switching material resolves a published row", False, snow_time)
    else:
        want_snow = _module_factor(snow_row, "fresh_snow", 45.0)
        snow_factor = float(page.evaluate("() => planeForRow(activeRow()).factor"))
        record(
            "switching material moves the plane and matches the module (sand -> snow)",
            abs(snow_factor - want_snow) < 5e-5 and snow_factor > sand_factor,
            f"sand={sand_factor:.4f} snow={snow_factor:.6f} module={want_snow:.6f}",
        )
        record(
            "hero names the new material",
            "Fresh snow" in str(snow_hero) and "tilted 45" in str(snow_hero),
            str(snow_hero)[-110:],
        )
    page.select_option("#surface", "dry_beach_sand")
    page.wait_for_timeout(1000)

    # 2c. the material's model quality must reach the reader, not just the
    # payload (audit Phase 1 item 3: surface_model_quality carried to display).
    panel_text = str(page.evaluate(
        "() => (document.getElementById('surfacecontext')||{}).textContent || ''"
    ))
    quality = re.search(r"surface quality ([a-z][a-z /-]{2,})", panel_text)
    record(
        "panel discloses the material's model quality as words",
        quality is not None
        and quality.group(1).strip() not in ("unknown", "undefined", "none")
        and "no material applied" not in panel_text,
        panel_text[-110:],
    )

    # 3. honesty of the two live-only controls on a published page
    class_copy = page.evaluate(
        "() => [...document.querySelectorAll('#classbox .note')].map(e => e.textContent).join(' ')"
    )
    record(
        "schedule is marked environmental-only, not silently inert",
        "cannot re-rank for a schedule" in class_copy and "environmental" in class_copy,
        class_copy[:170],
    )
    record(
        "personal MMD is hidden with a stated reason",
        page.evaluate("() => document.getElementById('mmdbasis').type") == "hidden"
        and "live server"
        in str(page.evaluate("() => (document.getElementById('mmdstatic')||{}).textContent")),
        page.evaluate("() => (document.getElementById('mmdstatic')||{}).textContent"),
    )

    # 4a. UI semantic validators: the rendered ranking row, the day card
    # and the hero must agree with the payload they were built from -
    # "wrong number on screen" is invisible to a payload-only test.
    def _round(value: object) -> int | None:
        """Rounded int for a payload number or a rendered cell, else None."""
        try:
            return round(float(str(value)))
        except (TypeError, ValueError):
            return None

    ui_row_time = str(page.evaluate("() => (activeRow()||{}).time"))[:16]
    cells = page.evaluate(
        f"() => {{ const tr = document.querySelector('#detail tr[data-time^=\"{ui_row_time}\"]');"
        f" return tr ? [...tr.children].map(td => td.textContent.trim()) : null; }}"
    )
    prow = next(
        (r for r in payload["half_hour"] if str(r["time"]).startswith(ui_row_time)), None
    )
    if prow is None or not isinstance(cells, list) or len(cells) < 8:
        record("ranking row resolves to a payload row", False, [ui_row_time, cells])
    else:
        want_dose = prow.get("delayed_pigmentation_dose_30m_j_m2") or prow.get("tan_dose_30m_j_m2")
        for idx, field, want in (
            (3, "Dose J/m²", want_dose),
            (5, "Overall", prow.get("overall_tan_opportunity_0_100")),
            (6, "Abs", prow.get("tan_score_absolute_0_100")),
            (7, "Local", prow.get("local_tan_score_0_100")),
        ):
            shown = str(cells[idx]).strip()
            want_rounded, shown_rounded = _round(want), _round(shown)
            record(
                f"ranking row agrees with the payload: {field}",
                want_rounded is not None and want_rounded == shown_rounded,
                f"shown={shown} payload={want}",
            )

    # the day card's window must be the window its dose came from
    day = page.evaluate(
        "() => { const d = (DATA.daily||[]).find(x => x.date === SEL);"
        " return d ? {date: d.date, start: d.best_usable_30m_start, end: d.best_usable_30m_end,"
        " dose: d.best_usable_30m_dose_j_m2} : null; }"
    )
    card = str(page.evaluate(
        "() => { const c = document.querySelector('.daycell[aria-selected=\"true\"]');"
        " return c ? c.textContent : ''; }"
    ))
    def _hhmm(stamp: object) -> str:
        text = str(stamp)
        hour, minute = int(text[11:13]), text[14:16]
        suffix = "AM" if hour < 12 else "PM"
        hour12 = hour % 12 or 12
        return f"{hour12} {suffix}" if minute == "00" else f"{hour12}:{minute} {suffix}"

    if day and day["start"]:
        want_start, want_end = _hhmm(day["start"]), _hhmm(day["end"])
        record(
            "day card shows the dose and the window that dose came from",
            str(_round(day["dose"])) in card and want_start in card and want_end in card,
            [f"dose={day['dose']}", want_start, want_end, card[:80]],
        )
    else:
        record("day card shows a dose for the selected day", bool(card.strip()), card[:110])

    # the three score columns must sit together, and say how they differ
    headers = page.evaluate(
        "() => [...document.querySelectorAll('#detail table:last-of-type thead th')]"
        ".map(h => [h.textContent.trim(), h.title])"
    )
    by_name = {str(h[0]): str(h[1]) for h in headers} if isinstance(headers, list) else {}
    record(
        "Dose/Overall/Abs/Local are shown together with distinguishing semantics",
        {"Dose J/m²", "Overall", "Abs", "Local"} <= set(by_name)
        and "worldwide" in by_name.get("Abs", "")
        and "within this location" in by_name.get("Local", ""),
        sorted(by_name),
    )

    # 3a2. Every day without a usable interval must SAY so in its card,
    # not render a grade (audit: Oct 17 carried 751.6 J/m2 of blocked
    # radiation and rendered "POOR" beside "0 J/m2").
    no_window = [
        d["date"] for d in payload["daily"]
        if d.get("best_usable_30m_start") in (None, "")
    ]
    cards = page.evaluate(
        "() => Object.fromEntries([...document.querySelectorAll('.daycell')]"
        ".map(c => [c.dataset.date, c.textContent.replace(/\\s+/g,' ')]))"
    )
    if no_window:
        wrong = [
            d for d in no_window
            if "NO USABLE WINDOW" not in str(cards.get(d, ""))
            or str(cards.get(d, "")).split("NO USABLE WINDOW")[0].strip().split()[-1]
            in {"POOR", "FAIR", "GOOD", "EXCELLENT"}
        ]
        record(
            f"days with no usable window say so in their card ({len(no_window)} of them)",
            not wrong,
            wrong or [d for d in no_window][:2],
        )
    else:
        record("the run has at least one no-window day to check", True, "skipped: none")

    # 3a3. times must say which zone they are in (audit Phase 2 item 4), and the
    # schedule is read in that same zone.
    tz_line = page.evaluate(
        "() => (document.getElementById('tzline')||{}).textContent || ''"
    )
    record(
        "times state the site timezone on the rendered page",
        "site zone:" in str(tz_line) and "America/" in str(tz_line)
        and "schedule" in str(tz_line),
        tz_line,
    )

    # 3b. the spectral tier must be labelled for what it is: nothing said
    # "degraded" anywhere before, while the docs require the label.
    prov = page.evaluate(
        "() => { const p = document.getElementById('provenance');"
        " return p ? {text: p.textContent, title: p.title} : null; }"
    )
    record(
        "Tier-C is labelled a fixed-band proxy where the number is shown",
        bool(prov)
        and "fixed-band proxy" in str(prov["text"])
        and "+204%" in str(prov["title"])
        and "WOUDC" in str(prov["title"]),
        [str(prov["text"])[-90:], str(prov["title"])[:90]],
    )

    # 3c. the UVI fusion must name its reference honestly: it is scored
    # against Open-Meteo's own retrospective, which is not truth.
    gloss = page.evaluate(
        "() => [...document.querySelectorAll('.gloss')].map(e => e.textContent).join(' ')"
    )
    titles = page.evaluate(
        "() => [...document.querySelectorAll('th[title*=\"inverse-error fusion\"]')]"
        ".map(t => t.title)"
    )
    cond_basis = "not independent truth" in str(gloss)
    cond_limit = any("flatters agreement" in str(t) for t in titles)
    record(
        "UVI fusion names its non-independent reference (baseline + limitation)",
        cond_basis and cond_limit,
        [f"basis={cond_basis}", f"limit={cond_limit}", f"nTitles={len(titles)}",
         str(gloss)[-70:]],
    )

    # 3d. rank and score semantics must be named with their versions:
    # an unversioned score is an unfalsifiable claim.
    versions = page.evaluate(
        "() => ({prov: (document.getElementById('provenance')||{}).textContent || '',"
        " panel: (document.getElementById('surfacecontext')||{}).textContent || ''})"
    )
    record(
        "rank and score semantics carry their versions where they are read",
        "action-spectrum-v2" in str(versions["prov"])
        and "fixed-duration-dose-v2" in str(versions["panel"])
        and "heuristic-reliability-v1" in str(versions["panel"]),
        [str(versions["prov"])[:70], str(versions["panel"])[-70:]],
    )

    # 3e. confidence must stay labelled a heuristic: the number is a
    # reliability estimate, not a calibrated interval.
    conf_title = page.evaluate(
        "() => { const t = [...document.querySelectorAll('#detail th')]"
        ".find(h => h.textContent.trim() === 'Conf'); return t ? t.title : ''; }"
    )
    hero_title = page.evaluate(
        "() => { const s = document.querySelector('#hero span[title]');"
        " return s ? s.title : ''; }"
    )
    # The column says what the number is; the headline number carries the
    # disclaimer that it is not a calibrated interval.
    record(
        "confidence is labelled a heuristic, not a calibrated interval",
        "euristic" in str(conf_title)
        and "not an empirically calibrated" in str(hero_title),
        [str(conf_title)[:70], str(hero_title)[:70]],
    )

    # 4. site picker links the other published page
    options = page.evaluate(
        "() => [...document.getElementById('locsel').options].map(o => o.value + '|' + (o.dataset.url||''))"
    )
    record(
        "site picker carries the other site as a link, not an in-place switch",
        any("pacific-palisades" in str(o) for o in options),
        options,
    )

    # 5. the no-usable-window path. This run may have a window every day,
    # so force the branch instead of depending on today's weather: null
    # the day's window fields and re-render exactly as the app would.
    # The hero reports bestDay(), which SELECTS over the payload, so
    # nulling one day just promotes the runner-up. Force the state a
    # genuinely windowless run has: no day carries a usable window.
    forced = page.evaluate("""() => {
      for (const d of (DATA.daily || [])) {
        for (const k of ['best_usable_30m_start','best_usable_30m_end',
                         'strongest_30m_start','strongest_30m_end',
                         'best_usable_30m_dose_j_m2','strongest_30m_dose_j_m2',
                         'best_30m_tan_dose_j_m2','best_30m_start']) { d[k] = null; }
      }
      render();
      return document.getElementById('hero').textContent.replace(/\\s+/g,' ');
    }""")
    record(
        "a day with no usable window says so instead of showing 0 J/m² as fine",
        forced is not None
        and ("NO USABLE WINDOW" in str(forced) or "missing usable light" in str(forced)),
        forced,
    )
    page.reload(wait_until="networkidle")
    page.wait_for_timeout(2000)

    # 6. the site switch is a real navigation to the other published page.
    # A frozen fixture ships one page, so there is nothing to navigate to.
    sibling = site_dir / "sites"
    if not sibling.is_dir():
        record("site picker navigation", True, "skipped: this site dir ships one page")
    else:
        page.select_option("#locsel", "pacific-palisades")
        page.wait_for_timeout(3000)
        landed = page.url
        other_hero = page.evaluate(
            "() => (document.getElementById('hero')||{}).textContent || ''"
        )
        record(
            "site picker navigates to the other site's own page and payload",
            "pacific-palisades" in landed and "best day" in other_hero,
            f"{landed} :: {other_hero[:90]}",
        )
        page.goto(url, wait_until="networkidle")
        page.wait_for_timeout(2000)

        cal_title = page.evaluate("() => (document.getElementById('cal')||{}).title || ''")
        record(
            "the published calendar says it is environmental (no schedule/surface claim)",
            "environmental calendar" in str(cal_title).lower()
            and "schedule" in str(cal_title)
            and "surface" in str(cal_title),
            cal_title,
        )

        # 6b. the CSV export must carry what the page shows: same day, same dose
        # column, same values (audit Phase 2 item 5: calendar/export consistency).
        csv_text = ""
        try:
            with page.expect_download() as download_info:
                page.click('button[onclick="exportDayCsv()"]')
            csv_text = Path(str(download_info.value.path())).read_text(encoding="utf-8")
        except Exception as exc:  # noqa: BLE001 - reported, not swallowed
            record("day CSV export downloads", False, str(exc)[:120])
        if csv_text:
            lines = csv_text.splitlines()
            columns = lines[0].split(",")
            record(
                "day CSV header names the dose column the table shows",
                "tan_dose_30m_j_m2" in columns and "time" in columns,
                columns[:8],
            )
            exported = {}
            for line in lines[1:]:
                parts = line.split(",")
                exported[parts[0]] = parts[columns.index("tan_dose_30m_j_m2")] if len(parts) > 1 else ""
            payload_rows = {
                str(r["time"])[:16]: r.get("tan_dose_30m_j_m2") for r in payload["half_hour"]
            }
            checked = 0
            mismatched = []
            for stamp, value in exported.items():
                want = payload_rows.get(stamp[:16])
                if want is None or value == "":
                    continue
                checked += 1
                if abs(float(value) - float(want)) > 1e-6:
                    mismatched.append((stamp, value, want))
            record(
                "day CSV dose values equal the payload they came from",
                checked > 0 and not mismatched,
                f"{checked} rows checked; mismatches {mismatched[:2]}",
            )
    # 7b. §5 headline provenance: the page must name which UVI is the headline,
    # carry the fusion and the source spread beside it, and never ship the copy
    # placeholder raw. The value checks are conditional on the payload actually
    # carrying the fields, so an artifact published before this contract does not
    # fail the gate - but a page that hides a field the payload does carry does.
    html = page.content()
    record(
        "fusion copy placeholder is substituted, not shipped raw",
        "__FUSION_LIMIT__" not in html,
        "raw placeholder in the page" if "__FUSION_LIMIT__" in html else "substituted",
    )
    record(
        "hourly table labels the headline, the fusion and the spread",
        "not the headline" in html and ">Fusion</th>" in html and "ΔUV</th>" in html,
        "missing: " + ", ".join(
            t for t, ok in (("headline copy", "not the headline" in html),
                            ("Fusion column", ">Fusion</th>" in html),
                            ("spread column", "ΔUV</th>" in html))
            if not ok
        ),
    )
    rendered = page.evaluate("""() => {
      const t = [...document.querySelectorAll('table')].find(
        x => (x.tHead && x.tHead.textContent || '').includes('Fusion'));
      if (!t) return null;
      const heads = [...t.tHead.rows[0].cells].map(c => c.textContent.trim());
      return [...t.tBodies[0].rows].map(r => {
        const cells = {};
        heads.forEach((h, i) => { cells[h] = (r.cells[i] || {}).textContent || ''; });
        return {time: (r.getAttribute('data-time') || '').slice(0, 16), cells};
      });
    }""") or []
    by_time = {str(r.get("time", ""))[:16]: r for r in payload.get("hourly") or []}

    def _shown(cell: str) -> float | None:
        text = cell.replace("\u2212", "-").strip()
        try:
            return float(text)
        except ValueError:
            return None

    pairs = [(row, by_time[row["time"]]) for row in rendered if row["time"] in by_time]
    record(
        "hourly rows on screen match the payload rows they came from",
        bool(pairs) and len(pairs) == len(rendered),
        f"{len(pairs)} of {len(rendered)} rendered rows joined to the payload",
    )

    fusion_rows = [(r, pr) for r, pr in pairs if isinstance(pr.get("uvi_fusion"), (int, float))]
    if fusion_rows:
        mismatched: list[tuple[str, object, object]] = []
        for row, payload_row in fusion_rows:
            want_fusion = payload_row.get("uvi_fusion")
            if not isinstance(want_fusion, (int, float)):
                continue
            shown = _shown(row["cells"].get("Fusion", ""))
            if shown is None or abs(shown - float(want_fusion)) > 0.051:
                mismatched.append((row["time"], row["cells"].get("Fusion"), want_fusion))
        record(
            "Fusion column shows the fused UVI the payload publishes",
            not mismatched,
            f"{len(fusion_rows)} rows checked; mismatches {mismatched[:2]}",
        )

    spread_rows = [
        (r, pr) for r, pr in pairs if isinstance(pr.get("uvi_source_spread"), (int, float))
    ]
    if spread_rows:
        bad_spread: list[tuple[str, object, object]] = []
        for row, payload_row in spread_rows:
            want_spread = payload_row.get("uvi_source_spread")
            if not isinstance(want_spread, (int, float)):
                continue
            shown = _shown(row["cells"].get("ΔUV", ""))
            if shown is None or abs(shown - float(want_spread)) > 0.051:
                bad_spread.append((row["time"], row["cells"].get("ΔUV"), want_spread))
        record(
            "ΔUV column shows the source spread the payload publishes",
            not bad_spread,
            f"{len(spread_rows)} rows checked; mismatches {bad_spread[:2]}",
        )

        # the UV∘ cell appends the min-max envelope exactly when the payload row
        # has two visible sources and a spread at or above the disagree flag
        def _wants_envelope(payload_row: dict[str, object]) -> bool:
            spread = payload_row.get("uvi_source_spread")
            if not isinstance(spread, (int, float)) or float(spread) < 1.0:
                return False
            visible = sum(
                1 for key in ("uv_index", "uvi_cams", "uvi_epa")
                if isinstance(payload_row.get(key), (int, float))
            )
            return visible >= 2

        misfiled: list[tuple[str, str, object]] = []
        for row, payload_row in spread_rows:
            cell = row["cells"].get("UV∘", "")
            if _wants_envelope(payload_row):
                if "\u2013" not in cell:
                    misfiled.append((row["time"], "envelope missing where the payload has one", cell))
            elif "\u2013" in cell:
                misfiled.append((row["time"], "envelope shown without the payload spread", cell))
        record(
            "UV column shows the source envelope exactly where the payload has one",
            not misfiled,
            f"{sum(1 for _, pr in spread_rows if _wants_envelope(pr))} rows should show an envelope; "
            f"{misfiled[:2]}",
        )

    # 7. calendar artifact
    href = page.evaluate("() => (document.querySelector('a[href*=\"calendar\"]')||{}).href || ''")
    ics = (site_dir / "calendar.ics").read_text(encoding="utf-8")
    record(
        "calendar link is the published .ics, never the live API path",
        "calendar.ics" in str(href) and "/api/" not in str(href) and ics.startswith("BEGIN:VCALENDAR"),
        str(href),
    )


def verify(site_dir: Path, shots_dir: Path) -> None:
    try:
        sync_api = importlib.import_module("playwright.sync_api")
    except ImportError:
        raise SystemExit(
            "playwright is not installed. Run: "
            "uv run --with playwright python scripts/verify_rendered_ui.py"
        ) from None

    payload = json.loads((site_dir / "data.json").read_text(encoding="utf-8"))
    httpd, url = _serve(site_dir)
    try:
        with sync_api.sync_playwright() as pw:
            browser = pw.chromium.launch()
            for width, height, tag in VIEWPORTS:
                global _viewport_label
                _viewport_label = f"[{tag} {width}px] "
                page = browser.new_page(viewport={"width": width, "height": height})
                errors: list[str] = []
                page.on("pageerror", lambda e, _err=errors: _err.append(str(e)))
                page.on(
                    "console",
                    lambda m, _err=errors: _err.append(m.text) if m.type == "error" else None,
                )
                page.goto(url, wait_until="networkidle")
                page.wait_for_timeout(2500)

                # No unsignaled horizontal page overflow: the day strip scrolls
                # internally, the document must not.
                metrics = page.evaluate(
                    "() => ({inner: innerWidth, doc: document.documentElement.scrollWidth,"
                    " body: document.body.scrollWidth})"
                )
                record(
                    "no horizontal page overflow",
                    int(metrics["doc"]) <= int(metrics["inner"]) + 1
                    and int(metrics["body"]) <= int(metrics["inner"]) + 1,
                    metrics,
                )
                _checks(page, payload, site_dir, url, errors)
                _ = page.screenshot(path=str(shots_dir / f"{tag}-{width}.png"))
                page.close()
            browser.close()
    finally:
        httpd.shutdown()


def compare_baseline(shots: Path, baseline: Path) -> None:
    """Compare this run's screenshots with a stored baseline, if one exists.

    A pixel baseline is only meaningful when it was produced on the SAME renderer
    as the run (fonts and rasterisation differ across platforms), so this seeds
    nothing automatically: it compares when a baseline is present and records an
    explicit notice when it is not. Seed it with:

      mkdir -p <baseline> && cp <shots>/*.png <baseline>/

    Pillow is optional only while no baseline exists: once the baseline is
    seeded, a missing Pillow is a failure, because "skipped" would report success
    while checking nothing.
    """
    if not baseline.is_dir() or not any(baseline.glob("*.png")):
        record("pixel baseline compared", True, f"no baseline seeded yet at {baseline}")
        return
    try:
        image_module = importlib.import_module("PIL.Image")
        image_chops = importlib.import_module("PIL.ImageChops")
    except ImportError:
        record(
            "pixel baseline compared",
            False,
            "baseline is seeded but Pillow is not installed - run this step with "
            "`uv run --with pillow` rather than skipping the comparison",
        )
        return
    for shot in sorted(shots.glob("*.png")):
        want = baseline / shot.name
        if not want.exists():
            record(f"pixel baseline has {shot.name}", False, "missing from the baseline")
            continue
        with image_module.open(shot) as got_img, image_module.open(want) as want_img:
            if got_img.size != want_img.size:
                record(f"pixel baseline size {shot.name}", False, [got_img.size, want_img.size])
                continue
            diff = image_chops.difference(got_img.convert("RGB"), want_img.convert("RGB"))
            bbox = diff.getbbox()
            changed = 0 if bbox is None else sum(1 for p in diff.convert("L").getdata() if p > 16)
            total = got_img.size[0] * got_img.size[1]
            share = changed / max(total, 1)
        record(
            f"pixel baseline matches {shot.name}",
            share <= 0.005,
            f"{share * 100:.3f}% of pixels differ (tolerance 0.500%)",
        )


def write_report(out: Path, site_dir: Path, shots: Path) -> int:
    failed = [c for c in CHECKS if not c[1]]
    lines = [
        "# Rendered-UI verification (Phase 2 acceptance)",
        "",
        f"Artifact: `{site_dir}` · checks: **{len(CHECKS) - len(failed)}/{len(CHECKS)} passed**",
        "",
        (
            "Driven by real Chromium over the committed static export "
            "(`uv run --with playwright python scripts/verify_rendered_ui.py`)."
        ),
        "",
        f"Screenshots: `{shots}/` (desktop-1350.png, mobile-390.png).",
        "",
        "| check | result | observed |",
        "|---|---|---|",
    ]
    for name, ok, observed in CHECKS:
        lines.append(f"| {name} | {'PASS' if ok else 'FAIL'} | `{observed.replace('|', '/')}` |")
    lines.append("")
    _ = out.write_text("\n".join(lines), encoding="utf-8")
    print(f"\nrendered-ui: {len(CHECKS) - len(failed)}/{len(CHECKS)} passed -> {out}")
    return 1 if failed else 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--site-dir", default="docs")
    ap.add_argument("--out", default="docs/validation/rendered_ui_verification.md")
    ap.add_argument(
        "--shots-dir",
        default="",
        help="Where to write screenshots (default: <out> sibling directory rendered_ui/)",
    )
    ap.add_argument(
        "--baseline",
        default=None,
        help=(
            "Directory of baseline PNGs to diff against. Opt in, and only for a "
            "fixture: the published artifact changes with every payload, so "
            "comparing it against a stored baseline fails for reasons that are "
            "not regressions (see scripts/build_rendered_fixture.py)."
        ),
    )
    ns = ap.parse_args(argv)
    shots = Path(ns.shots_dir) if ns.shots_dir else Path(ns.out).parent / "rendered_ui"
    shots.mkdir(parents=True, exist_ok=True)
    verify(Path(ns.site_dir), shots)
    global _viewport_label
    _viewport_label = ""  # the baseline covers every viewport's screenshots
    if ns.baseline:
        compare_baseline(shots, Path(ns.baseline))
    else:
        record("pixel baseline compared", True, "no --baseline given")
    return write_report(Path(ns.out), Path(ns.site_dir), shots)


if __name__ == "__main__":
    raise SystemExit(main())
