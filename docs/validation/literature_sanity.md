# Literature-informed regression invariants (v5 photobiology)

Studies encoded: 8. No individual-subject data fabricated.

- [PASS] FDA-3630 anchor at 280 nm: S(280)=3.142850e-01 vs table 3.142850e-01
- [PASS] FDA-3630 anchor at 296 nm: S(296)=1.000000e+00 vs table 1.000000e+00
- [PASS] FDA-3630 anchor at 302 nm: S(302)=8.158920e-01 vs table 8.158920e-01
- [PASS] FDA-3630 anchor at 315 nm: S(315)=2.945930e-02 vs table 2.945930e-02
- [PASS] FDA-3630 anchor at 340 nm: S(340)=1.518410e-03 vs table 1.518410e-03
- [PASS] FDA-3630 anchor at 400 nm: S(400)=1.793360e-04 vs table 1.793360e-04
- [PASS] FDA-3630 normalization maximum at 296 nm: table maximum 1.0 sits at 296 nm (title says 'Normalized to 292 nm')
- [PASS] Parrish-1982 UVB>>UVA delayed effectiveness: S(290-295)/S(360-365) = 1146x (0.898 vs 7.84e-04)
- [PASS] Keong-1990 photoaddition (no sqrt interaction): E(UVA+UVB)=0.645535 == E(UVA)+E(UVB)=0.645535
- [PASS] erythema/melanogenesis endpoint separation (mel/ery rises into UVA): S_mel/S_ery = 300nm:1.49, 320nm:1.65, 340nm:1.57, 365nm:1.77
- [PASS] IPD UVA-dominant, UVB-silent: IPD(340)=1.00 peak, IPD(300)=0.003
- [PASS] IPD vs melanogenesis separated at 340 nm: IPD(340)=1.00 vs S_mel(340)=1.52e-03 (existing-pigment darkening vs new melanogenesis)
- [PASS] SED/TanDose non-interchangeability (UVI6/UVA35 hour): SED=5.40 (erythemal) vs TanDose=2374 J/m^2 mel (delayed-melanogenesis)
- [INFO] Wolber-2008 SSR synergy: physical exposure stays wavelength-additive (check 2); any super-additive pigment response belongs in TanResponseModel, which is intentionally unshipped until a fitted model beats cumulative dose.
- [INFO] MITF-timer (PMID 30401431): mechanistic prior only; no interval optimum is hard-coded anywhere in the pipeline.
