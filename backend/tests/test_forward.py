"""Writing down what the rule says, before the outcome exists.

This is the only thing in the system that can settle the question the project
turns on. The rule clears four of the five bars on history and fails the fifth
- forward evidence - and the only way to earn that is to record what it says on
data nobody has searched, before the answer is known.

So these tests are about the record being trustworthy rather than about the
rule being right: the same instant for every instrument, both arms together,
and no way to inflate the sample by running twice.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from app.core.enums import Timeframe
from app.models.instruments import Instrument
from app.models.journal import ARM_CONTROL, ARM_RULE, JournalEntry
from app.models.market_data import Bar
from app.services import journal_log
from app.workers import forward

NOW = datetime(2026, 8, 15, 12, 0, tzinfo=UTC)


@pytest.fixture()
def market(session, provider):
    """Thirty instruments with enough history to rank, spread apart in price."""
    from app.core.enums import AssetClass

    for n in range(30):
        instrument = Instrument(
            symbol=f"SYM{n:02d}",
            name=f"Test {n:02d}",
            asset_class=AssetClass.FOREX,
        )
        session.add(instrument)
        session.flush()
        base = 100.0
        for i in range(forward.LOOKBACK):
            # A flat history, then a final bar displaced by n - so the ranking
            # has a clean, known order.
            close = base if i < forward.LOOKBACK - 1 else base + (n - 15)
            session.add(
                Bar(
                    instrument_id=instrument.id,
                    timeframe=Timeframe.H1.value,
                    provider_id=provider.id,
                    event_time=NOW - timedelta(hours=forward.LOOKBACK - i),
                    revision=1,
                    ingested_at=NOW,
                    open=close,
                    high=close + 1,
                    low=close - 1,
                    close=close,
                    volume=100,
                    quality_score=1.0,
                )
            )
    session.flush()
    return session


class TestTheSnapshotIsOneInstant:
    def test_every_instrument_is_cut_at_the_same_bar(self, market):
        """A cross-section assembled from whatever each instrument last
        published would rank one instrument's Tuesday against another's
        Wednesday and call the difference a signal."""
        built, latest = forward.snapshot(market, as_of=NOW)

        assert latest is not None
        assert len(built) == 30
        assert all(len(v["closes"]) == forward.LOOKBACK for v in built.values())

    def test_an_instrument_without_enough_history_is_left_out(self, session):
        built, latest = forward.snapshot(session, as_of=NOW)

        assert built == {}
        assert latest is None


class TestRecording:
    def test_both_arms_are_written(self, market):
        result = forward.record_cycle(market, as_of=NOW)

        assert result["recorded"] > 0
        rule = market.query(JournalEntry).filter_by(arm=ARM_RULE).count()
        control = market.query(JournalEntry).filter_by(arm=ARM_CONTROL).count()
        assert rule == control > 0

    def test_the_reasoning_travels_with_the_decision(self, market):
        """A record with no reasoning cannot be re-examined, and a forward
        series that cannot be re-examined is a number to be believed."""
        forward.record_cycle(market, as_of=NOW)
        entry = market.query(JournalEntry).filter_by(arm=ARM_RULE).first()

        assert entry.before["rule"] == "cross-sectional-stretch"
        assert "stretch" in entry.before
        assert entry.before["stop_multiple"] == forward.STOP_MULTIPLE

    def test_running_twice_does_not_inflate_the_sample(self, market):
        """The whole measurement rests on this count. A cycle that overlaps the
        previous one must not double it."""
        first = forward.record_cycle(market, as_of=NOW)
        second = forward.record_cycle(market, as_of=NOW)

        assert first["recorded"] > 0
        assert second["recorded"] == 0
        assert second["already_recorded"] == first["recorded"]

    def test_both_tails_are_taken(self, market):
        result = forward.record_cycle(market, as_of=NOW)

        assert result["longs"]
        assert result["shorts"]
        assert len(result["longs"]) == len(result["shorts"])

    def test_the_extremes_are_the_ones_chosen(self, market):
        """SYM00 is furthest below its mean and SYM29 furthest above."""
        result = forward.record_cycle(market, as_of=NOW)

        assert "SYM00" in result["longs"]
        assert "SYM29" in result["shorts"]

    def test_a_thin_market_records_nothing_and_says_why(self, session):
        result = forward.record_cycle(session, as_of=NOW)

        assert result["recorded"] == 0
        assert result["reason"]


class TestItFeedsTheComparison:
    def test_the_recorded_entries_reach_the_journal_summary(self, market):
        forward.record_cycle(market, as_of=NOW)

        described = journal_log.summary(market)

        assert described["arms"][ARM_RULE]["recorded"] > 0
        assert described["arms"][ARM_CONTROL]["recorded"] > 0
        # Nothing has resolved, so the comparison must report nothing rather
        # than zero - an empty measurement is not a measurement of zero.
        assert described["comparison"]["edge_over_control"] is None


class TestTheInstantIsWhereTheMarketWas:
    """Not the newest bar anywhere. Those differ on every weekend: crypto
    trades through it and FX does not, so the newest bar in the database
    belongs to BTCUSD while every currency pair last printed on Friday.

    Taking the maximum made the whole FX book look two days stale against one
    instrument that never sleeps, and the staleness guard - correctly - threw
    all of it away. The first live cycle after that guard shipped ranked two
    instruments out of forty-nine."""

    def test_one_instrument_trading_late_does_not_move_the_instant(
        self, market, session, provider
    ):
        from app.core.enums import AssetClass

        # A crypto pair whose last bar is a day after everything else.
        crypto = Instrument(
            symbol="BTCUSD", name="Bitcoin", asset_class=AssetClass.CRYPTO
        )
        session.add(crypto)
        session.flush()
        for i in range(forward.LOOKBACK):
            session.add(
                Bar(
                    instrument_id=crypto.id,
                    timeframe=Timeframe.H1.value,
                    provider_id=provider.id,
                    event_time=NOW + timedelta(hours=i + 1),
                    revision=1,
                    ingested_at=NOW,
                    open=100,
                    high=101,
                    low=99,
                    close=100,
                    volume=1,
                    quality_score=1.0,
                )
            )
        session.flush()

        _, latest = forward.snapshot(session, as_of=NOW + timedelta(days=2))

        # The instant is where thirty instruments printed, not where one did.
        assert latest is not None
        assert latest <= NOW

    def test_the_whole_book_still_ranks_on_a_weekend(self, market, session, provider):
        """The failure this exists to prevent: everything excluded as stale
        because one instrument never sleeps."""
        from app.core.enums import AssetClass

        crypto = Instrument(
            symbol="ETHUSD", name="Ether", asset_class=AssetClass.CRYPTO
        )
        session.add(crypto)
        session.flush()
        for i in range(forward.LOOKBACK):
            session.add(
                Bar(
                    instrument_id=crypto.id,
                    timeframe=Timeframe.H1.value,
                    provider_id=provider.id,
                    event_time=NOW + timedelta(hours=i + 1),
                    revision=1,
                    ingested_at=NOW,
                    open=100,
                    high=101,
                    low=99,
                    close=100,
                    volume=1,
                    quality_score=1.0,
                )
            )
        session.flush()

        result = forward.record_cycle(session, as_of=NOW + timedelta(days=2))

        assert result["recorded"] > 0, result.get("reason")
        assert result["considered"] >= 30
