"""Application configuration.

Secrets come from the environment only. Nothing here is ever logged verbatim -
see `safe_summary()` for the redacted view used by diagnostics.
"""

from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

Environment = Literal["development", "test", "staging", "production"]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="MOLIDO_",
        env_file=(".env", "../infra/.env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_name: str = "MolidoTrade AI"
    env: Environment = "development"

    database_url: str = "postgresql+psycopg://molido:molido@localhost:5432/molidotrade"
    redis_url: str = "redis://localhost:6379/0"

    log_level: str = "INFO"
    log_json: bool = False

    # Datasets scoring below this are flagged and excluded from training reads.
    min_quality_score: float = Field(default=0.80, ge=0.0, le=1.0)

    # 0 disables the limit. Guards against accidental unbounded historical scans.
    max_asof_age_days: int = 0

    # Ingestion resilience
    ingest_max_retries: int = 5
    ingest_backoff_base_seconds: float = 1.0
    ingest_chunk_days: int = 30

    # Security. Off by default while every route is read-only; the first
    # mutating endpoint must flip this on and keep it on.
    require_auth: bool = False
    rate_limit_per_minute: int = 120

    # Collector (the long-running data-gathering worker)
    collector_provider: str = "yfinance"
    collector_interval_seconds: int = 900
    watchlist: str = (
        "EURUSD:EURUSD=X:H1,GBPUSD:GBPUSD=X:H1,XAUUSD:GC=F:H1,BTCUSD:BTC-USD:H1"
    )

    @property
    def is_production(self) -> bool:
        return self.env == "production"

    def safe_summary(self) -> dict[str, str | bool | float | int]:
        """Config view that is safe to log or expose to operators."""
        return {
            "app_name": self.app_name,
            "env": self.env,
            "database": _redact_dsn(self.database_url),
            "redis": _redact_dsn(self.redis_url),
            "log_level": self.log_level,
            "min_quality_score": self.min_quality_score,
        }


def _redact_dsn(dsn: str) -> str:
    """Strip credentials from a connection string so it can be shown safely."""
    if "@" not in dsn:
        return dsn
    scheme, _, rest = dsn.partition("://")
    _, _, host = rest.rpartition("@")
    return f"{scheme}://***@{host}"


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
