# WOUDC Brewer spectral validation (independent, §8.5)

Scans: **1878** from 2 station(s), window 2023-01-01..2024-12-31.
Stations: Toronto, Uccle.

Each scan is a measured 280-400 nm Brewer spectrum (WOUDC Spectral_1.0, QC flags preserved in the source files). UVA/UVB/erythemal/E_DP are integrated from the measured spectrum against the shipped action spectra; `proxy_rel_err` is the Tier-C fixed-band proxy error on the same row.

## Overall

| n | median rel-err | median abs rel-err | p95 abs rel-err |
|---|---|---|---|
| 1878 | +2.193 | 2.193 | 2.698 |

Measured E_DP,h median **0.0312 W/m²** (p05 0.0008, p95 0.3301).

## Sky split (IntCIE median 13.267)

| sky | n | median rel-err | median abs rel-err | p95 abs rel-err |
|---|---|---|---|---|
| summer-clear | 939 | +2.290 | 2.290 | 2.702 |
| cloudy | 939 | +2.071 | 2.071 | 2.692 |

## SZA bins

| bin | n | median rel-err | median abs rel-err | p95 abs rel-err |
|---|---|---|---|---|
| 0-30 | 54 | +1.980 | 1.980 | 2.227 |
| 30-45 | 241 | +2.112 | 2.112 | 2.485 |
| 45-60 | 429 | +2.307 | 2.307 | 2.670 |
| 60-70 | 382 | +2.613 | 2.613 | 2.722 |
| 70-80 | 507 | +2.291 | 2.291 | 2.672 |
| 80-90 | 265 | +1.552 | 1.552 | 1.974 |

## Per station (station-held-out analogue: each station's own scans)

| station | n | median rel-err | median abs rel-err | p95 abs rel-err |
|---|---|---|---|---|
| Toronto | 943 | +2.149 | 2.149 | 2.715 |
| Uccle | 935 | +2.250 | 2.250 | 2.649 |

## Seasonal subsets

| season | n | median rel-err | median abs rel-err | p95 abs rel-err |
|---|---|---|---|---|
| DJF | 294 | +2.082 | 2.082 | 2.723 |
| MAM | 202 | +2.090 | 2.090 | 2.704 |
| JJA | 140 | +2.185 | 2.185 | 2.681 |
| SON | 307 | +2.375 | 2.375 | 2.710 |

## Measurement context

- Brewer MKII/MKIII spectral scans; WOUDC QC flags live in the source files and are not re-derived here.
- Instrument uncertainty is of order several percent in UVB and grows at high SZA; these thresholds are product release gates, not claims that the instruments are exact.

## Release targets (§8.5)

| target | value | verdict |
|---|---|---|
| median abs rel-err, all qualified | <= 0.15 | FAIL |
| median abs rel-err, clear-sky | <= 0.10 | FAIL |

**Note.** This scores the Tier-C fixed-band proxy, the only spectral model available offline; it is the same proxy the contract requires to stay labelled degraded. A gate-passing Tier-B emulator replaces this comparison when it exists.

