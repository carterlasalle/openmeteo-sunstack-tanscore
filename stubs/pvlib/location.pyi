"""Local stubs for the pvlib.location surface SunStack uses."""

import pandas as pd

class Location:
    latitude: float
    longitude: float
    tz: str
    altitude: float
    name: str | None
    def __init__(
        self,
        latitude: float,
        longitude: float,
        tz: str = ...,
        altitude: float = ...,
        name: str | None = ...,
    ) -> None: ...
    def get_solarposition(
        self,
        times: pd.DatetimeIndex,
        pressure: float | None = ...,
        temperature: float = ...,
        **kwargs: object,
    ) -> pd.DataFrame: ...
    def get_clearsky(
        self,
        times: pd.DatetimeIndex,
        model: str = ...,
        **kwargs: object,
    ) -> pd.DataFrame: ...
    def get_airmass(
        self,
        times: pd.DatetimeIndex,
        solar_position: pd.DataFrame | None = ...,
        model: str = ...,
    ) -> pd.DataFrame: ...
