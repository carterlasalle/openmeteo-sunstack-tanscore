# §7.2 band-weight diagnostics (dynamic vs fixed-band proxy)

Corpus: `data/research/spectral_corpus` · qualified rows: **1795** (E_DP >= 0.01 W/m²).

Fixed-band Tier-C weights: `w_uvb=0.56232`, `w_uva=0.0027738`.

`w_band = sum(E_lambda*S)/sum(E_lambda)` over each true spectrum; `proxy_rel_err` is the Tier-C fixed-band E_DP relative error on the same row.

## Overall

| metric | median | p05 | p95 |
|---|---|---|---|
| w_uvb | 0.14028 | 0.07545 | 0.21110 |
| w_uva | 0.0018200 | 0.0014065 | 0.0020158 |
| proxy_rel_err | +2.0401 | +1.4162 | +2.3247 |

The fixed-band proxy is biased by a median **+204.0%** with a p05-p95 span of +141.6% to +232.5% — the band-shape error is NOT secondary.

## Stratum: `sza_deg`

| bin | n | w_uvb med | w_uva med | proxy rel-err med | p95 | abs med |
|---|---|---|---|---|---|---|
| 0-40 | 908 | 0.1636 | 0.001898 | +1.851 | +2.184 | 1.851 |
| 40-60 | 453 | 0.1272 | 0.001760 | +2.199 | +2.336 | 2.199 |
| 60-75 | 338 | 0.0871 | 0.001547 | +2.253 | +2.338 | 2.253 |
| 75-90 | 96 | 0.0806 | 0.001406 | +2.060 | +2.234 | 2.060 |

## Stratum: `ozone_du`

| bin | n | w_uvb med | w_uva med | proxy rel-err med | p95 | abs med |
|---|---|---|---|---|---|---|
| 0-280 | 573 | 0.1758 | 0.001904 | +1.732 | +2.293 | 1.732 |
| 280-340 | 430 | 0.1530 | 0.001848 | +1.955 | +2.324 | 1.955 |
| 340-400 | 432 | 0.1320 | 0.001794 | +2.098 | +2.330 | 2.098 |
| 400-500 | 360 | 0.1156 | 0.001723 | +2.175 | +2.335 | 2.175 |

## Stratum: `aod340`

| bin | n | w_uvb med | w_uva med | proxy rel-err med | p95 | abs med |
|---|---|---|---|---|---|---|
| 0-0.15 | 927 | 0.1408 | 0.001831 | +2.029 | +2.328 | 2.029 |
| 0.15-0.35 | 395 | 0.1401 | 0.001827 | +2.041 | +2.318 | 2.041 |
| 0.35-0.6 | 242 | 0.1410 | 0.001810 | +2.049 | +2.323 | 2.049 |
| 0.6-1.01 | 231 | 0.1389 | 0.001794 | +2.048 | +2.327 | 2.048 |

## Stratum: `ssa340`

| bin | n | w_uvb med | w_uva med | proxy rel-err med | p95 | abs med |
|---|---|---|---|---|---|---|
| 0.84-0.9 | 596 | 0.1415 | 0.001819 | +2.026 | +2.323 | 2.026 |
| 0.9-0.94 | 486 | 0.1425 | 0.001818 | +2.026 | +2.329 | 2.026 |
| 0.94-1.001 | 713 | 0.1392 | 0.001824 | +2.057 | +2.322 | 2.057 |

## Stratum: `total_cloud_cover`

| bin | n | w_uvb med | w_uva med | proxy rel-err med | p95 | abs med |
|---|---|---|---|---|---|---|
| 0-0.05 | 94 | 0.1494 | 0.001847 | +1.958 | +2.319 | 1.958 |
| 0.05-0.35 | 542 | 0.1397 | 0.001819 | +2.047 | +2.327 | 2.047 |
| 0.35-0.75 | 715 | 0.1425 | 0.001824 | +2.026 | +2.325 | 2.026 |
| 0.75-1.001 | 444 | 0.1371 | 0.001814 | +2.061 | +2.323 | 2.061 |

## Stratum: `altitude_m`

| bin | n | w_uvb med | w_uva med | proxy rel-err med | p95 | abs med |
|---|---|---|---|---|---|---|
| 0-500 | 219 | 0.1422 | 0.001805 | +2.017 | +2.331 | 2.017 |
| 500-1500 | 462 | 0.1410 | 0.001819 | +2.046 | +2.323 | 2.046 |
| 1500-2500 | 448 | 0.1398 | 0.001813 | +2.039 | +2.322 | 2.039 |
| 2500-4001 | 666 | 0.1394 | 0.001835 | +2.043 | +2.327 | 2.043 |

## Stratum: `albedo`

| bin | n | w_uvb med | w_uva med | proxy rel-err med | p95 | abs med |
|---|---|---|---|---|---|---|
| 0-0.15 | 264 | 0.1423 | 0.001785 | +2.050 | +2.343 | 2.050 |
| 0.15-0.35 | 397 | 0.1395 | 0.001797 | +2.043 | +2.330 | 2.043 |
| 0.35-0.6 | 518 | 0.1420 | 0.001825 | +2.032 | +2.326 | 2.032 |
| 0.6-1.001 | 616 | 0.1394 | 0.001855 | +2.037 | +2.317 | 2.037 |

## Reading

- A single fixed `w_band` cannot hold across SZA/ozone/aerosol/cloud; the per-regime columns show how far it moves.
- This is why Tier-C is labelled a *proxy* and why a gate-passing Tier-B emulator is required before any validated-spectral claim.

