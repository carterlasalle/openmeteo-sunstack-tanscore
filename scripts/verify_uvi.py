#!/usr/bin/env python3
"""Rolling UVI verification: committed docs/data.json snapshots vs hindsight.

Compares mature predictions (run_day < target_day) from every committed
snapshot against the Open-Meteo previous-runs best_match retrospective
REFERENCE (not truth: shared provider DNA flatters OM ~0.1-0.2).

Scores per source (OM/CAMS/EPA/consensus) at 1-day lead, 12-2PM EDT:
MAE, bias, RMSE + per-day breakdown. Fails loudly if consensus regresses
past OM (the median-must-not-lose-its-best-input invariant).

Usage: uv run python scripts/verify_uvi.py [--refetch]
Writes docs/validation/uvi_verification.md (not committed by CI).
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import requests

ROOT = Path(__file__).resolve().parent.parent
LAT, LON = 41.703293, -86.238292
UTC_HOURS = ("16:00", "17:00", "18:00")  # 12-2PM EDT


def snapshot_revs() -> list[str]:
    out = subprocess.run(
        ["git", "log", "--format=%H", "--", "docs/data.json"],
        capture_output=True, text=True, check=True, cwd=ROOT).stdout
    return [r for r in out.split() if r.strip()]


def extract_preds(revs: list[str]) -> pd.DataFrame:
    rows = []
    for rev in revs:
        try:
            raw = subprocess.run(
                ["git", "show", rev + ":docs/data.json"],
                capture_output=True, text=True, timeout=30, cwd=ROOT,
                check=True).stdout
            d = json.loads(raw)
        except (subprocess.CalledProcessError, json.JSONDecodeError,
                UnicodeDecodeError) as exc:
            print(f"skip {rev[:8]}: {exc}", file=sys.stderr)
            continue
        created = d.get("summary", {}).get("created_at", "")[:10]
        for x in d.get("hourly", []):
            t = x.get("time", "")
            if t[11:16] in UTC_HOURS and len(t) >= 10:
                rows.append((created, t[:10], t[11:16], x.get("uv_index"),
                             x.get("uvi_cams"), x.get("uvi_epa"),
                             x.get("uvi_consensus")))
    return pd.DataFrame(rows, columns=["run_day", "target_day", "utc", "om",
                                       "cams", "epa", "cons"])


def fetch_truth(days: list[str], cache: Path) -> pd.DataFrame:
    if cache.exists() and "--refetch" not in sys.argv:
        cached = pd.read_parquet(cache)
        return cached if isinstance(cached, pd.DataFrame) else pd.DataFrame(cached)
    params = {"latitude": LAT, "longitude": LON, "start_date": min(days),
              "end_date": max(days),
              "hourly": "uv_index,uv_index_clear_sky,cloud_cover",
              "timezone": "America/Indiana/Indianapolis", "models": "best_match"}
    r = requests.get("https://previous-runs-api.open-meteo.com/v1/forecast",
                     params=params, timeout=120)
    r.raise_for_status()
    payload = r.json()
    h = pd.DataFrame(payload["hourly"] if isinstance(payload, dict) else [])
    h["target_day"] = h["time"].str.slice(0, 10)
    h["utc"] = h["time"].str.slice(11, 16)
    sub = h.loc[h["utc"].isin(list(UTC_HOURS)), ["target_day", "utc", "uv_index"]]
    t = pd.DataFrame(sub).rename(columns={"uv_index": "retrospective_reference"})
    cache.parent.mkdir(parents=True, exist_ok=True)
    t.to_parquet(cache, index=False)
    return t


def main() -> int:
    revs = snapshot_revs()
    preds = extract_preds(revs)
    preds = preds[(pd.to_datetime(preds["run_day"]) + pd.Timedelta(days=1))
                  == pd.to_datetime(preds["target_day"])]
    _days = sorted(str(d) for d in pd.Series(preds["target_day"].tolist()).unique())
    truth = fetch_truth(_days,
                        ROOT / "docs" / "validation" / ".uvi_truth_cache.parquet")
    j = preds.merge(truth, on=["target_day", "utc"], how="inner")
    lines = ["# UVI verification (retrospective reference, not truth)",
             "",
             f"Snapshots: {len(revs)} | 1-day-lead rows: {len(j)}",
             "",
             "| source | n | MAE | bias | RMSE |",
             "|---|---|---|---|---|"]
    stats = {}
    for col in ("om", "cams", "epa", "cons"):
        v = j.dropna(subset=[col, "retrospective_reference"])
        if not len(v):
            lines.append(f"| {col} | 0 | -- | -- | -- |")
            continue
        err = v[col] - v["retrospective_reference"]
        stats[col] = (float(np.abs(err).mean()), float(err.mean()))
        lines.append(f"| {col} | {len(v)} | {np.abs(err).mean():.2f} "
                     f"| {err.mean():+.2f} | {np.sqrt((err**2).mean()):.2f} |")
    lines += ["",
              "Reference: Open-Meteo previous-runs best_match (shared-DNA caveat).",
              "Target: MAE < 1.0, |bias| < 0.3 per source at 1-day lead."]
    out = ROOT / "docs" / "validation" / "uvi_verification.md"
    out.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(out.read_text())
    # Invariant: consensus must not lose badly to its best input.
    if "cons" in stats and "om" in stats and stats["cons"][0] > stats["om"][0] + 0.5:
        print("FAIL: consensus MAE exceeds OM MAE by >0.5", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
