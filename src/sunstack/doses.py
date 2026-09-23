"""Time-integrated doses: TanDose (melanogenic), SED (erythemal), UVA/UVB physical.

All integrals use trapezoidal time integration over ACTUAL timestamps, never
value * nominal interval. Gaps larger than config.TANDOSE_MAX_INTERP_GAP_S
split the integration and mark tan_dose_complete/sed_complete = False with a
coverage fraction. Night rows integrate as zero.
"""
from __future__ import annotations

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


def _utc_seconds(frame: pd.DataFrame) -> np.ndarray:
    if "time_utc" in frame:
        t = pd.to_datetime(frame["time_utc"], utc=True)
    else:
        t = pd.to_datetime(frame["time"], utc=True, errors="coerce")
    return t.map(lambda x: x.timestamp()).to_numpy(dtype=float)


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
    for i in range(n):
        if not finite[i]:
            continue
        lo = secs[i] - window_s
        acc, covered, split, count = 0.0, 0.0, False, 0
        prev, k = i, i - 1
        while k >= 0:
            if not finite[k]:
                k -= 1
                continue
            if secs[k] < lo - 1e-9:
                break
            dt = float(secs[prev] - secs[k])
            if dt < 0:
                break
            if dt > max_gap:
                split = True
                break
            acc += 0.5 * (vals[prev] + vals[k]) * dt
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
    """Trailing-window trapezoidal dose ending at each row's timestamp.

    Missing (NaN) samples are absent data, never zeros — see _rolling_integral.
    """
    vals = pd.to_numeric(frame[value_col], errors="coerce").to_numpy(dtype=float) \
        if value_col in frame else np.full(len(frame), np.nan)
    secs = _utc_seconds(frame)
    dose, _, _ = _rolling_integral(vals, secs, window_s)
    if kind == "sed":
        dose = dose / 100.0
    if kind == "uv_cm2":
        dose = dose / 1e4
    return pd.Series(dose, index=frame.index, name=out_name)


def _window_flags(frame: pd.DataFrame, window_s: float,
                  value_col: str | None = None) -> tuple[pd.Series, pd.Series]:
    """Per-row (complete, coverage_fraction) for a trailing window.

    Timestamp support is shared by every dose family on the same grid, but a
    row whose own value is missing is never marked complete: an UNKNOWN dose
    must not wear a complete flag. Pass value_col=None only for pure
    timestamp grids.
    """
    secs = _utc_seconds(frame)
    if value_col is not None and value_col in frame:
        vals = pd.to_numeric(frame[value_col], errors="coerce").to_numpy(dtype=float)
    else:
        vals = np.zeros(len(frame)) if value_col is None else np.full(len(frame), np.nan)
    _, complete, coverage = _rolling_integral(vals, secs, window_s)
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
            out["erythemal_irradiance_wm2"] = (
                pd.to_numeric(out["uv_index"], errors="coerce") / 40.0
            )
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

    work = out.copy()
    work["_e_mel"] = e_mel.to_numpy()
    work["_ery"] = ery.to_numpy()
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
        # Row-level gap marking (§1.3): timestamp-only, shared by every dose
        # family on the same grid. UVA/UVB/pigment doses share the TanDose
        # flags; SED carries its own pair.
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
    return out


def _group_col(group: pd.DataFrame, name: str) -> pd.Series:
    # Missing input is UNKNOWN (NaN), never zero exposure. integrate_* skip
    # non-finite samples, so a wholly missing column yields NaN/incomplete.
    if name not in group.columns:
        return pd.Series(np.nan, index=group.index, dtype="float64")
    return pd.to_numeric(group[name], errors="coerce")


def _ery_or_uvi(group: pd.DataFrame, ery: pd.Series) -> pd.Series:
    """Use measured erythemal irradiance; derive from UVI only when absent.

    Data we already have (UVI) must not degrade into missing SED, but a
    derived value is still marked by its source column, never invented.
    """
    if ery.notna().any():
        return ery
    if "uv_index" in group.columns:
        return pd.to_numeric(group["uv_index"], errors="coerce") / 40.0
    return ery


def day_totals(frame: pd.DataFrame) -> pd.DataFrame:
    """Daily integrated totals with gap flags (one row per local date)."""
    if frame.empty:
        return pd.DataFrame()
    work = frame.copy()
    work["_secs"] = _utc_seconds(work)
    # Local date for day grouping.
    try:
        from zoneinfo import ZoneInfo

        tz = ZoneInfo(config.TIMEZONE)
        local = pd.to_datetime(work["time_utc"] if "time_utc" in work else work["time"],
                               utc=True).dt.tz_convert(tz)
        work["_date"] = local.dt.date.astype(str)
    except (TypeError, ValueError, KeyError, AttributeError):
        work["_date"] = pd.to_datetime(
            work["time"] if "time" in work else work["time_utc"]).astype(str).str.slice(0, 10)
    rows = []
    for date, g in work.sort_values("_secs").groupby("_date"):
        e = _group_col(g, "melanogenic_effective_irradiance_wm2")
        ery = _ery_or_uvi(g, _group_col(g, "erythemal_irradiance_wm2"))
        uva = _group_col(g, "predicted_uva_wm2")
        uvb = _group_col(g, "predicted_uvb_wm2")
        t = pd.to_datetime(g["time_utc"] if "time_utc" in g else g["time"], utc=True)
        td = integrate_tandose(t, e)
        sd = integrate_sed(t, ery)
        uva_d = integrate_band_dose(t, uva)
        uvb_d = integrate_band_dose(t, uvb)
        rows.append({
            "date": date,
            "tan_dose_day_j_m2": round(float(td["tan_dose_melanogenic_j_m2"]), 1),
            "tan_dose_day_reference_minutes": round(reference_minutes(
                float(td["tan_dose_melanogenic_j_m2"]),
                float(config.GLOBAL_MELANOGENIC_REFERENCE_WM2)), 1),
            "tan_dose_complete": bool(td["tan_dose_complete"]),
            "tan_dose_coverage_fraction": round(float(td["tan_dose_coverage_fraction"]), 3),
            "sed_day_total": round(float(sd["sed"]), 3),
            "sed_complete": bool(sd["sed_complete"]),
            "uva_dose_day_j_m2": round(float(uva_d["dose_j_m2"]), 1),
            "uvb_dose_day_j_m2": round(float(uvb_d["dose_j_m2"]), 2),
        })
    return pd.DataFrame(rows)


def window_dose(frame: pd.DataFrame, start, end) -> dict[str, float]:
    """Cumulative doses over a candidate window [start, end)."""
    sub = frame.copy()
    sub["_t"] = pd.to_datetime(sub["dt"] if "dt" in sub else sub["time"], errors="coerce")
    mask = (sub["_t"] >= pd.to_datetime(start)) & (sub["_t"] < pd.to_datetime(end))
    g = sub.loc[mask]
    if g.empty:
        return {"tan_dose_best_window_j_m2": 0.0, "sed_best_window": 0.0,
                "uva_dose_window_j_m2": 0.0, "uvb_dose_window_j_m2": 0.0}
    t = pd.to_datetime(g["dt"] if "dt" in g else g["time"], utc=True)

    def _gcol(name: str) -> pd.Series:
        # Missing input is UNKNOWN (NaN), never zero exposure.
        if name not in g.columns:
            return pd.Series(np.nan, index=g.index, dtype="float64")
        return pd.to_numeric(g[name], errors="coerce")

    td = integrate_tandose(t, _gcol("melanogenic_effective_irradiance_wm2"))
    sd = integrate_sed(t, _ery_or_uvi(g, _gcol("erythemal_irradiance_wm2")))
    uva_d = integrate_band_dose(t, _gcol("predicted_uva_wm2"))
    uvb_d = integrate_band_dose(t, _gcol("predicted_uvb_wm2"))
    return {
        "tan_dose_best_window_j_m2": round(float(td["tan_dose_melanogenic_j_m2"]), 1),
        "sed_best_window": round(float(sd["sed"]), 3),
        "uva_dose_window_j_m2": round(float(uva_d["dose_j_m2"]), 1),
        "uvb_dose_window_j_m2": round(float(uvb_d["dose_j_m2"]), 2),
    }
