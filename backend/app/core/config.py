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

    #: How many reverse proxies sit in front of this application.
    #:
    #: The rate limiter counts failures per caller address, and an address a
    #: caller can choose is not a limit. `X-Forwarded-For` is a header, so
    #: anybody can send one; the only entries in it that mean anything are the
    #: ones a proxy this deployment controls appended itself, counted from the
    #: right.
    #:
    #: 0 - nothing in front. The socket address is used and the header is
    #:     ignored entirely, which is the safe default: a deployment that
    #:     trusted the header while directly exposed would let every attacker
    #:     pick a fresh address per request.
    #: 1 - one proxy, which is this project's Caddy. The last entry is what
    #:     Caddy saw, and everything to its left was supplied by the caller.
    #: 2+ - a CDN in front of Caddy. Set it to the real number: setting it too
    #:     high reads an address the caller wrote.
    #:
    #: Getting this wrong in the other direction is not silent either - with 0
    #: behind a proxy, every request appears to come from the proxy and the
    #: address ladder becomes one bucket holding everybody.
    trusted_proxy_hops: int = 0

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

    # ------------------------------------------------------------------ analyst
    #
    #: The key for the second brain's language half. Empty means the analyst is
    #: not configured, and `brain.analyst` says exactly that rather than
    #: returning a plausible paragraph it made up - which is the one failure
    #: mode a commentary layer must not have.
    #:
    #: Never logged. `safe_summary` reports whether it is set, never its value.
    anthropic_api_key: str = ""

    #: Which model reads the trace. The analyst reasons about a chain of
    #: eighteen gates and is asked to disagree with it; that is not a task for
    #: the cheap tier, and it runs at most a few times per decision rather than
    #: per bar.
    analyst_model: str = "claude-opus-5"

    #: How hard it is allowed to think. `high` is the default across the API;
    #: named here so lowering it is a visible decision rather than a silent one.
    analyst_effort: Literal["low", "medium", "high", "xhigh", "max"] = "high"

    #: Ceiling per call. Non-streaming, so this stays well under the SDK's HTTP
    #: timeout - the analyst answers one question about one trace and has no
    #: reason to produce a long document.
    analyst_max_tokens: int = 8000

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
    #: Per-account risk, as "login=percent,login=percent". A login not named
    #: here uses the figure above.
    #:
    #: This exists because the smallest trade a broker will accept is a fixed
    #: size, not a fixed fraction: 0.01 lots of EURUSD behind a 26-pip stop
    #: risks $2.60 whatever the account holds. A $50 account at 0.75% may
    #: risk 38 cents, so every order it computes rounds to zero and it trades
    #: nothing - not because a rule refused it but because arithmetic did.
    #:
    #: A single global figure cannot fix that. Raising it enough for the $50
    #: account would put $10,000 behind every trade on the $196,000 one, and
    #: the whole reason the fleet has both is that they are different
    #: decisions. So the override is per account and touches nothing else.
    account_risk_percent: str = ""
    autotrade_max_open_positions: int = 8
    #: Which brain each account trades, as "login=strategy,login=strategy".
    #: A login not named here trades the incumbent. A strategy name nothing
    #: registered is a refusal at cycle time, never a silent fallback - an
    #: account trading a brain nobody assigned is the mistake this exists
    #: to prevent.
    account_strategies: str = ""
    #: How many brains must agree on a symbol and side before an order is
    #: sent. 1 is a brain acting alone; 2 is the roadmap's agreement gate.
    #: Non-trading brains vote too - recording them is what buys their vote.
    consensus_required: int = 1

    #: Which timeframes the rule records decisions on, comma separated.
    #:
    #: Adding one does not dilute the hourly evidence: entries carry their own
    #: timeframe now and the measurement groups on it, so H1 and M5 accumulate
    #: as separate bodies of proof rather than one blurred pile.
    #:
    #: The reason to add M5 is arithmetic. The forward test needs about 6,573
    #: independent instants to separate this edge from noise, which is roughly
    #: a year of hourly bars and about a month of five-minute ones. The reason
    #: to be careful about it is also arithmetic, and points the other way: the
    #: spread is a constant while bar range falls with the square root of time,
    #: so the same 1.4 pip spread is 16% of an average hourly bar and near 58%
    #: of a five-minute one. Faster answers, dearer trades. The measurement is
    #: net of costs, which is exactly why it is allowed to settle this.
    #: Measured on all four now, not just the hourly one. The arithmetic above
    #: was already written and was already the answer: 6,573 instants is a year
    #: of hourly bars and a week of one-minute ones, and collecting only H1
    #: made the wait a year for no reason but that nothing else was fetched.
    #:
    #: Each timeframe is measured separately, so if the spread does eat the
    #: edge at one minute the journal says so about one minute rather than
    #: contaminating the hourly answer. That separation is the whole reason
    #: this is safe to widen.
    forward_timeframes: str = "D1,H1,M15,M5,M1"

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
            # Whether, not what. An operator needs to know the analyst can run;
            # nobody needs the key in a log line.
            "analyst_configured": bool(self.anthropic_api_key),
            "analyst_model": self.analyst_model,
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
