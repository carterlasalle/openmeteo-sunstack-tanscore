"""Literature-informed regression invariants for the v5 photobiology model.

Uses only aggregate published observations (data/research/exposure_studies.json)
plus the shipped action spectra — never fabricated individual-subject data.
Writes docs/validation/literature_sanity.md. Fails loudly (exit 1) if any
invariant breaks, so regressions in spectra or weighting cannot ship silent.
Naming note (contract §21): these are regression invariants pinned to
literature-described behavior, NOT independent reproductions of published
numeric results — except the FDA-table anchor checks, which verify exact
transcribed values against Form FDA 3630 Appendix B.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import TypedDict, cast

import numpy as np

sys.path.insert(0, "src")

from sunstack.photobiology import (
    ACTION_SPECTRUM_STEM,
    ActionSpectrum,
    effectiveness_at,
    erythemal_irradiance_from_uvi,
    load_action_spectrum,
)
from sunstack.spectral import melanogenic_from_broadband

LINES: list[str] = []


class StudiesDoc(TypedDict):
    studies: list[object]


def _at(spec: ActionSpectrum, wave: float) -> float:
    """Single-wavelength effectiveness with statically known types."""
    got = effectiveness_at(spec, np.array([wave]))
    return float(got.mean())


def _mean_at(spec: ActionSpectrum, waves: tuple[float, ...]) -> float:
    got = effectiveness_at(spec, np.array(list(waves)))
    return float(got.mean())


def check(name: str, ok: bool, detail: str) -> None:
    LINES.append(f"- [{'PASS' if ok else 'FAIL'}] {name}: {detail}")
    if not ok:
        raise SystemExit(f"LITERATURE SANITY FAILED: {name}: {detail}")


def _read_studies_count() -> int:
    text = Path("data/research/exposure_studies.json").read_text(encoding="utf-8")
    doc = cast(StudiesDoc, json.loads(text))
    return len(doc["studies"])


def _parse_args(argv: list[str] | None) -> Path:
    import argparse

    parser = argparse.ArgumentParser()
    _ = parser.add_argument("--out", default="docs/validation/literature_sanity.md")
    ns = parser.parse_args(argv)
    return Path(cast(str, ns.out))


def main(argv: list[str] | None = None) -> None:
    out: Path = _parse_args(argv)
    LINES.clear()
    LINES.append("# Literature-informed regression invariants (v5 photobiology)")
    LINES.append("")
    LINES.append(
        f"Studies encoded: {_read_studies_count()}. No individual-subject data fabricated.")
    LINES.append("")

    mel = load_action_spectrum(ACTION_SPECTRUM_STEM)
    ery = load_action_spectrum("cie_erythema_reference")
    ipd = load_action_spectrum("ipd_action_spectrum")

    # 0. FDA-table anchors: exact transcribed values from Form FDA 3630
    # Appendix B (contract §24.1). These pin the transcription, not the biology.
    for wave, want in ((280.0, 0.314285), (296.0, 1.0), (302.0, 0.815892),
                       (315.0, 0.0294593), (340.0, 0.00151841), (400.0, 0.000179336)):
        got = _at(mel, wave)
        check(f"FDA-3630 anchor at {wave:.0f} nm",
              abs(got - want) / max(want, 1e-12) < 1e-6,
              f"S({wave:.0f})={got:.6e} vs table {want:.6e}")
    check("FDA-3630 normalization maximum at 296 nm",
          mel.name == ACTION_SPECTRUM_STEM and _at(mel, 296.0) == 1.0,
          "table maximum 1.0 sits at 296 nm (title says 'Normalized to 292 nm')")

    # 1. Parrish 1982: delayed-melanogenesis effectiveness collapses UVB->UVA.
    uvb = _mean_at(mel, (290.0, 292.0, 295.0))
    uva = _mean_at(mel, (360.0, 362.0, 365.0))
    check("Parrish-1982 UVB>>UVA delayed effectiveness",
          uvb / uva > 100,
          f"S(290-295)/S(360-365) = {uvb/uva:.0f}x ({uvb:.3f} vs {uva:.2e})")

    # 2. Keong 1990 photoaddition: 290 nm + 360 nm MPDs add, no interaction.
    e12 = float(melanogenic_from_broadband(30.0, 1.0))
    e1 = float(melanogenic_from_broadband(30.0, 0.0))
    e2 = float(melanogenic_from_broadband(0.0, 1.0))
    check("Keong-1990 photoaddition (no sqrt interaction)",
          abs(e12 - (e1 + e2)) < 1e-12,
          f"E(UVA+UVB)={e12:.6f} == E(UVA)+E(UVB)={e1+e2:.6f}")

    # 3. Erythema and melanogenesis are different endpoints (not interchangeable).
    # Measured FDA-table fact: melanogenic effectiveness falls SLOWER through the
    # UVA than erythemal effectiveness, so the mel/ery ratio rises with
    # wavelength (per joule of UVA, more tanning per burn than in UVB).
    # The v4 check asserted e_ery(300)/e_mel(300) > 1, which was an artifact of
    # the old provisional curve (unity at 280-290 nm); the transcribed table has
    # S_mel(300) = 0.964 > S_ery(300) = 0.649. Assert the measured gradient.
    ratios: dict[float, float] = {}
    for wave in (300.0, 320.0, 340.0, 365.0):
        e_mel = _at(mel, wave)
        e_ery = _at(ery, wave)
        ratios[wave] = e_mel / e_ery if e_ery > 0 else float("nan")
    rising = ratios[320.0] > ratios[300.0] and ratios[365.0] > ratios[340.0] > 1.0
    parts = [f"{w:.0f}nm:{r:.2f}" for w, r in sorted(ratios.items())]
    check("erythema/melanogenesis endpoint separation (mel/ery rises into UVA)",
          bool(rising),
          "S_mel/S_ery = " + ", ".join(parts))

    # 4. IPD is UVA-dominant and silent in UVB; melanogenesis is the reverse.
    ipd_340 = _at(ipd, 340.0)
    ipd_300 = _at(ipd, 300.0)
    check("IPD UVA-dominant, UVB-silent",
          ipd_340 == 1.0 and ipd_300 < 0.05,
          f"IPD(340)={ipd_340:.2f} peak, IPD(300)={ipd_300:.3f}")
    mel_340 = _at(mel, 340.0)
    check("IPD vs melanogenesis separated at 340 nm",
          ipd_340 / mel_340 > 100,
          f"IPD(340)={ipd_340:.2f} vs S_mel(340)={mel_340:.2e} (existing-pigment darkening vs new melanogenesis)")

    # 5. SED and TanDose diverge by construction on the same hour.
    e_mel_hour = float(melanogenic_from_broadband(35.0, 1.0))
    sed_hour = float(erythemal_irradiance_from_uvi(6.0) * 3600 / 100)
    tandose_hour = e_mel_hour * 3600
    check("SED/TanDose non-interchangeability (UVI6/UVA35 hour)",
          abs(sed_hour - 5.4) < 1e-9 and tandose_hour > 1000,
          f"SED={sed_hour:.2f} (erythemal) vs TanDose={tandose_hour:.0f} J/m^2 mel (delayed-melanogenesis)")

    # 6. Wolber 2008 framing: SSR-vs-isolated-band synergy belongs downstream.
    wolber = ("- [INFO] Wolber-2008 SSR synergy: physical exposure stays wavelength-additive (check 2); "
              "any super-additive pigment response belongs in TanResponseModel, which is intentionally "
              "unshipped until a fitted model beats cumulative dose.")
    LINES.append(wolber)
    # 7. MITF timer prior: mechanistic only, no hard-coded optimum.
    mitf = ("- [INFO] MITF-timer (PMID 30401431): mechanistic prior only; "
            "no interval optimum is hard-coded anywhere in the pipeline.")
    LINES.append(mitf)

    _ = out.parent.mkdir(parents=True, exist_ok=True)
    _ = out.write_text("\n".join(LINES) + "\n", encoding="utf-8")
    print("\n".join(LINES))
    print(f"\nwrote {out}")


if __name__ == "__main__":
    main()
