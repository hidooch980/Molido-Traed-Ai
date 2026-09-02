"""One row per service-level observation (see `app.ops.slo`)."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import Float, Index, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, UUIDPrimaryKeyMixin, utcnow
from app.db.types import JSONType, TimestampType


class SloObservation(Base, UUIDPrimaryKeyMixin):
    __tablename__ = "slo_observations"
    __table_args__ = (Index("ix_slo_observations_metric_time", "metric", "observed_at"),)

    observed_at: Mapped[datetime] = mapped_column(TimestampType, nullable=False, default=utcnow)
    metric: Mapped[str] = mapped_column(String(64), nullable=False)
    value: Mapped[float] = mapped_column(Float, nullable=False)
    detail: Mapped[dict] = mapped_column(JSONType, default=dict, nullable=False)
