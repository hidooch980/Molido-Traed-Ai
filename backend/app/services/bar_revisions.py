"""Append broker observations without rewriting prices or knowledge time.

The caller owns the transaction. Identical republishes do nothing; corrections
receive a new revision. Concurrent inserts never overwrite an existing version.
"""

from collections import defaultdict
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.orm import Session, aliased

from app.models.market_data import Bar

FIELDS = ("open", "high", "low", "close", "volume", "tick_volume", "spread", "quality_score")


def latest_bar_query(*conditions):
    """One latest revision per bar, ordered chronologically before any LIMIT.

    Visibility conditions belong inside the ranking so an unknown revision
    cannot hide the previously known one. Callers supply their time bounds.
    """
    ranked = select(
        Bar,
        func.row_number().over(
            partition_by=(Bar.instrument_id, Bar.provider_id, Bar.timeframe, Bar.event_time),
            order_by=(Bar.revision.desc(), Bar.ingested_at.desc()),
        ).label("_latest_revision"),
    ).where(*conditions).subquery()
    latest = aliased(Bar, ranked)
    return select(latest).where(ranked.c._latest_revision == 1).order_by(latest.event_time)


def _aware(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def _number(name: str, value: Any) -> Decimal | None:
    if value is None:
        return None
    if isinstance(value, bool):
        raise ValueError("A bar value must be a finite number")
    try:
        number = Decimal(str(value))
        if not number.is_finite():
            raise ValueError("A bar value must be finite")
        scale = Bar.__table__.c[name].type.scale
        return number.quantize(Decimal(1).scaleb(-scale), rounding=ROUND_HALF_UP)
    except InvalidOperation as exc:
        raise ValueError("A bar value cannot be represented") from exc


def _same(left, right):
    return all(_number(k, left.get(k)) == _number(k, right.get(k)) for k in FIELDS)


def append_only_bars(session: Session, rows: list[dict[str, Any]]) -> int:
    """Return actual inserts; preserve previous observations and first receipt.

    A conflicting concurrent writer is reread under READ COMMITTED. If it
    remains unresolved, raise so the caller can roll back rather than silently
    claiming a correction was stored. No commit is performed here.
    """
    if not rows:
        return 0
    dialect = session.get_bind().dialect.name
    if dialect not in ("postgresql", "sqlite"):
        raise ValueError("Append-only bars require PostgreSQL or SQLite")
    insert = pg_insert if dialect == "postgresql" else sqlite_insert
    groups = defaultdict(dict)
    # Validate and deduplicate the whole incoming batch before writing anything.
    for raw in rows:
        row = dict(raw)
        row["event_time"] = _aware(row["event_time"])
        row["ingested_at"] = _aware(row["ingested_at"])
        for field in FIELDS:
            if field in row:
                row[field] = _number(field, row[field])
        key = (row["instrument_id"], row["provider_id"], str(row["timeframe"]))
        stamp = row["event_time"]
        previous = groups[key].get(stamp)
        if previous is not None and (not _same(previous, row)
                                     or previous.get("source_ref") != row.get("source_ref")):
            raise ValueError("Conflicting observations for one bar in the same batch")
        if previous is not None and previous["ingested_at"] <= row["ingested_at"]:
            continue
        groups[key][stamp] = row

    total = 0
    for (instrument_id, provider_id, timeframe), by_stamp in groups.items():
        remaining = dict(by_stamp)
        for attempt in range(3):
            if not remaining:
                break
            latest = {}
            stamps = list(remaining)
            for start in range(0, len(stamps), 400):
                found = session.execute(
                    select(Bar.__table__).where(
                        Bar.instrument_id == instrument_id,
                        Bar.provider_id == provider_id,
                        Bar.timeframe == timeframe,
                        Bar.event_time.in_(stamps[start:start+400]),
                    ).order_by(Bar.revision.desc())
                ).mappings()
                for old in found:
                    latest.setdefault(_aware(old["event_time"]), old)
            pending = []
            for stamp, row in list(remaining.items()):
                old = latest.get(stamp)
                merged = {field: old.get(field) if old else None for field in FIELDS}
                merged["source_ref"] = old.get("source_ref") if old else None
                merged.update(row)
                if merged.get("quality_score") is None:
                    merged["quality_score"] = Decimal("1.000")
                if (old is not None and _same(old, merged)
                        and old.get("source_ref") == merged.get("source_ref")):
                    remaining.pop(stamp)
                    continue
                if old is not None and row["ingested_at"] < _aware(old["ingested_at"]):
                    raise ValueError("A correction cannot predate the recorded observation")
                merged["revision"] = old["revision"]+1 if old is not None else 1
                pending.append(merged)
            for start in range(0, len(pending), 50):
                inserted = session.execute(
                    insert(Bar).values(pending[start:start+50])
                    .on_conflict_do_nothing()
                    .returning(Bar.event_time)
                ).scalars().all()
                for stamp in inserted:
                    remaining.pop(_aware(stamp))
                total += len(inserted)
        if remaining:
            raise RuntimeError("Concurrent bar correction unresolved; roll back and retry")
    session.flush()
    return total
