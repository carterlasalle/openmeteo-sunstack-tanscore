"""Property-based HTTP tests against the FastAPI surface (schemathesis).

Kept out of the default suite on purpose: this is advisory while the API has no
fuzzing history, and the analysis workflow runs it explicitly. By hand:

    uv run pytest tests/test_api_contract.py -q -p no:randomly

Four things here cost a CI cycle each to learn, recorded so they are not
rediscovered:

* `schemathesis run` has no `--app` option in 4.27, so the ASGI app goes through
  this pytest integration. The pytest plugin's own decorator is untyped and its
  injected fixture must be named exactly `case`; `from_asgi(...).as_strategy()`
  with `@given` is fully typed and needs no such convention.
* `create_app(root)` wants a *run* directory (`latest/tables/*`,
  `latest/summary.json`), not a page directory. Pointed at a page it answers 503
  "No SunStack run found" - correct behaviour for an empty install, but the whole
  budget would go on one documented error path. So the run directory is built
  from the committed payload: deterministic, offline, real request contracts.
* `POST /api/refresh` calls `run_live`, which fetches live data. Fuzzing it
  un-stubbed launches the pipeline (observed: a probe hung past 900s). The
  `run_live_fn` parameter is the seam `create_app` already exposes for this.
* `json.loads` is annotated `Any`, so the payload is narrowed once here rather
  than letting `Any` spread (the same cast `serving.py` uses).
"""

from __future__ import annotations

import json
import os
import pathlib
import tempfile
from typing import cast

import pandas as pd
import pytest
import schemathesis
from hypothesis import HealthCheck, given, settings
from hypothesis.strategies import SearchStrategy
from schemathesis.checks import CheckContext, CheckFunction
from schemathesis.core.transport import Response
from schemathesis.specs.openapi.adapter.parameters import OpenApiParameter
from schemathesis.specs.openapi.adapter.responses import OpenApiResponses
from schemathesis.specs.openapi.adapter.security import OpenApiSecurityParameters
from schemathesis.specs.openapi.checks import positive_data_acceptance
from schemathesis.specs.openapi.schemas import OpenApiSchema

from sunstack.opportunity import CLASSES_ORDER_MESSAGE
from sunstack.serving import PERSONAL_MMD_BASIS_MESSAGE
from sunstack.ui import create_app

# The exact instantiation of the generic the library builds internally
# (`schemathesis/specs/openapi/schemas.py` defines OpenApiCase this way behind
# TYPE_CHECKING); spelled out here because it is not importable at runtime.
OpenApiCase = schemathesis.Case[
    schemathesis.APIOperation[
        OpenApiParameter, OpenApiResponses, OpenApiSecurityParameters, OpenApiSchema
    ]
]

# `positive_data_acceptance` is exported as `CheckClass | CheckFunction`; it is a
# function, so one cast names that (a library typing gap, not a suppression).
_positive_acceptance_check = cast(CheckFunction, positive_data_acceptance)

# Rejections a schema-driven client cannot avoid, each a rule about the
# *relationship* between values that the OpenAPI format has no way to state -
# JSON Schema cannot compare two properties, and query parameters cannot depend
# on one another. Listed by name, so a 400 for any *other* reason still fails the
# check (a genuine schema over-promise is still caught).
_CROSS_FIELD_RULES = (CLASSES_ORDER_MESSAGE, PERSONAL_MMD_BASIS_MESSAGE)

FIXTURE = pathlib.Path(__file__).parent / "fixtures" / "rendered_site"
PAYLOAD = FIXTURE / "data.json"
EXAMPLES = int(os.environ.get("SUNSTACK_SCHEMATHESIS_EXAMPLES", "25"))

pytestmark = pytest.mark.skipif(
    not PAYLOAD.is_file(), reason="the rendered-site fixture is not present"
)


def _table_rows(payload: object, key: str) -> list[dict[str, object]]:
    """Narrow one payload table by validation, not by assertion."""
    if not isinstance(payload, dict):
        return []
    rows = cast("dict[str, object]", payload).get(key)
    if not isinstance(rows, list):
        return []
    return [
        cast("dict[str, object]", row)
        for row in cast("list[object]", rows)
        if isinstance(row, dict)
    ]


def _summary_object(payload: object) -> dict[str, object] | None:
    """Narrow the payload's summary object by validation, not by assertion."""
    if not isinstance(payload, dict):
        return None
    summary = cast("dict[str, object]", payload).get("summary")
    return cast("dict[str, object]", summary) if isinstance(summary, dict) else None


def _run_root() -> pathlib.Path:
    """The run directory the API reads, built from the committed payload."""
    root = pathlib.Path(tempfile.mkdtemp(prefix="sunstack-api-contract-"))
    tables = root / "latest" / "tables"
    tables.mkdir(parents=True)
    payload: object = cast(object, json.loads(PAYLOAD.read_text(encoding="utf-8")))

    # read_table() prefers parquet and falls back to CSV; CSV keeps this free of
    # a pyarrow round-trip and of any column-dtype guessing.
    for key, name in (("hourly", "tan_forecast_hourly"), ("half_hour", "tan_forecast_30min")):
        rows = _table_rows(payload, key)
        if rows:
            pd.DataFrame(rows).to_csv(tables / f"{name}.csv", index=False)

    summary = _summary_object(payload)
    if summary is not None:
        _ = (root / "latest" / "summary.json").write_text(
            json.dumps(summary), encoding="utf-8"
        )
    return root


_root = _run_root()


def _no_network_run_live(*args: object, **kwargs: object) -> pathlib.Path:
    """Stand in for the pipeline: /api/refresh must not fetch live data here."""
    _ = (args, kwargs)
    return _root / "latest"


_schema = schemathesis.openapi.from_asgi(
    "/openapi.json", create_app(_root, run_live_fn=_no_network_run_live)
)


def _positive_acceptance(
    ctx: CheckContext, response: Response, case: OpenApiCase
) -> bool | None:
    """`positive_data_acceptance`, tolerating the one documented inexpressible 400.

    The API rejects some schema-valid requests for rules about the relationship
    between values (`classes` ordering; `personal_mmd` requiring a basis), which
    the OpenAPI format cannot express. Only a 400 whose body names one of those
    documented rules is excused; any other 400 still fails the check.
    """
    if response.status_code == 400 and any(rule in response.text for rule in _CROSS_FIELD_RULES):
        return True
    return _positive_acceptance_check(ctx, response, case)


@settings(
    max_examples=EXAMPLES,
    deadline=None,
    # The app reads tables per request, so the first example is genuinely slow;
    # `too_slow` and `filter_too_much` are about search efficiency, not the
    # contract under test.
    suppress_health_check=[HealthCheck.too_slow, HealthCheck.filter_too_much],
)
@given(cast(SearchStrategy[OpenApiCase], _schema.as_strategy()))
def test_api_contract(case: OpenApiCase) -> None:
    """Every generated case must satisfy the schema it was generated from."""
    _ = case.call_and_validate(
        excluded_checks=[_positive_acceptance_check],
        additional_checks=[cast(CheckFunction, _positive_acceptance)],
    )
