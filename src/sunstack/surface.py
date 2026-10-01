"""Local surface/material model for ground-reflected skin-plane exposure (v5).

Contract §12: the user must be able to change the surface they are on. Two
concepts stay separate:

1. regional/background surface albedo — CAMS ``forecast_albedo`` over a broad
   grid cell, relevant to atmospheric RT and multiple scattering;
2. local user surface reflectance — grass/sand/concrete/snow/water around the
   user, relevant to ground-reflected exposure onto the skin plane.

Never overwrite one with the other. ``surface_extent_mode`` defaults to
``local`` (near-field reflection only); ``broad`` additionally feeds the
Tier-B RT boundary condition because the user declares broad homogeneity.

Preset defaults (§12.10) are UVB/broadband-UV proxy midpoints of cited IARC
ranges with the range preserved as uncertainty — not universal constants. A
scalar proxy is NEVER copied into both bands as spectral truth: without a
measured curve the preset carries ``broadband_uv_proxy`` quality and applies
as a flat degraded reflectance only when the caller allows it.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import numpy as np

SURFACE_MODEL_VERSION = "uv-surface-v1"


@dataclass(frozen=True)
class SurfaceProfile:
    slug: str
    display_name: str
    optical_model: str  # lambertian | water_fresnel | snow_spectral | none
    proxy_reflectance: float  # UVB/broadband-UV proxy default (§12.10)
    reflectance_low: float
    reflectance_high: float
    spectral_quality: str  # measured_spectral | measured_broadband | literature_range | broadband_uv_proxy | custom | none
    source_citation: str
    state: str
    rt_background_ok: bool  # appropriate as broad RT boundary condition


PRESETS: dict[str, SurfaceProfile] = {
    "unknown": SurfaceProfile(
        "unknown", "Unknown surface", "none", 0.0, 0.0, 0.0,
        "none", "no assertion", "unknown", False),
    "grass_summer": SurfaceProfile(
        "grass_summer", "Summer grass", "lambertian", 0.0285, 0.020, 0.037,
        "broadband_uv_proxy", "IARC UV reflectance table (NCBI NBK401584): summer lawn grass 2.0-3.7% UVB",
        "dry summer lawn", True),
    "grass_winter": SurfaceProfile(
        "grass_winter", "Winter grass", "lambertian", 0.0400, 0.030, 0.050,
        "broadband_uv_proxy", "IARC table dormant-grass range 3-5% UVB",
        "dormant/brown", True),
    "dry_beach_sand": SurfaceProfile(
        "dry_beach_sand", "Dry beach sand", "lambertian", 0.1650, 0.150, 0.180,
        "broadband_uv_proxy", "IARC table: dry light beach sand 15-18% UVB",
        "dry", True),
    "wet_beach_sand": SurfaceProfile(
        "wet_beach_sand", "Wet beach sand", "lambertian", 0.0710, 0.060, 0.082,
        "broadband_uv_proxy", "IARC table: wet sand ~7% UVB",
        "wet", True),
    "light_concrete": SurfaceProfile(
        "light_concrete", "Light concrete", "lambertian", 0.1100, 0.100, 0.120,
        "broadband_uv_proxy", "IARC table: light concrete 10-12% UVB",
        "dry", True),
    "aged_concrete": SurfaceProfile(
        "aged_concrete", "Aged concrete", "lambertian", 0.0760, 0.070, 0.082,
        "broadband_uv_proxy", "IARC table: aged concrete 7.0-8.2% UVB",
        "weathered", True),
    "fresh_asphalt": SurfaceProfile(
        "fresh_asphalt", "Fresh asphalt", "lambertian", 0.0455, 0.041, 0.050,
        "broadband_uv_proxy", "IARC table: fresh asphalt 4.1-5.0% UVB",
        "fresh", True),
    "aged_asphalt": SurfaceProfile(
        "aged_asphalt", "Aged asphalt", "lambertian", 0.0695, 0.050, 0.089,
        "broadband_uv_proxy", "IARC table: aged asphalt 5.0-8.9% UVB",
        "weathered", True),
    "weathered_wood_deck": SurfaceProfile(
        "weathered_wood_deck", "Weathered wood deck", "lambertian", 0.0640, 0.050, 0.078,
        "broadband_uv_proxy", "representative measured value, weathered wood",
        "weathered", False),
    "open_water": SurfaceProfile(
        "open_water", "Open water", "water_fresnel", 0.0330, 0.020, 0.060,
        "broadband_uv_proxy", "diffuse baseline ~3%; specular geometry-dependent, can be much higher",
        "calm-to-rippled", True),
    "sea_foam": SurfaceProfile(
        "sea_foam", "Sea foam", "lambertian", 0.2750, 0.250, 0.300,
        "broadband_uv_proxy", "IARC table: sea foam 25-30% UVB",
        "foamy", False),
    "fresh_snow": SurfaceProfile(
        "fresh_snow", "Fresh snow", "lambertian", 0.88, 0.80, 0.90,
        "broadband_uv_proxy", "literature commonly ~0.8-0.9 UVB; spectral snow model preferred",
        "fresh", True),
    "aged_snow": SurfaceProfile(
        "aged_snow", "Aged snow", "lambertian", 0.50, 0.40, 0.60,
        "broadband_uv_proxy", "representative two-day-old snow; spectral snow model preferred",
        "aged", True),
    "custom": SurfaceProfile(
        "custom", "Custom reflectance", "lambertian", 0.0, 0.0, 1.0,
        "custom", "caller-supplied reflectances", "custom", False),
}

def load_surface_materials(path: Path) -> list[dict[str, object]]:
    """Load the version-controlled surface provenance registry."""
    import yaml

    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(raw, list):
        raise TypeError("surface materials registry must be a list")
    return raw


def validate_surface_materials() -> None:
    """Assert that the surface provenance registry matches the runtime presets."""
    materials = load_surface_materials(
        Path(__file__).resolve().parents[2]
        / "data" / "research" / "surfaces" / "surface_materials.yaml"
    )
    by_slug = {material["slug"]: material for material in materials}
    assert set(by_slug) == set(PRESETS)
    assert len(by_slug) == len(materials)
    for slug, profile in PRESETS.items():
        material = by_slug[slug]
        for field in ("proxy_reflectance", "reflectance_low", "reflectance_high"):
            assert abs(float(material[field]) - getattr(profile, field)) <= 1e-12

SURFACE_EXTENT_MODES = ("local", "broad")


def resolve_surface(
    slug: str | None,
    uva_reflectance: float | None = None,
    uvb_reflectance: float | None = None,
) -> SurfaceProfile:
    """Resolve a surface slug (or custom reflectances) to a preset profile."""
    key = (slug or "unknown").strip().lower()
    if key == "custom":
        if uva_reflectance is None or uvb_reflectance is None:
            raise ValueError("ERROR surface: custom surface requires both --surface-uva-reflectance and --surface-uvb-reflectance in [0,1]")
        for v in (uva_reflectance, uvb_reflectance):
            if not (0.0 <= float(v) <= 1.0):
                raise ValueError(f"ERROR surface: custom reflectance {v} outside [0,1]")
        mid = (float(uva_reflectance) + float(uvb_reflectance)) / 2.0
        return SurfaceProfile(
            "custom", "Custom reflectance", "lambertian", mid, 0.0, 1.0,
            "custom", "caller-supplied reflectances", "custom", False)
    if key not in PRESETS:
        raise ValueError(f"ERROR surface: unknown surface {slug!r}; allowed: {sorted(PRESETS)}")
    return PRESETS[key]


def water_fresnel_reflectance(
    incidence_rad: np.ndarray | float,
    diffuse_baseline: float = 0.033,
) -> np.ndarray:
    """Unpolarized Fresnel reflectance for open water (§12.4).

    Specular reflection from incidence angle (n_water ≈ 1.34 in UV); diffuse
    baseline added separately. NOT a flat Lambertian constant and NOT forced
    monotonic like one — reflection rises steeply at grazing incidence.
    """
    theta: np.ndarray = np.asarray(incidence_rad, dtype=float)
    n = 1.34
    clipped: np.ndarray = np.clip(theta, 0, np.pi / 2)
    cos_i: np.ndarray = np.clip(np.cos(clipped), 0, 1)
    sin_t: np.ndarray = np.clip(np.sin(np.arccos(cos_i)) / n, 0, 1)
    cos_t: np.ndarray = np.sqrt(np.clip(1.0 - sin_t ** 2, 0, 1))
    rs: np.ndarray = ((cos_i - n * cos_t) / (cos_i + n * cos_t + 1e-12)) ** 2
    rp: np.ndarray = ((n * cos_i - cos_t) / (n * cos_i + cos_t + 1e-12)) ** 2
    fresnel: np.ndarray = 0.5 * (rs + rp)
    return np.clip(fresnel + diffuse_baseline, 0, 1)


def lambertian_ground_view_factor(tilt_deg: float) -> float:
    """Ground-view fraction for a tilted plane (isotropic geometry).

    A flat horizontal plane (tilt 0) sees NO ground: factor 0. A vertical
    plane sees half ground. The UI must not claim a ground-reflection boost
    for the exact horizontal geometry.
    """
    import math as _math

    tilt = _math.radians(float(tilt_deg))
    return 0.5 * (1.0 - _math.cos(tilt))
