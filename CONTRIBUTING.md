# Contributing to SunStack TanScore

SunStack is a strict, evidence-first forecasting stack. Small changes can
silently shift published scores, so contributions are welcome when they
preserve the invariants and include evidence for the behavior they change.

Read [AGENTS.md](AGENTS.md) for repository engineering rules and
[README.md](README.md#safety-model) for the strictness model.

## Development setup

### Prerequisites

- Git
- Python `3.13`
- [uv](https://docs.astral.sh/uv/)

```bash
git clone https://github.com/carterlasalle/openmeteo-sunstack-tanscore.git
cd openmeteo-sunstack-tanscore
uv sync
```

Confirm the baseline before editing:

```bash
uv run pytest tests/ -q
uv run ruff check src tests
```

`uv run sunstack doctor --probe` makes **real live Open-Meteo requests** and
prints per-feed latency and exact failures. Calibration (`uv run sunstack
setup`) downloads decades of history plus CAMS data — run it once, not per
change; do not commit the downloaded data except through the scheduled
pipeline's paths.

## Branch and commit workflow

1. Start from current `main`.
2. Create a focused branch such as `feat/disagreement-flag` or `fix/hrrr-bounds`.
3. Keep each commit coherent and independently reviewable.
4. Use a short imperative subject (e.g. `Flag UV/broadband input disagreement visibly`).
5. Push the branch and open a pull request. Do not push directly to `main`.

## Making a change

### Behavior changes and bug fixes

Write a failing test for the observable contract first. Then make the
smallest complete fix and show the test passing. Existing test layers live in
`tests/test_core.py`: scoring invariants (global-vs-local, monotonicity),
30-minute interpolation bounds, night-zero behavior, CAMS fallback, schedule
wiring, export shape; `tests/test_photobiology.py`: E_mel/TanDose/SED math,
action spectra, skin-plane physics, validator-adjacent proofs;
`tests/test_v4_scoring.py`: v4 scoring audit trail, dose flags, contracts,
serving; `tests/test_cams_time_decode.py`: CAMS time decoding.

Do not add tests that pin incidental formatting, duplicate type checking, or
assert implementation wiring. Configuration such as the scheduled workflow is
an observable contract and may be tested structurally.

### Scoring changes

- Absolute TanScore stays globally anchored; local stays a percentile.
  Never mix the two.
- Confidence and feasibility change trust/usability, never physics values.
- New heuristics need stated priors and dated evidence in
  `docs/RESEARCH_NOTES.md`, not fitted constants without provenance.
- `uv run sunstack run` must still fail loudly (exit 1) on missing critical
  sources — never silence a failure to make a run green.

### Photobiology refresh chain

Touching action spectra, the spectral layer, dose integration, or the global
reference requires the full refresh, in order (each step is pinned in-suite,
so a skipped step breaks loudly rather than drifting silently):

1. `python3 scripts/build_action_spectra.py --out /tmp/spec` — output must
   reproduce the committed `data/research/action_spectra/` files
   byte-identically (spectra provenance test).
2. `python3 scripts/rebuild_v4_references.py` (no `--adopt`) — committed
   `local_reference.*` files must reproduce byte-identically; adopting a new
   reference requires `--adopt-empirical-p999 --new-version` (never silent).
3. `python3 scripts/rescore_latest_v4.py` — the SystemExit validation gate
   must pass on real run tables.
4. `python3 scripts/validate_external.py` (holdout skill floors live
   in-suite) and `python3 scripts/check_literature.py` (6 gates in-suite).
5. `uv run pytest tests/ -q` and `uv run ruff check src tests`.

### Docs and thresholds

Keep task-oriented information in `README.md`, dated evidence in
`docs/RESEARCH_NOTES.md`. Threshold changes go through `.env.example` /
environment variables, not hardcoded constants beside the old ones.

## Verification matrix

Run the narrowest relevant check while iterating. Before requesting review:

```bash
uv run pytest tests/ -q
uv run ruff check src tests
```

## Pull request checklist

A review-ready pull request should state:

- the problem and requirement being satisfied;
- the design decision and relevant invariants;
- files and public contracts changed;
- the failing test or reproduction observed before the fix, when applicable;
- exact verification commands and results;
- rollout implications (does the next scheduled run publish different data?);
- documentation updated;
- anything intentionally not verified.

Before requesting review:

- [ ] The diff contains only changes needed for the stated goal.
- [ ] Exported symbols and callers are updated together.
- [ ] No plaintext secret, credential, or sensitive provider response is present.
- [ ] Required tests fail for a plausible regression and pass after the change.
- [ ] `pytest` and `ruff` pass.
- [ ] Scheduled-run output implications are stated (new columns, changed scores, export shape).
- [ ] Destructive or external actions were not performed without explicit authorization.

## Security and operational issues

Do not disclose credentials, token values, or sensitive incident data in a
public issue or pull request. Revoke exposed credentials immediately. For a
security-sensitive change, document the trust boundary and rollback plan in
the pull request. See [SECURITY.md](SECURITY.md).
