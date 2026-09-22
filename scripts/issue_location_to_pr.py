"""Parse a `[Location]:` issue body into a one-entry locations.yaml append.

Secret-free by construction: pure text parsing + registry validation via
sunstack.config. Runs on `issues` events (unprivileged); the PR it opens is
what the existing location-intake workflow validates and the owner merges.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

import yaml

from sunstack.config import load_sites

FIELD_IDS = ("location-name", "slug", "latitude", "longitude", "timezone")


def parse_issue_body(body: str) -> dict[str, str]:
    """Extract issue-form fields from the rendered markdown body.

    Issue forms render as `### Label\\n\\nvalue` sections. Labels are matched
    case-insensitively; values are stripped. Raises ValueError when a
    required field is missing.
    """
    sections = re.split(r"^###\s+", body, flags=re.MULTILINE)
    found: dict[str, str] = {}
    for sec in sections:
        head, _, value = sec.partition("\n")
        label = head.strip().lower()
        for fid, label_match in (
            ("location-name", "location name"),
            ("slug", "proposed slug"),
            ("latitude", "latitude"),
            ("longitude", "longitude"),
            ("timezone", "timezone"),
        ):
            if label == label_match:
                found[fid] = value.strip()
    missing = [f for f in FIELD_IDS if not found.get(f)]
    if missing:
        raise ValueError(f"issue is missing fields: {missing}")
    return found


def slugify(name: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")
    return slug or "site"


def build_entry(fields: dict[str, str]) -> dict[str, object]:
    lat = float(fields["latitude"])
    lon = float(fields["longitude"])
    if not (-90 <= lat <= 90 and -180 <= lon <= 180):
        raise ValueError("coordinates out of range")
    slug = (fields.get("slug") or "").strip() or slugify(fields["location-name"])
    if not re.fullmatch(r"[a-z0-9][a-z0-9-]*", slug):
        raise ValueError(f"bad slug: {slug!r}")
    return {
        "slug": slug,
        "name": fields["location-name"].strip(),
        "lat": lat,
        "lon": lon,
        "timezone": fields["timezone"].strip(),
        "enabled": True,
        "default": False,
    }


def main() -> int:
    if len(sys.argv) != 4:
        print(
            "usage: issue_location_to_pr.py <issue-body.md> <base-locations.yaml> <out-locations.yaml>"
        )
        return 2
    body_path, base_path, out_path = (Path(a) for a in sys.argv[1:])
    fields = parse_issue_body(body_path.read_text(encoding="utf-8"))
    entry = build_entry(fields)
    base = load_sites(base_path)  # validates timezone, ranges, exactly-one-default
    if any(s.slug == entry["slug"] for s in base):
        raise ValueError(f"slug already exists: {entry['slug']}")
    rows: list[dict[str, object]] = yaml.safe_load(
        base_path.read_text(encoding="utf-8")
    )
    rows.append(entry)
    _ = out_path.write_text(yaml.safe_dump(rows, sort_keys=False), encoding="utf-8")
    print(
        f"Proposing **{entry['name']}** (`{entry['slug']}`): {entry['lat']}, {entry['lon']} ({entry['timezone']})"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
