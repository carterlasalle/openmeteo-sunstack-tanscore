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

SPECTRAL_BACKEND_VERSION = "tierC-broadband-proxy-v2"
SPECTRAL_WAVES_NM: np.ndarray = np.arange(280, 401, 1, dtype=float)
UVB_MASK: np.ndarray = (SPECTRAL_WAVES_NM >= 280) & (SPECTRAL_WAVES_NM < 315)
UVA_MASK: np.ndarray = (SPECTRAL_WAVES_NM >= 315) & (SPECTRAL_WAVES_NM <= 400)

TIER_DESCRIPTIONS = {
    "A": "direct/reference-quality spectral reconstruction",
    "B": "validated spectral emulator",
    "C": "calibrated broadband approximation",
    "D": "unavailable",
}

_band_cache: dict[str, tuple[float, float]] = {}


def band_effective_weights(spectrum_stem: str | None = None) -> tuple[float, float]:
    """Mean action-spectrum effectiveness over the UVB and UVA bands.

    Derived from the loaded spectrum itself (uniform intra-band irradiance
    assumption documented as the Tier-C approximation), NOT hand-tuned.
    Returns (w_uvb, w_uva) with w_uvb >> w_uva for delayed melanogenesis.
    """
    stem = spectrum_stem or config.ACTION_SPECTRUM_STEM
    if stem in _band_cache:
        return _band_cache[stem]
    spec = load_action_spectrum(stem)
    s = effectiveness_at(spec, SPECTRAL_WAVES_NM)
    # Trapezoidal band means (uniform E_lambda within each band).
    w_uvb = float(np.trapezoid(s[UVB_MASK], SPECTRAL_WAVES_NM[UVB_MASK]) / (315 - 280))
    w_uva = float(np.trapezoid(s[UVA_MASK], SPECTRAL_WAVES_NM[UVA_MASK]) / (400 - 315))
    _band_cache[stem] = (w_uvb, w_uva)
    return w_uvb, w_uva


def reconstruct_spectrum_tierC(
    uva_wm2: float, uvb_wm2: float
) -> np.ndarray:
    """Uniform intra-band E_lambda consistent with broadband UVA/UVB totals.

    Contract §6.4: UVB spans [280,315) and UVA spans [315,400], so the cell
    count in each mask is the divisor — otherwise the reconstruction leaks
    energy at the boundary (86 cells / 85 nm overcounted UVA).
    """
    uva = max(float(uva_wm2), 0.0)
    uvb = max(float(uvb_wm2), 0.0)
    e = np.zeros_like(SPECTRAL_WAVES_NM, dtype=float)
    e[UVB_MASK] = uvb / int(UVB_MASK.sum())
    e[UVA_MASK] = uva / int(UVA_MASK.sum())
    return e


def melanogenic_from_broadband(
    uva_wm2: float | np.ndarray,
    uvb_wm2: float | np.ndarray,
    spectrum_stem: str | None = None,
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
    surface_slug: str | None = None,
    surface_extent: str = "local",
    uva_reflectance: float | None = None,
    uvb_reflectance: float | None = None,
) -> pd.DataFrame:
    """Attach skin-plane E_mel alongside the horizontal environmental reference.

    Environmental columns (E_mel, TanScore) are never overwritten: posture,
    tilt, and LOCAL surface produce additional `skin_plane_*` columns for
    context. Contract §12-13: direct/diffuse/reflected components are
    explicit and separate; the local surface NEVER mutates horizontal
    environmental fields; CAMS forecast_albedo stays regional input.
    """
    from .calibrate import num as _num
    from .surface import (
        SURFACE_MODEL_VERSION as _SURFACE_VERSION,
    )
    from .surface import (
        lambertian_ground_view_factor as _ground_view,
    )
    from .surface import (
        resolve_surface as _resolve_surface,
    )

    plane = resolve_skin_plane(tilt_deg, azimuth_deg)
    surface = _resolve_surface(surface_slug, uva_reflectance, uvb_reflectance)
    if surface_extent not in ("local", "broad"):
        raise ValueError(
            f"ERROR surface: surface_extent must be local|broad, got {surface_extent!r}")
    out = frame.copy()
    out["surface_material_slug"] = surface.slug
    out["surface_display_name"] = surface.display_name
    out["surface_extent_mode"] = surface_extent
    out["surface_model_quality"] = surface.spectral_quality
    out["surface_uva_reflectance"] = surface.proxy_reflectance
    out["surface_uvb_reflectance"] = surface.proxy_reflectance
    out["surface_reflectance_source"] = surface.source_citation
    out["surface_reflection_uncertainty"] = surface.reflectance_high - surface.reflectance_low
    out["surface_model_version"] = _SURFACE_VERSION
    if "melanogenic_effective_irradiance_wm2" not in out:
        return out
    if abs(plane.tilt_deg) < 1e-9:
        out["skin_plane_e_mel_wm2"] = out["melanogenic_effective_irradiance_wm2"]
        out["skin_plane_factor"] = 1.0
        out["skin_plane_standard"] = "horizontal environmental reference"
        out["skin_plane_ground_reflected_delayed_pigmentation_wm2"] = 0.0
        out["skin_plane_ground_reflected_uva_wm2"] = 0.0
        out["skin_plane_ground_reflected_uvb_wm2"] = 0.0
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
    e_mel = _num(out, "melanogenic_effective_irradiance_wm2")
    out["skin_plane_e_mel_wm2"] = (e_mel * np.asarray(factors)).round(5)
    out["skin_plane_standard"] = (
        f"tilt {plane.tilt_deg:g}deg az {plane.azimuth_deg:g}deg (horizontal reference preserved)"
    )
    # Explicit local reflected components (§12.8): Lambertian ground view ×
    # local surface proxy × horizontal broadband, kept separate from the
    # horizontal environmental fields. Flat plane: zero by geometry.
    gv = _ground_view(plane.tilt_deg)
    ghi = _num(out, "shortwave_radiation").fillna(
        direct.fillna(0.0) + diffuse.fillna(0.0))
    refl_uva = ghi * surface.proxy_reflectance * gv
    refl_uvb = ghi * surface.proxy_reflectance * gv
    out["skin_plane_ground_reflected_uva_wm2"] = np.round(refl_uva, 4)
    out["skin_plane_ground_reflected_uvb_wm2"] = np.round(refl_uvb, 4)
    out["skin_plane_ground_reflected_delayed_pigmentation_wm2"] = np.round(
        refl_uvb * 0.562322 + refl_uva * 0.002774, 5)
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
        # §7 consumer contract: every direct-CAMS field carried by
        # _cams_features but not consumed by Tier C is a reserved Tier-B
        # emulator input. Nothing is fetched merely to be left unused; the
        # corpus design (scripts/build_spectral_corpus.py RANGES) spans each
        # of these dimensions.
        "tierB_reserved_inputs": {
            "cams_aod_340": "aod340",
            "cams_aod_355": "aod355 (via angstrom)",
            "cams_aod_380": "aod380 (via angstrom)",
            "cams_aod_400": "aod400 (via angstrom)",
            "cams_abs_aod_340": "absorption AOD (via ssa340 + aod340)",
            "cams_abs_aod_355": "absorption AOD (via angstrom)",
            "cams_abs_aod_380": "absorption AOD (via angstrom)",
            "cams_abs_aod_400": "absorption AOD (via angstrom)",
            "cams_ssa_340": "ssa340",
            "cams_ssa_355": "ssa340 (spectral slope via angstrom)",
            "cams_ssa_380": "ssa340 (spectral slope via angstrom)",
            "cams_ssa_400": "ssa340 (spectral slope via angstrom)",
            "cams_asymmetry_340": "asymmetry",
            "cams_asymmetry_355": "asymmetry",
            "cams_asymmetry_380": "asymmetry",
            "cams_asymmetry_400": "asymmetry",
            "cams_ozone_du": "ozone_du",
            "cams_water_vapor": "water_vapor_kg_m2",
            "cams_cloud_liquid_water": "cloud_liquid_g_m2",
            "cams_cloud_ice_water": "cloud_ice_g_m2",
            "cams_total_cloud": "total_cloud_cover",
            "cams_forecast_albedo": "albedo",
            "cams_erythemal_irradiance_wm2": "validation target (held-out)",
            "cams_uv_index": "validation target (held-out)",
        },
    }


TIERB_CLEAR_SKY_VERSION = "degraded_clear_sky_parametric_v1"


def tierB_clear_sky_uv(
    sza_deg: float | np.ndarray,
    ozone_du: float | np.ndarray,
    aod340: float | np.ndarray,
    albedo: float | np.ndarray = 0.2,
) -> tuple[np.ndarray, np.ndarray]:
    """Analytic clear-sky parametric fallback (degraded Tier C, no ML).

    Beer-Lambert direct + parametric diffuse against the TOA spectrum,
    integrated against the shipped action spectra. NOT a libRadtran
    replacement and NOT Tier B: honest error bars are ~11 W/m2 UVA / 0.37 UVB
    on the POWER test split (measured Sep 2026, clear-sky only, no cloud
    term). Used ONLY when the ML bundle is missing;
    the calibrated ML remains the production path whenever available.

    Residual-transmission ML on top of a physics baseline was attempted and
    REJECTED: UVA test-MAE 0.59 vs raw-ML 0.35 on the same split (Sep 2026).
    Broadband→broadband has no meaningful Tier-B without real spectral
    targets; this fallback is a physics floor, not an upgrade.
    """
    sza = np.asarray(sza_deg, dtype=float)
    o3 = np.asarray(ozone_du, dtype=float)
    aod = np.asarray(aod340, dtype=float)
    alb = np.asarray(albedo, dtype=float)
    mu = np.cos(np.radians(np.clip(sza, 0, 89.9)))
    # Fitted once on the POWER training domain (train years only):
    # log band-transmission ~ ozone + aerosol/slant + albedo bounce.
    # Coefficients from Ridge on log(UV/clear_ghi); recorded here, not tuned.
    toa_uva, toa_uvb = 68.0, 4.6  # TOA band integrals, W/m2
    t_uva = np.exp(-0.0021 * o3 / mu - 0.55 * aod / mu) * (1 + 0.35 * alb)
    t_uvb = np.exp(-0.0110 * o3 / mu - 0.85 * aod / mu) * (1 + 0.30 * alb)
    day = (sza < 90) & np.isfinite(mu) & (mu > 0)
    uva = np.where(day, toa_uva * mu * np.clip(t_uva, 0, 1.2), 0.0)
    uvb = np.where(day, toa_uvb * mu * np.clip(t_uvb, 0, 1.2), 0.0)
    return uva, uvb

# Back-compat alias: the old tierB-clear-sky-v1 name survives one migration
# version so serialized artifacts stay parseable; new code must use
# degraded_clear_sky_parametric_v1.
TIERB_CLEAR_SKY_VERSION_LEGACY_ALIAS = "tierB-clear-sky-v1"


def spectral_tier_for_row(has_emulator: bool = False, has_reference: bool = False) -> str:
    """Tier C: implemented (broadband reconstruction). Tier B: reserved for a
    validated libRadtran-trained emulator behind the manifest contract below;
    the analytic clear-sky fallback is degraded Tier C, never Tier B.
    Tier A: reserved. Production resolves C with ML, degraded-C without."""
    if has_reference:
        return "A"
    if has_emulator:
        return "B"
    return "C"


TIER_B_REQUIRED_MANIFEST_FIELDS = (
    "spectral_emulator_version",
    "spectral_training_manifest_sha256",
    "libradtran_version",
    "parameter_ranges",
    "validation_metrics",
)


def validate_tierB_manifest(manifest: dict[str, object]) -> dict[str, object]:
    """Enforce the Tier-B emulator manifest contract. Fails loudly.

    Strict mode calls this before trusting any Tier-B spectral output: the
    emulator version, training-manifest checksum, libRadtran provenance,
    parameter ranges, and held-out validation metrics must all be present.
    """
    if not isinstance(manifest, dict):
        raise TypeError("ERROR spectral: Tier-B manifest must be a mapping")
    missing = [f for f in TIER_B_REQUIRED_MANIFEST_FIELDS if f not in manifest]
    if missing:
        raise ValueError(
            f"ERROR spectral: Tier-B manifest missing fields: {missing}. "
            f"Build the corpus with scripts/build_spectral_corpus.py first."
        )
    metrics = manifest["validation_metrics"]
    if not isinstance(metrics, dict) or not metrics:
        raise ValueError(
            "ERROR spectral: Tier-B manifest has no held-out validation metrics"
        )
    return manifest
