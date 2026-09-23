# Literature sanity checks (aggregate observations only)

Studies encoded: 8. No individual-subject data fabricated.

- [PASS] Parrish-1982 UVB>>UVA delayed effectiveness: S(290-295)/S(360-365) = 1247x (0.866 vs 6.94e-04)
- [PASS] Keong-1990 photoaddition (no sqrt interaction): E(UVA+UVB)=0.726138 == E(UVA)+E(UVB)=0.726138
- [PASS] erythema/melanogenesis endpoint crossing (UVB vs UVA): S_ery(300)/S_mel(300)=1.44 vs S_mel(340)/S_ery(340)=3.11
- [PASS] IPD UVA-dominant, UVB-silent: IPD(340)=1.00 peak, IPD(300)=0.003
- [PASS] IPD vs melanogenesis separated at 340 nm: IPD(340)=1.00 vs S_mel(340)=3.00e-03 (existing-pigment darkening vs new melanogenesis)
- [PASS] SED/TanDose non-interchangeability (UVI6/UVA35 hour): SED=5.40 (erythemal) vs TanDose=2706 J/m^2 mel (delayed-melanogenesis)
- [INFO] Wolber-2008 SSR synergy: physical exposure stays wavelength-additive (check 2); any super-additive pigment response belongs in TanResponseModel, which is intentionally unshipped until a fitted model beats cumulative dose.
- [INFO] MITF-timer (PMID 30401431): mechanistic prior only; no interval optimum is hard-coded anywhere in the pipeline.
