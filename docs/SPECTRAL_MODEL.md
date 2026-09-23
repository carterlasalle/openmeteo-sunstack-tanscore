# Spectral model

`src/sunstack/spectral.py` produces skin-plane spectral irradiance over
~280-400 nm. `src/sunstack/photobiology.py` convolves it with the action
spectrum. `src/sunstack/doses.py` integrates; `src/sunstack/tan_response.py`
is the (interface-only) downstream response model.

## Reference backend and emulator plan

1. Generate a physically diverse libRadtran/uvspec training/LUT corpus
   offline (280-400 nm, high-resolution UV settings; realistic ozone, SZA,
   altitude, aerosol optics, albedo, cloud ranges).
2. Train or interpolate a fast runtime spectral emulator.
3. Validate emulator spectra and integrated products on held-out libRadtran
   cases; validate broadband UVA/UVB against NASA POWER history; validate
   erythemal output against CAMS/Open-Meteo UVI.
4. Persist the emulator with an explicit version and training-manifest
   checksum.

## Runtime tiers

- **A** direct/reference-quality reconstruction (reserved; never silently claimed).
- **B** validated spectral emulator (reserved; requires training manifest).
  The Tier-B manifest contract (`spectral.validate_tierB_manifest`) requires
  `spectral_emulator_version`, `spectral_training_manifest_sha256`,
  `libradtran_version`, `parameter_ranges`, and non-empty held-out
  `validation_metrics`, enforced before any Tier-B output is trusted.
  Generate the offline design with
  `python3 scripts/build_spectral_corpus.py --samples 2000`
  (runs uvspec per sample only when libRadtran is installed; otherwise the
  deterministic design + manifest is the artifact, never fake spectra).
- **C** calibrated broadband approximation (**current production**,
  `tierC-broadband-v1`): distributes predicted UVA/UVB uniformly within
  315-400 / 280-315 nm and convolves with S_mel. Band weights
  (w_uvb >> w_uva) derive from the spectrum itself, not hand tuning.
  Wavelength-additive by construction.
- **D** unavailable (strict mode fails).

Strict mode requires A/B once production-ready; `--allow-degraded` may permit
C with the tier exposed on every output. The legacy 55/30/15 formula is never
a silent fallback.

## Skin-plane exposure

Configured via `SUNSTACK_SKIN_TILT_DEG` / `SUNSTACK_SKIN_AZIMUTH_DEG`
(plus horizontal/lying-flat, standing, and user tilt/azimuth presets in the
UI roadmap). Direct uses incidence angle; diffuse uses isotropic sky-view
plus albedo ground bounce and is never discarded. Snow blocking stays an
outdoor-feasibility rule; snow albedo still raises the radiation quantities.

## Sub-hour broadband corrections (not scoring weights)

Two bounded broadband corrections touch UVB/UVI with a square-root factor,
and neither is the removed 55/30/15 interaction:

- Clear-sky-index geometry correction (`build_30min_forecast`): the HRRR/TOA
  broadband ratio rescales UVA linearly and UVB/UVI by its square root
  (bounded 0.7-1.3), because band-integrated UVB responds sublinearly to a
  broadband GHI change under shifting cloud.
- Native-HRRR override: same bounded pattern (0.45-1.55) against the
  kt-improved baseline.

Both operate on interpolated broadband inputs before the wavelength-additive
Tier-C convolution. Production Absolute TanScore itself contains no sqrt
term: `score = clip(100 * E_mel / E_ref)`.

## Inputs consumed (as available)

Solar zenith/elevation/azimuth, altitude, skin-plane tilt/azimuth, ozone,
AOD/absorption/SSA/asymmetry at 340/355/380/400 nm, water vapor, cloud
liquid/ice, total cloud, albedo, direct/diffuse broadband, CAMS UVBED
(dose rate) + clear-sky companion + downward UV, Open-Meteo UVI + clear-sky UVI.
