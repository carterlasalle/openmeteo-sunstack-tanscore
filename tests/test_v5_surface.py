"""Surface/material selection tests (v5 contract §12.9, §24.5)."""

from __future__ import annotations

import numpy as np
import pandas as pd


def _env_frame() -> pd.DataFrame:
    return pd.DataFrame({
        "melanogenic_effective_irradiance_wm2": [0.5, 0.5],
        "tan_score_absolute_0_100": [30.0, 30.0],
        "sza": [40.0, 40.0],
        "solar_azimuth_deg": [180.0, 180.0],
        "direct_radiation": [500.0, 500.0],
        "diffuse_radiation": [200.0, 200.0],
        "shortwave_radiation": [700.0, 700.0],
        "albedo": [0.2, 0.2],
    })


def test_preset_schema_provenance_complete() -> None:
    from sunstack.surface import PRESETS

    required = {"unknown", "grass_summer", "grass_winter", "dry_beach_sand",
                "wet_beach_sand", "light_concrete", "aged_concrete",
                "fresh_asphalt", "aged_asphalt", "weathered_wood_deck",
                "open_water", "sea_foam", "fresh_snow", "aged_snow", "custom"}
    assert required.issubset(set(PRESETS))
    for slug, p in PRESETS.items():
        assert p.slug == slug
        assert p.display_name
        assert p.optical_model in ("lambertian", "water_fresnel", "snow_spectral", "none")
        assert p.spectral_quality in ("measured_spectral", "measured_broadband",
                                      "literature_range", "broadband_uv_proxy",
                                      "custom", "none")
        assert p.source_citation
        if slug not in ("unknown", "custom"):
            assert 0.0 < p.proxy_reflectance < 1.0
            assert p.reflectance_low <= p.proxy_reflectance <= p.reflectance_high


def test_grass_less_than_dry_sand_dry_more_than_wet() -> None:
    from sunstack.surface import PRESETS

    assert PRESETS["grass_summer"].proxy_reflectance < PRESETS["dry_beach_sand"].proxy_reflectance
    assert PRESETS["dry_beach_sand"].proxy_reflectance > PRESETS["wet_beach_sand"].proxy_reflectance
    assert PRESETS["fresh_snow"].proxy_reflectance > 10 * PRESETS["grass_summer"].proxy_reflectance


def test_custom_reflectance_bounds() -> None:
    import pytest

    from sunstack.surface import resolve_surface

    with pytest.raises(ValueError):
        _ = resolve_surface("custom", 0.1, None)
    with pytest.raises(ValueError):
        _ = resolve_surface("custom", 1.5, 0.1)
    with pytest.raises(ValueError):
        _ = resolve_surface("nope-not-a-surface")
    ok = resolve_surface("custom", 0.1, 0.2)
    assert ok.slug == "custom"


def test_local_surface_never_changes_horizontal_environment() -> None:
    from sunstack.spectral import apply_skin_plane

    base = _env_frame()
    grass = apply_skin_plane(base, 45.0, 180.0, surface_slug="grass_summer")
    sand = apply_skin_plane(base, 45.0, 180.0, surface_slug="dry_beach_sand")
    for col in ("melanogenic_effective_irradiance_wm2", "tan_score_absolute_0_100"):
        assert grass[col].tolist() == base[col].tolist()
        assert sand[col].tolist() == base[col].tolist()
    # Reflected component DOES move with surface on a tilted plane.
    g = float(grass["skin_plane_ground_reflected_delayed_pigmentation_wm2"].iloc[0])
    s = float(sand["skin_plane_ground_reflected_delayed_pigmentation_wm2"].iloc[0])
    assert s > g > 0


def test_flat_plane_zero_ground_view() -> None:
    from sunstack.spectral import apply_skin_plane
    from sunstack.surface import lambertian_ground_view_factor

    assert lambertian_ground_view_factor(0.0) == 0.0
    out = apply_skin_plane(_env_frame(), 0.0, 180.0, surface_slug="fresh_snow")
    assert float(out["skin_plane_ground_reflected_delayed_pigmentation_wm2"].iloc[0]) == 0.0


def test_tilted_plane_monotonic_in_reflectance() -> None:
    from sunstack.spectral import apply_skin_plane

    vals = []
    for slug in ("grass_summer", "wet_beach_sand", "dry_beach_sand", "fresh_snow"):
        out = apply_skin_plane(_env_frame(), 60.0, 180.0, surface_slug=slug)
        vals.append(float(out["skin_plane_ground_reflected_delayed_pigmentation_wm2"].iloc[0]))
    assert vals == sorted(vals)


def test_water_not_flat_lambertian() -> None:
    from sunstack.surface import water_fresnel_reflectance

    r = water_fresnel_reflectance(np.array([0.0, 0.8, 1.45]))
    # Grazing incidence reflects far more than overhead: geometry-dependent,
    # never a flat constant.
    assert float(r[2]) > 3 * float(r[0])
    assert float(r[1]) > float(r[0])


def test_unknown_means_no_correction_not_silent_albedo() -> None:
    from sunstack.spectral import apply_skin_plane

    out = apply_skin_plane(_env_frame(), 60.0, 180.0, surface_slug="unknown")
    assert float(out["skin_plane_ground_reflected_delayed_pigmentation_wm2"].iloc[0]) == 0.0
    assert out["surface_model_quality"].iloc[0] == "none"
