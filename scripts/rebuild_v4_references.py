"""Rebuild v4 references: local_reference (per site) + empirical grounding for the global reference.

Order of operations (adoption-safe):

1. Compute the pooled daylight E_mel distribution across all sites first.
2. If --adopt-empirical-p999 is passed (requires --new-version), apply the
   adopted value/version to the runtime config AND the manifest BEFORE any
   local reference is built, so local percentiles, version files, and the
   manifest can never disagree.
3. Build each site's local reference (melanogenic-effective scoring; legacy
   55/30/15 kept as a diagnostic column only).

Re-run after any action-spectrum or spectral-backend change.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, "src")

from sunstack import config  # noqa: E402
from sunstack.calibrate import build_local_reference  # noqa: E402
from sunstack.spectral import melanogenic_from_broadband  # noqa: E402


def _git_sha() -> str:
    try:
        out = subprocess.run(["git", "rev-parse", "--short", "HEAD"],
                             capture_output=True, text=True, check=False, timeout=10)
        return out.stdout.strip() or "unknown"
    except (OSError, subprocess.SubprocessError):
        return "unknown"


def _pooled_distribution(sites: list[config.Site], root: Path) -> dict[str, float]:
    pooled: list[np.ndarray] = []
    for site in sites:
        caldir = root / ("data/calibration" if site.default
                         else f"data/sites/{site.slug}/calibration")
        train_p = caldir / "training_calibration_hourly.parquet"
        if not train_p.exists():
            print(f"SKIP {site.slug}: no {train_p}")
            continue
        with config.use_site(site):
            training = pd.read_parquet(train_p)
            day = training.loc[
                (pd.to_numeric(training["ghi"], errors="coerce").fillna(0) > 10)
                & (pd.to_numeric(training["sza"], errors="coerce").fillna(180) < 90)]
            uva = pd.to_numeric(day["uva"], errors="coerce").fillna(0).to_numpy()
            if "uvb" in day:
                uvb = pd.to_numeric(day["uvb"], errors="coerce").fillna(0).to_numpy()
            else:
                uvb = pd.to_numeric(day["uvi"], errors="coerce").fillna(0).to_numpy() * 0.15
            pooled.append(melanogenic_from_broadband(uva, uvb))
    if not pooled:
        raise SystemExit("no training climatology found; nothing rebuilt")
    all_e = np.concatenate(pooled)
    emp = {f"p{q}": round(float(np.percentile(all_e, q)), 3)
           for q in (50, 90, 99, 99.9)}
    emp["p100max"] = round(float(all_e.max()), 3)
    emp["n"] = int(all_e.size)
    print("pooled daylight E_mel (Tier-C, melanogenic W/m^2):", emp)
    return emp


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", default=".", help="Repository root")
    ap.add_argument("--adopt-empirical-p999", action="store_true",
                    help="Adopt pooled p99.9 as the reference (requires --new-version)")
    ap.add_argument("--new-version", default=None)
    args = ap.parse_args()
    root = Path(args.root)

    sites = config.load_sites(root / "locations.yaml")
    emp = _pooled_distribution(sites, root)

    ref_path = root / "data/calibration/global_melanogenic_reference/reference.json"
    manifest = json.loads(ref_path.read_text(encoding="utf-8"))
    manifest["empirical_two_site_grounding"] = {
        "method": "Tier-C E_mel over pooled daylight training climatology "
                  "(NASA POWER UVA/UVB, south-bend + pacific-palisades, "
                  "ghi>10 & sza<90)",
        "distribution": emp,
        "note": "Temperate/subtropical sites only (max UVI ~11-12 in tables); "
                "unsampled equatorial/high-altitude extremes justify headroom "
                "above the pooled p99.9.",
    }
    manifest["build_date"] = datetime.now(UTC).date().isoformat()
    manifest["code_git_sha"] = _git_sha()
    if args.adopt_empirical_p999:
        if not args.new_version:
            raise SystemExit("--adopt-empirical-p999 requires --new-version (no silent recalibration)")
        manifest["global_reference_e_mel_wm2"] = emp["p99.9"]
        manifest["global_reference_version"] = args.new_version
        # Apply to the LIVE runtime config before building anything, so local
        # references, version files, and the manifest all agree.
        config.GLOBAL_MELANOGENIC_REFERENCE_WM2 = float(emp["p99.9"])
        config.GLOBAL_MELANOGENIC_REFERENCE_VERSION = args.new_version
        print(f"ADOPTED new reference {emp['p99.9']} ({args.new_version})")
    else:
        print(f"reference value unchanged: {manifest['global_reference_e_mel_wm2']} "
              f"({manifest['global_reference_version']})")
    ref_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    print(f"wrote {ref_path}")

    for site in sites:
        caldir = root / ("data/calibration" if site.default
                         else f"data/sites/{site.slug}/calibration")
        train_p = caldir / "training_calibration_hourly.parquet"
        if not train_p.exists():
            continue
        with config.use_site(site):
            training = pd.read_parquet(train_p)
            ref = build_local_reference(training, caldir)
            print(f"{site.slug}: rebuilt local_reference ({len(ref)} rows, "
                  f"model={config.TAN_SCORE_MODEL_VERSION}, "
                  f"ref={config.GLOBAL_MELANOGENIC_REFERENCE_VERSION})")


if __name__ == "__main__":
    main()
