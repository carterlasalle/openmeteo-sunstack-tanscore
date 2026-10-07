"""Stub for the single sklearn estimator SunStack trains (UVA/UVB bundle)."""

from typing import Self

import numpy as np
import pandas as pd

class HistGradientBoostingRegressor:
    def __init__(
        self,
        *,
        loss: str = ...,
        learning_rate: float = ...,
        max_iter: int = ...,
        max_leaf_nodes: int = ...,
        min_samples_leaf: int = ...,
        l2_regularization: float = ...,
        random_state: int | None = ...,
        **kwargs: object,
    ) -> None: ...
    def fit(
        self,
        X: pd.DataFrame,
        y: pd.Series,
        sample_weight: object = ...,
        *,
        X_val: pd.DataFrame | None = ...,
        y_val: pd.Series | None = ...,
        sample_weight_val: object = ...,
    ) -> Self: ...
    def predict(self, X: pd.DataFrame) -> np.ndarray: ...