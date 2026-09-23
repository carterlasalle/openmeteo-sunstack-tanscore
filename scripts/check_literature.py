"""Sanity-check v4 model behavior against published controlled-exposure literature.

Uses only aggregate published observations (data/research/exposure_studies.json)
plus the shipped action spectra — never fabricated individual-subject data.
Writes docs/validation/literature_sanity.md. Fails loudly (exit 1) if any
sanity gate breaks, so regressions in spectra or weighting cannot ship silent.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, "src")

from sunstack.photobiology import (  # noqa: E402
    effectiveness_at,
    erythemal_irradiance_from_uvi,
    load_action_spectrum,
)
from sunstack.spectral import melanogenic_from_broadband  # noqa: E402

LINES: list[str] = []


def check(name: str, ok: bool, detail: str) -> None:
    LINES.append(f"- [{'PASS' if ok else 'FAIL'}] {name}: {detail}")
    if not ok:
        raise SystemExit(f"LITERATURE SANITY FAILED: {name}: {detail}")


def main() -> None:
    studies = json.loads(
        (Path("data/research/exposure_studies.json")).read_text(encoding="utf-8"))
    LINES.append("# Literature sanity checks (aggregate observations only)")
    LINES.append("")
    LINES.append(f"Studies encoded: {len(studies['studies'])}. "
                 "No individual-subject data fabricated.")
    LINES.append("")

    mel = load_action_spectrum("parrish_delayed_melanogenesis")
    ery = load_action_spectrum("cie_erythema_reference")
    ipd = load_action_spectrum("ipd_action_spectrum")

    # 1. Parrish 1982: delayed-melanogenesis effectiveness collapses UVB->UVA.
    uvb = float(effectiveness_at(mel, np.array([290.0, 292.0, 295.0])).mean())
    uva = float(effectiveness_at(mel, np.array([360.0, 362.0, 365.0])).mean())
    check("Parrish-1982 UVB>>UVA delayed effectiveness",
          uvb / uva > 100,
          f"S(290-295)/S(360-365) = {uvb/uva:.0f}x "
          f"({uvb:.3f} vs {uva:.2e})")

    # 2. Keong 1990 photoaddition: 290 nm + 360 nm MPDs add, no interaction.
    e12 = float(melanogenic_from_broadband(30.0, 1.0))
    e1 = float(melanogenic_from_broadband(30.0, 0.0))
    e2 = float(melanogenic_from_broadband(0.0, 1.0))
    check("Keong-1990 photoaddition (no sqrt interaction)",
          abs(e12 - (e1 + e2)) < 1e-12,
          f"E(UVA+UVB)={e12:.6f} == E(UVA)+E(UVB)={e1+e2:.6f}")

    # 3. Erythema and melanogenesis are different endpoints (not interchangeable).
    # Normalized to unity at 290 nm, the spectra CROSS: erythema falls faster
    # through the UVA, so UVA is relatively more melanogenic than
    # erythemogenic per joule (why UVA tans with less burn).
    e_ery_300 = float(effectiveness_at(ery, np.array([300.0]))[0])
    e_mel_300 = float(effectiveness_at(mel, np.array([300.0]))[0])
    e_ery_340 = float(effectiveness_at(ery, np.array([340.0]))[0])
    e_mel_340 = float(effectiveness_at(mel, np.array([340.0]))[0])
    check("erythema/melanogenesis endpoint crossing (UVB vs UVA)",
          e_ery_300 / e_mel_300 > 1.0 and e_mel_340 / e_ery_340 > 1.0,
          f"S_ery(300)/S_mel(300)={e_ery_300/e_mel_300:.2f} vs "
          f"S_mel(340)/S_ery(340)={e_mel_340/e_ery_340:.2f}")

    # 4. IPD is UVA-dominant and silent in UVB; melanogenesis is the reverse.
    ipd_340 = float(effectiveness_at(ipd, np.array([340.0]))[0])
    ipd_300 = float(effectiveness_at(ipd, np.array([300.0]))[0])
    check("IPD UVA-dominant, UVB-silent",
          ipd_340 == 1.0 and ipd_300 < 0.05,
          f"IPD(340)={ipd_340:.2f} peak, IPD(300)={ipd_300:.3f}")
    mel_340 = float(effectiveness_at(mel, np.array([340.0]))[0])
    check("IPD vs melanogenesis separated at 340 nm",
          ipd_340 / mel_340 > 100,
          f"IPD(340)={ipd_340:.2f} vs S_mel(340)={mel_340:.2e} "
          f"(existing-pigment darkening vs new melanogenesis)")

    # 5. SED and TanDose diverge by construction on the same hour.
    e_mel_hour = float(melanogenic_from_broadband(35.0, 1.0))
    sed_hour = float(erythemal_irradiance_from_uvi(6.0) * 3600 / 100)
    tandose_hour = e_mel_hour * 3600
    check("SED/TanDose non-interchangeability (UVI6/UVA35 hour)",
          abs(sed_hour - 5.4) < 1e-9 and tandose_hour > 1000,
          f"SED={sed_hour:.2f} (erythemal) vs "
          f"TanDose={tandose_hour:.0f} J/m^2 mel (delayed-melanogenesis)")

    # 6. Wolber 2008 framing: SSR-vs-isolated-band synergy belongs downstream.
    LINES.append("- [INFO] Wolber-2008 SSR synergy: physical exposure stays "
                 "wavelength-additive (check 2); any super-additive pigment "
                 "response belongs in TanResponseModel, which is intentionally "
                 "unshipped until a fitted model beats cumulative dose.")
    # 7. MITF timer prior: mechanistic only, no hard-coded optimum.
    LINES.append("- [INFO] MITF-timer (PMID 30401431): mechanistic prior only; "
                 "no interval optimum is hard-coded anywhere in the pipeline.")

    out = Path("docs/validation/literature_sanity.md")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("\n".join(LINES) + "\n", encoding="utf-8")
    print("\n".join(LINES))
    print(f"\nwrote {out}")


if __name__ == "__main__":
    main()
