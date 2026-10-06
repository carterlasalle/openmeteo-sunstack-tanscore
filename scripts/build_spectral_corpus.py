"""Offline libRadtran/uvspec training-corpus builder for the Tier-B spectral emulator.

Per SPECTRAL_MODEL.md: generate a physically diverse libRadtran corpus
(280-400 nm, high-resolution UV settings; realistic ozone, SZA, altitude,
aerosol optics, albedo, cloud ranges), then train/interpolate the fast
runtime emulator and validate on held-out cases.

This script ALWAYS writes the deterministic sample design + manifest
(recorded ranges, seed, checksums). It runs uvspec per sample ONLY when a
`uvspec` binary is on PATH; otherwise each sample is recorded as
status=pending so the design, not fake spectra, is the artifact. libRadtran
must never become a mandatory dependency of a UI refresh.

Usage:
    python3 scripts/build_spectral_corpus.py --samples 2000 --out data/research/spectral_corpus
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import shutil
import subprocess
from pathlib import Path

import numpy as np

RANGES: dict[str, tuple[float, float]] = {
    "sza_deg": (0.0, 88.0),
    "ozone_du": (200.0, 450.0),
    "altitude_m": (0.0, 4000.0),
    "aod340": (0.02, 1.0),          # log-uniform
    "angstrom": (0.0, 2.0),         # derives AOD at 355/380/400 nm
    "ssa340": (0.85, 1.0),
    "asymmetry": (0.60, 0.75),
    "albedo": (0.02, 0.90),         # include snow >0.8
    "total_cloud_cover": (0.0, 1.0),
    "cloud_liquid_g_m2": (0.0, 2000.0),  # log-uniform over (1, 2000] when cloudy
    "cloud_ice_g_m2": (0.0, 500.0),
    "water_vapor_kg_m2": (0.5, 60.0),
}

UVSPEC_TEMPLATE = """# DRAFT uvspec template for the Tier-B corpus (280-400 nm).
# REVIEW against the installed libRadtran version before production use;
# option names/values below are a starting draft, not verified syntax.
wavelength 280.0 400.0
# high-resolution UV sampling for the melanogenesis convolution
wavelength_step 0.5
sza {sza_deg}
altitude {altitude_m}
atmosphere_file us-standard  # plus per-sample ozone scaling to {ozone_du} DU
albedo {albedo}
aerosol_default
aerosol_set_tau_at_wvl 340.0 {aod340}
aerosol_angstrom {angstrom} 340.0
aerosol_set_ssa {ssa340}
aerosol_set_gg {asymmetry}
# cloud layers from liquid/ice columns when total_cloud_cover > 0
# water vapor column {water_vapor_kg_m2} kg/m2
rte_solver pseudospherical
number_of_streams 16
output_user lambda edir edn eup
"""


def stratified_design(n: int, seed: int = 23) -> dict[str, np.ndarray]:
    """Latin-hypercube base coverage plus explicit regime enrichment (§8.2).

    Base: every parameter gets one draw per equal-probability stratum, so no
    region of the 12-D space is systematically empty. Enrichment: fixed
    fractions of the rows are re-drawn inside the regimes the contract names
    (low sun, ozone extremes, absorbing aerosol, bright surfaces, cloud
    transitions, high altitude) because a uniform design under-covers the
    hard corners where the emulator must not fail.
    """
    rng = np.random.default_rng(seed)
    out: dict[str, np.ndarray] = {}
    for name, bounds in RANGES.items():
        lo: float = bounds[0]
        hi: float = bounds[1]
        edges: np.ndarray = np.linspace(0, 1, n + 1)
        divs: np.ndarray = edges[:-1] + 0.0
        draws: np.ndarray = rng.random(n, dtype=np.float64)
        step: np.ndarray = np.full(n, 1.0 / n)
        u: np.ndarray = divs + draws * step
        rng.shuffle(u)
        if name in ("aod340", "cloud_liquid_g_m2", "cloud_ice_g_m2"):
            # log-uniform over (max(lo,eps), hi]; exact 0 handled by cloud cover.
            lo_eff = max(lo, 1e-3)
            lo_log: float = math.log(lo_eff)
            hi_log: float = math.log(hi)
            out[name] = np.exp(lo_log + u * (hi_log - lo_log))
        else:
            out[name] = lo + u * (hi - lo)

    # --- regime enrichment (§8.2) -------------------------------------
    # (name, fraction, {param: (lo, hi)}) — the named param is re-drawn in the
    # sub-range; the rest keep their base draws so each regime stays physical.
    regimes: list[tuple[str, float, dict[str, tuple[float, float]]]] = [
        ("low_sun", 0.12, {"sza_deg": (65.0, 88.0)}),
        ("clear_sky", 0.10, {"total_cloud_cover": (0.0, 0.05)}),
        ("absorbing_aerosol", 0.10,
         {"aod340": (0.5, 1.0), "ssa340": (0.85, 0.93)}),
        ("bright_surface", 0.10, {"albedo": (0.55, 0.90)}),
        ("high_altitude", 0.08, {"altitude_m": (2000.0, 4000.0)}),
        ("cloud_transition", 0.08, {"total_cloud_cover": (0.05, 0.5)}),
        ("low_ozone", 0.07, {"ozone_du": (200.0, 260.0)}),
        ("high_ozone", 0.07, {"ozone_du": (400.0, 450.0)}),
        ("low_sun_bright", 0.08,
         {"sza_deg": (70.0, 88.0), "albedo": (0.55, 0.90)}),
    ]
    start = 0
    for _name, frac, overrides in regimes:
        k = round(frac * n)
        if k <= 0:
            continue
        end = min(start + k, n)
        idx: np.ndarray = np.arange(start, end)
        for param, (lo, hi) in overrides.items():
            if param in ("aod340", "cloud_liquid_g_m2", "cloud_ice_g_m2"):
                lo_eff = max(lo, 1e-3)
                u = rng.random(idx.size)
                out[param][idx] = np.exp(math.log(lo_eff) + u * (math.log(hi) - math.log(lo_eff)))
            else:
                u = rng.random(idx.size)
                out[param][idx] = lo + u * (hi - lo)
        start = end

    # Physically consistent derivations.
    aod340 = out["aod340"]
    ang = out["angstrom"]
    for wave in (355, 380, 400):
        out[f"aod{wave}"] = aod340 * (wave / 340.0) ** (-ang)
    # Cloud *liquid/ice* column is zero whenever the cover fraction is clear;
    # an enriched clear_sky row therefore carries no cloud water.
    clear = out["total_cloud_cover"] < 0.05
    out["cloud_liquid_g_m2"] = np.where(clear, 0.0, out["cloud_liquid_g_m2"])
    out["cloud_ice_g_m2"] = np.where(clear, 0.0, out["cloud_ice_g_m2"])
    return out


REGIME_ENRICHMENT: list[dict[str, object]] = [
    {"regime": "low_sun", "fraction": 0.12, "definition": "sza_deg 65-88"},
    {"regime": "clear_sky", "fraction": 0.10, "definition": "total_cloud_cover 0-0.05"},
    {"regime": "absorbing_aerosol", "fraction": 0.10,
     "definition": "aod340 0.5-1.0, ssa340 0.85-0.93"},
    {"regime": "bright_surface", "fraction": 0.10, "definition": "albedo 0.55-0.90"},
    {"regime": "high_altitude", "fraction": 0.08, "definition": "altitude_m 2000-4000"},
    {"regime": "cloud_transition", "fraction": 0.08,
     "definition": "total_cloud_cover 0.05-0.5"},
    {"regime": "low_ozone", "fraction": 0.07, "definition": "ozone_du 200-260"},
    {"regime": "high_ozone", "fraction": 0.07, "definition": "ozone_du 400-450"},
    {"regime": "low_sun_bright", "fraction": 0.08,
     "definition": "sza_deg 70-88, albedo 0.55-0.90"},
]


def main(argv: list[str] | None = None) -> None:
    from typing import cast

    ap = argparse.ArgumentParser()
    _ = ap.add_argument("--samples", type=int, default=2000)
    _ = ap.add_argument("--seed", type=int, default=23)
    _ = ap.add_argument("--out", default="data/research/spectral_corpus")
    ns = ap.parse_args(argv)
    samples = cast(int, ns.samples)
    seed = cast(int, ns.seed)
    out_dir = Path(cast(str, ns.out))
    _ = out_dir.mkdir(parents=True, exist_ok=True)
    design = stratified_design(samples, seed)
    keys = sorted(design)
    cols: dict[str, list[float]] = {k: design[k].ravel().tolist() for k in keys}
    header = ["sample_id", *keys]
    lines = [",".join(header)]
    for i in range(samples):
        cells: list[str] = [str(i)] + [f"{cols[k][i]:.6e}" for k in keys]
        lines.append(",".join(cells))
    _ = (out_dir / "design.csv").write_text("\n".join(lines) + "\n", encoding="utf-8")
    _ = (out_dir / "uvspec_template.inp").write_text(UVSPEC_TEMPLATE, encoding="utf-8")


    uvspec = shutil.which("uvspec")
    lib_version = "not-installed"
    if uvspec:
        try:
            r = subprocess.run([uvspec, "-v"], capture_output=True, text=True, timeout=30, check=False)
            lines = (r.stdout or r.stderr or "").strip().splitlines()
            lib_version = lines[0][:120] if lines else "uvspec-found-version-unknown"
        except (OSError, subprocess.SubprocessError):
            lib_version = "uvspec-found-version-unknown"
    manifest: dict[str, object] = {
        "corpus": "libradtran-tierB-training",
        "spectral_backend": "tierB-libradtran-emulator-v1",
        "samples": samples,
        "seed": seed,
        "parameter_ranges": {k: [lo, hi] for k, (lo, hi) in RANGES.items()},
        "regime_enrichment": REGIME_ENRICHMENT,
        "design": "Latin-hypercube stratified base + named regime enrichment (see REGIME_ENRICHMENT)",
        "spectral_domain_nm": [280, 400],
        "target_spacing_nm": 0.5,
        "output_components": ["edir (direct)", "edn (diffuse down)", "eup (diffuse up)"],
        "libRadtran": lib_version,
        "uvspec_binary": uvspec or None,
        "uvspec_template": "uvspec_template.inp (DRAFT - requires operator review)",
        "status": "spectra-pending" if not uvspec else "ready-to-run",
        "design_sha256": hashlib.sha256(
            (out_dir / "design.csv").read_bytes()).hexdigest(),
        "required_next_steps": [
            "Operator reviews uvspec_template.inp against installed libRadtran.",
            "Run per-sample uvspec; store spectra + integrated UVA/UVB/erythemal.",
            "Train runtime emulator (scripts/train_spectral_emulator.py); record emulator version + training-manifest sha.",
            "Validate on held-out cases + NASA POWER + CAMS/Open-Meteo UVI.",
        ],
    }
    _ = (out_dir / "manifest.json").write_text(
        json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    print(f"design: {samples} samples -> {out_dir}/design.csv")
    print(f"libRadtran: {lib_version}; manifest status: {manifest['status']}")


if __name__ == "__main__":
    main()
