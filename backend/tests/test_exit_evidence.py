"""Weekly exit evidence from the journal's recorded paths."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from app.learning import exit_evidence as ee
from app.models.journal import ARM_RULE, JournalEntry

START = datetime(2026, 9, 1, tzinfo=UTC)


def _row(session, i, *, r, best, worst, strategy="tsm", symbol=None, hours_open=1, recorded=True):
    after = {"best_r_before_close": best, "worst_r_before_close": worst} if recorded else {}
    session.add(
        JournalEntry(
            symbol=symbol or f"S{i}",
            decision="long",
            opened_at=START + timedelta(hours=i * 3),
            closed_at=START + timedelta(hours=i * 3 + hours_open),
            arm=ARM_RULE,
            strategy=strategy,
            r_multiple=r,
            price_source="metatrader",
            after=after,
            during={},
        )
    )


def test_losers_that_were_ahead_propose_a_stop_to_entry(session):
    for i in range(20):
        _row(session, i, r=-1.0, best=0.8, worst=-0.9)  # losers that had been at +0.8
    for i in range(20, 40):
        _row(session, i, r=1.5, best=1.5, worst=-0.2)  # winners that never dipped
    session.flush()

    [brain] = ee.evidence(session)

    assert brain.positions == 40
    assert brain.losers_ahead[0.7] == 20
    assert any("stop to entry at +0.5R" in p for p in brain.proposals())


def test_nothing_is_said_below_the_minimum(session):
    for i in range(10):
        _row(session, i, r=-1.0, best=0.9, worst=-0.9)
    for i in range(10, 20):
        _row(session, i, r=1.5, best=1.5, worst=-0.1)
    session.flush()

    [brain] = ee.evidence(session)
    assert brain.positions < ee.MIN_POSITIONS
    assert brain.proposals() == []
    assert "حکمی نیست" in ee.compose([brain])


def test_winners_that_went_deep_block_the_proposal(session):
    for i in range(20):
        _row(session, i, r=-1.0, best=0.8, worst=-0.9)
    for i in range(20, 40):
        _row(session, i, r=1.5, best=1.5, worst=-0.8)  # every winner dipped below -0.5
    session.flush()

    [brain] = ee.evidence(session)
    assert not any("stop to entry" in p for p in brain.proposals())


def test_repeats_of_one_position_count_once_and_unrecorded_rows_are_skipped(session):
    _row(session, 0, r=-1.0, best=0.8, worst=-0.9, symbol="EURUSD", hours_open=10)
    _row(session, 1, r=-1.0, best=0.8, worst=-0.9, symbol="EURUSD", hours_open=10)  # opens while 0 is open
    _row(session, 2, r=1.5, best=1.5, worst=-0.1, recorded=False)
    session.flush()

    [brain] = ee.evidence(session)
    assert brain.positions == 1
