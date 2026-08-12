"""Feature contract and registry (spec phase 7).

A feature is a **pure, deterministic function of a bar window**. That constraint
is what makes the whole learning pipeline reproducible: given the same bars, a
feature must produce the same number today, in a backtest, and during training
three months from now. Anything that reads a clock, a database, or a live quote
is not a feature and does not belong here.

Two declarations carry real weight:

* `lookback` — how many bars the feature needs *before* the one being computed.
  The feature store uses it to fetch exactly that much history and to refuse
  computation when there is not enough, rather than quietly emitting a value
  derived from three bars when the spec says fifty.
* `version` — bumped whenever the maths changes. Stored alongside every value,
  so a model trained on `rsi_14 v1` can never be silently fed `v2` numbers.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from typing import Protocol

from app.core.errors import ConfigurationError, InsufficientDataError
from app.services.point_in_time import BarView


class FeatureFn(Protocol):
    """Computes one value from a window ending at the target bar.

    `bars` is chronological and its **last element is the bar being described**.
    Returning None means "not applicable here" (rare); insufficient history is
    signalled by the store before the function is ever called.
    """

    def __call__(self, bars: Sequence[BarView]) -> float | None: ...


@dataclass(frozen=True)
class FeatureSpec:
    name: str
    version: int
    lookback: int
    fn: FeatureFn
    description: str = ""
    # Features that are ratios/indices rather than prices; useful later for
    # normalization decisions in the model layer.
    unitless: bool = True
    tags: tuple[str, ...] = field(default_factory=tuple)

    @property
    def key(self) -> str:
        return f"{self.name}@v{self.version}"

    def compute(self, bars: Sequence[BarView]) -> float | None:
        if len(bars) < self.lookback + 1:
            raise InsufficientDataError(
                f"Feature {self.key} needs {self.lookback + 1} bars.",
                feature=self.name,
                required=self.lookback + 1,
                available=len(bars),
            )
        # Hand the function exactly the window it declared. Passing more would
        # let a sloppy implementation quietly depend on extra history that the
        # store did not promise to fetch.
        return self.fn(bars[-(self.lookback + 1) :])


_REGISTRY: dict[str, FeatureSpec] = {}


def register(spec: FeatureSpec) -> FeatureSpec:
    existing = _REGISTRY.get(spec.name)
    if existing is not None and existing.version == spec.version:
        raise ConfigurationError(
            f"Feature {spec.name} v{spec.version} is already registered. "
            "Bump the version when the maths changes.",
            feature=spec.name,
        )
    _REGISTRY[spec.name] = spec
    return spec


def feature(
    name: str, *, version: int = 1, lookback: int, description: str = "", **kwargs
) -> Callable[[FeatureFn], FeatureSpec]:
    """Decorator form: keeps the maths and its metadata in one place."""

    def wrap(fn: FeatureFn) -> FeatureSpec:
        return register(
            FeatureSpec(
                name=name,
                version=version,
                lookback=lookback,
                fn=fn,
                description=description or (fn.__doc__ or "").strip().split("\n")[0],
                **kwargs,
            )
        )

    return wrap


def get(name: str) -> FeatureSpec:
    try:
        return _REGISTRY[name]
    except KeyError as exc:
        raise ConfigurationError(
            f"Unknown feature {name!r}", available=sorted(_REGISTRY)
        ) from exc


def all_specs() -> list[FeatureSpec]:
    return [_REGISTRY[name] for name in sorted(_REGISTRY)]


def names() -> list[str]:
    return sorted(_REGISTRY)


def max_lookback(feature_names: Sequence[str]) -> int:
    return max((get(n).lookback for n in feature_names), default=0)


def clear() -> None:
    """Test helper."""
    _REGISTRY.clear()
