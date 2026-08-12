"""Feature definitions.

Importing this package registers every built-in feature. New feature modules
must be imported here or the registry will not know about them.
"""

from app.features import indicators  # noqa: F401  (registers the built-ins)
from app.features.base import (
    FeatureSpec,
    all_specs,
    get,
    max_lookback,
    names,
    register,
)

__all__ = ["FeatureSpec", "all_specs", "get", "max_lookback", "names", "register"]
