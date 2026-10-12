#!/usr/bin/env python3
"""Build the frozen site fixture used by the rendered-UI visual gate.

A pixel baseline for this dashboard is worthless against the *live* artifact:
every scheduled run rewrites the payload (dates, doses, confidence), so the
screenshots change for reasons that are not regressions. The visual gate
therefore renders a frozen fixture: the committed template sidecars plus a
trimmed payload carrying a fixed set of days.

The fixture is small on purpose - it exists to detect layout and markup
regressions, not to reproduce a real forecast. Regenerate it only when the
payload schema changes, and update the baseline in the same commit.

Usage:
  uv run python scripts/build_rendered_fixture.py [--site-dir docs] [--out tests/fixtures/rendered_site] [--days 2]
"""

from __future__ import annotations

import argparse
import json
import shutil
from pathlib import Path

SIDECARS = ("skin.json", "surfaces.json", "locations.json", "calendar.ics")


def build(site_dir: Path, out_dir: Path, days: int) -> dict[str, object]:
    """Write a frozen copy of the page plus a payload trimmed to `days` days."""
    payload = json.loads((site_dir / "data.json").read_text(encoding="utf-8"))
    keep = [str(d["date"]) for d in payload["daily"][:days]]

    trimmed = dict(payload)
    trimmed["daily"] = [d for d in payload["daily"] if str(d["date"]) in keep]
    for key in ("hourly", "half_hour"):
        rows = payload.get(key) or []
        trimmed[key] = [r for r in rows if str(r.get("time", ""))[:10] in keep]
    # The payload advertises its run; a frozen fixture must not look current.
    summary = dict(trimmed.get("summary") or {})
    summary["run_tag"] = "fixture"
    summary["site_name"] = "Fixture site"
    trimmed["summary"] = summary

    out_dir.mkdir(parents=True, exist_ok=True)
    _ = shutil.copyfile(site_dir / "index.html", out_dir / "index.html")
    for name in SIDECARS:
        src = site_dir / name
        if src.exists():
            _ = shutil.copyfile(src, out_dir / name)
    text = json.dumps(trimmed, separators=(",", ":"), sort_keys=True)
    _ = (out_dir / "data.json").write_text(text, encoding="utf-8")
    sizes = {
        name: (out_dir / name).stat().st_size
        for name in ("index.html", "data.json")
    }
    return {"days": keep, "rows": {k: len(trimmed.get(k) or []) for k in ("daily", "hourly", "half_hour")},
            "bytes": sizes}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    _ = ap.add_argument("--site-dir", default="docs")
    _ = ap.add_argument("--out", default="tests/fixtures/rendered_site")
    _ = ap.add_argument("--days", type=int, default=2)
    ns = ap.parse_args(argv)
    info = build(Path(ns.site_dir), Path(ns.out), int(ns.days))
    payload = json.loads((Path(ns.out) / "data.json").read_text(encoding="utf-8"))
    info["is_valid_json"] = isinstance(payload.get("daily"), list)
    print(json.dumps(info, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
