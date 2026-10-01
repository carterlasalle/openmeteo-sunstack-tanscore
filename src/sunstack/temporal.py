"""First-class temporal-support semantics for radiation/weather quantities (v5).

Contract §5: NASA POWER hourly timestamps identify the START of the hour while
Open-Meteo ordinary solar-radiation fields are backward means over the
PRECEDING hour. A POWER value stamped 12:00 and an Open-Meteo hourly mean
stamped 12:00 do not describe the same interval, so merging by raw timestamp
is a category error. This module is the versioned registry plus the interval
conversion/alignment primitives every physics consumer must use.

TOA note (contract §5.6): the fixed ``1361.1*cos(SZA)`` approximation is a
mean-distance estimate, never "exact"; ``extra_radiation_date_dependent`` is
the date-dependent form.

Version: ``interval-contract-v1`` (``config.TEMPORAL_SEMANTICS_VERSION``).
"""

from __future__ import annotations

from dataclasses import dataclass
from itertools import pairwise
from typing import Any, Literal

import numpy as np
import pandas as pd

from .calibrate import scol as _scol

SupportType = Literal["instant", "interval_mean", "interval_sum", "cumulative_since_cycle"]
AnchorType = Literal["interval_start", "interval_end", "interval_midpoint", "valid_time"]


@dataclass(frozen=True)
class TemporalSemantics:
    """Support contract for one source variable."""

    source: str
    variable: str
    support: SupportType
    anchor: AnchorType
    duration_s: float
    native_resolution_s: float = 0.0
    time_standard: str = "UTC"
    temporal_source: str = ""


TEMPORAL_SEMANTICS_VERSION = "interval-contract-v1"

# Registry: pinned provider semantics the pipeline may rely on. Entries are
# deliberately explicit per variable family rather than per model so a new
# model reuses the family contract instead of inventing its own.
REGISTRY: tuple[TemporalSemantics, ...] = (
    # NASA POWER hourly: stamp is the start of the hour it averages.
    TemporalSemantics(
        source="nasa_power", variable="ALLSKY_*",
        support="interval_mean", anchor="interval_start", duration_s=3600,
        native_resolution_s=3600, temporal_source="POWER Hourly API",
    ),
    # Open-Meteo ordinary hourly radiation/weather: backward mean over the
    # preceding hour, stamped at the interval end.
    TemporalSemantics(
        source="open_meteo", variable="hourly_radiation",
        support="interval_mean", anchor="interval_end", duration_s=3600,
        native_resolution_s=3600, temporal_source="Open-Meteo forecast API",
    ),
    TemporalSemantics(
        source="open_meteo", variable="hourly_weather",
        support="interval_mean", anchor="interval_end", duration_s=3600,
        native_resolution_s=3600, temporal_source="Open-Meteo forecast API",
    ),
    # Open-Meteo `_instant` radiation: point sample at the stamp.
    TemporalSemantics(
        source="open_meteo", variable="*_instant",
        support="instant", anchor="valid_time", duration_s=0,
        native_resolution_s=900, temporal_source="Open-Meteo forecast API",
    ),
    # Open-Meteo HRRR 15-min ordinary fields: backward 15-min means.
    TemporalSemantics(
        source="open_meteo_hrrr15", variable="*_15min",
        support="interval_mean", anchor="interval_end", duration_s=900,
        native_resolution_s=900, temporal_source="Open-Meteo HRRR 15-min API",
    ),
    # CAMS accumulated downward UV: cumulative dose since cycle start.
    TemporalSemantics(
        source="cams", variable="downward_uv_accumulated",
        support="cumulative_since_cycle", anchor="valid_time", duration_s=0,
        native_resolution_s=3600, temporal_source="CAMS ADS forecast",
    ),
    # CAMS instantaneous diagnostics (UVBED rate, ozone, aerosol optics):
    # point values at the valid time.
    TemporalSemantics(
        source="cams", variable="instantaneous",
        support="instant", anchor="valid_time", duration_s=0,
        native_resolution_s=3600, temporal_source="CAMS ADS forecast",
    ),
    # EPA hourly UVI: hourly value stamped at the hour.
    TemporalSemantics(
        source="epa", variable="uvi_hourly",
        support="interval_mean", anchor="interval_end", duration_s=3600,
        native_resolution_s=3600, temporal_source="EPA Envirofacts hourly UV",
    ),
)


def interval_bounds(
    stamps_utc: Any, support: SupportType, anchor: AnchorType, duration_s: float
) -> pd.DataFrame:
    """Canonical [interval_start, interval_end) + midpoint for stamped values.

    Instant support yields zero-duration intervals at the stamp itself.
    """
    t = pd.to_datetime(stamps_utc, utc=True)
    if support == "instant" or duration_s <= 0:
        start = t
        end = t
        mid = t
    elif anchor == "interval_start":
        start = t
        end = t + pd.to_timedelta(duration_s, unit="s")
        mid = t + pd.to_timedelta(duration_s / 2.0, unit="s")
    elif anchor == "interval_end":
        end = t
        start = t - pd.to_timedelta(duration_s, unit="s")
        mid = t - pd.to_timedelta(duration_s / 2.0, unit="s")
    elif anchor == "interval_midpoint":
        mid = t
        start = t - pd.to_timedelta(duration_s / 2.0, unit="s")
        end = t + pd.to_timedelta(duration_s / 2.0, unit="s")
    else:  # valid_time anchor for interval support: treat stamp as end
        end = t
        start = t - pd.to_timedelta(duration_s, unit="s")
        mid = t - pd.to_timedelta(duration_s / 2.0, unit="s")
    return pd.DataFrame({
        "interval_start": start,
        "interval_end": end,
        "interval_midpoint": mid,
    })


def power_hourly_to_intervals(frame: pd.DataFrame) -> pd.DataFrame:
    """Attach canonical interval bounds to NASA POWER hourly rows."""
    out = frame.copy()
    if "time_utc" not in out.columns or out.empty:
        return out
    bounds = interval_bounds(_scol(out, "time_utc"), "interval_mean", "interval_start", 3600)
    for col in ("interval_start", "interval_end", "interval_midpoint"):
        out[col] = bounds[col].to_numpy()
    out["radiation_support_type"] = "interval_mean"
    out["temporal_semantics_version"] = TEMPORAL_SEMANTICS_VERSION
    return out


def openmeteo_hourly_to_intervals(frame: pd.DataFrame, time_col: str = "time") -> pd.DataFrame:
    """Attach canonical interval bounds to Open-Meteo hourly rows."""
    out = frame.copy()
    if time_col not in out.columns or out.empty:
        return out
    bounds = interval_bounds(_scol(out, time_col), "interval_mean", "interval_end", 3600)
    for col in ("interval_start", "interval_end", "interval_midpoint"):
        out[col] = bounds[col].to_numpy()
    out["radiation_support_type"] = "interval_mean"
    out["temporal_semantics_version"] = TEMPORAL_SEMANTICS_VERSION
    return out


def align_training_intervals(
    power: pd.DataFrame, predictors: pd.DataFrame,
) -> pd.DataFrame:
    """Merge POWER targets with predictors by canonical midpoint overlap.

    Both frames must carry ``interval_midpoint`` (see the two helpers above).
    Predictor rows join to the POWER row whose midpoint they are nearest to,
    within half the POWER interval; raw-timestamp ``merge_asof`` with an
    arbitrary tolerance is not used.
    """
    if power.empty or predictors.empty:
        return pd.DataFrame()
    if "interval_midpoint" not in power.columns or "interval_midpoint" not in predictors.columns:
        raise ValueError(
            "ERROR temporal: align_training_intervals requires interval_midpoint "
            "on both frames (run power_hourly_to_intervals / openmeteo_hourly_to_intervals first)"
        )
    left = power.sort_values("interval_midpoint").reset_index(drop=True)
    right = predictors.sort_values("interval_midpoint").reset_index(drop=True)
    lmid = pd.to_datetime(left["interval_midpoint"], utc=True)
    rmid = pd.to_datetime(right["interval_midpoint"], utc=True)
    # Nearest-predictor index per target via searchsorted on sorted midpoints.
    rsecs = rmid.map(lambda x: x.timestamp()).to_numpy(dtype=float)
    lsecs = lmid.map(lambda x: x.timestamp()).to_numpy(dtype=float)
    pos = np.searchsorted(rsecs, lsecs)
    take = np.clip(pos, 0, len(right) - 1)
    # Also consider the neighbor below for true nearest.
    below = np.clip(pos - 1, 0, len(right) - 1)
    use_below = np.abs(rsecs[below] - lsecs) < np.abs(rsecs[take] - lsecs)
    take = np.where(use_below, below, take)
    gap = np.abs(rsecs[take] - lsecs)
    ok = gap <= 1800.0  # half the hourly target interval
    lidx = np.where(ok)[0]
    if len(lidx) == 0:
        return pd.DataFrame()
    merged = pd.concat(
        [left.iloc[lidx].reset_index(drop=True),
         right.iloc[take[lidx]].reset_index(drop=True).add_prefix("pred_")],
        axis=1,
    )
    return merged


def integrate_interval_means_exact(
    interval_s: np.ndarray, means_wm2: np.ndarray,
) -> tuple[float, bool, float]:
    """Exact energy of interval-mean irradiance: sum(Ebar * dt).

    Never trapezoid-integrate adjacent interval means as point samples.
    Returns (dose_J_m2, complete, coverage_fraction). A non-finite mean or
    non-positive duration marks the window incomplete; a wholly unknown
    window is NaN (never zero).
    """
    dt = np.asarray(interval_s, dtype=float)
    ebar = np.asarray(means_wm2, dtype=float)
    if len(dt) == 0 or len(ebar) == 0:
        return float("nan"), False, 0.0
    valid = np.isfinite(dt) & np.isfinite(ebar) & (dt > 0)
    if not bool(valid.any()):
        return float("nan"), False, 0.0
    dose = float(np.sum(dt[valid] * ebar[valid]))
    complete = bool(valid.all())
    coverage = float(np.sum(dt[valid]) / np.sum(dt[dt > 0])) if bool((dt > 0).any()) else 0.0
    return max(dose, 0.0), complete, float(np.clip(coverage, 0, 1))


def integrate_point_samples_trapezoid(
    secs: np.ndarray, values_wm2: np.ndarray, max_gap_s: float = 3600.0,
) -> tuple[float, bool, float]:
    """Trapezoidal integral for TRUE point samples only.

    A lone valid sample over a nonzero window is UNKNOWN (NaN), never numeric
    zero (contract §17.1): one point spans zero time but cannot claim the
    window's energy.
    """
    t = np.asarray(secs, dtype=float)
    v = np.asarray(values_wm2, dtype=float)
    order = np.argsort(t, kind="stable")
    t = t[order]
    v = v[order]
    valid = np.isfinite(t) & np.isfinite(v)
    n_valid = int(valid.sum())
    if n_valid == 0:
        return float("nan"), False, 0.0
    span = float(np.max(t[valid]) - np.min(t[valid])) if n_valid > 1 else 0.0
    window = float(np.max(t) - np.min(t)) if len(t) > 1 else 0.0
    if n_valid == 1:
        # One point over a nonzero requested window: unknown energy.
        if window > 0:
            return float("nan"), False, 0.0
        return 0.0, False, 0.0
    dose, covered, complete = 0.0, 0.0, True
    idx = np.where(valid)[0]
    for a, b in pairwise(idx):
        dt = float(t[b] - t[a])
        if dt <= 0:
            continue
        if dt > max_gap_s:
            complete = False
            continue
        dose += 0.5 * (v[a] + v[b]) * dt
        covered += dt
    coverage = (covered / span) if span > 0 else 1.0
    return float(max(dose, 0.0)), bool(complete), float(np.clip(coverage, 0, 1))


def cams_accumulation_to_interval_means(
    times_utc: Any, accumulated_j_m2: Any, cycle_ids: Any,
) -> pd.DataFrame:
    """Difference CAMS accumulated downward UV within each forecast cycle.

    Never differences across cycles; negative increments are an error/reset
    signal carried explicitly (never silently clipped); the first interval of
    a cycle is UNKNOWN unless the provider supplies a defined zero at cycle
    start, in which case the caller passes it as an explicit row.
    """
    t = pd.to_datetime(times_utc, utc=True)
    _coerced = pd.to_numeric(accumulated_j_m2, errors="coerce")
    assert isinstance(_coerced, pd.Series)
    acc: np.ndarray = _coerced.to_numpy()
    cyc: np.ndarray = pd.Series(np.asarray(cycle_ids)).astype(str).to_numpy()  # type: ignore[union-attr]
    secs: np.ndarray = t.map(lambda x: x.timestamp()).to_numpy()  # type: ignore[union-attr]
    order: np.ndarray = np.argsort(secs, kind="stable")
    out_rows: list[dict[str, object]] = []
    for pos in range(len(order)):
        i = int(order[pos])
        # First row of each cycle: no backward difference exists.
        prev = int(order[pos - 1]) if pos > 0 else -1
        ok = bool(prev >= 0 and cyc[prev] == cyc[i]
                  and np.isfinite(acc[prev]) and np.isfinite(acc[i]))
        if not ok:
            out_rows.append({
                "interval_end": t.iloc[i],
                "interval_mean_wm2": float("nan"),
                "interval_s": float("nan"),
                "imputed": False,
                "reset_signal": False,
                "complete": False,
            })
            continue
        dt = float(secs[i] - secs[prev])
        dv = float(acc[i] - acc[prev])
        if dt <= 0:
            out_rows.append({
                "interval_end": t.iloc[i],
                "interval_mean_wm2": float("nan"),
                "interval_s": float("nan"),
                "imputed": False,
                "reset_signal": True,
                "complete": False,
            })
            continue
        if dv < 0:
            # Accumulation reset / new cycle disguised as continuity.
            out_rows.append({
                "interval_end": t.iloc[i],
                "interval_mean_wm2": float("nan"),
                "interval_s": dt,
                "imputed": False,
                "reset_signal": True,
                "complete": False,
            })
            continue
        out_rows.append({
            "interval_end": t.iloc[i],
            "interval_mean_wm2": dv / dt,
            "interval_s": dt,
            "imputed": False,
            "reset_signal": False,
            "complete": True,
        })
    return pd.DataFrame(out_rows)


def extra_radiation_date_dependent(day_of_year: np.ndarray) -> np.ndarray:
    """Date-dependent extraterrestrial normal irradiance (pvlib-backed).

    Contract §5.6: never call the fixed 1361.1*cos(SZA) approximation exact.
    """
    import pvlib.irradiance as _irr

    doy = np.asarray(day_of_year, dtype=float)
    vals: list[float] = doy.ravel().tolist()
    raw: list[object] = [_irr.get_extra_radiation(int(v)) for v in vals]
    out: list[float] = []
    for v in raw:
        assert isinstance(v, (int, float))
        out.append(float(v))
    return np.asarray(out, dtype=float)
