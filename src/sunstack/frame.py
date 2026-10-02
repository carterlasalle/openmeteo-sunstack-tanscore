"""Unique-column frame accessors shared across the pipeline (v5).

`calibrate.scol/num` are the canonical helpers; this module exists only to
break the `calibrate <-> temporal/spectral` import cycles flagged by
`reportImportCycles`. It has no other dependencies inside the package.
"""

from __future__ import annotations

import pandas as pd


def scol(frame: pd.DataFrame, name: str) -> pd.Series:
    """Unique-column access with a verified Series contract.

    Plain ``frame[name]`` types as Series | DataFrame and silently returns a
    DataFrame on duplicated labels, which then fails far from the cause.
    This fails loud at the access instead.
    """
    out = frame[name]
    if not isinstance(out, pd.Series):
        raise TypeError(f"expected unique Series column {name!r}, got {type(out).__name__}")
    return out


def num(frame: pd.DataFrame, name: str, default: float = float("nan")) -> pd.Series:
    """Numeric-column read with a quiet default (missing → NaN column)."""
    if name not in frame:
        return pd.Series(default, index=frame.index, dtype="float64")
    out = pd.to_numeric(scol(frame, name), errors="coerce")
    if not isinstance(out, pd.Series):
        raise TypeError(f"expected numeric Series for column {name!r}")
    return out
