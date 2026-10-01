# Spectral model

`src/sunstack/spectral.py` reconstructs the environmental-horizontal spectrum
over ~280-400 nm and attaches optional skin-plane direct/diffuse/local-reflected
context. `src/sunstack/photobiology.py` convolves each exposure basis with the
action spectrum; `src/sunstack/doses.py` integrates it; `tan_response.py` is
the interface-only downstream response model. Neither spectrum is a
melanin-color prediction.

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
- **B** validated spectral emulator, `tierB-libradtran-emulator-v1`. Its
  manifest must contain `spectral_emulator_version`,
  `spectral_training_manifest_sha256`, `libradtran_version`, `parameter_ranges`,
  and non-empty held-out `validation_metrics`; those gates pass before Tier-B
  output is trusted.
- **C** explicitly degraded broadband proxy, `tierC-broadband-proxy-v2`. It
  distributes predicted UVA/UVB uniformly within 315-400 / 280-315 nm and
  convolves with the action spectrum; it is wavelength-additive, but it is not
  a validated spectral emulator.
- **D** unavailable (strict mode fails).

Current status: no gate-passing Tier-B emulator is wired (`SUNSTACK_TIERB_MANIFEST`
unset, no uvspec binary/corpus in this environment), so strict runs publish
Tier-C by default with its tier on every output. A tier A/B claim without a
validated manifest fails loudly instead of scoring silently as Tier C.
`--allow-degraded` additionally permits pre-manifest/sklearn-drift bundles.
The legacy 55/30/15 formula is never a silent fallback.

## Temporal and erythemal hierarchy

`interval-contract-v1` distinguishes interval means from point samples: an
interval mean is integrated over its declared support, while point samples use
actual timestamps. Final UVI consensus precedes
`erythemal_irradiance_wm2 = uvi_consensus / 40`; SED integrates that final
consensus-derived erythemal field, never a raw provider or pre-fusion value.

## Skin-plane exposure

`SUNSTACK_SKIN_TILT_DEG` / `SUNSTACK_SKIN_AZIMUTH_DEG` configure the optional
plane. Direct uses incidence angle; diffuse uses isotropic sky view; local
reflected context uses the selected local surface profile. CAMS
`forecast_albedo` remains a regional RT input and never becomes local surface
reflectance. Environmental-horizontal fields remain immutable; the plane is
additional context.

## Known Tier-C limitation: uniform intra-band shape

Tier C distributes predicted broadband UVA/UVB uniformly within 315–400 /
280–315 nm. Real solar spectra do not look like that — ozone removes almost
all sub-300 nm photons, concentrating UVB energy toward 305–315 nm where
melanogenesis effectiveness differs steeply from the band mean. This shape
error is real but, on current evidence, SECONDARY: Tier C run on measured
POWER broadband (no ML, no forecast) yields an E_mel/E_ery ratio flat at
~7.4 across SZA 0–80° (n≈30k), and the ML mapping itself holds ≤8% bias to
SZA 80 on POWER inputs. The live-run ratio fall (5.7 → 1.9) is instead
dominated by the denominator: archived Open-Meteo UVI runs +51% above NASA
POWER truth at SZA 50–65° and +175% at 65–80° (n≈5k/2.7k), inflating E_ery
exactly where the ratio falls — corroborated by the independent BSRN finding
of +29% NWP broadband brightness. POWER truth is itself modeled, so this
attribution is corroborating rather than definitive; Tier B (libRadtran-
trained spectral shape, held-out validation) must reproduce the SZA-ratio
curve against spectra, not just broadband.

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
