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

    # Security. Off by default while every route is read-only, which keeps the
    # public dashboard reachable. This is not an honour system: app.api.guard
    # refuses to start the application if an execute route exists while it is
    # false, so the first execution endpoint cannot ship without it.
    require_auth: bool = False

    #: Where the API drops broker-login requests for the host agent to apply.
    #: The API runs in a container and MetaTrader runs on the host under Wine,
    #: so a shared directory is the seam - the alternative is handing a
    #: web-facing process the host's systemd, which is not a trade worth making.
    mt5_queue_dir: str = "/var/molido/mt5-queue"

    #: The chat channel. Empty means this deployment does not send - never
    #: "send to nobody" and never "try anyway". A token here authenticates a
    #: channel rather than a person, which is why the channel is read-only.
    telegram_bot_token: str = ""
    telegram_chat_id: str = ""

    #: An SMTP relay, not a mail server on this host. A fresh VPS address has no
    #: sending reputation, and mail from one lands in spam whatever SPF, DKIM
    #: and DMARC say - reputation is earned over months, so verification mail
    #: sent from here would produce users who cannot finish registering and an
    #: operator hunting a bug in working code.
    #:
    #: Empty means this deployment does not send, stated rather than silent.
    smtp_host: str = ""
    smtp_port: int = 587
    smtp_user: str = ""
    smtp_password: str = ""
    smtp_from: str = ""

    #: Where a verification link points. Set per deployment because the API
    #: cannot know the address a browser reached it on - behind a proxy the
    #: Host header is whatever the proxy was told, and a link built from it is
    #: a link an attacker can aim somewhere else.
    public_base_url: str = "http://185.204.169.240"

    rate_limit_per_minute: int = 120

    # Execution. Three separate switches on purpose: enabling the engine and
    # allowing it to send real orders are different decisions, and one flag
    # would mean whoever makes the first also makes the second. Every default
    # refuses, and `app.execution.safety` re-checks all of them per order.
    enable_execution: bool = False
    execution_dry_run: bool = True

    #: Send live orders even though no registered edge clears the bar.
    #:
    #: Named for what it does rather than something comfortable, because the
    #: name is the only warning somebody gets at the moment they set it. The
    #: measured edge over a random control is currently z = 1.10 against a
    #: required 1.96 - not distinguishable from entering at random - and an
    #: edge that small is smaller than the spread, so live trading under this
    #: setting pays the broker on every round trip for a return of about zero.
    #:
    #: It exists because it is the account holder's money and their decision.
    #: It defaults to refusing, cannot be reached by accident, and `autopilot`
    #: reports it in every response so it cannot be forgotten once set.
    trade_without_proven_edge: bool = False

    #: Send live orders to a real-money account.
    #:
    #: Separate from every other switch, and separate on purpose. The other
    #: three are decisions about this deployment; this one is a decision about
    #: this account, and the difference between practising and losing money is
    #: not a difference that should ride on a flag somebody set weeks ago for a
    #: demo. MetaTrader reports the account type and the bridge publishes it, so
    #: this is checked against the terminal rather than trusted from config.
    allow_real_money_orders: bool = False
    max_risk_r_per_order: float = 1.0

    #: How hard the autopilot trades. Settings rather than constants because
    #: these are the two numbers most worth turning on a practice account and
    #: least worth editing code to change - and because the value that makes
    #: sense for a demo is not the value that makes sense anywhere else.
    #:
    #: The defaults are the conservative pair the live cycle has been running.
    #: Raising them changes how much of the account one bad instant can take:
    #: risk percent times open positions is the fraction of equity at stake if
    #: every stop fills at once, and the cross-section deliberately takes both
    #: tails, so its positions are correlated and "at once" is the normal case
    #: rather than the tail one. `account_gate` still refuses a real-money
    #: account whatever these say.
    autotrade_risk_percent: float = 0.25
    autotrade_max_open_positions: int = 8

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
