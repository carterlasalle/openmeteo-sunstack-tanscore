"""Minimal local stubs for pvlib (upstream ships none).

Only the surface SunStack uses is declared. Without this, `pvlib.location` and
`pvlib.irradiance` resolve to Unknown and erase the types of every solar-
geometry value derived from them.
"""

from . import irradiance as irradiance
from . import location as location

__version__: str
