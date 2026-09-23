"""Generate versioned action-spectrum resources (1 nm, 280-400 nm).

Provisional delayed-melanogenesis shape is a log-linear interpolation through
anchor points approximating the published Parrish et al. 1982 delayed-tanning
effectiveness curve. It is NOT the exact CIE 103/3 pigmentation table, which
could not be obtained in legally usable machine-readable form. See adjacent
metadata JSON files for full provenance. Do not edit CSVs by hand; rerun this
script so checksums stay consistent.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

import numpy as np

OUT = Path(__file__).resolve().parents[1] / "data" / "research" / "action_spectra"

WAVES = np.arange(280, 401, 1, dtype=float)


def cie_erythema(w: np.ndarray) -> np.ndarray:
    s = np.empty_like(w, dtype=float)
    for i, lam in enumerate(w):
        if lam <= 298:
            s[i] = 1.0
        elif lam <= 328:
            s[i] = 10.0 ** (0.094 * (298.0 - lam))
        else:
            s[i] = 10.0 ** (0.015 * (139.0 - lam))
    return s


# Provisional delayed-melanogenesis anchors (wavelength_nm, effectiveness),
# normalized to 1.0 at 280-290 nm. Approximates Parrish et al. 1982 delayed
# pigmentation effectiveness falloff: ~unity in UVB, ~1e-2 by 320-330 nm,
# ~1e-3 by 340-360 nm, ~1e-4 by 400 nm. Log-linear between anchors.
MEL_ANCHORS = np.array([
    (280.0, 1.0),
    (290.0, 1.0),
    (295.0, 0.72),
    (300.0, 0.45),
    (305.0, 0.24),
    (310.0, 0.12),
    (315.0, 0.055),
    (320.0, 0.025),
    (325.0, 0.014),
    (330.0, 0.0080),
    (335.0, 0.0048),
    (340.0, 0.0030),
    (345.0, 0.0021),
    (350.0, 0.0015),
    (355.0, 0.00105),
    (360.0, 0.00078),
    (365.0, 0.00060),
    (370.0, 0.00045),
    (375.0, 0.00035),
    (380.0, 0.00028),
    (385.0, 0.00023),
    (390.0, 0.00018),
    (395.0, 0.00014),
    (400.0, 0.00012),
])


def interp_log(anchors: np.ndarray, waves: np.ndarray) -> np.ndarray:
    ax, ay = anchors[:, 0], np.log10(anchors[:, 1])
    return 10.0 ** np.interp(waves, ax, ay)


def ipd_spectrum(w: np.ndarray) -> np.ndarray:
    """Broad UVA-dominant IPD/PPD shape: Gaussian peak near 340 nm.

    Zero below 300 nm (IPD is not a UVB endpoint), sigma ~28 nm, normalized
    to 1.0 at 340 nm. A short-wave logistic cutoff (midpoint 312 nm, width
    2.5 nm) confines the effective domain to ~320-400 nm per the published
    IPD literature; the 320-400 nm shape is essentially the pure Gaussian.
    Existing-pigment oxidation/redistribution endpoint only.
    """
    g = np.exp(-0.5 * ((w - 340.0) / 28.0) ** 2)
    cutoff = 1.0 / (1.0 + np.exp(-(w - 312.0) / 2.5))
    g = g * cutoff
    g[w < 300] = 0.0
    return g / g.max()


def sha256_of(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_csv(name: str, values: np.ndarray) -> Path:
    p = OUT / name
    lines = ["wavelength_nm,effectiveness"]
    for w, v in zip(WAVES, values):
        lines.append(f"{w:.0f},{v:.6e}")
    p.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return p


def write_meta(name: str, meta: dict) -> Path:
    p = OUT / name
    p.write_text(json.dumps(meta, indent=2) + "\n", encoding="utf-8")
    return p


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    ery = cie_erythema(WAVES)
    mel = interp_log(MEL_ANCHORS, WAVES)
    ipd = ipd_spectrum(WAVES)

    p_ery = write_csv("cie_erythema_reference.csv", ery)
    p_par = write_csv("parrish_delayed_melanogenesis.csv", mel)
    # CIE 103/3 pigmentation table is not available in legally usable
    # machine-readable form; ship the provisional shape under the CIE filename
    # ONLY with explicit provisional labeling so strict mode can refuse it.
    p_cie_pig = write_csv("cie_pigmentation_reference.csv", mel)
    p_ipd = write_csv("ipd_action_spectrum.csv", ipd)

    common_mel_anchors = [{"wavelength_nm": float(w), "effectiveness": float(v)}
                          for w, v in MEL_ANCHORS]

    metas = {
        "cie_erythema_reference.meta.json": {
            "resource": "cie_erythema_reference.csv",
            "source_title": "Erythema reference action spectrum and standard erythema dose",
            "authors": "McKinlay AF, Diffey BL",
            "year": 1987,
            "identifier": "CIE S 007/E-1998 (CIE erythema action spectrum; originally CIE 1987)",
            "biological_endpoint": "erythema (sunburn reddening), human skin",
            "subject_population": "human reference action spectrum (population-averaged, not per-subject)",
            "wavelengths_tested_nm": "250-400 (production domain 280-400)",
            "assessment_time_after_exposure": "erythema assessed ~24 h (reference weighting, not a tanning endpoint)",
            "normalization_convention": "1.0 at 250-298 nm; 10^(0.094*(298-lambda)) 298-328 nm; 10^(0.015*(139-lambda)) 328-400 nm",
            "original_units": "dimensionless relative effectiveness",
            "digitization_method": "closed-form CIE equation evaluated at 1 nm, not digitized from a figure",
            "wavelength_spacing_nm": 1,
            "spectral_domain_nm": [280, 400],
            "interpolation_guidance": "log-space (log10 effectiveness) interpolation between tabulated points",
            "checksum_sha256": sha256_of(p_ery),
            "tier": "canonical",
            "limitations": "Erythema endpoint only. Must NEVER be used as a melanogenesis weighting. Population reference, not individual prediction.",
        },
        "parrish_delayed_melanogenesis.meta.json": {
            "resource": "parrish_delayed_melanogenesis.csv",
            "source_title": "Erythema and melanogenesis action spectra of normal human skin",
            "authors": "Parrish JA, Jaenicke KF, Anderson RR",
            "year": 1982,
            "identifier": "DOI 10.1111/j.1751-1097.1982.tb04362.x; PMID 7122713",
            "biological_endpoint": "delayed tanning / delayed melanogenesis (new pigmentation, distinct from immediate pigment darkening)",
            "subject_population": "normal human skin, Caucasian subjects (small-n monochromator study; see paper for details)",
            "wavelengths_tested_nm": "290-400 nm monochromator bands (production table extrapolated to 280-289 nm at unity with explicit uncertainty)",
            "assessment_time_after_exposure": "delayed pigmentation assessed ~7 days after exposure (visual grading of delayed tanning)",
            "normalization_convention": "1.0 at 280-290 nm; log-linear interpolation through documented anchor points",
            "original_units": "dimensionless relative effectiveness (reciprocal minimal melanogenesis dose)",
            "digitization_method": "provisional anchor points approximating the published delayed-pigmentation curve shape; NOT a pixel digitization of a figure. Replace with exact digitization or licensed CIE table when available.",
            "anchor_points": common_mel_anchors,
            "wavelength_spacing_nm": 1,
            "spectral_domain_nm": [280, 400],
            "interpolation_guidance": "log-space (log10 effectiveness) interpolation; linear interpolation in effectiveness is INVALID across orders of magnitude",
            "checksum_sha256": sha256_of(p_par),
            "tier": "provisional",
            "limitations": "Provisional shape. Small historical subject panel; Caucasian skin only; visual grading; 280-289 nm is an assumption of continued high effectiveness, not a measurement. Do not present as exact CIE 103/3 values.",
        },
        "cie_pigmentation_reference.meta.json": {
            "resource": "cie_pigmentation_reference.csv",
            "source_title": "Reference Action Spectra for Ultraviolet Induced Erythema and Pigmentation of Different Human Skin Types",
            "authors": "Commission Internationale de l'Eclairage (CIE)",
            "year": 1993,
            "identifier": "CIE 103/3 (exact machine-readable table NOT obtained)",
            "biological_endpoint": "delayed pigmentation (intended canonical basis)",
            "subject_population": "unavailable - exact CIE table not legally/technically obtained",
            "wavelengths_tested_nm": "unavailable",
            "assessment_time_after_exposure": "unavailable",
            "normalization_convention": "CSV currently holds the provisional Parrish-approximated shape as a PLACEHOLDER, normalized 1.0 at 280-290 nm",
            "original_units": "dimensionless relative effectiveness (placeholder)",
            "digitization_method": "none - placeholder copy of provisional shape pending licensed CIE 103/3 acquisition",
            "wavelength_spacing_nm": 1,
            "spectral_domain_nm": [280, 400],
            "interpolation_guidance": "log-space; strict production mode MUST refuse this resource until tier is canonical",
            "checksum_sha256": sha256_of(p_cie_pig),
            "tier": "provisional",
            "status": "PLACEHOLDER - exact CIE 103/3 values NOT included. Do not cite as CIE data. Strict mode must require the canonical spectrum.",
            "limitations": "NOT CIE DATA. Placeholder only. Any use must be labeled provisional and versioned as action-spectrum-v1-provisional.",
        },
        "ipd_action_spectrum.meta.json": {
            "resource": "ipd_action_spectrum.csv",
            "source_title": "Immediate/persistent pigment darkening (IPD/PPD) action spectrum literature synthesis",
            "authors": "Multiple (provisional synthesis; see PHOTOBIOLOGY_MODEL.md for primary references)",
            "year": 2008,
            "identifier": "provisional synthesis - no single canonical IPD standard",
            "biological_endpoint": "existing-pigment oxidation/redistribution / persistent darkening (NOT new melanogenesis)",
            "subject_population": "human skin with existing pigment; endpoint requires pigment to darken",
            "wavelengths_tested_nm": "320-400 nm effective domain (logistic short-wave cutoff below ~312 nm; values below 300 nm set to 0)",
            "assessment_time_after_exposure": "minutes to hours after exposure (transient to persistent darkening, fades without new melanin)",
            "normalization_convention": "1.0 at 340 nm peak; Gaussian sigma 28 nm with short-wave logistic cutoff (midpoint 312 nm, width 2.5 nm)",
            "original_units": "dimensionless relative effectiveness",
            "digitization_method": "analytic Gaussian model of the broad 320-400 nm IPD peak near 340 nm with a short-wave cutoff, not a digitization",
            "wavelength_spacing_nm": 1,
            "spectral_domain_nm": [280, 400],
            "interpolation_guidance": "linear interpolation acceptable (dynamic range < 2 orders); keep separate from melanogenesis channel",
            "checksum_sha256": sha256_of(p_ipd),
            "tier": "provisional",
            "limitations": "Optional second channel only. Must never merge into production TanScore without a justified response model. Broad literature shape, not a fitted standard.",
        },
    }
    for name, meta in metas.items():
        write_meta(name, meta)
    print(f"Wrote {len(metas)} spectra + metadata to {OUT}")


if __name__ == "__main__":
    main()
