"""Time-integrated doses: TanDose (melanogenic), SED (erythemal), UVA/UVB physical.

Point samples use trapezoidal integration over actual timestamps; interval
means use their exact rectangular support. Gaps or incomplete interval cover
mark tan_dose_complete/sed_complete = False with a coverage fraction. Night
rows integrate as zero.
"""
from __future__ import annotations

from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd

from . import config
from .calibrate import num
from .photobiology import (
    TAN_DOSE_MODEL_VERSION,
    integrate_band_dose,
    integrate_sed,
    integrate_tandose,
    reference_minutes,
)
from .temporal import integrate_interval_means_exact


def _utc_seconds(frame: pd.DataFrame) -> np.ndarray:
    if "time_utc" in frame:
        t = pd.to_datetime(frame["time_utc"], utc=True)
    else:
        t = pd.to_datetime(frame["time"], utc=True, errors="coerce")
    # Unparseable stamps become NaN (absent samples), never an exception that
    # would nuke the whole frame's doses: _rolling_integral skips them loudly
    # via NaN doses + incomplete flags.
    return t.map(lambda x: x.timestamp() if pd.notna(x) else float("nan")).to_numpy(dtype=float)


def _interval_bounds_seconds(frame: pd.DataFrame) -> tuple[np.ndarray, np.ndarray] | None:
    for start_col, end_col in (
        ("interval_start_utc", "interval_end_utc"),
        ("interval_start", "interval_end"),
    ):
        if start_col in frame and end_col in frame:
            start = pd.to_datetime(frame[start_col], utc=True, errors="coerce")
            end = pd.to_datetime(frame[end_col], utc=True, errors="coerce")
            return (
                start.map(lambda x: x.timestamp() if pd.notna(x) else float("nan")).to_numpy(dtype=float),
                end.map(lambda x: x.timestamp() if pd.notna(x) else float("nan")).to_numpy(dtype=float),
            )
    return None


def _uses_interval_means(frame: pd.DataFrame) -> bool:
    support = frame.get("radiation_support_type")
    return (
        isinstance(support, pd.Series)
        and bool(support.fillna("").eq("interval_mean").all())
        and _interval_bounds_seconds(frame) is not None
    )


def _interval_mean_integral(
    frame: pd.DataFrame,
    vals: np.ndarray | pd.Series,
    start_s: float,
    end_s: float,
    bounds: tuple[np.ndarray, np.ndarray] | None = None,
) -> tuple[float, bool, float]:
    if not np.isfinite(start_s) or not np.isfinite(end_s) or end_s <= start_s:
        return float("nan"), False, 0.0
    bounds = _interval_bounds_seconds(frame) if bounds is None else bounds
    if bounds is None:
        return float("nan"), False, 0.0
    starts, ends = bounds
    values = np.asarray(vals, dtype=float)
    if values.shape != starts.shape:
        return float("nan"), False, 0.0
    overlap = np.minimum(ends, end_s) - np.maximum(starts, start_s)
    overlap = np.where(np.isfinite(overlap), np.maximum(overlap, 0.0), 0.0)
    selected = overlap > 0
    if not bool(selected.any()):
        return float("nan"), False, 0.0
    dose, values_complete, _ = integrate_interval_means_exact(
        overlap[selected], values[selected]
    )
    span = end_s - start_s
    valid = selected & np.isfinite(values)
    covered = float(overlap[valid].sum())
    geometry = float(overlap[selected].sum())
    coverage = float(np.clip(covered / span, 0.0, 1.0))
    complete = bool(
        values_complete
        and geometry >= span - 1e-6
        and covered >= span - 1e-6
    )
    return dose, complete, coverage


def _rolling_interval_integral(
    frame: pd.DataFrame, vals: np.ndarray, window_s: float
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    dose = np.full(len(vals), np.nan)
    complete = np.zeros(len(vals), dtype=bool)
    coverage = np.zeros(len(vals), dtype=float)
    bounds = _interval_bounds_seconds(frame)
    if bounds is None:
        return dose, complete, coverage
    _, ends = bounds
    for i, end_s in enumerate(ends):
        if np.isfinite(end_s):
            dose[i], complete[i], coverage[i] = _interval_mean_integral(
                frame, vals, end_s - window_s, end_s, bounds
            )
    return dose, complete, coverage


def _window_utc_seconds(value: str | pd.Timestamp, *, local: bool = True) -> float:
    stamp = value if isinstance(value, pd.Timestamp) else pd.Timestamp(value)
    if not isinstance(stamp, pd.Timestamp):
        return float("nan")
    if stamp.tzinfo is None:
        if local:
            stamp = stamp.tz_localize(
                ZoneInfo(config.TIMEZONE), ambiguous=False, nonexistent="shift_forward"
            )
        else:
            stamp = stamp.tz_localize("UTC")
    return float(stamp.tz_convert("UTC").timestamp())


def _rolling_integral(
    vals: np.ndarray, secs: np.ndarray, window_s: float
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Trailing-window trapezoidal integrals with gap splitting.

    Non-finite values are ABSENT samples, never zeros: legs connect
    consecutive finite stamps, so a hole either splits the window (dt >
    max_gap, loud) or is spanned by one bounded leg. Returns per row
    (dose_joules, complete, coverage_fraction). Zero integrated legs means
    the window's dose is UNKNOWN (NaN), never zero: e.g. a trailing-15m dose
    on an hourly grid cannot be computed, and reporting 0 would imply no
    exposure. ``complete`` is True only when the row's own value is finite
    and the full window is covered without a gap split.
    """
    n = len(secs)
    dose = np.full(n, np.nan)
    complete = np.zeros(n, dtype=bool)
    coverage = np.zeros(n, dtype=float)
    max_gap = float(config.TANDOSE_MAX_INTERP_GAP_S)
    finite = np.isfinite(vals) & np.isfinite(secs)
    # Chronological order is required for the backward walk; input frames are
    # chronological in production, but sorting here (stable) makes shuffled
    # or DST-reordered inputs integrate identically instead of silently
    # producing garbage. Results map back to original row positions.
    order = np.argsort(secs, kind="stable")
    s_vals = vals[order]
    s_secs = secs[order]
    s_finite = finite[order]
    for pos in range(n):
        i = order[pos]
        if not s_finite[pos]:
            continue
        lo = s_secs[pos] - window_s
        acc, covered, split, count = 0.0, 0.0, False, 0
        prev, k = pos, pos - 1
        while k >= 0:
            if not s_finite[k]:
                k -= 1
                continue
            if s_secs[k] < lo - 1e-9:
                break
            dt = float(s_secs[prev] - s_secs[k])
            if dt < 0:
                break
            if dt > max_gap:
                split = True
                break
            acc += 0.5 * (s_vals[prev] + s_vals[k]) * dt
            covered += dt
            count += 1
            prev, k = k, k - 1
        if count > 0:
            dose[i] = acc
        coverage[i] = float(np.clip(covered / window_s, 0, 1)) if window_s > 0 else 1.0
        complete[i] = bool(count > 0 and not split and covered >= window_s - 1e-6)
    return dose, complete, coverage


def _rolling_dose(
    frame: pd.DataFrame, value_col: str, window_s: float, out_name: str,
    kind: str,
) -> pd.Series:
    """Trailing-window dose ending at each interval end or point timestamp."""
    vals = num(frame, value_col).to_numpy(dtype=float)
    if _uses_interval_means(frame):
        dose, _, _ = _rolling_interval_integral(frame, vals, window_s)
    else:
        dose, _, _ = _rolling_integral(vals, _utc_seconds(frame), window_s)
    if kind == "sed":
        dose = dose / 100.0
    return pd.Series(dose, index=frame.index, name=out_name)


def _window_flags(frame: pd.DataFrame, window_s: float,
                  value_col: str | None = None) -> tuple[pd.Series, pd.Series]:
    """Per-row (complete, coverage_fraction) for a trailing window.

    Flags share the timestamp grid but respect the given family's own missing
    values: a row whose own value is missing is never marked complete, so an
    UNKNOWN dose never wears a complete flag. Pass value_col=None only for
    pure timestamp grids.
    """
    if value_col is None:
        vals = np.zeros(len(frame))
    else:
        vals = num(frame, value_col).to_numpy(dtype=float)
    if _uses_interval_means(frame):
        _, complete, coverage = _rolling_interval_integral(frame, vals, window_s)
    else:
        _, complete, coverage = _rolling_integral(vals, _utc_seconds(frame), window_s)
    return (pd.Series(complete, index=frame.index),
            pd.Series(np.round(coverage, 4), index=frame.index))


def add_interval_doses(frame: pd.DataFrame) -> pd.DataFrame:
    """Attach trailing 15m/30m/1h TanDose, SED, UVA/UVB doses + reference minutes."""
    out = frame.copy()
    if out.empty:
        return out
    if "melanogenic_effective_irradiance_wm2" not in out:
        out["melanogenic_effective_irradiance_wm2"] = np.nan
    if "erythemal_irradiance_wm2" not in out:
        if "uv_index" in out:
            out["erythemal_irradiance_wm2"] = num(out, "uv_index") / 40.0
        else:
            out["erythemal_irradiance_wm2"] = np.nan
    e_mel = num(out, "melanogenic_effective_irradiance_wm2")
    ery = num(out, "erythemal_irradiance_wm2")
    uva = num(out, "predicted_uva_wm2") if "predicted_uva_wm2" in out else e_mel * np.nan
    uvb = num(out, "predicted_uvb_wm2") if "predicted_uvb_wm2" in out else e_mel * np.nan
    pig = num(out, "pigment_darkening_effective_irradiance") \
        if "pigment_darkening_effective_irradiance" in out else e_mel * np.nan
    # NOTE: no fillna(0) anywhere here. A missing input sample is UNKNOWN and
    # must integrate as NaN (loud), never as zero exposure. Only genuinely
    # measured zeros (night rows carry 0.0) integrate as zero.
    # Contract §17.4: rolling SED fills erythemal holes from final consensus
    # UVI first, raw OM display UVI only where consensus itself is missing.
    work = out.copy()
    work["_e_mel"] = e_mel.to_numpy()
    work["_ery"] = _ery_or_uvi(out, ery).to_numpy()
    work["sed_uvi_source"] = sed_uvi_source(out, ery).to_numpy()
    work["_uva"] = uva.to_numpy()
    work["_uvb"] = uvb.to_numpy()
    work["_pig"] = pig.to_numpy()
    for label, sec in (("15m", 900.0), ("30m", 1800.0), ("1h", 3600.0)):
        out[f"tan_dose_{label}_j_m2"] = _rolling_dose(work, "_e_mel", sec, "", "tandose").to_numpy()
        out[f"sed_{label}"] = _rolling_dose(work, "_ery", sec, "", "sed").to_numpy()
        out[f"uva_dose_{label}_j_m2"] = _rolling_dose(work, "_uva", sec, "", "tandose").to_numpy()
        out[f"uvb_dose_{label}_j_m2"] = _rolling_dose(work, "_uvb", sec, "", "tandose").to_numpy()
        out[f"uva_dose_{label}_j_cm2"] = (out[f"uva_dose_{label}_j_m2"] / 1e4).round(5)
        out[f"pigment_darkening_dose_{label}_j_m2"] = _rolling_dose(
            work, "_pig", sec, "", "tandose").to_numpy()
        # Row-level support coverage is shared by every dose family on the
        # same grid. UVA/UVB/pigment doses share the TanDose flags; SED carries
        # its own pair.
        done, cov = _window_flags(work, sec, "_e_mel")
        out[f"tan_dose_{label}_complete"] = done.to_numpy(dtype=bool)
        out[f"tan_dose_{label}_coverage_fraction"] = cov.to_numpy(dtype=float)
        sdone, scov = _window_flags(work, sec, "_ery")
        out[f"sed_{label}_complete"] = sdone.to_numpy(dtype=bool)
        out[f"sed_{label}_coverage_fraction"] = scov.to_numpy(dtype=float)
    ref = float(config.GLOBAL_MELANOGENIC_REFERENCE_WM2)
    for label in ("15m", "30m", "1h"):
        out[f"tan_dose_{label}_reference_minutes"] = (
            out[f"tan_dose_{label}_j_m2"] / ref / 60.0
        ).round(2)
    out["tan_dose_model_version"] = TAN_DOSE_MODEL_VERSION
    out["sed_uvi_source"] = work["sed_uvi_source"].to_numpy()
    # v5 canonical endpoint names (contract §2.1.B): every emitted tan_dose_*
    # column gets an exact delayed_pigmentation_dose_* twin; old names stay.
    for col in [c for c in out.columns if "tan_dose" in str(c)]:
        out[str(col).replace("tan_dose", "delayed_pigmentation_dose")] = out[col]
    return out


def _group_col(group: pd.DataFrame, name: str) -> pd.Series:
    # Missing input is UNKNOWN (NaN), never zero exposure. integrate_* skip
    # non-finite samples, so a wholly missing column yields NaN/incomplete.
    return num(group, name)


def _ery_or_uvi(group: pd.DataFrame, ery: pd.Series) -> pd.Series:
    """Use erythemal irradiance; derive from final consensus UVI only when absent.

    Contract §17.4: SED uses final `uvi_consensus` first. Raw OM display UVI
    fills only consensus holes; both-missing stays unknown, never invented.
    """
    # Rowwise: fill ONLY the holes (audit: the .any() check kept null ery
    # where UVI existed). combine_first never invents where both miss.
    filled = ery.copy()
    if "uvi_consensus" in group.columns:
        filled = filled.combine_first(num(group, "uvi_consensus") / 40.0)
    if "uv_index" in group.columns:
        filled = filled.combine_first(num(group, "uv_index") / 40.0)
    return filled


def sed_uvi_source(group: pd.DataFrame, ery: pd.Series) -> pd.Series:
    """Per-row SED UVI provenance: final consensus, degraded raw OM, or missing."""
    src = pd.Series("final", index=ery.index, dtype=object)
    if "uvi_consensus" in group.columns:
        cons_missing = num(group, "uvi_consensus").isna().to_numpy()
    else:
        cons_missing = np.ones(len(ery), dtype=bool)
    ery_missing = ery.isna().to_numpy()
    src[(~ery_missing)] = "final"
    src[(ery_missing) & (~cons_missing)] = "final"
    if "uv_index" in group.columns:
        om_have = num(group, "uv_index").notna().to_numpy()
        src[(ery_missing) & (cons_missing) & (om_have)] = "degraded_om"
    src[(ery_missing) & (cons_missing) &
        ((~num(group, "uv_index").notna().to_numpy())
         if "uv_index" in group.columns else True)] = "missing"
    return src


def day_totals(frame: pd.DataFrame) -> pd.DataFrame:
    """Daily integrated totals with gap flags (one row per local date)."""
    if frame.empty:
        return pd.DataFrame()
    work = frame.copy()
    work["_secs"] = _utc_seconds(work)
    # Local date for day grouping. Half-hour frames carry local wall-clock
    # `time`/`dt` WITHOUT a time_utc column (strings do not survive the
    # numeric resample), so a wall date must be read directly: parsing it as
    # UTC and converting again would shift whole mornings into the previous
    # day at non-UTC sites and silently drop dawn exposure from day totals.
    if "time_utc" in work.columns:
        try:
            tz = ZoneInfo(config.TIMEZONE)
            local = pd.to_datetime(work["time_utc"], utc=True).dt.tz_convert(tz)
            work["_date"] = local.dt.date.astype(str)
        except (TypeError, ValueError, KeyError, AttributeError):
            work["_date"] = pd.to_datetime(work["time_utc"], utc=True).dt.date.astype(str)
    else:
        wall = pd.to_datetime(work["dt"] if "dt" in work.columns else work["time"])
        try:
            work["_date"] = wall.dt.date.astype(str)
        except AttributeError:
            work["_date"] = wall.astype(str).str.slice(0, 10)
    gap = float(config.TANDOSE_MAX_INTERP_GAP_S)
    interval_means = _uses_interval_means(work)
    rows = []
    for date, g in work.sort_values("_secs").groupby("_date"):
        source = work if interval_means else g
        e = _group_col(source, "melanogenic_effective_irradiance_wm2")
        ery = _ery_or_uvi(source, _group_col(source, "erythemal_irradiance_wm2"))
        uva = _group_col(source, "predicted_uva_wm2")
        uvb = _group_col(source, "predicted_uvb_wm2")
        if interval_means:
            day_start = _window_utc_seconds(str(date))
            day_end = _window_utc_seconds(
                str(pd.Timestamp(str(date)) + pd.DateOffset(days=1))
            )
            td_dose, td_complete, td_coverage = _interval_mean_integral(
                source, e, day_start, day_end
            )
            sd_dose, sd_complete, sd_coverage = _interval_mean_integral(
                source, ery, day_start, day_end
            )
            uva_dose, uva_complete, uva_coverage = _interval_mean_integral(
                source, uva, day_start, day_end
            )
            uvb_dose, uvb_complete, uvb_coverage = _interval_mean_integral(
                source, uvb, day_start, day_end
            )
            td = {
                "tan_dose_melanogenic_j_m2": td_dose,
                "tan_dose_complete": td_complete,
                "tan_dose_coverage_fraction": td_coverage,
            }
            sd = {
                "sed": sd_dose / 100.0,
                "sed_complete": sd_complete,
                "sed_coverage_fraction": sd_coverage,
            }
            uva_d = {
                "dose_j_m2": uva_dose,
                "complete": uva_complete,
                "coverage_fraction": uva_coverage,
            }
            uvb_d = {
                "dose_j_m2": uvb_dose,
                "complete": uvb_complete,
                "coverage_fraction": uvb_coverage,
            }
        else:
            t = pd.to_datetime(g["time_utc"] if "time_utc" in g else g["time"], utc=True)
            td = integrate_tandose(t, e, gap)
            sd = integrate_sed(t, ery, gap)
            uva_d = integrate_band_dose(t, uva, gap)
            uvb_d = integrate_band_dose(t, uvb, gap)
        day_dose = round(float(td["tan_dose_melanogenic_j_m2"]), 1)
        day_ref_min = round(reference_minutes(
            float(td["tan_dose_melanogenic_j_m2"]),
            float(config.GLOBAL_MELANOGENIC_REFERENCE_WM2)), 1)
        day_complete = bool(td["tan_dose_complete"])
        day_coverage = round(float(td["tan_dose_coverage_fraction"]), 3)
        rows.append({
            "date": date,
            "tan_dose_day_j_m2": day_dose,
            # v5 canonical endpoint names (contract §2.1.B): exact twins,
            # legacy tan_dose_* names stay as migration aliases.
            "delayed_pigmentation_dose_day_j_m2": day_dose,
            "tan_dose_day_reference_minutes": day_ref_min,
            "delayed_pigmentation_dose_day_reference_minutes": day_ref_min,
            "tan_dose_complete": day_complete,
            "delayed_pigmentation_dose_complete": day_complete,
            "tan_dose_coverage_fraction": day_coverage,
            "delayed_pigmentation_dose_coverage_fraction": day_coverage,
            "sed_day_total": round(float(sd["sed"]), 3),
            "sed_complete": bool(sd["sed_complete"]),
            "sed_coverage_fraction": round(float(sd["sed_coverage_fraction"]), 3),
            "uva_dose_day_j_m2": round(float(uva_d["dose_j_m2"]), 1),
            "uvb_dose_day_j_m2": round(float(uvb_d["dose_j_m2"]), 2),
        })
    return pd.DataFrame(rows)


def window_dose(frame: pd.DataFrame, start, end,
                max_gap_s: float | None = None) -> dict[str, float]:
    """Cumulative doses over a candidate window [start, end].

    Interval means are clipped to the exact window span; point samples retain
    the existing inclusive-endpoint trapezoid semantics.
    """
    gap = float(config.TANDOSE_MAX_INTERP_GAP_S) if max_gap_s is None else float(max_gap_s)
    sub = frame.copy()
    interval_means = _uses_interval_means(sub)
    window_is_local = "dt" in sub or "time" in sub
    g = pd.DataFrame()
    if interval_means:
        source = sub
    else:
        time_col = "dt" if "dt" in sub else "time"
        sub["_t"] = pd.to_datetime(sub[time_col], errors="coerce")
        mask = (sub["_t"] >= pd.to_datetime(start)) & (sub["_t"] <= pd.to_datetime(end))
        g = sub.loc[mask]
        source = g
    if not interval_means and g.empty:
        # No samples inside the window: exposure is UNKNOWN (NaN), never
        # zero — zero would claim a measured absence of sun.
        nan = float("nan")
        return {
            "tan_dose_best_window_j_m2": nan, "sed_best_window": nan,
            "uva_dose_window_j_m2": nan, "uvb_dose_window_j_m2": nan,
            "tan_dose_best_window_complete": False,
            "tan_dose_best_window_coverage_fraction": nan,
            # v5 canonical endpoint names (contract §2.1.B): exact twins,
            # legacy tan_dose_* names stay as migration aliases.
            "delayed_pigmentation_dose_best_window_j_m2": nan,
            "delayed_pigmentation_dose_best_window_complete": False,
            "delayed_pigmentation_dose_best_window_coverage_fraction": nan,
            "sed_best_window_complete": False,
            "sed_best_window_coverage_fraction": nan}
    def _gcol(name: str) -> pd.Series:
        return _group_col(source, name)

    if interval_means:
        window_start = _window_utc_seconds(start, local=window_is_local)
        window_end = _window_utc_seconds(end, local=window_is_local)
        td_dose, td_complete, td_coverage = _interval_mean_integral(
            source, _gcol("melanogenic_effective_irradiance_wm2"), window_start, window_end
        )
        sd_dose, sd_complete, sd_coverage = _interval_mean_integral(
            source, _ery_or_uvi(source, _gcol("erythemal_irradiance_wm2")),
            window_start, window_end,
        )
        uva_dose, uva_complete, uva_coverage = _interval_mean_integral(
            source, _gcol("predicted_uva_wm2"), window_start, window_end
        )
        uvb_dose, uvb_complete, uvb_coverage = _interval_mean_integral(
            source, _gcol("predicted_uvb_wm2"), window_start, window_end
        )
        td = {
            "tan_dose_melanogenic_j_m2": td_dose,
            "tan_dose_complete": td_complete,
            "tan_dose_coverage_fraction": td_coverage,
        }
        sd = {
            "sed": sd_dose / 100.0,
            "sed_complete": sd_complete,
            "sed_coverage_fraction": sd_coverage,
        }
        uva_d = {
            "dose_j_m2": uva_dose,
            "complete": uva_complete,
            "coverage_fraction": uva_coverage,
        }
        uvb_d = {
            "dose_j_m2": uvb_dose,
            "complete": uvb_complete,
            "coverage_fraction": uvb_coverage,
        }
    else:
        t = pd.to_datetime(g["dt"] if "dt" in g else g["time"], utc=True)
        td = integrate_tandose(t, _gcol("melanogenic_effective_irradiance_wm2"), gap)
        sd = integrate_sed(t, _ery_or_uvi(g, _gcol("erythemal_irradiance_wm2")), gap)
        uva_d = integrate_band_dose(t, _gcol("predicted_uva_wm2"), gap)
        uvb_d = integrate_band_dose(t, _gcol("predicted_uvb_wm2"), gap)
    win_dose = round(float(td["tan_dose_melanogenic_j_m2"]), 1)
    win_complete = bool(td["tan_dose_complete"])
    win_coverage = round(float(td["tan_dose_coverage_fraction"]), 3)
    return {
        "tan_dose_best_window_j_m2": win_dose,
        # v5 canonical endpoint names (contract §2.1.B): exact twins, legacy
        # tan_dose_* names stay as migration aliases.
        "delayed_pigmentation_dose_best_window_j_m2": win_dose,
        "tan_dose_best_window_complete": win_complete,
        "delayed_pigmentation_dose_best_window_complete": win_complete,
        "tan_dose_best_window_coverage_fraction": win_coverage,
        "delayed_pigmentation_dose_best_window_coverage_fraction": win_coverage,
        "sed_best_window": round(float(sd["sed"]), 3),
        "sed_best_window_complete": bool(sd["sed_complete"]),
        "sed_best_window_coverage_fraction": round(float(sd["sed_coverage_fraction"]), 3),
        "uva_dose_window_j_m2": round(float(uva_d["dose_j_m2"]), 1),
        "uvb_dose_window_j_m2": round(float(uvb_d["dose_j_m2"]), 2),
    }
