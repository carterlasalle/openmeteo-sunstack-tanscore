"""Unique-column frame accessors shared across the pipeline (v5).

`calibrate.scol/num` are the canonical helpers; this module exists only to
break the `calibrate <-> temporal/spectral` import cycles flagged by
`reportImportCycles`. It has no other dependencies inside the package.
"""

from __future__ import annotations

import math
from typing import cast

import pandas as pd


def scol(frame: pd.DataFrame, name: str) -> pd.Series:
    """Unique-column access with a verified Series contract.

    Plain ``frame[name]`` silently returns a DataFrame on duplicated labels,
    which then fails far from the cause. This fails loud at the access instead.

    The value is deliberately widened to ``object`` before the check: the
    indexing stub promises a Series, but the runtime really can hand back a
    DataFrame, so the guard has to stay reachable for both the checker and the
    duplicated-label case.
    """
    out = cast(object, frame[name])
    if not isinstance(out, pd.Series):
        raise TypeError(f"expected unique Series column {name!r}, got {type(out).__name__}")
    return cast("pd.Series", out)


def num(frame: pd.DataFrame, name: str, default: float = math.nan) -> pd.Series[float]:
    """Numeric-column read with a quiet default (missing → NaN column).

    The return dtype is pinned to float so callers keep real types through
    ``fillna``/``clip``/arithmetic; a bare ``pd.Series`` would erase every
    downstream expression to ``Any``.
    """
    if name not in frame:
        return pd.Series(default, index=frame.index, dtype="float64")
    out = cast(object, pd.to_numeric(scol(frame, name), errors="coerce"))
    if not isinstance(out, pd.Series):
        raise TypeError(f"expected numeric Series for column {name!r}")
    return cast("pd.Series[float]", out)
