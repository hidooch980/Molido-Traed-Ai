"""API DTOs."""

from __future__ import annotations

import uuid
from datetime import date, datetime, time

from pydantic import BaseModel, ConfigDict, Field

from app.core.enums import AssetClass, DataQualityIssue, Severity, Timeframe


class InstrumentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    symbol: str
    name: str
    asset_class: AssetClass
    base_currency: str | None = None
    quote_currency: str | None = None
    exchange: str | None = None
    timezone: str
    is_active: bool


class BarOut(BaseModel):
    event_time: datetime
    open: float
    high: float
    low: float
    close: float
    volume: float | None = None
    tick_volume: float | None = None
    spread: float | None = None
    revision: int
    quality_score: float


class BarsResponse(BaseModel):
    """Bars plus the exact reading conditions that produced them.

    `as_of` is echoed back deliberately: a series is only meaningful together
    with the knowledge cutoff it was read at, and callers that cache results
    need to key on it.
    """

    instrument_id: uuid.UUID
    symbol: str
    timeframe: Timeframe
    as_of: datetime
    count: int
    training_eligible: bool
    bars: list[BarOut]


class FindingOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    issue: DataQualityIssue
    severity: Severity
    timeframe: Timeframe
    window_start: datetime
    window_end: datetime
    detected_at: datetime
    affected_rows: int
    expected: str | None = None
    observed: str | None = None
    resolved_at: datetime | None = None


class DatasetQualityOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    timeframe: Timeframe
    provider_id: uuid.UUID
    score: float
    coverage_start: datetime | None = None
    coverage_end: datetime | None = None
    expected_bars: int
    actual_bars: int
    open_findings: int
    is_training_eligible: bool
    evaluated_at: datetime | None = None


class DataQualityResponse(BaseModel):
    instrument_id: uuid.UUID
    symbol: str
    datasets: list[DatasetQualityOut]
    findings: list[FindingOut]


class FeatureSpecOut(BaseModel):
    name: str
    version: int
    lookback: int
    description: str
    tags: list[str] = []


class FeatureRowOut(BaseModel):
    event_time: datetime
    source_revision: int
    # None means "could not be computed here" (usually insufficient warm-up),
    # never a substituted zero.
    values: dict[str, float | None]


class FeaturesResponse(BaseModel):
    instrument_id: uuid.UUID
    symbol: str
    timeframe: Timeframe
    as_of: datetime
    count: int
    materialized_values: int
    materialized_features: int
    rows: list[FeatureRowOut]


class EpisodeOut(BaseModel):
    event_time: datetime
    # When this episode became usable evidence. Always after event_time.
    outcome_ready_at: datetime
    horizon_bars: int
    entry_price: float
    session_labels: list[str] = []
    features: dict = {}
    # Direction-agnostic: "favourable" is undefined without a decision.
    max_up_pct: float | None = None
    max_down_pct: float | None = None
    forward_return_pct: float | None = None
    bars_to_max_up: int | None = None
    bars_to_max_down: int | None = None
    # Reserved for later phases; null until those phases exist.
    regime: str | None = None
    strategy: str | None = None
    decision: str | None = None


class EpisodesResponse(BaseModel):
    instrument_id: uuid.UUID
    symbol: str
    timeframe: Timeframe
    as_of: datetime
    count: int
    stored: int
    matured: int
    distribution: dict
    episodes: list[EpisodeOut]


class MarketMemoryResponse(BaseModel):
    instrument_id: uuid.UUID
    symbol: str
    timeframe: Timeframe
    as_of: datetime
    # Free-form per horizon: the shape differs between an available snapshot
    # and an unavailable one, and flattening them would hide which is which.
    horizons: list[dict]
    agreement: dict


class SymbolProfileOut(BaseModel):
    kind: str
    profile_version: int
    as_of: datetime
    computed_at: datetime
    # How many bars the claim rests on. A percentile from 200 bars and one from
    # 200,000 are different claims; the consumer must be able to tell.
    sample_size: int
    coverage_start: datetime | None = None
    coverage_end: datetime | None = None
    data: dict
    warnings: list[str] = []


class SymbolDnaResponse(BaseModel):
    instrument_id: uuid.UUID
    symbol: str
    timeframe: Timeframe
    as_of: datetime
    profiles: list[SymbolProfileOut]
    # Facets the spec asks for that cannot be computed yet, with the reason.
    unavailable: dict[str, str] = {}


class SessionStatusOut(BaseModel):
    """Market state at one instant, with the reasoning shown.

    `next_open` / `next_close` are nullable rather than defaulted: a market
    that genuinely never closes reports `null`, which is different from
    "unknown" and different again from an invented far-future timestamp.
    """

    instrument_id: uuid.UUID
    symbol: str
    at: datetime
    is_open: bool
    timezone: str
    market_code: str
    active_sessions: list[str]
    holiday: str | None = None
    next_open: datetime | None = None
    next_close: datetime | None = None


class HolidayOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    market_code: str
    holiday_date: date
    kind: str
    name: str
    opens_at: time | None = None
    closes_at: time | None = None


class DependencyHealth(BaseModel):
    name: str
    healthy: bool
    detail: str | None = None
    latency_ms: float | None = None


class HealthResponse(BaseModel):
    status: str = Field(description="ok | degraded | safe_mode")
    version: str
    environment: str
    safe_mode: bool
    safe_mode_reasons: list[str] = []
    dependencies: list[DependencyHealth] = []


class ErrorResponse(BaseModel):
    error: str
    message: str
    context: dict = {}
