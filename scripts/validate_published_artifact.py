"""Independent serialized-artifact validator (v5 contract section 22).

Reads data.json outputs AS CONSUMERS SEE THEM and independently recomputes
invariants. ``validation_issues=[]`` may only be emitted after this serialized
check passes. Fatal checks: schema/versions present, spectrum checksum,
model/reference manifest compatibility, unique UVI counts, consensus within
range, E_ery equals UVI/40, SED recomputation, delayed-pigmentation dose
recomputation, night-UV bound, true peaks, at_best interval provenance,
feasibility missingness honesty, source-count bounds, surface invariance,
no deprecated ranking key, row/summary version agreement.
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
    "manifests_compatible",
    "unique_uvi_source_count",
    "uvi_consensus_within_range",
    "ery_equals_uvi_over_40",
    "sed_recomputes",
    "dp_dose_recomputes",
    "no_finite_night_uv",
    "peaks_are_true_maxima",
    "at_best_from_window",
    "feasibility_missingness_honest",
    "confidence_contract",
    "source_counts_bounded",
    "surface_local_mode_invariant",
    "daylight_fit_denominator",
    "no_deprecated_ranking_key",
    "row_summary_version_agreement",
    "no_stale_local_reference",
    "no_premanifest_model",
    "row_action_spectrum_identity",
]
# Fields whose name says "value at the selected best window/time": each must
# equal its source column on the row the daily row selects (best_30m_start),
# never another metric's peak. (source columns, absolute tolerance)
_AT_BEST_FIELDS: dict[str, tuple[tuple[str, ...], float]] = {
    "day_absolute_at_best_usable_30m_0_100": (("tan_score_absolute_0_100",), 0.15),
    "day_local_at_best_usable_30m_0_100": (("local_tan_score_0_100",), 0.15),
    "day_confidence_at_peak_0_100": (("tan_forecast_confidence_0_100",), 0.15),
    "uvi_at_best": (("uvi_consensus", "uv_index"), 0.06),
    "temperature_at_best_f": (("temperature_2m",), 0.11),
    "precip_at_best_pct": (("precipitation_probability",), 0.11),
}


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


def _twin_mismatch(alias: object, twin: object) -> bool:
    """True when both names are published and disagree (canonical twin rule).

    The v5 canonical names are exact copies of the legacy columns; a build
    that publishes only the legacy name is accepted (migration window).
    """
    if alias is None or twin is None:
        return False
    if isinstance(alias, bool) or isinstance(twin, bool):
        return bool(alias) != bool(twin)
    if _is_finite(alias) and _is_finite(twin):
        return abs(_num(alias) - _num(twin)) > 1e-9
    return str(alias) != str(twin)


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

    # §22.3 model/reference manifests compatible: the published identity block
    # must agree with itself (summary vs score_semantics vs daily rows) and
    # with the shipped reference manifests on disk. Unreadable/absent shipped
    # manifests are skipped (a consumer cannot be shown a claim we never made).
    semantic_raw = summary.get("score_semantics")
    semantic_block = (cast(dict[str, object], semantic_raw)
                      if isinstance(semantic_raw, dict) else None)
    if semantic_block is not None:
        for key in ("tan_score_model_version", "photobiology_model_version",
                    "action_spectrum_version", "fusion_version",
                    "confidence_version", "window_rank_version",
                    "global_reference_version"):
            if (key in summary and key in semantic_block
                    and summary[key] != semantic_block[key]):
                failures["manifests_compatible"].append(
                    f"summary {key} != score_semantics {key}")
        backend = summary.get("spectral_backend")
        strict_backend = semantic_block.get("spectral_backend_strict")
        degraded_backend = semantic_block.get("spectral_backend_degraded")
        if (isinstance(backend, str) and isinstance(strict_backend, str)
                and isinstance(degraded_backend, str)
                and backend not in (strict_backend, degraded_backend)):
            failures["manifests_compatible"].append(
                f"spectral_backend {backend} not declared in score_semantics")
    try:
        ref_path = Path("data/calibration/global_melanogenic_reference/reference.json")
        ref_version: object = None
        if ref_path.exists():
            ref = cast(dict[str, object],
                       json.loads(ref_path.read_text(encoding="utf-8")))
            ref_version = ref.get("global_reference_version")
            for key in ("global_reference_version", "global_reference_e_mel_wm2"):
                if key not in ref or key not in summary:
                    continue
                if key == "global_reference_e_mel_wm2" and _is_finite(ref[key]) and _is_finite(summary[key]):
                    if abs(_num(ref[key]) - _num(summary[key])) > 1e-9:
                        failures["manifests_compatible"].append(
                            f"summary {key} != shipped reference manifest")
                elif ref[key] != summary[key]:
                    failures["manifests_compatible"].append(
                        f"summary {key} != shipped reference manifest")
        local_path = Path("data/calibration/local_reference_version.json")
        if local_path.exists():
            local = cast(dict[str, object],
                         json.loads(local_path.read_text(encoding="utf-8")))
            for key in ("tan_score_model_version", "global_reference_version"):
                if key in local and key in summary and local[key] != summary[key]:
                    failures["manifests_compatible"].append(
                        f"summary {key} != local reference manifest")
            if (ref_version is not None
                    and "global_reference_version" in local
                    and local["global_reference_version"] != ref_version):
                failures["manifests_compatible"].append(
                    "local reference manifest != global reference manifest")
    except (OSError, ValueError) as exc:
        failures["manifests_compatible"].append(str(exc))

    rows = _rows_of(hourly if hourly else half)
    # §22.19 no stale local reference: rows stamped stale fail — a published
    # artifact must never present legacy percentiles as current. Rows without
    # the signal predate the gate and are skipped, never failed.
    for _stale_row in _rows_of(half or hourly):
        if _stale_row.get("local_reference_stale") is True:
            failures["no_stale_local_reference"].append(
                f"{_stale_row.get('time')}: local_reference_stale=true")
            break
    # §22.20 no pre-manifest model: rows whose calibration tier is missing
    # (never scored by a manifest-bound bundle) fail. Tier present = gated
    # upstream; tier absent = unpublished provenance.
    for _tier_row in _rows_of(half or hourly):
        if "tan_calibration_tier" in _tier_row and not _tier_row.get("tan_calibration_tier"):
            failures["no_premanifest_model"].append(
                f"{_tier_row.get('time')}: tan_calibration_tier missing")
            break
    # §3/§28: every published row must name the action spectrum its scores were
    # convolved against. The carry-out whitelist in build_30min_forecast dropped
    # these columns once, silently, because every other recomputed child still
    # shipped (RESEARCH_NOTES defect E). A row that cannot name its spectrum is
    # not publishable, so absence is fatal, not merely a mismatch.
    _sum_spec = summary.get("action_spectrum_version")
    for _id_row in _rows_of(half or hourly):
        if _id_row.get("action_spectrum_version") != _sum_spec:
            failures["row_action_spectrum_identity"].append(
                f"{_id_row.get('time')}: row action_spectrum_version {_id_row.get('action_spectrum_version')!r} != summary {_sum_spec!r}")
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
        for key in ("tan_score_model_version", "spectral_backend", "action_spectrum_version"):
            if key in row and key in summary and row[key] != summary[key]:
                failures["row_summary_version_agreement"].append(f"{stamp}: {key} {row[key]} != summary {summary[key]}")
        # §22.13 confidence contract: confidence must be a calibrated function
        # of expected error (100*exp(-err/1.2), never sunniness), possibly
        # reduced by the published disagreement penalties (uv_input_disagree
        # halves, uvi spread ×0.85 mild / ×0.65 strong; physics untouched).
        # Recompute the mapping from the row's own uvi_expected_abs_error and
        # require the published confidence to match one of the legal states.
        # Rows without an error estimate are skipped (pre-contract artifacts).
        _err = row.get("uvi_expected_abs_error")
        _conf = row.get("tan_forecast_confidence_0_100")
        if _is_finite(_err) and _is_finite(_conf):
            import math as _math

            _base_conf = round(
                min(100.0, max(1.0, 100.0 * _math.exp(-_num(_err) / 1.2))), 1)
            _legal = {round(_base_conf * f, 1)
                      for f in (1.0, 0.85, 0.65, 0.5, 0.5 * 0.85, 0.5 * 0.65)}
            if min(abs(_num(_conf) - v) for v in _legal) > 1.5:
                failures["confidence_contract"].append(
                    f"{stamp}: confidence {_conf} not in {sorted(_legal)}")

    day_rows = _rows_of(daily)
    half_rows = _rows_of(half)
    # §22.17 setup: the artifact declares its own deprecated names; ranking
    # keys must not name one of them (or a column that is not published).
    deprecated_names: set[str] = set()
    declared_deprecated = summary.get("deprecated_fields")
    if isinstance(declared_deprecated, list):
        deprecated_names.update(str(x) for x in cast(list[object], declared_deprecated))
    declared_aliases = summary.get("deprecated_aliases")
    if isinstance(declared_aliases, dict):
        deprecated_names.update(
            str(k) for k in cast(dict[object, object], declared_aliases))
    emitted_columns: set[str] = set()
    for r in (half_rows or rows):
        emitted_columns.update(str(k) for k in r)
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
        # §16.5/§27.11: every *_at_best* field carries the value of the
        # interval the daily row selects (best_30m_start), never another
        # metric's peak.
        sel_stamp = str(day.get("best_30m_start") or "")[:16]
        sel_row = next((r for r in scoped_pool
                        if str(r.get("time", ""))[:16] == sel_stamp), None)
        if sel_row is not None:
            for day_col, (src_cols, tol) in _AT_BEST_FIELDS.items():
                if day_col not in day:
                    continue
                src = next((sel_row.get(c) for c in src_cols
                            if _is_finite(sel_row.get(c))), None)
                if not _is_finite(day.get(day_col)) or not _is_finite(src):
                    continue
                if abs(_num(day[day_col]) - _num(src)) > tol:
                    failures["at_best_from_window"].append(
                        f"{date}: {day_col} != value at {sel_stamp}")
        # §22.17: no deprecated v4 column may serve as the v5 ranking key.
        # A ranking declaration the artifact publishes must name a live,
        # non-deprecated column.
        for key, value in day.items():
            if "rank" not in key or not isinstance(value, str):
                continue
            if value in deprecated_names:
                failures["no_deprecated_ranking_key"].append(
                    f"{date}: {key} names deprecated column {value}")
            elif key.endswith("_rank_key") and value not in emitted_columns:
                failures["no_deprecated_ranking_key"].append(
                    f"{date}: {key} names unemitted column {value}")

    def _row_interval_seconds(r: dict[str, object] | None) -> float | None:
        # Explicit interval support wins: the row's own [start, end] bounds
        # give the exact rectangular duration. None = legacy point sample.
        if not isinstance(r, dict):
            return None
        if r.get("radiation_support_type") != "interval_mean":
            return None
        try:
            s = datetime.fromisoformat(str(r.get("interval_start_utc")))
            e = datetime.fromisoformat(str(r.get("interval_end_utc")))
        except (ValueError, TypeError):
            return None
        dt = (e - s).total_seconds()
        return dt if dt > 0 else None

    def _rect_or_trap(r1: dict[str, object] | None, e1: float, e0: float, dt: float) -> float:
        dur = _row_interval_seconds(r1)
        if dur is not None:
            return e1 * dur
        return 0.5 * (e0 + e1) * dt

    # SED recompute: support-aware. Interval-mean rows (with explicit
    # [interval_start_utc, interval_end_utc]) integrate rectangularly
    # (E_bar × duration, contract §5.4); legacy point-sample rows fall back
    # to trapezoid legs. Pure python, no pandas: the validator must not
    # share the pipeline's frame logic.
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
        for (t0, e0, _), (t1, e1, s1) in pairwise(parsed):
            dt = (t1 - t0).total_seconds()
            if abs(dt - 1800.0) > 60.0:
                continue
            r1 = next((r for r in rows if r.get("time") == s1), None)
            expected = _rect_or_trap(r1, e1, e0, dt) / 100.0
            # Trailing doses END at their row stamp: the [t0, t1] leg lives on
            # the row at t1 (the t0 row's value covers [t0-30m, t0]).
            emitted = next((r.get("sed_30m") for r in rows if r.get("time") == s1), None)
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

    # §22.8 delayed-pigmentation dose independently recomputes: rectangular
    # interval doses where rows carry explicit support (contract §5.4),
    # trapezoid legs for legacy point samples — plus the day and window
    # totals that must fall out of those same rows. Canonical twins are
    # verified whenever a build emits them (legacy-only artifacts are
    # accepted during the migration window).
    try:
        dp_rows = half_rows or rows
        dp_pts: list[tuple[datetime, float, dict[str, object]]] = []
        for r in dp_rows:
            t = r.get("time")
            e = r.get("delayed_pigmentation_effective_irradiance_horizontal_wm2")
            if not _is_finite(e):
                e = r.get("melanogenic_effective_irradiance_wm2")
            if not isinstance(t, str) or not _is_finite(e):
                continue
            try:
                dp_pts.append((datetime.fromisoformat(t), _num(e), r))
            except ValueError:
                continue
        dp_pts.sort(key=lambda p: p[0])

        def _window_integral(start: datetime, end: datetime) -> float:
            total = 0.0
            for (t0, leg0, _), (t1, leg1, r1) in pairwise(dp_pts):
                dt = (t1 - t0).total_seconds()
                # Same gap rule as the pipeline; published window stamps bound
                # real samples, so legs are always fully inside or outside.
                if dt > 3600.0 or t0 < start or t1 > end:
                    continue
                total += _rect_or_trap(r1, leg1, leg0, dt)
            return total

        for (t0, leg0, _), (t1, leg1, r1) in pairwise(dp_pts):
            dt = (t1 - t0).total_seconds()
            if abs(dt - 1800.0) > 60.0:
                continue
            expected = _rect_or_trap(r1, leg1, leg0, dt)
            emitted = r1.get("delayed_pigmentation_dose_30m_j_m2",
                             r1.get("tan_dose_30m_j_m2"))
            if _is_finite(emitted) and abs(_num(emitted) - expected) > max(0.05, 0.05 * abs(expected)):
                failures["dp_dose_recomputes"].append(f"{t1}: 30m dose mismatch")
            for alias, twin in (("tan_dose_30m_j_m2", "delayed_pigmentation_dose_30m_j_m2"),
                                ("tan_dose_30m_complete", "delayed_pigmentation_dose_30m_complete"),
                                ("tan_dose_30m_coverage_fraction",
                                 "delayed_pigmentation_dose_30m_coverage_fraction")):
                if _twin_mismatch(r1.get(alias), r1.get(twin)):
                    failures["dp_dose_recomputes"].append(f"{t1}: {twin} != {alias}")
        for day in _rows_of(daily):
            stamp = str(day.get("date", ""))
            day_pts = [p for p in dp_pts if p[0].date().isoformat() == stamp]
            if day_pts:
                expected_day = _window_integral(day_pts[0][0], day_pts[-1][0])
                emitted_day = day.get("delayed_pigmentation_dose_day_j_m2",
                                      day.get("tan_dose_day_j_m2"))
                if _is_finite(emitted_day) and abs(_num(emitted_day) - expected_day) > max(0.5, 0.05 * abs(expected_day)):
                    failures["dp_dose_recomputes"].append(f"{stamp}: day dose mismatch")
            for alias, twin in (("tan_dose_day_j_m2", "delayed_pigmentation_dose_day_j_m2"),
                                ("tan_dose_complete", "delayed_pigmentation_dose_complete"),
                                ("tan_dose_coverage_fraction",
                                 "delayed_pigmentation_dose_coverage_fraction"),
                                ("tan_dose_best_window_j_m2",
                                 "delayed_pigmentation_dose_best_window_j_m2"),
                                ("tan_dose_best_window_complete",
                                 "delayed_pigmentation_dose_best_window_complete"),
                                ("tan_dose_best_window_coverage_fraction",
                                 "delayed_pigmentation_dose_best_window_coverage_fraction")):
                if _twin_mismatch(day.get(alias), day.get(twin)):
                    failures["dp_dose_recomputes"].append(f"{stamp}: {twin} != {alias}")
            for start_col, end_col, dose_col, twin_name in (
                ("best_usable_30m_start", "best_usable_30m_end",
                 "best_usable_30m_dose_j_m2", None),
                ("best_window_start", "best_window_end", "tan_dose_best_window_j_m2",
                 "delayed_pigmentation_dose_best_window_j_m2"),
            ):
                start, end = day.get(start_col), day.get(end_col)
                if not (isinstance(start, str) and isinstance(end, str)):
                    continue
                dose = day.get(dose_col)
                if twin_name is not None and day.get(twin_name) is not None:
                    dose = day[twin_name]
                if not _is_finite(dose):
                    continue
                try:
                    expected = _window_integral(datetime.fromisoformat(start),
                                                datetime.fromisoformat(end))
                except ValueError:
                    continue
                if abs(_num(dose) - expected) > max(0.5, 0.05 * abs(expected)):
                    failures["dp_dose_recomputes"].append(
                        f"{stamp}: {dose_col} does not recompute over {start_col}")
    except (ValueError, TypeError) as exc:
        failures["dp_dose_recomputes"].append(str(exc))

    for r in rows:
        if "surface_material_slug" in r and "melanogenic_effective_irradiance_wm2" not in r:
            failures["surface_local_mode_invariant"].append("surface context without horizontal E_mel")
            break

    # §22.16 static Fit denominator: every published half-hour row must be a
    # daylight row under the export mask (is_day>0 else solar_elevation>0).
    # Night rows in the served payload would silently enter Fit's denominator.
    for r in half_rows or rows:
        _is_day = r.get("is_day")
        _elev = r.get("solar_elevation_deg")
        _daylit = (_is_finite(_is_day) and _num(_is_day) > 0) or (
            _is_finite(_elev) and _num(_elev) > 0)
        # Frames without either signal retain all rows (same rule as export).
        _has_signal = _is_finite(_is_day) or _is_finite(_elev)
        if _has_signal and not _daylit:
            failures["daylight_fit_denominator"].append(
                f"{r.get('time')}: night row in daylight payload")
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
