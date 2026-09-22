"""Bootstrap calibration for registry sites missing artifacts.

Post-merge automation only: runs on main with secrets after owner approval.
For each enabled site lacking uva_uvb_models.joblib or local_reference.parquet,
runs `sunstack bootstrap --site <slug>` (full NASA POWER + Open-Meteo history +
CAMS EAC4 + model training). Already-calibrated sites are skipped, so normal
registry edits cost nothing and a new location self-provisions on merge.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from sunstack import config
from sunstack.cli import calibration_paths


def _missing(site_slug: str | None) -> bool:
    _, calibration_dir, _ = calibration_paths(Path("data"), site_slug)
    required = [calibration_dir / "uva_uvb_models.joblib", calibration_dir / "local_reference.parquet"]
    return not all(p.exists() for p in required)


def _parse_args(argv: list[str] | None = None) -> None:
    import argparse

    parser = argparse.ArgumentParser(description="Bootstrap missing site calibrations")
    _ = parser.parse_args(argv)


def main() -> int:
    _parse_args()
    sites = config.active_sites()
    default_slug = config.default_site().slug
    pending = [s for s in sites if _missing(None if s.slug == default_slug else s.slug)]
    if not pending:
        print("All enabled sites already calibrated; nothing to do.")
        return 0
    print(f"Calibrating {len(pending)} site(s): {', '.join(s.slug for s in pending)}")
    failed: list[str] = []
    for site in pending:
        print(f"--- bootstrap --site {site.slug} ({site.name}) ---", flush=True)
        proc = subprocess.run(
            ["uv", "run", "sunstack", "bootstrap", "--site", site.slug],
            check=False,
        )
        if proc.returncode != 0:
            print(f"FAILED calibration for {site.slug} (exit {proc.returncode})")
            failed.append(site.slug)
    if failed:
        print(f"Calibration failed for: {failed}")
        return 1
    print("All pending site calibrations complete.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
