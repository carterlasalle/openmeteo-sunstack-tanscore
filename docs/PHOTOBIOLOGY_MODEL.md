# Photobiology model (v4, action-spectrum-v1)

Production TanScore is a normalized instantaneous melanogenic-effective
irradiance. TanDose is its time integral. No hand weights. No square-root
interaction.

## Core equations

Spectral surface irradiance on the configured skin plane:

```text
E_lambda(t, lambda)  [W m^-2 nm^-1], 280-400 nm at ~1 nm
```

Melanogenic effective irradiance (delayed-melanogenesis endpoint):

```text
E_mel(t) = integral E_lambda(t,lambda) S_mel(lambda) dlambda
```

Absolute TanScore:

```text
score = clip(100 * E_mel / E_mel_global_reference, 0, 100)
```

Reference: `global-mel-ref-v1-provisional`, E_mel = 1.6 W/m^2 (99.9th
percentile of the provisional stratified natural-sun corpus). Recalibration
creates a new score model version; the reference is never silently changed.

## Why the interaction term was removed

Keong et al. 1990 (PMID 2103131) exposed human subjects at 290 nm and
360 nm. Fractional UVA and UVB minimal-pigmentation doses combined by
**photoaddition**, including with a three-hour interval. The base
irradiance/dose model is therefore wavelength-additive:

```text
sum(E_lambda * effectiveness_lambda)
```

not `sqrt(UVA * UVB)` or any manually imposed interaction.

Wolber et al. 2008 found solar-simulated radiation produced more new pigment
than isolated UVB/UVA and suggested synergy. That is evidence for a possible
nonlinear **downstream biological-response** model, not for modifying the
physical action-spectrum convolution. Physical exposure (`photobiology.py`,
`spectral.py`) and downstream response (`tan_response.py`) remain separate;
adaptation/saturation/recovery live exclusively in TanResponse and never
rescale photons inside TanDose.

## Endpoints (not interchangeable)

- SED = erythema-weighted cumulative exposure (independent channel).
- TanDose = delayed-melanogenesis-weighted cumulative exposure (model-defined).
- MMD = subject/source/endpoint-specific response threshold (measured, not modeled here).
- UVA/UVB dose = physical broadband energy (diagnostic, not biological).
- PigmentDarkeningDose = separate UVA-dominant existing-pigment endpoint.
- TanResponse = modeled final biological response to exposure history (interface-only).

## Tiers and failure modes

- Spectral tiers A (reference) / B (validated emulator) / C (calibrated
  broadband approximation, current production) / D (unavailable).
- Strict mode fails loudly on missing spectra, domain gaps, negative
  effectiveness, non-monotonic wavelengths, unphysical irradiance, and (when
  `SUNSTACK_REQUIRE_CANONICAL_SPECTRUM=1`) provisional-tier spectra.
- `--allow-degraded` may permit tier C with every output exposing the tier;
  it never silently falls back to the legacy 55/30/15 formula.
- `sunstack debug --photobiology` prints model version, spectrum checksums,
  backend/tier, global reference, current E_mel, both UVI sources,
  disagreement, TanScore, interval TanDose, SED, UVA/UVB doses, and fallbacks.
