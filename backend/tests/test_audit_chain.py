"""The audit chain: an edit is provable, and history is never rewritten."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from sqlalchemy import select

from app.core.enums import AuditEventType
from app.models.audit import AuditChainHead, AuditEvent
from app.services import audit


def three(session):
    for i in range(3):
        audit.record(session, AuditEventType.SYSTEM_STARTED if hasattr(AuditEventType, "SYSTEM_STARTED") else "test.event", summary=f"event {i}", payload={"i": i})
    session.commit()


class TestRecording:
    def test_events_are_numbered_and_linked(self, session):
        three(session)
        rows = session.execute(select(AuditEvent).order_by(AuditEvent.sequence)).scalars().all()

        assert [r.sequence for r in rows] == [0, 1, 2]
        assert rows[0].previous_hash == audit.GENESIS_HASH
        assert rows[1].previous_hash == rows[0].entry_hash
        assert rows[2].previous_hash == rows[1].entry_hash
        head = session.get(AuditChainHead, 1)
        assert head.sequence == 2 and head.entry_hash == rows[2].entry_hash

    def test_the_chain_verifies(self, session):
        three(session)
        result = audit.verify(session)

        assert result.intact is True
        assert result.chained == 3 and result.pre_chain == 0
        assert result.problems == []


class TestTampering:
    def test_editing_a_payload_breaks_the_chain_at_that_row(self, session):
        three(session)
        victim = session.execute(select(AuditEvent).where(AuditEvent.sequence == 1)).scalar_one()
        victim.payload = {"i": 99}
        session.commit()

        result = audit.verify(session)

        assert result.intact is False
        assert result.first_broken_sequence == 1
        assert "does not hash to its own fields" in result.problems[0]

    def test_deleting_a_row_is_a_gap(self, session):
        three(session)
        victim = session.execute(select(AuditEvent).where(AuditEvent.sequence == 1)).scalar_one()
        session.delete(victim)
        session.commit()

        result = audit.verify(session)

        assert result.intact is False
        assert "gap" in result.problems[0]

    def test_a_backdated_row_is_reported(self, session):
        three(session)
        rows = session.execute(select(AuditEvent).order_by(AuditEvent.sequence)).scalars().all()
        # Re-hash consistently so only the ordering is wrong: a forger who
        # recomputes hashes still cannot move time backwards unnoticed.
        rows[2].occurred_at = rows[1].occurred_at - timedelta(days=1)
        rows[2].entry_hash = audit.entry_hash(rows[2], previous_hash=rows[1].entry_hash)
        head = session.get(AuditChainHead, 1)
        head.entry_hash = rows[2].entry_hash
        session.commit()

        result = audit.verify(session)

        assert result.intact is False
        assert "occurred before" in result.problems[0]


class TestPreChainRows:
    def test_old_rows_are_counted_not_verified_and_not_rewritten(self, session):
        legacy = AuditEvent(
            occurred_at=datetime(2026, 8, 1, tzinfo=UTC),
            service="backend",
            event_type="legacy.event",
            payload={},
        )
        session.add(legacy)
        session.commit()
        three(session)

        result = audit.verify(session)

        assert result.pre_chain == 1
        assert result.chained == 3
        assert result.intact is True
        session.refresh(legacy)
        assert legacy.sequence is None and legacy.entry_hash is None

    def test_an_empty_chain_is_not_intact(self, session):
        assert audit.verify(session).intact is False


class TestTail:
    def test_a_tail_walk_verifies_the_last_events_and_the_head(self, session):
        for i in range(10):
            audit.record(session, "test.event", payload={"i": i})
        session.commit()

        result = audit.verify(session, tail=3)

        assert result.intact is True and result.chained == 3

    def test_a_tail_walk_still_catches_a_tampered_tail(self, session):
        for i in range(10):
            audit.record(session, "test.event", payload={"i": i})
        session.commit()
        victim = session.execute(select(AuditEvent).where(AuditEvent.sequence == 9)).scalar_one()
        victim.summary = "rewritten"
        session.commit()

        assert audit.verify(session, tail=3).intact is False
