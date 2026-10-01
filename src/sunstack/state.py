"""Single-pass final derived-state pipeline (v5 contract §4).

Problem it fixes: the 30-minute path recomputed primitive/source UVI fields
(HRRR broadband correction, native override, kt interpolation) and then left
dependent columns (consensus, erythemal, SED, source count, confidence) from
an earlier state. ``recompute_derived_state()`` regenerates every child value
from final primitive inputs in dependency order, so no stage can interpolate
or carry a derived child after a parent changes.

Required final order (contract §4): primitives, temporal alignment, broadband
correction, source UVI, fusion, range/spread/unique count, erythemal,
spectral UVA/UVB plus delayed-pigmentation channel, clear-sky/transmission,
percentiles, uncertainty/reliability, surface/skin-plane, feasibility,
interval doses, ranking, summaries, serialization, validation.
"""

from __future__ import annotations

import math

import numpy as np
import pandas as pd

from . import config
from .calibrate import num as _num


def _col_arr(frame: pd.DataFrame, name: str, default: float = math.nan) -> np.ndarray:
    return np.asarray(_num(frame, name, default), dtype=float)


def _stack_sources(frame: pd.DataFrame) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    if "uvi_openmeteo" in frame:
        om = _col_arr(frame, "uvi_openmeteo")
    else:
        om = _col_arr(frame, "uv_index")
    if "uvi_cams" in frame:
        cams = _col_arr(frame, "uvi_cams")
    else:
        cams = np.full(len(frame), np.nan)
    if "uvi_epa" in frame:
        epa = _col_arr(frame, "uvi_epa")
    else:
        epa = np.full(len(frame), np.nan)
    return om, cams, epa


def fuse_uvi_unique_count(frame: pd.DataFrame) -> pd.DataFrame:
    """Final UVI fusion: plain NaN-tolerant median plus UNIQUE provider count.

    The old OMx2 vote median had non-obvious behavior ([0,2,6,6] gives 4, not
    an OM tie-break to 6). v5 headline fusion is the ordinary median over
    finite sources; ``uvi_consensus_sources`` counts unique providers
    (OM/CAMS/EPA present), never weighted votes. The legacy vote count rides
    along as ``uvi_consensus_vote_count`` for migration diagnostics.
    """
    out = frame.copy()
    om, cams, epa = _stack_sources(out)
    stacked = np.vstack([om, cams, epa])
    with np.errstate(divide="ignore", invalid="ignore"):
        out["uvi_consensus"] = np.round(np.nanmedian(stacked, axis=0), 3)
        finite = np.isfinite(stacked)
        out["uvi_consensus_sources"] = np.asarray(finite.sum(axis=0), dtype=int)
        # Legacy OMx2 vote count, migration diagnostic only.
        vote_arr: np.ndarray = np.asarray(
            2 * finite[0].astype(int) + finite[1].astype(int) + finite[2].astype(int))
        out["uvi_consensus_vote_count"] = np.asarray(vote_arr, dtype=int)
        spread = np.nanmax(stacked, axis=0) - np.nanmin(stacked, axis=0)
        out["uvi_source_spread"] = np.round(spread, 3)
        out["uvi_sunny"] = np.round(np.nanmax(stacked, axis=0), 3)
        out["uvi_cloudy"] = np.round(np.nanmin(stacked, axis=0), 3)
    out["fusion_version"] = config.FUSION_VERSION
    return out


def recompute_derived_state(frame: pd.DataFrame) -> pd.DataFrame:
    """Regenerate all child values from final primitive inputs, in order.

    Parents: uvi_openmeteo/uvi_cams/uvi_epa (or uv_index), predicted UVA/UVB,
    is_day. Children recomputed: consensus family, erythemal, E_mel/Absolute,
    pigment-darkening, source disagreement diagnostics. Local percentiles are
    NOT recomputed here (they need the calibration reference; the caller
    refreshes them against the final physics instead of carrying old values).
    """
    from .photobiology import (
        absolute_tan_score_from_melanogenic_irradiance,
        erythemal_irradiance_from_uvi,
    )
    from .spectral import melanogenic_from_broadband, pigment_darkening_from_broadband

    out = frame.copy()
    if out.empty:
        return out
    out = fuse_uvi_unique_count(out)
    # Erythemal from FINAL consensus, nowhere else.
    cons = _col_arr(out, "uvi_consensus")
    out["erythemal_irradiance_wm2"] = np.round(erythemal_irradiance_from_uvi(cons), 5)
    if {"predicted_uva_wm2", "predicted_uvb_wm2"}.issubset(out.columns):
        uva = _col_arr(out, "predicted_uva_wm2")
        uvb = _col_arr(out, "predicted_uvb_wm2")
        e_mel = melanogenic_from_broadband(uva, uvb)
        if "is_day" in out:
            isday = _col_arr(out, "is_day")
            isday = np.where(np.isfinite(isday), isday, 1.0)
            night: np.ndarray = np.equal(isday, 0.0)
            e_mel = np.array(e_mel, dtype=float, copy=True)
            e_mel[night] = 0.0
        out["melanogenic_effective_irradiance_wm2"] = np.round(e_mel, 5)
        out["tan_score_absolute_0_100"] = np.round(
            absolute_tan_score_from_melanogenic_irradiance(
                e_mel, float(config.GLOBAL_MELANOGENIC_REFERENCE_WM2)), 1)
        out["pigment_darkening_effective_irradiance"] = np.round(
            pigment_darkening_from_broadband(uva, uvb), 5)
    # Disagreement from FINAL sources (recompute after final fusion).
    if "uvi_openmeteo" in out:
        om_v = _col_arr(out, "uvi_openmeteo")
    else:
        om_v = cons
    if "uvi_cams" in out:
        cams_v = _col_arr(out, "uvi_cams")
    else:
        cams_v = np.zeros(len(out))
    with np.errstate(divide="ignore", invalid="ignore"):
        denom = np.maximum(np.maximum(om_v, cams_v), 0.5)
        diff = om_v - cams_v
        out["uvi_difference_absolute"] = np.round(diff, 3)
        out["uvi_difference_percent"] = np.round(100.0 * np.abs(diff) / denom, 2)
    return out
