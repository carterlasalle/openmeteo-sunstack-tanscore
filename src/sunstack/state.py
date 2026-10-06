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
from .frame import num as _num


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


_SOURCE_BIAS = (-0.11, -1.03, 0.0)  # UVI verification file, 1-day lead (OM, CAMS, EPA)
_SOURCE_MAE = (0.48, 1.14, 1.0)  # OM, CAMS verified; EPA default (n=0)
_FUSION_WEIGHT_CAP = 0.6  # max single-source share: no false certainty
# Fixed skill shares from the verification MAEs: 1/MAE^2 normalized, then
# the dominant share clipped at 0.6 (false-certainty guard) with the clipped
# slack redistributed to the uncapped sources. Per-row weights restrict these
# shares to finite sources and renormalize.
_RAW = np.array([1.0 / m**2 for m in _SOURCE_MAE])
_fixed_shares = np.clip(_RAW / _RAW.sum(), 0.0, _FUSION_WEIGHT_CAP)
_FIXED_SHARES_NORM: np.ndarray = _fixed_shares / _fixed_shares.sum()


def _source_weights(finite: np.ndarray) -> np.ndarray:
    # A source-free row keeps NaN weights, hence NaN consensus (never zero).
    weights = np.where(finite, np.asarray(_FIXED_SHARES_NORM)[:, None], np.nan)
    with np.errstate(divide="ignore", invalid="ignore"):
        return weights / np.nansum(weights, axis=0)


def fuse_uvi_unique_count(frame: pd.DataFrame) -> pd.DataFrame:
    """Final UVI fusion: bias-corrected inverse-error weights + count.

    Skill weights come from the UVI verification file, not the code: OM bias
    -0.11 MAE 0.48, CAMS bias -1.03 MAE 1.14 (1-day lead), EPA bias 0 MAE 1.0
    (default: zero scored rows). Consensus is the weighted mean of
    bias-corrected sources (value minus bias) with weights 1/MAE^2 normalized,
    each share capped at 0.6 (false-certainty guard) and renormalized over
    the sources finite in each row. ``uvi_consensus_sources`` counts unique
    providers (OM/CAMS/EPA present),
    never weighted votes. The legacy vote count rides along as
    ``uvi_consensus_vote_count`` for migration diagnostics.
    """
    out = frame.copy()
    om, cams, epa = _stack_sources(out)
    stacked = np.vstack([om, cams, epa])
    weights = _source_weights(np.isfinite(stacked))
    with np.errstate(divide="ignore", invalid="ignore"):
        corrected = stacked - np.asarray(_SOURCE_BIAS)[:, None]
        consensus = np.nansum(corrected * weights, axis=0)
        finite = np.isfinite(stacked)
        # Bias correction is a daytime debias: at night (raw sources ~0)
        # value-minus-bias invents 0.22 out of a [0,0] range, which the
        # range gate correctly refuses to publish. Clamp into the raw
        # finite-source range so consensus never leaves what was observed.
        lo = np.nanmin(stacked, axis=0)
        hi = np.nanmax(stacked, axis=0)
        consensus = np.where(finite.any(axis=0), np.clip(consensus, lo, hi), np.nan)
        # Source-free rows emit NaN consensus, never a zero masquerading as
        # clean air; downstream SED integrates them as gaps, not zeros.
        out["uvi_consensus"] = np.round(np.where(finite.any(axis=0), consensus, np.nan), 3)
        out["uvi_consensus_sources"] = np.asarray(finite.sum(axis=0), dtype=int)
        # Legacy OMx2 vote count, migration diagnostic only.
        vote_arr: np.ndarray = np.asarray(
            2 * finite[0].astype(int) + finite[1].astype(int) + finite[2].astype(int))
        out["uvi_consensus_vote_count"] = np.asarray(vote_arr, dtype=int)
        out["uvi_source_values"] = [tuple(np.round(row, 3)) for row in stacked.T]
        out["uvi_source_weights"] = [tuple(np.round(row, 3)) for row in weights.T]
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
        from .spectral import load_tierB_emulator as _loadB
        from .spectral import predict_tierB_channels as _predB

        _b = _loadB()
        _bp = None
        _need = ("sza_deg", "ozone_du", "aod340", "albedo")
        if _b is not None and all(c in out.columns for c in _need):
            _bp = _predB(out, _b)
        e_mel = np.asarray(_bp[2], dtype=float) if _bp is not None else melanogenic_from_broadband(uva, uvb)
        if "is_day" in out:
            isday = _col_arr(out, "is_day")
            isday = np.where(np.isfinite(isday), isday, 1.0)
            night: np.ndarray = np.equal(isday, 0.0)
            e_mel = np.array(e_mel, dtype=float, copy=True)
            e_mel[night] = 0.0
        out["melanogenic_effective_irradiance_wm2"] = np.round(e_mel, 5)
        # v5 canonical twin (§2.1.A): exact copy of the horizontal environmental
        # value, so frames that stop at this stage still carry both names.
        out["delayed_pigmentation_effective_irradiance_horizontal_wm2"] = out[
            "melanogenic_effective_irradiance_wm2"]
        out["tan_score_absolute_0_100"] = np.round(
            absolute_tan_score_from_melanogenic_irradiance(
                e_mel, float(config.GLOBAL_MELANOGENIC_REFERENCE_WM2)), 1)
        out["pigment_darkening_effective_irradiance"] = np.round(
            pigment_darkening_from_broadband(uva, uvb), 5)
        # §2.2 defines `delayed_pigmentation_transmission_ratio` as
        # E_DP_all_sky / E_DP_clear_sky and exposes it only "where the backend
        # can compute both". No shipped backend can: the all-sky numerator comes
        # from the broadband reconstruction (or the Tier-B emulator, which has no
        # cloud-free mode), while the only available clear-sky UV model is the
        # degraded parametric fallback, whose absolute scale is wrong by ~2.2x on
        # UVA and ~34x on UVB at SZA 47 deg (measured Oct 2026 against the
        # production channels). Dividing the two would publish a ~10x
        # model-disagreement factor under a name that claims atmospheric
        # transmission, so the field is deliberately not emitted. It returns when
        # a backend can evaluate one model with clouds present and absent.
    # §3/§28: rows carry the exact action-spectrum identity, not just the score
    # model version, so a serialized row is self-describing.
    from .photobiology import load_action_spectrum as _load_spec

    out["action_spectrum_version"] = config.ACTION_SPECTRUM_VERSION
    out["action_spectrum_sha256"] = _load_spec(config.ACTION_SPECTRUM_STEM).sha256
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
