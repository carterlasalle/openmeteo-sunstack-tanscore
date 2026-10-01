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
    # Physically consistent derivations.
    aod340 = out["aod340"]
    ang = out["angstrom"]
    for wave in (355, 380, 400):
        out[f"aod{wave}"] = aod340 * (wave / 340.0) ** (-ang)
    # Clear-sky rows carry no cloud water regardless of the sampled columns.
    clear = out["total_cloud_cover"] < 0.05
    out["cloud_liquid_g_m2"] = np.where(clear, 0.0, out["cloud_liquid_g_m2"])
    out["cloud_ice_g_m2"] = np.where(clear, 0.0, out["cloud_ice_g_m2"])
    return out


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
        "regime_enrichment": [
            "low sun (SZA 70-88)",
            "high ozone (400-450 DU) and low ozone (200-250 DU)",
            "high/absorbing aerosol (AOD340 > 0.5, SSA340 < 0.92)",
            "bright snow/sand surfaces (albedo > 0.5)",
            "cloud transitions (total_cloud_cover 0.05-0.5)",
            "high altitude (2000-4000 m)",
        ],
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
