# SunStack v5 baseline (2026-09-30)

Recorded before any v5 contract work. Environment: `uv sync --locked`, Python 3.13 via uv.

## Test suite

`uv run pytest tests/ -q`: **1 failed, 207 passed, 2 skipped** (15 warnings).

- Sole failure: `tests/test_v4_scoring.py::test_canonical_env_parsing_is_explicit`
  - Cause: test shells out to system `python3` (macOS Xcode Python 3.9) with a
    bare `PATH=/usr/bin:/bin`, so `from sunstack import config` crashes on
    `datetime.UTC` (3.9 has no `datetime.UTC`) and stdout is empty.
  - Pre-existing environment/istanbul issue, not a code regression. Under `uv run`
    the same import works. Left untouched pending v5 test overhaul.

## Lint

`uv run ruff check src tests scripts`: **49 errors** (15 auto-fixable):

- 26× `ISC004` unparenthesized implicit string concatenation in collection
- 11× `RUF100` unused `noqa: E402`
- 5× `BLE001` blind `except Exception`
- 2× `I001` unsorted import blocks
- 1× `F841` unused `cols` (`scripts/build_spectral_corpus.py:101`)
- 1× `F401` unused `numpy` import
- 1× `PLW1510` `subprocess.run` without `check`
- 1× `RUF046` redundant `int()` cast
- 1× `DTZ011` `datetime.date.today()` used

## Types

`uv run basedpyright`: **1082 errors, 4426 warnings** — overwhelmingly
`reportMissingParameterType`/unknown-type warnings in untyped code plus one
`reportMissingImports` (`issue_location_to_pr` script import). No typed baseline;
v5 work must not increase error count on files it touches.

## Runtime

- `uv run sunstack doctor`: OK (ADS/CAMS credentials, UVA/UVB model, climatology,
  skill table, action spectra, `global-mel-ref-v1-provisional` 1.6 W/m²).
- `uv run sunstack debug`: OK, latest run `20260929_195749` (south-bend, strict).
- `scc drift`: no drift findings.
- No libRadtran/`uvspec` binary on PATH (Tier-B corpus builder runs in
  design-only mode).
- `pvlib 0.15.2`, `hypothesis`, `scipy 1.18.1`, `sklearn 1.9.1` all importable
  under `uv run python`.
- FDA Form 3630 PDF reachable (HTTP 200, `FDA-3630_Stat_Sec_Ext_09-23-2026.pdf`);
  WOUDC data-access page reachable (HTTP 200).

## Pre-existing semantic notes (v5 contract §27, confirmed present)

Provisional Parrish curve with 280–289 unity assumption; Tier-C proxy labeled
`tierC-broadband-v1`; `tierB-clear-sky-v1` fallback name; OM×2 vote median fusion;
sunniness-coupled confidence; `uvi_consensus_sources` counts finite votes;
`THUNDER_CODES={95,96,99}` (no 97); lone-sample dose returns numeric 0;
trapezoid-only dose engine; no temporal-support registry; no surface module.
