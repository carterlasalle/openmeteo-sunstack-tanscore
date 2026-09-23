"""Spectral radiation layer: skin-plane E_lambda over ~280-400 nm.

Runtime tiers:
  A = direct/reference-quality spectral reconstruction (reserved for a future
      libRadtran-backed path; not yet wired, never silently claimed)
  B = validated spectral emulator (reserved; requires training manifest)
  C = calibrated broadband approximation (production default in v4):
      distributes predicted broadband UVA/UVB uniformly across their bands and
      convolves with the melanogenesis action spectrum. Wavelength-additive by
      construction: E_mel = UVA*<S>_UVA + UVB*<S>_UVB. No sqrt interaction.
  D = unavailable (strict mode fails; --allow-degraded never invents physics)

Skin-plane orientation uses broadband direct/diffuse partition with an
isotropic-sky diffuse model plus incidence-angle direct projection. Diffuse is
never discarded; reflected UV enters through the albedo term where supported.
Snow blocking stays an outdoor-feasibility rule, never a radiation-physics rule.
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass

import numpy as np
import pandas as pd

from . import config
from .photobiology import (
    effectiveness_at,
    load_action_spectrum,
)

SPECTRAL_BACKEND_VERSION = "tierC-broadband-v1"
SPECTRAL_WAVES_NM = np.arange(280, 401, 1, dtype=float)
UVB_MASK = (SPECTRAL_WAVES_NM >= 280) & (SPECTRAL_WAVES_NM < 315)
UVA_MASK = (SPECTRAL_WAVES_NM >= 315) & (SPECTRAL_WAVES_NM <= 400)

TIER_DESCRIPTIONS = {
    "A": "direct/reference-quality spectral reconstruction",
    "B": "validated spectral emulator",
    "C": "calibrated broadband approximation",
    "D": "unavailable",
}

_band_cache: dict[str, tuple[float, float]] = {}


def band_effective_weights(spectrum_stem: str = "parrish_delayed_melanogenesis") -> tuple[float, float]:
    """Mean action-spectrum effectiveness over the UVB and UVA bands.

    Derived from the loaded spectrum itself (uniform intra-band irradiance
    assumption documented as the Tier-C approximation), NOT hand-tuned.
    Returns (w_uvb, w_uva) with w_uvb >> w_uva for delayed melanogenesis.
    """
    if spectrum_stem in _band_cache:
        return _band_cache[spectrum_stem]
    spec = load_action_spectrum(spectrum_stem)
    s = effectiveness_at(spec, SPECTRAL_WAVES_NM)
    # Trapezoidal band means (uniform E_lambda within each band).
    w_uvb = float(np.trapezoid(s[UVB_MASK], SPECTRAL_WAVES_NM[UVB_MASK]) / (315 - 280))
    w_uva = float(np.trapezoid(s[UVA_MASK], SPECTRAL_WAVES_NM[UVA_MASK]) / (400 - 315))
    _band_cache[spectrum_stem] = (w_uvb, w_uva)
    return w_uvb, w_uva


def reconstruct_spectrum_tierC(
    uva_wm2: float, uvb_wm2: float
) -> np.ndarray:
    """Uniform intra-band E_lambda consistent with broadband UVA/UVB totals."""
    uva = max(float(uva_wm2), 0.0)
    uvb = max(float(uvb_wm2), 0.0)
    e = np.zeros_like(SPECTRAL_WAVES_NM, dtype=float)
    e[UVB_MASK] = uvb / (315 - 280)
    e[UVA_MASK] = uva / (400 - 315)
    return e


def melanogenic_from_broadband(
    uva_wm2: float | np.ndarray,
    uvb_wm2: float | np.ndarray,
    spectrum_stem: str = "parrish_delayed_melanogenesis",
) -> np.ndarray:
    """Tier-C E_mel from broadband UVA/UVB. Wavelength-additive, no interaction."""
    w_uvb, w_uva = band_effective_weights(spectrum_stem)
    uva = np.clip(np.asarray(uva_wm2, dtype=float), 0, None)
    uvb = np.clip(np.asarray(uvb_wm2, dtype=float), 0, None)
    return uvb * w_uvb + uva * w_uva


def pigment_darkening_from_broadband(
    uva_wm2: float | np.ndarray,
    uvb_wm2: float | np.ndarray,
) -> np.ndarray:
    """Separate UVA-dominant IPD channel. Never merged into TanScore."""
    from .photobiology import load_action_spectrum as _load

    spec = _load("ipd_action_spectrum")
    s = effectiveness_at(spec, SPECTRAL_WAVES_NM)
    w_uvb = float(np.trapezoid(s[UVB_MASK], SPECTRAL_WAVES_NM[UVB_MASK]) / 35.0)
    w_uva = float(np.trapezoid(s[UVA_MASK], SPECTRAL_WAVES_NM[UVA_MASK]) / 85.0)
    uva = np.clip(np.asarray(uva_wm2, dtype=float), 0, None)
    uvb = np.clip(np.asarray(uvb_wm2, dtype=float), 0, None)
    return uvb * w_uvb + uva * w_uva


@dataclass(frozen=True)
class SkinPlane:
    tilt_deg: float
    azimuth_deg: float


def resolve_skin_plane(
    tilt_deg: float | None = None, azimuth_deg: float | None = None
) -> SkinPlane:
    tilt = float(config.SKIN_TILT_DEG if tilt_deg is None else tilt_deg)
    az = float(config.SKIN_AZIMUTH_DEG if azimuth_deg is None else azimuth_deg)
    if not (0 <= tilt <= 180) or not (0 <= az < 360):
        raise ValueError("ERROR spectral: skin-plane tilt must be 0-180, azimuth 0-360")
    return SkinPlane(tilt_deg=tilt, azimuth_deg=az)


def skin_plane_factor(
    tilt_deg: float,
    solar_zenith_deg: float,
    solar_azimuth_deg: float,
    skin_azimuth_deg: float,
    direct_wm2: float,
    diffuse_wm2: float,
    albedo: float = 0.2,
) -> float:
    """Broadband skin-plane / horizontal ratio (isotropic sky + ground bounce).

    Direct: DNI-equivalent projected by incidence cosine. Diffuse: isotropic
    sky-view factor (1+cos tilt)/2 plus ground-reflected albedo*(1-cos tilt)/2.
    Tilt 0 returns exactly 1.0 (horizontal environmental reference).
    """
    tilt = np.radians(float(tilt_deg))
    if abs(tilt) < 1e-9:
        return 1.0
    sza = np.radians(float(solar_zenith_deg))
    saa = np.radians(float(solar_azimuth_deg - skin_azimuth_deg))
    cos_inc = np.cos(sza) * np.cos(tilt) + np.sin(sza) * np.sin(tilt) * np.cos(saa)
    cos_inc = max(float(cos_inc), 0.0)
    cos_sza = max(float(np.cos(sza)), 0.0)
    direct_h = max(float(direct_wm2), 0.0)
    diffuse_h = max(float(diffuse_wm2), 0.0)
    ghi_h = direct_h + diffuse_h
    if ghi_h <= 1e-9 or cos_sza <= 1e-6:
        return 1.0
    # Direct horizontal ~= DNI*cos(sza); recover DNI then project.
    dni = direct_h / cos_sza
    direct_plane = dni * cos_inc
    sky_view = 0.5 * (1.0 + np.cos(tilt))
    ground_view = 0.5 * (1.0 - np.cos(tilt))
    diffuse_plane = diffuse_h * sky_view + ghi_h * max(float(albedo), 0.0) * ground_view
    return float((direct_plane + diffuse_plane) / ghi_h)


def apply_skin_plane(
    frame: pd.DataFrame,
    tilt_deg: float | None = None,
    azimuth_deg: float | None = None,
) -> pd.DataFrame:
    """Attach skin-plane E_mel alongside the horizontal environmental reference.

    Environmental columns (E_mel, TanScore) are never overwritten: posture and
    tilt produce additional `skin_plane_*` columns for context.
    """
    from .calibrate import num as _num

    plane = resolve_skin_plane(tilt_deg, azimuth_deg)
    out = frame.copy()
    if "melanogenic_effective_irradiance_wm2" not in out:
        return out
    if abs(plane.tilt_deg) < 1e-9:
        out["skin_plane_e_mel_wm2"] = out["melanogenic_effective_irradiance_wm2"]
        out["skin_plane_factor"] = 1.0
        out["skin_plane_standard"] = "horizontal environmental reference"
        return out
    sza = _num(out, "sza").fillna(90.0 - _num(out, "solar_elevation_deg").fillna(0.0))
    saz = _num(out, "solar_azimuth_deg").fillna(180.0)
    direct = _num(out, "direct_radiation").fillna(_num(out, "direct_normal_irradiance").fillna(0.0) * 0.5)
    diffuse = _num(out, "diffuse_radiation").fillna(0.0)
    alb = _num(out, "albedo").fillna(0.2)
    factors = [
        skin_plane_factor(
            plane.tilt_deg, float(z), float(a), plane.azimuth_deg,
            float(d), float(f), float(al),
        )
        for z, a, d, f, al in zip(sza, saz, direct, diffuse, alb)
    ]
    out["skin_plane_factor"] = np.round(factors, 4)
    out["skin_plane_e_mel_wm2"] = (
        pd.to_numeric(out["melanogenic_effective_irradiance_wm2"], errors="coerce")
        * np.asarray(factors)
    ).round(5)
    out["skin_plane_standard"] = (
        f"tilt {plane.tilt_deg:g}deg az {plane.azimuth_deg:g}deg (horizontal reference preserved)"
    )
    return out


def emulator_manifest(spectral_backend: str = SPECTRAL_BACKEND_VERSION) -> dict[str, object]:
    waves_hash = hashlib.sha256(SPECTRAL_WAVES_NM.tobytes()).hexdigest()
    w_uvb, w_uva = band_effective_weights()
    return {
        "spectral_backend": spectral_backend,
        "spectral_emulator_version": SPECTRAL_BACKEND_VERSION,
        "spectral_training_manifest_sha256": waves_hash,
        "spectral_domain_nm": [280, 400],
        "spectral_spacing_nm": 1,
        "tierC_band_weights": {"w_uvb": w_uvb, "w_uva": w_uva},
        "tier_definitions": TIER_DESCRIPTIONS,
        "note": (
            "Tier C derives band weights from the action spectrum itself "
            "(uniform intra-band Tier-C approximation). No hand tuning."
        ),
    }


def spectral_tier_for_row(has_emulator: bool = False, has_reference: bool = False) -> str:
    if has_reference:
        return "A"
    if has_emulator:
        return "B"
    return "C"
