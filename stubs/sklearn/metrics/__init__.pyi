"""Stub for the sklearn metrics SunStack reports calibration quality with."""

import numpy as np
import pandas as pd

def mean_absolute_error(
    y_true: np.ndarray | pd.Series,
    y_pred: np.ndarray | pd.Series,
    *,
    sample_weight: object = ...,
    multioutput: str = ...,
) -> float: ...
def mean_squared_error(
    y_true: np.ndarray | pd.Series,
    y_pred: np.ndarray | pd.Series,
    *,
    sample_weight: object = ...,
    multioutput: str = ...,
) -> float: ...
def r2_score(
    y_true: np.ndarray | pd.Series,
    y_pred: np.ndarray | pd.Series,
    *,
    sample_weight: object = ...,
    multioutput: str = ...,
    force_finite: bool = ...,
) -> float: ...