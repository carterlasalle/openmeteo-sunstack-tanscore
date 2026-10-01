# Action spectra

Resources live in `data/research/action_spectra/` (1 nm, 280-400 nm). Each CSV
has an adjacent `.meta.json` with source title, authors, year, DOI/PMID/CIE
identifier, endpoint, population, wavelengths, assessment time, normalization,
original units, digitization method, checksum, and limitations.

## Current resources

- `parrish_fda_3630.csv` (tier **provisional**): primary delayed-pigmentation
  basis, version `parrish-fda-3630-v1`. FDA Form 3630 (09/26) Appendix B
  1-nm transcription of Parrish JA, Jaenicke KF, Anderson RR. 1982
  (PMID 7122713), normalized 1.0 at 296 nm. Endpoint: delayed tanning/new
  melanogenesis (~7-day visual grading, Type II skin). Replaces the retired
  `parrish_delayed_melanogenesis.csv` approximation (which assumed 280-289 nm
  unity; measured table: 280 nm = 0.314). Log-space interpolation only where
  resampling is unavoidable; the 1-nm table needs none on the production grid.
- `parrish_delayed_melanogenesis.csv` (tier **retired**): superseded
  approximation kept for history only; never loaded in production.
- `cie_pigmentation_reference.csv` (tier **provisional PLACEHOLDER**): exact
  CIE 103/3 ("Reference Action Spectra for Ultraviolet Induced Erythema and
  Pigmentation of Different Human Skin Types", 1993) table not legally or
  technically obtained. The file holds the provisional shape as an explicit
  placeholder. **Do not cite as CIE data.** Strict canonical mode
  (`SUNSTACK_REQUIRE_CANONICAL_SPECTRUM=1`) refuses to run on it.
- `cie_erythema_reference.csv` (tier **canonical**): closed-form CIE erythema
  equation (McKinlay & Diffey; CIE S 007/E-1998). Erythema endpoint only;
  never a melanogenesis weighting.
- `ipd_action_spectrum.csv` (tier **provisional**): broad 320-400 nm IPD/PPD
  shape peaking near 340 nm (Gaussian sigma 28 nm with a short-wave logistic
  cutoff below ~312 nm; existing-pigment oxidation/redistribution).
  Optional second channel only; never merged into TanScore.

## Method rules

- Interpolation in **log-space** (log10 effectiveness) for melanogenesis and
  erythema spectra; linear interpolation is invalid across orders of magnitude.
- Validation fails loudly on missing resources, domain gaps (< 280-400 nm),
  negative effectiveness, non-monotonic/duplicated wavelengths, checksum
  mismatch, and unphysical spectral irradiance.
- Rebuild checksums with `python3 scripts/build_action_spectra.py`; never
  hand-edit CSVs.
