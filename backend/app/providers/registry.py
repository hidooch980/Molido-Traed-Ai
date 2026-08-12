"""Provider registry.

Maps a provider `code` to a live adapter instance. Ingestion resolves adapters
through here, so adding a feed is a registration, not a code change in the
pipeline.
"""

from __future__ import annotations

from pathlib import Path

from app.core.errors import ConfigurationError
from app.providers.base import MarketDataProvider
from app.providers.csv_provider import CsvProvider

_registry: dict[str, MarketDataProvider] = {}


def register(provider: MarketDataProvider) -> None:
    _registry[provider.code] = provider


def get_provider(code: str) -> MarketDataProvider:
    try:
        return _registry[code]
    except KeyError as exc:
        raise ConfigurationError(
            f"No market-data adapter registered for provider {code!r}",
            registered=sorted(_registry),
        ) from exc


def registered_codes() -> list[str]:
    return sorted(_registry)


def clear() -> None:
    """Test helper."""
    _registry.clear()


def install_defaults(data_root: Path | str = "data/providers") -> None:
    """Register adapters that need no credentials.

    yfinance is not installed by default here: it makes network calls, and an
    adapter that silently reaches the internet during tests is a liability.
    Operators register it explicitly.
    """
    register(CsvProvider(Path(data_root) / "csv"))
