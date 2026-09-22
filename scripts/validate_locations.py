"""Validate a proposed locations.yaml against the base registry.

Unprivileged by design: pure YAML parsing and geometry checks, no network,
no secrets, no calibration. Runs on pull_request_target against the BASE
commit, so fork code never executes.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from sunstack.config import default_site, load_sites


def _parse_args(argv: list[str] | None = None) -> tuple[Path, Path]:
    parser = argparse.ArgumentParser(description="Validate a proposed locations registry")
    _ = parser.add_argument("--base", required=True)
    _ = parser.add_argument("--proposed", required=True)
    parsed = parser.parse_args(argv)
    fields: dict[str, object] = vars(parsed)
    base_arg: object = fields.get("base")
    proposed_arg: object = fields.get("proposed")
    if not isinstance(base_arg, str) or not isinstance(proposed_arg, str):
        raise TypeError("registry paths must be strings")
    return Path(base_arg), Path(proposed_arg)


def main() -> int:
    base_path, proposed_path = _parse_args()
    try:
        base = load_sites(base_path)
    except (TypeError, ValueError) as exc:
        print(f"### Location intake: base registry invalid\n\n`{exc}`")
        return 1
    try:
        proposed = load_sites(proposed_path)
    except (TypeError, ValueError) as exc:
        print(f"### Location intake: proposed registry rejected\n\n`{exc}`")
        return 1

    base_slugs = {s.slug for s in base}
    new = [s for s in proposed if s.slug not in base_slugs]
    removed = [s.slug for s in base if s.slug not in {s.slug for s in proposed}]
    changed = [s.slug for s in proposed if s.slug in base_slugs and s != next(b for b in base if b.slug == s.slug)]

    lines = ["### Location intake: validation"]
    if removed or changed:
        lines.append(f"REJECTED: proposals may only append entries (removed={removed}, changed={changed}).")
        print("\n".join(lines))
        return 1
    if not new:
        lines.append("No new locations proposed.")
        print("\n".join(lines))
        return 0
    default = default_site(proposed_path)
    for s in new:
        lines.append(f"- **{s.name}** (`{s.slug}`): {s.lat}, {s.lon} ({s.timezone})")
    lines.append(f"Default stays `{default.slug}`. Owner approval still required before any calibration runs.")
    print("\n".join(lines))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
