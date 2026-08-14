"""Operational memory: what broke, what was tried, and whether it worked.

Without this the system starts from zero every time. The same failure is
diagnosed again, the same remedy is rediscovered, and an alert that has fired
four hundred times looks exactly like one firing for the first time.

Two decisions shape the table.

Occurrences are counted on one row rather than appended as new ones. A
fingerprint - the stable part of a failure, with timestamps and instance ids
stripped out - is what makes "this is the same thing again" a fact rather than
an impression. It is also the only thing that can carry an alert cooldown: you
cannot suppress a repeat you cannot recognise.

Resolution is recorded with evidence, not with a button. `resolved_at` is set
when the signal that raised the incident stops being true, and `remedy` is
credited only when a later occurrence of the same fingerprint cleared after it.
Anything looser records a coincidence and hands it to the next reader as
knowledge.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin
from app.db.types import JSONType, TimestampType


class Incident(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "incidents"

    #: The stable identity of a failure, with everything variable removed. Two
    #: occurrences share it or they are different incidents; there is no third
    #: answer, which is what makes counting and cooldown possible at all.
    fingerprint: Mapped[str] = mapped_column(String(200), nullable=False, index=True)

    #: Where the signal came from: a container healthcheck, a readiness probe,
    #: a data-quality sweep, a worker. Recorded so a remedy can be judged
    #: against the kind of thing it fixed.
    source: Mapped[str] = mapped_column(String(60), nullable=False, index=True)

    #: What a person reads first. Short, specific, and free of timestamps -
    #: those live in the columns, and putting them here would make every
    #: occurrence look unique.
    summary: Mapped[str] = mapped_column(String(400), nullable=False)

    #: info / warning / serious / critical. Stored as text rather than an enum
    #: column so a new level does not need a migration to be recorded, and
    #: validated in the service where the meaning lives.
    severity: Mapped[str] = mapped_column(String(20), nullable=False, index=True)

    #: How many times this exact failure has been seen. The first occurrence
    #: sets it to 1; nothing ever resets it, because a problem that returns
    #: after being fixed is more interesting than one that never left.
    occurrences: Mapped[int] = mapped_column(Integer, default=1, nullable=False)

    first_seen_at: Mapped[datetime] = mapped_column(TimestampType, nullable=False)
    last_seen_at: Mapped[datetime] = mapped_column(TimestampType, nullable=False, index=True)

    #: Set when the raising signal stops being true, and cleared again if it
    #: returns. An open incident is one the system currently believes is real.
    resolved_at: Mapped[datetime | None] = mapped_column(TimestampType, nullable=True)

    #: What was done, if anything. Free text on purpose: the useful remedies
    #: are sentences, and a fixed vocabulary invented up front would describe
    #: the failures somebody imagined rather than the ones that happened.
    remedy: Mapped[str | None] = mapped_column(Text, nullable=True)

    #: True only when a later occurrence of this fingerprint cleared after the
    #: remedy was applied. Anything looser is a coincidence being handed to the
    #: next reader as knowledge.
    remedy_confirmed: Mapped[bool] = mapped_column(default=False, nullable=False)

    #: When an alert last went out for this fingerprint. The cooldown reads
    #: this and nothing else, so suppression survives a restart - an in-memory
    #: cooldown forgets on the one event most likely to cause a storm.
    last_alerted_at: Mapped[datetime | None] = mapped_column(TimestampType, nullable=True)

    #: Whatever the signal carried. Kept whole rather than flattened into
    #: columns, because the field that turns out to matter is never the one
    #: anybody predicted.
    details: Mapped[dict[str, Any]] = mapped_column(JSONType, default=dict, nullable=False)
