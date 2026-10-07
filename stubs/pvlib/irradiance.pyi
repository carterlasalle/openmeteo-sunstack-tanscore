"""Local stubs for the pvlib.irradiance surface SunStack uses."""

from typing import overload

import numpy as np
import pandas as pd

@overload
def get_extra_radiation(
    datetime_or_doy: float,
    solar_constant: float = ...,
    method: str = ...,
) -> float: ...
@overload
def get_extra_radiation(
    datetime_or_doy: pd.DatetimeIndex | pd.Series,
    solar_constant: float = ...,
    method: str = ...,
) -> pd.Series: ...
def clearness_index(
    ghi: pd.Series,
    solar_zenith: pd.Series,
    extraterrestrial_radiation: np.ndarray,
) -> pd.Series: ...
