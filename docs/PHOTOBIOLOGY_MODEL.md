# Photobiology model (v5 delayed-pigmentation endpoint)

Production TanScore is normalized delayed-pigmentation-weighted irradiance and
TanDose is its time integral. This is an action-spectrum-weighted exposure
endpoint, not measured melanin synthesis or a melanin-color prediction.
No hand weights. No square-root interaction.

## Core equations

The canonical exposure base is environmental horizontal:

```text
E_DP,h(t) = integral E_lambda,h(t,lambda) S_DP(lambda) dlambda
```

The optional skin-plane counterpart is built from direct, diffuse, and local
reflected components under the selected surface/geometry context; it never
overwrites the horizontal environmental quantity.

```text
score = clip(100 * E_DP,h / E_mel_global_reference, 0, 100)
```

`parrish-fda-3630-v1` identifies the delayed-pigmentation action spectrum.
`global-mel-ref-v1-provisional`, E_mel = 1.6 W/m^2, remains the fixed reference;
recalibration creates a new score model version rather than silently changing it.

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

## Tiers, support, and SED hierarchy

- Tier A is reserved reference reconstruction. Tier B is
  `tierB-libradtran-emulator-v1` and is usable only after its version,
  training-manifest SHA, libRadtran provenance, parameter ranges, and non-empty
  held-out validation metrics pass the manifest gate.
- Tier C is the explicitly labeled degraded broadband proxy
  `tierC-broadband-proxy-v2`; `--allow-degraded` may permit it, but it is never
  a silent substitute for Tier B. Strict mode fails loudly when its required
  spectral tier/data are unavailable.
- `interval-contract-v1` distinguishes interval-mean radiation from point
  samples: means integrate over declared support; point samples integrate over
  actual timestamps.
- `erythemal_irradiance_wm2 = uvi_consensus / 40` is derived after final UVI
  consensus. SED integrates that final-consensus erythemal field, never raw or
  pre-fusion UVI.
