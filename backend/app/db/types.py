"""Portable column types.

Production runs on PostgreSQL and uses native `uuid`/`jsonb`. The test suite
runs on in-memory SQLite so the point-in-time, ingestion and tenant-isolation
regression tests execute everywhere — including CI with no database container.
These types let one set of models serve both without conditional code in the
model files.

`GUID` is a TypeDecorator rather than a plain `with_variant`: SQLite's driver
cannot bind a `uuid.UUID` object, so the value has to be converted on the way
in and rebuilt on the way out. Models still see `uuid.UUID` on both backends.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import CHAR, JSON, DateTime, Dialect, TypeDecorator
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PgUUID


class GUID(TypeDecorator):
    """UUID column: native `uuid` on PostgreSQL, `CHAR(36)` elsewhere."""

    impl = CHAR
    cache_ok = True

    def load_dialect_impl(self, dialect: Dialect):
        if dialect.name == "postgresql":
            return dialect.type_descriptor(PgUUID(as_uuid=True))
        return dialect.type_descriptor(CHAR(36))

    def process_bind_param(self, value: Any, dialect: Dialect) -> Any:
        if value is None:
            return None
        if not isinstance(value, uuid.UUID):
            value = uuid.UUID(str(value))
        if dialect.name == "postgresql":
            return value
        return str(value)

    def process_result_value(self, value: Any, dialect: Dialect) -> uuid.UUID | None:
        if value is None:
            return None
        if isinstance(value, uuid.UUID):
            return value
        return uuid.UUID(str(value))


class UTCDateTime(TypeDecorator):
    """Timestamp that is always timezone-aware UTC in Python.

    PostgreSQL `timestamptz` already round-trips an aware value; SQLite drops
    the offset and hands back a naive datetime. A naive timestamp in this
    system is not a cosmetic problem — the point-in-time comparisons that
    prevent lookahead would raise or, worse, compare against a wrong instant.
    So the offset is re-attached on read and normalised to UTC on write.
    """

    impl = DateTime
    cache_ok = True

    def load_dialect_impl(self, dialect: Dialect):
        return dialect.type_descriptor(DateTime(timezone=True))

    def process_bind_param(self, value: Any, dialect: Dialect) -> Any:
        if value is None:
            return None
        if isinstance(value, datetime) and value.tzinfo is not None:
            return value.astimezone(UTC)
        return value

    def process_result_value(self, value: Any, dialect: Dialect) -> datetime | None:
        if value is None:
            return None
        if value.tzinfo is None:
            return value.replace(tzinfo=UTC)
        return value.astimezone(UTC)


UUIDType = GUID()
JSONType = JSONB().with_variant(JSON(), "sqlite")
TimestampType = UTCDateTime()
