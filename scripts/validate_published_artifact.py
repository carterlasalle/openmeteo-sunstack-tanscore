"""Independent serialized-artifact validator (v5 contract section 22).

Reads data.json outputs AS CONSUMERS SEE THEM and independently recomputes
invariants. ``validation_issues=[]`` may only be emitted after this serialized
check passes. Fatal checks: schema/versions present, spectrum checksum,
unique UVI counts, consensus within range, E_ery equals UVI/40, SED
recomputation, night-UV bound, true peaks, feasibility missingness honesty,
source-count bounds, surface invariance, row/summary version agreement.
"""

from __future__ import annotations

import json
import math
from datetime import datetime
from pathlib import Path
from typing import TypedDict, cast

FATAL_CHECKS = [
    "schema_version_present",
    "action_spectrum_checksum",
    "unique_uvi_source_count",
    "uvi_consensus_within_range",
    "ery_equals_uvi_over_40",
    "sed_recomputes",
    "no_finite_night_uv",
    "peaks_are_true_maxima",
    "feasibility_missingness_honest",
    "source_counts_bounded",
    "surface_local_mode_invariant",
    "row_summary_version_agreement",
]


class ArtifactDoc(TypedDict):
    summary: dict[str, object]
    hourly: list[object]
    half_hour: list[object]
    daily: list[object]


def _is_finite(x: object) -> bool:
    if isinstance(x, bool):
        return False
    if isinstance(x, (int, float)):
        return math.isfinite(float(x))
    if isinstance(x, str):
        try:
            return math.isfinite(float(x))
        except ValueError:
            return False
    return False


def _num(x: object) -> float:
    assert isinstance(x, (int, float, str)) and _is_finite(x)
    if isinstance(x, str):
        return float(x)
    return float(x)


def _rows_of(items: list[object]) -> list[dict[str, object]]:
    out: list[dict[str, object]] = []
    for r in items:
        if isinstance(r, dict):
            out.append(cast(dict[str, object], r))
    return out


def validate_artifact(data_path: Path) -> dict[str, object]:
    """Validate a serialized data.json artifact. Returns failures by check."""
    from itertools import pairwise

    doc = cast(ArtifactDoc, json.loads(Path(data_path).read_text(encoding="utf-8")))
    summary = doc.get("summary", {})
    hourly = doc.get("hourly", [])
    half = doc.get("half_hour", [])
    daily = doc.get("daily", [])
    failures: dict[str, list[str]] = {c: [] for c in FATAL_CHECKS}

    for key in ("schema_version", "tan_score_model_version",
                "action_spectrum_version", "fusion_version",
                "confidence_version", "window_rank_version"):
        if not summary.get(key):
            failures["schema_version_present"].append(f"summary missing {key}")

    try:
        from sunstack.photobiology import ACTION_SPECTRUM_STEM, load_action_spectrum

        spec = load_action_spectrum(ACTION_SPECTRUM_STEM)
        meta_path = Path("data/research/action_spectra") / f"{ACTION_SPECTRUM_STEM}.meta.json"
        if meta_path.exists():
            meta = cast(dict[str, object], json.loads(meta_path.read_text(encoding="utf-8")))
            if meta.get("checksum_sha256") != spec.sha256:
                failures["action_spectrum_checksum"].append("shipped checksum mismatch")
            ver = summary.get("action_spectrum_version")
            allowed = (meta.get("action_spectrum_version"), spec.name, ACTION_SPECTRUM_STEM)
            if ver not in allowed:
                failures["action_spectrum_checksum"].append(
                    "summary action_spectrum_version disagrees with shipped metadata")
    except (ImportError, OSError, ValueError) as exc:
        failures["action_spectrum_checksum"].append(str(exc))

    rows = _rows_of(hourly if hourly else half)
    for row in rows:
        stamp = row.get("time")
        # Same triple the fusion consumes (state._stack_sources): uvi_openmeteo
        # when present else the OM display value uv_index, plus CAMS and EPA.
        om_col = ("uvi_openmeteo" if _is_finite(row.get("uvi_openmeteo"))
                  else "uv_index")
        vals = [row.get(c) for c in (om_col, "uvi_cams", "uvi_epa")]
        finite = [_num(v) for v in vals if _is_finite(v)]
        cons = row.get("uvi_consensus")
        n_src = row.get("uvi_consensus_sources")
        if _is_finite(n_src) and int(_num(n_src)) != len(finite):
            failures["unique_uvi_source_count"].append(f"{stamp}: sources={n_src} vs {len(finite)} finite")
        if _is_finite(n_src) and int(_num(n_src)) > 3:
            failures["source_counts_bounded"].append(f"{stamp}: sources={n_src} > 3 providers")
        if _is_finite(cons) and len(finite) >= 2 and not min(finite) - 0.01 <= _num(cons) <= max(finite) + 0.01:
            failures["uvi_consensus_within_range"].append(f"{stamp}: consensus {cons} outside range")
        ery = row.get("erythemal_irradiance_wm2")
        if _is_finite(cons) and _is_finite(ery) and abs(_num(ery) - _num(cons) / 40.0) > 1e-3:
            failures["ery_equals_uvi_over_40"].append(f"{stamp}: E_ery {ery} != UVI/40")
        if row.get("is_day") == 0 and _is_finite(cons) and abs(_num(cons)) > 0.05:
            failures["no_finite_night_uv"].append(f"{stamp}: night UVI {cons}")
        feas = row.get("outdoor_feasibility_0_100")
        if feas is not None and _is_finite(feas) and float(_num(feas)) == 100.0 and row.get("outdoor_feasibility_complete") is False:
            failures["feasibility_missingness_honest"].append(f"{stamp}: 100 feasibility with complete=false")
        for key in ("tan_score_model_version", "spectral_backend"):
            if key in row and key in summary and row[key] != summary[key]:
                failures["row_summary_version_agreement"].append(f"{stamp}: {key} {row[key]} != summary {summary[key]}")

    day_rows = _rows_of(daily)
    half_rows = _rows_of(half)
    for day in day_rows:
        date = str(day.get("date", ""))
        # Peaks are built from the 30-min daylight frame (build_daily_summary
        # over tan_forecast_30min); hourly rows are coarser and must never be
        # the comparison set when half-hour rows exist for the date.
        scoped_pool = ([r for r in half_rows if str(r.get("time", ""))[:10] == date]
                       or [r for r in rows if str(r.get("time", ""))[:10] == date])
        for peak_col, src_col in (("day_absolute_peak_0_100", "tan_score_absolute_0_100"),
                                  ("day_local_peak_0_100", "local_tan_score_0_100")):
            if peak_col not in day:
                continue
            colmax = max((_num(r.get(src_col)) for r in scoped_pool if _is_finite(r.get(src_col))), default=float("nan"))
            if _is_finite(day.get(peak_col)) and _is_finite(colmax) and abs(_num(day[peak_col]) - colmax) > 0.15:
                failures["peaks_are_true_maxima"].append(f"{day.get('date')}: {peak_col} != max")

    # SED recompute: consecutive 30-min rows with finite erythemal must match
    # the emitted trailing sed_30m within tolerance (pure-python trapezoid,
    # no pandas: the validator must not share the pipeline's frame logic).
    try:
        stamps: list[str] = []
        ervals: list[float] = []
        for r in rows:
            t = r.get("time")
            e = r.get("erythemal_irradiance_wm2")
            if isinstance(t, str) and _is_finite(e):
                stamps.append(t)
                ervals.append(_num(e))
        parsed: list[tuple[datetime, float, str]] = []
        for t, e in zip(stamps, ervals):
            try:
                parsed.append((datetime.fromisoformat(t), e, t))
            except ValueError:
                continue
        parsed.sort(key=lambda p: p[0])
        checked = 0
        for (t0, e0, s0), (t1, e1, s1) in pairwise(parsed):
            dt = (t1 - t0).total_seconds()
            if abs(dt - 1800.0) > 60.0:
                continue
            expected = 0.5 * (e0 + e1) * dt / 100.0
            emitted = next((r.get("sed_30m") for r in rows if r.get("time") in (s0, s1)), None)
            if _is_finite(emitted):
                checked += 1
                if abs(_num(emitted) - expected) > max(0.05, 0.05 * abs(expected)):
                    failures["sed_recomputes"].append(f"{s1}: sed_30m mismatch")
        if not checked and len(parsed) >= 2:
            total = sum(0.5 * (a[1] + b[1]) * (b[0] - a[0]).total_seconds() for a, b in pairwise(parsed)) / 100.0
            if not math.isfinite(total) or total < 0:
                failures["sed_recomputes"].append("SED recomputation non-finite")
    except (ValueError, TypeError) as exc:
        failures["sed_recomputes"].append(str(exc))

    for r in rows:
        if "surface_material_slug" in r and "melanogenic_effective_irradiance_wm2" not in r:
            failures["surface_local_mode_invariant"].append("surface context without horizontal E_mel")
            break

    failed = {k: v for k, v in failures.items() if v}
    return {"passed": not failed, "failures": failed, "checks": FATAL_CHECKS, "artifact": str(data_path)}


def main(argv: list[str] | None = None) -> int:
    import argparse

    ap = argparse.ArgumentParser()
    _ = ap.add_argument("artifact", default="docs/data.json", nargs="?")
    ns = ap.parse_args(argv)
    result = validate_artifact(Path(cast(str, ns.artifact)))
    print(json.dumps(result, indent=2))
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
