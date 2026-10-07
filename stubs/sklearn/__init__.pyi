"""Minimal local stubs for scikit-learn (upstream ships none).

Only the surface SunStack uses is declared: the regressor it trains the
UVA/UVB bundle with, the metrics it reports, and the version string the
bundle manifest pins.
"""

from . import ensemble as ensemble
from . import metrics as metrics

__version__: str