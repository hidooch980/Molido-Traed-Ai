"""World state (spec phase 12, §11).

One object describing everything the system knows about an instrument at one
instant. Later phases — the regime engine, the cognitive brain, the risk brain —
all consume this rather than each re-deriving state from bars, so that a
decision and its explanation are built from exactly the same picture.

Two design rules, both learned from the layers below.

**Every field carries its own availability.** A world state where
`volatility: null` is indistinguishable from `volatility: 0.0` is worse than
no world state at all. Each block reports `available` plus a reason when it is
missing, so a consumer must handle the gap rather than average over it.

**Assembly never fabricates.** This module joins existing measurements; it does
not invent new ones. The spec lists macro, news and sentiment as part of world
state — none of those have a data source yet, so they appear as explicitly
unavailable rather than as a plausible zero. `sentiment: 0.5` would be
inherited by every model built on top of this.

The assembly is read-only and side-effect free: it is safe to call on every
request, and it is not stored, because a stored snapshot can drift from the
bars it claims to summarise.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from sqlalchemy.orm import Session

from app.core.enums import Timeframe
from app.core.errors import InsufficientDataError, MolidoError, ValidationFailedError
from app.core.logging import get_logger
from app.models.instruments import Instrument
from app.services import feature_store, market_memory, point_in_time, sessions, symbol_dna
from app.services.instruments import get_instrument

log = get_logger(__name__)

# Facets the spec asks of world state that have no data source yet. Named so
# the gap is visible to whoever builds the regime engine on top of this.
UNAVAILABLE_BLOCKS: dict[str, str] = {
    "macro": "needs an economic-data provider",
    "news": "needs a news feed (phase 4 providers)",
    "sentiment": "needs a legitimately sourced sentiment feed",
    "correlation_matrix": "needs the multi-instrument correlation job (phase 22)",
    "currency_strength": "needs a full-universe basket calculation",
    "regime": "needs the regime engine (phase 13)",
}


@dataclass
class Block:
    """One area of the world state, with its own availability."""

    available: bool
    data: dict[str, Any] = field(default_factory=dict)
    reason: str | None = None

    def as_dict(self) -> dict[str, Any]:
        if not self.available:
            return {"available": False, "reason": self.reason}
        return {"available": True, **self.data}


def _unavailable(reason: str) -> Block:
    return Block(available=False, reason=reason)


@dataclass
class WorldState:
    instrument_id: uuid.UUID
    symbol: str
    timeframe: Timeframe
    as_of: datetime
    blocks: dict[str, Block]

    def as_dict(self) -> dict[str, Any]:
        return {
            "instrument_id": str(self.instrument_id),
            "symbol": self.symbol,
            "timeframe": self.timeframe.value,
            "as_of": self.as_of.isoformat(),
            **{name: block.as_dict() for name, block in self.blocks.items()},
            "unavailable": UNAVAILABLE_BLOCKS,
        }

    @property
    def available_blocks(self) -> list[str]:
        return sorted(name for name, b in self.blocks.items() if b.available)


def _price_block(
    session: Session, instrument_id: uuid.UUID, timeframe: Timeframe, as_of: datetime
) -> Block:
    bars = point_in_time.get_bars(session, instrument_id, timeframe, as_of, lookback=2)
    if not bars:
        return _unavailable("no bar closed and known at this instant")

    latest = bars[-1]
    previous = bars[-2] if len(bars) > 1 else None
    change = (
        (latest.close - previous.close) / previous.close
        if previous and previous.close > 0
        else None
    )
    return Block(
        available=True,
        data={
            "event_time": latest.event_time.isoformat(),
            "open": latest.open,
            "high": latest.high,
            "low": latest.low,
            "close": latest.close,
            "spread": latest.spread,
            "volume": latest.volume,
            "bar_change_pct": round(change, 10) if change is not None else None,
            "revision": latest.revision,
            "quality_score": latest.quality_score,
        },
    )


def _session_block(session: Session, instrument: Instrument, as_of: datetime) -> Block:
    calendar = sessions.build_calendar(session, instrument)
    local_date = as_of.astimezone(calendar.zone).date()
    holiday = calendar.holidays.get(local_date)
    return Block(
        available=True,
        data={
            "is_open": calendar.is_open(as_of),
            "active": [s.value for s in sessions.active_sessions(as_of)],
            "timezone": calendar.timezone,
            "market_code": instrument.market_code,
            "holiday": holiday.name or holiday.kind.value if holiday else None,
        },
    )


def _freshness_block(
    session: Session, instrument_id: uuid.UUID, timeframe: Timeframe, as_of: datetime
) -> Block:
    """How stale the data is — the input to the spec's market-data failure policy.

    A world state that does not know its own age lets a decision be made on a
    feed that stopped hours ago, which looks exactly like a quiet market.
    """
    age = point_in_time.data_freshness_seconds(
        session, instrument_id, timeframe, now=as_of
    )
    if age is None:
        return _unavailable("no data to measure freshness against")

    limit = timeframe.delta.total_seconds() * 3
    return Block(
        available=True,
        data={
            "age_seconds": round(age, 1),
            "stale": age > limit,
            "stale_after_seconds": limit,
        },
    )


def _features_block(
    session: Session, instrument_id: uuid.UUID, timeframe: Timeframe, as_of: datetime
) -> Block:
    try:
        row = feature_store.compute_at(session, instrument_id, timeframe, as_of)
    except InsufficientDataError as exc:
        return _unavailable(exc.message)
    return Block(
        available=True,
        data={
            "event_time": row.event_time.isoformat(),
            "values": {k: v for k, v in row.values.items() if v is not None},
            "unavailable_features": sorted(
                k for k, v in row.values.items() if v is None
            ),
        },
    )


def _memory_block(
    session: Session,
    instrument_id: uuid.UUID,
    timeframe: Timeframe,
    as_of: datetime,
    memory: dict | None = None,
) -> Block:
    try:
        snapshots = memory or market_memory.recall_all(
            session, instrument_id, timeframe, as_of
        )
    except ValidationFailedError as exc:
        return _unavailable(exc.message)

    horizons = {h.value: s.as_dict() for h, s in snapshots.items()}
    if not any(s.available for s in snapshots.values()):
        return _unavailable("no horizon has enough history")

    return Block(
        available=True,
        data={
            "horizons": horizons,
            "agreement": market_memory.agreement(snapshots),
        },
    )


def _dna_block(
    session: Session, instrument_id: uuid.UUID, timeframe: Timeframe, as_of: datetime
) -> Block:
    """Stored behavioural profile, if one has been computed and was knowable.

    Deliberately reads the stored snapshot rather than recomputing: profiles
    scan thousands of bars, and world state is assembled per request.
    """
    stored = symbol_dna.latest_dna(session, instrument_id, timeframe, as_of)
    if not stored:
        return _unavailable("no profile computed at or before this instant")

    return Block(
        available=True,
        data={
            "profiles": {
                kind: {
                    "as_of": row.as_of.isoformat(),
                    "sample_size": row.sample_size,
                    "data": {k: v for k, v in (row.data or {}).items() if k != "_warnings"},
                }
                for kind, row in stored.items()
            }
        },
    )


def _quality_block(
    session: Session, instrument_id: uuid.UUID, timeframe: Timeframe
) -> Block:
    from sqlalchemy import select

    from app.models.ingestion import DatasetQuality

    rows = list(
        session.scalars(
            select(DatasetQuality).where(
                DatasetQuality.instrument_id == instrument_id,
                DatasetQuality.timeframe == timeframe,
            )
        )
    )
    if not rows:
        return _unavailable("dataset has not been evaluated")

    return Block(
        available=True,
        data={
            "datasets": [
                {
                    "provider_id": str(r.provider_id),
                    "score": float(r.score),
                    "open_findings": r.open_findings,
                    "training_eligible": r.is_training_eligible,
                    "actual_bars": r.actual_bars,
                }
                for r in rows
            ],
            # The gate, surfaced at the top level because every consumer needs
            # it and none should have to reduce the list themselves.
            "any_training_eligible": any(r.is_training_eligible for r in rows),
        },
    )


def build(
    session: Session,
    instrument_id: uuid.UUID,
    timeframe: Timeframe,
    as_of: datetime | None = None,
    memory: dict | None = None,
) -> WorldState:
    """Assemble the full picture at `as_of`.

    A failure in one block never fails the whole state: a world state missing
    its memory block is still useful, while an exception leaves the caller with
    nothing at all. Failures are recorded in the block's reason.

    `memory` lets a caller that has already recalled the horizons hand them
    over. Passing snapshots taken at a different `as_of` would put one instant's
    memory next to another instant's price, so the only safe caller is one that
    recalled at this exact cutoff.
    """
    cutoff = (as_of or datetime.now(UTC)).astimezone(UTC)
    if cutoff.tzinfo is None:
        raise ValidationFailedError("as_of must be timezone-aware (UTC)")

    instrument = get_instrument(session, instrument_id)

    builders: dict[str, Any] = {
        "price": lambda: _price_block(session, instrument_id, timeframe, cutoff),
        "session": lambda: _session_block(session, instrument, cutoff),
        "freshness": lambda: _freshness_block(session, instrument_id, timeframe, cutoff),
        "features": lambda: _features_block(session, instrument_id, timeframe, cutoff),
        "memory": lambda: _memory_block(
            session, instrument_id, timeframe, cutoff, memory
        ),
        "dna": lambda: _dna_block(session, instrument_id, timeframe, cutoff),
        "quality": lambda: _quality_block(session, instrument_id, timeframe),
    }

    blocks: dict[str, Block] = {}
    for name, builder in builders.items():
        try:
            blocks[name] = builder()
        except MolidoError as exc:
            blocks[name] = _unavailable(f"{exc.code}: {exc.message}")
        except Exception as exc:  # noqa: BLE001 - one block must not sink the rest
            log.error("world_state.block_failed", block=name, error=str(exc))
            blocks[name] = _unavailable(f"{type(exc).__name__}: {exc}")

    return WorldState(
        instrument_id=instrument.id,
        symbol=instrument.symbol,
        timeframe=timeframe,
        as_of=cutoff,
        blocks=blocks,
    )
