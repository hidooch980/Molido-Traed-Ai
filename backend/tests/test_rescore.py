"""Withdrawing the verdicts that were reached on the wrong bars.

The danger here is not the entries it touches, it is the ones it might: a
repair that silently re-opens correctly scored history would destroy more than
the fault did. So most of these tests are about what it leaves alone.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from app.core.enums import AssetClass, Timeframe
from app.models.instruments import Instrument
from app.models.journal import ARM_RULE, SOURCE_PUBLIC, JournalEntry
from app.workers import rescore

BEFORE = datetime(2026, 9, 4, 12, 0, tzinfo=UTC)
AFTER = datetime(2026, 9, 6, 12, 0, tzinfo=UTC)


def entry(session, *, timeframe, closed_at, outcome="win", r_multiple=1.0):
    row = JournalEntry(
        symbol="TESTFX",
        decision="long",
        opened_at=closed_at - timedelta(hours=2),
        arm=ARM_RULE,
        price_source=SOURCE_PUBLIC,
        timeframe=timeframe,
        closed_at=closed_at,
        outcome=outcome,
        r_multiple=r_multiple,
        before={"entry": 100.0, "stop": 97.5, "target": 102.5},
        after={"bars_to_resolve": 3},
    )
    session.add(row)
    session.flush()
    return row


def instrument(session):
    row = Instrument(symbol="TESTFX", name="Test", asset_class=AssetClass.FOREX)
    session.add(row)
    session.flush()
    return row


class TestItFindsExactlyTheMisScoredOnes:
    def test_an_m5_verdict_from_before_the_fix_is_found(self, session):
        instrument(session)
        entry(session, timeframe=Timeframe.M5.value, closed_at=BEFORE)

        assert len(rescore.candidates(session)) == 1

    def test_an_h1_verdict_is_left_alone(self, session):
        """H1 entries were always scored on H1 bars. They are the only ones
        the old default was right about."""
        instrument(session)
        entry(session, timeframe=Timeframe.H1.value, closed_at=BEFORE)

        assert rescore.candidates(session) == []

    def test_a_verdict_reached_after_the_fix_is_left_alone(self, session):
        instrument(session)
        entry(session, timeframe=Timeframe.M5.value, closed_at=AFTER)

        assert rescore.candidates(session) == []

    def test_an_entry_still_open_is_not_touched(self, session):
        instrument(session)
        row = entry(session, timeframe=Timeframe.M5.value, closed_at=BEFORE)
        row.closed_at = None
        row.outcome = None
        session.flush()

        assert rescore.candidates(session) == []


class TestItWithdrawsRatherThanErases:
    """This project does not rewrite history; it adds a correction beside it.
    A re-scored entry has to remain comparable with what the wrong bars said,
    because that comparison is the only way anybody can check this repair."""

    def test_the_retracted_verdict_is_kept(self, session):
        instrument(session)
        row = entry(
            session, timeframe=Timeframe.M5.value, closed_at=BEFORE, r_multiple=1.5
        )

        rescore.rescore(session, apply=True, now=AFTER)

        assert row.after["retracted"]["outcome"] == "win"
        assert row.after["retracted"]["r_multiple"] == 1.5
        assert row.after["retracted"]["detail"] == {"bars_to_resolve": 3}
        assert "H1 bars" in row.after["reason"]

    def test_the_entry_is_open_again(self, session):
        instrument(session)
        row = entry(session, timeframe=Timeframe.M5.value, closed_at=BEFORE)

        rescore.rescore(session, apply=True, now=AFTER)

        assert row.outcome is None
        assert row.closed_at is None
        assert row.r_multiple is None

    def test_the_decision_itself_is_untouched(self, session):
        """Only the claim about how it turned out was wrong."""
        instrument(session)
        row = entry(session, timeframe=Timeframe.M5.value, closed_at=BEFORE)

        rescore.rescore(session, apply=True, now=AFTER)

        assert row.decision == "long"
        assert row.before["entry"] == 100.0
        assert row.timeframe == Timeframe.M5.value

    def test_it_goes_to_the_front_of_the_resolver_s_rotation(self, session):
        """These are the entries this deployment broke, and the ones the
        scorecard is reading right now."""
        instrument(session)
        row = entry(session, timeframe=Timeframe.M5.value, closed_at=BEFORE)

        rescore.rescore(session, apply=True, now=AFTER)

        assert row.updated_at < BEFORE


class TestNothingHappensWithoutBeingAsked:
    def test_a_dry_run_changes_nothing(self, session):
        instrument(session)
        row = entry(session, timeframe=Timeframe.M5.value, closed_at=BEFORE)

        report = rescore.rescore(session, now=AFTER)

        assert report["found"] == 1
        assert report["applied"] is False
        assert row.outcome == "win"
        assert row.closed_at == BEFORE

    def test_the_dry_run_still_counts_what_it_would_touch(self, session):
        instrument(session)
        entry(session, timeframe=Timeframe.M5.value, closed_at=BEFORE)
        entry(session, timeframe=Timeframe.M15.value, closed_at=BEFORE, outcome="loss")

        report = rescore.rescore(session, now=AFTER)

        assert report["by_timeframe"] == {"M5": 1, "M15": 1}
        assert report["by_outcome"] == {"win": 1, "loss": 1}
