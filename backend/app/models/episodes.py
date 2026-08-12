"""Historical episodes (spec phase 10, §9).

An episode is a moment in a market's history, described by the state that was
knowable *at* that moment, paired with what happened *after* it.

That pairing is the whole value and the whole danger. The outcome is measured
forward, so an episode is not usable as evidence until its forward window has
closed. `outcome_ready_at` makes that explicit and queryable: it is
`event_time + horizon`, and every read filters on it. Without that column an
episode-based system looks brilliant in backtest and fails live, because it was
quietly learning from outcomes that had not happened yet.

Several columns the spec lists are deliberately nullable and unfilled:
`regime`, `strategy`, `decision`, `execution_quality`. They belong to phases
13, 19 and 25. Reserving them now keeps the schema stable; filling them with
guesses would poison every model trained on this table.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import ForeignKey, Index, Integer, Numeric, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.core.enums import Timeframe
from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin, utcnow
from app.db.types import JSONType, TimestampType, UUIDType


class Episode(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "episodes"
    __table_args__ = (
        UniqueConstraint(
            "instrument_id",
            "timeframe",
            "event_time",
            "horizon_bars",
            "builder_version",
            name="uq_episode_moment",
        ),
        # The index the maturity filter actually uses on every read.
        Index("ix_episodes_ready", "instrument_id", "timeframe", "outcome_ready_at"),
        Index("ix_episodes_lookup", "instrument_id", "timeframe", "event_time"),
    )

    instrument_id: Mapped[uuid.UUID] = mapped_column(
        UUIDType, ForeignKey("instruments.id", ondelete="CASCADE"), nullable=False, index=True
    )
    timeframe: Mapped[Timeframe] = mapped_column(String(8), nullable=False)
    builder_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)

    # The moment being described (the bar's open time).
    event_time: Mapped[datetime] = mapped_column(TimestampType, nullable=False)
    # How many bars forward the outcome was measured over.
    horizon_bars: Mapped[int] = mapped_column(Integer, nullable=False)
    # event_time + horizon. Before this instant the episode is not evidence.
    outcome_ready_at: Mapped[datetime] = mapped_column(TimestampType, nullable=False)
    computed_at: Mapped[datetime] = mapped_column(
        TimestampType, nullable=False, default=utcnow
    )

    # ---- state knowable AT event_time -------------------------------------
    entry_price: Mapped[float] = mapped_column(Numeric(20, 10), nullable=False)
    session_labels: Mapped[list] = mapped_column(JSONType, default=list, nullable=False)
    # Feature snapshot: exactly what the feature store returned for this bar.
    features: Mapped[dict] = mapped_column(JSONType, default=dict, nullable=False)

    # ---- outcome, measured FORWARD from event_time -------------------------
    # Direction-agnostic on purpose. "Favourable" and "adverse" are undefined
    # without a decision to be long or short, and no decision layer exists yet.
    # A later phase maps these to MFE/MAE once it knows the direction.
    max_up_pct: Mapped[float | None] = mapped_column(Numeric(20, 10), nullable=True)
    max_down_pct: Mapped[float | None] = mapped_column(Numeric(20, 10), nullable=True)
    forward_return_pct: Mapped[float | None] = mapped_column(Numeric(20, 10), nullable=True)
    bars_to_max_up: Mapped[int | None] = mapped_column(Integer, nullable=True)
    bars_to_max_down: Mapped[int | None] = mapped_column(Integer, nullable=True)
    outcome_bars: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    # ---- reserved for later phases -----------------------------------------
    regime: Mapped[str | None] = mapped_column(String(32), nullable=True)  # phase 13
    strategy: Mapped[str | None] = mapped_column(String(64), nullable=True)  # phase 19
    decision: Mapped[str | None] = mapped_column(String(16), nullable=True)  # phase 23
    r_multiple: Mapped[float | None] = mapped_column(Numeric(12, 6), nullable=True)  # phase 29
    execution_quality: Mapped[dict] = mapped_column(
        JSONType, default=dict, nullable=False
    )  # phase 25
