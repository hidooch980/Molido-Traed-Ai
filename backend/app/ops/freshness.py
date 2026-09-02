"""How old the data is, per source, judged against the interval it promised.

`data_is_fresh` had one number in mind - the age of "the feed" in bars - and
no feed to read it from, so it was undeterminable. There is not one feed. There
are four providers writing bars at several timeframes, and eight terminals
each publishing their own account. A single age hides which of them stopped.

So this measures every (provider, timeframe) that has written a bar in the
last week, and reports each one's age in its own bars. The number `readiness`
asks for is the age of the *best* source at the decision timeframe: if any
provider is current at H1, decisions have current H1 data, and a stale
secondary provider is a finding rather than a halt. Every source is listed
either way, because "the best one is fine" is not a reason to stop reading.

Read from the bar table, not from `ingestion_runs`: a run that finished with
zero rows written is a run, and the question is whether there are bars.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy.orm import Session

from app.core.enums import Timeframe

#: The timeframe decisions are made on, and so the one whose age matters.
DECISION_TIMEFRAME = Timeframe.H1

#: Beyond this many bars a source is stale. The same number the risk brain
#: uses (`HardLimits.max_data_age_bars`), stated once here so the two cannot
#: drift apart.
MAX_AGE_BARS = 3.0

#: Sources with no bar in this long are not stale, they are gone, and are
#: listed as absent rather than given an age in the thousands.
LOOKBACK = timedelta(days=7)


@dataclass(frozen=True)
class SourceAge:
    provider: str
    timeframe: str
    instruments: int
    last_event_time: datetime
    ingested_at: datetime | None
    age: timedelta
    expected_interval: timedelta

    @property
    def age_bars(self) -> float:
        seconds = self.expected_interval.total_seconds()
        return self.age.total_seconds() / seconds if seconds > 0 else float("inf")

    @property
    def fresh(self) -> bool:
        return self.age_bars <= MAX_AGE_BARS

    def as_dict(self) -> dict[str, Any]:
        return {
            "provider": self.provider,
            "timeframe": self.timeframe,
            "instruments": self.instruments,
            "last_event_time": self.last_event_time.isoformat(),
            "ingested_at": self.ingested_at.isoformat() if self.ingested_at else None,
            "age_seconds": round(self.age.total_seconds(), 1),
            "expected_interval_seconds": self.expected_interval.total_seconds(),
            "age_bars": round(self.age_bars, 2),
            "status": "fresh" if self.fresh else "stale",
        }


@dataclass
class FreshnessReport:
    measured_at: datetime
    sources: list[SourceAge] = field(default_factory=list)

    @property
    def decision_sources(self) -> list[SourceAge]:
        return [s for s in self.sources if s.timeframe == DECISION_TIMEFRAME.value]

    @property
    def best_decision_age_bars(self) -> float | None:
        """Age of the freshest source at the decision timeframe, or None when
        nothing has written a decision-timeframe bar in the lookback."""
        ages = [s.age_bars for s in self.decision_sources]
        return min(ages) if ages else None

    @property
    def fresh(self) -> bool:
        age = self.best_decision_age_bars
        return age is not None and age <= MAX_AGE_BARS

    def as_dict(self) -> dict[str, Any]:
        return {
            "measured_at": self.measured_at.isoformat(),
            "decision_timeframe": DECISION_TIMEFRAME.value,
            "max_age_bars": MAX_AGE_BARS,
            "best_decision_age_bars": (
                round(self.best_decision_age_bars, 2)
                if self.best_decision_age_bars is not None
                else None
            ),
            "fresh": self.fresh,
            "sources": [s.as_dict() for s in self.sources],
            "stale_sources": [
                f"{s.provider}/{s.timeframe}" for s in self.sources if not s.fresh
            ],
        }


def _aware(value: Any) -> datetime | None:
    if not isinstance(value, datetime):
        return None
    return value if value.tzinfo else value.replace(tzinfo=UTC)


def measure(session: Session, *, now: datetime | None = None) -> FreshnessReport:
    """Age every source that wrote a bar in the lookback window."""
    # Through the models rather than raw SQL so the timestamp type does the
    # decoding on every database: sqlite hands raw SQL back strings.
    from sqlalchemy import distinct, func, select

    from app.models.instruments import Provider
    from app.models.market_data import Bar

    moment = (now or datetime.now(UTC)).astimezone(UTC)
    report = FreshnessReport(measured_at=moment)
    statement = (
        select(
            Provider.code,
            Bar.timeframe,
            func.count(distinct(Bar.instrument_id)),
            func.max(Bar.event_time),
            func.max(Bar.ingested_at),
        )
        .join(Provider, Provider.id == Bar.provider_id)
        .where(Bar.event_time > moment - LOOKBACK)
        .group_by(Provider.code, Bar.timeframe)
    )
    rows = session.execute(statement).all()
    for provider, timeframe, instruments, last_event_time, ingested_at in rows:
        last = _aware(last_event_time)
        if last is None:
            continue
        try:
            interval = Timeframe(str(timeframe)).delta
        except ValueError:
            continue
        # A bar stamped at its open is complete one interval later; the age
        # that matters is measured from when the bar could have existed.
        age = moment - (last + interval)
        report.sources.append(
            SourceAge(
                provider=str(provider),
                timeframe=str(timeframe),
                instruments=int(instruments or 0),
                last_event_time=last,
                ingested_at=_aware(ingested_at),
                age=max(age, timedelta(0)),
                expected_interval=interval,
            )
        )
    report.sources.sort(key=lambda s: (s.timeframe, s.age))
    return report


__all__ = ["DECISION_TIMEFRAME", "MAX_AGE_BARS", "FreshnessReport", "SourceAge", "measure"]
