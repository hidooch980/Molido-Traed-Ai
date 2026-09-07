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
from app.models.instruments import Instrument, Provider
from app.models.journal import (
    ARM_CONTROL,
    ARM_RULE,
    SOURCE_BROKER,
    SOURCE_PUBLIC,
    JournalEntry,
)
from app.models.market_data import Bar
from app.services import journal_log
from app.workers import forward

NOW = datetime(2026, 8, 15, 12, 0, tzinfo=UTC)


@pytest.fixture()
def provider(session):
    """The public feed, under its own name.

    Shadows the shared fixture on purpose. The rule now runs on two price
    series and the recorder reads whichever it was asked for, so a fixture
    whose provider is called "test" would produce a market no source ever
    reads - and every test here would pass by ranking nothing.
    """
    row = Provider(code=SOURCE_PUBLIC, name="Public feed", capabilities={"ohlcv": True})
    session.add(row)
    session.flush()
    return row


@pytest.fixture()
def market(session, provider):
    """Thirty instruments with enough history to rank, spread apart in price."""
    # Real universe symbols, not invented ones. The ranking only considers
    # instruments in `RANKED_UNIVERSE`, so a fixture built from SYM00..SYM29
    # would exercise nothing but the exclusion.
    from app.brain.crosssection import RANKED_UNIVERSE
    from app.core.enums import AssetClass

    universe = sorted(RANKED_UNIVERSE)[:30]
    for n, symbol in enumerate(universe):
        instrument = Instrument(
            symbol=symbol,
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

        from app.brain.crosssection import RANKED_UNIVERSE

        universe = sorted(RANKED_UNIVERSE)[:30]
        assert universe[0] in result["longs"]
        assert universe[29] in result["shorts"]

    def test_a_thin_market_records_nothing_and_says_why(self, session):
        result = forward.record_cycle(session, as_of=NOW)

        assert result["recorded"] == 0
        assert result["reason"]


class TestItFeedsTheComparison:
    def test_the_recorded_entries_reach_the_journal_summary(self, market):
        forward.record_cycle(market, as_of=NOW)

        described = journal_log.summary(market)

        assert described["arms"][SOURCE_PUBLIC][ARM_RULE]["recorded"] > 0
        assert described["arms"][SOURCE_PUBLIC][ARM_CONTROL]["recorded"] > 0
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
        # A crypto pair whose last bar is a day after everything else.
        from app.brain.crosssection import RANKED_UNIVERSE
        from app.core.enums import AssetClass

        # In the universe, and outside the thirty the fixture already created.
        late_symbol = sorted(RANKED_UNIVERSE)[35]
        crypto = Instrument(
            symbol=late_symbol, name="Trades late", asset_class=AssetClass.FOREX
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
        from app.brain.crosssection import RANKED_UNIVERSE
        from app.core.enums import AssetClass

        late_symbol = sorted(RANKED_UNIVERSE)[36]
        crypto = Instrument(
            symbol=late_symbol, name="Trades late", asset_class=AssetClass.FOREX
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

    def test_no_series_reaches_past_the_chosen_instant(self, market, session, provider):
        """Point-in-time integrity, and the one that would have been invisible.

        The instant is Friday whenever the weekend is on, because that is the
        last bar the FX book shares - and crypto keeps printing through
        Saturday. Reading every instrument up to *now* would put Saturday
        prices inside a Friday cross-section: the mean, the last close and
        therefore the stretch would all contain data from after the moment
        being decided on.

        That flatters the rule silently and would have gone into the forward
        series as evidence."""
        from app.brain.crosssection import RANKED_UNIVERSE
        from app.core.enums import AssetClass

        # In the universe, and outside the thirty the fixture already created.
        late_symbol = sorted(RANKED_UNIVERSE)[35]
        crypto = Instrument(
            symbol=late_symbol, name="Trades late", asset_class=AssetClass.FOREX
        )
        session.add(crypto)
        session.flush()
        # Bars either side of the instant the FX book will settle on.
        for i in range(forward.LOOKBACK + 24):
            session.add(
                Bar(
                    instrument_id=crypto.id,
                    timeframe=Timeframe.H1.value,
                    provider_id=provider.id,
                    event_time=NOW - timedelta(hours=forward.LOOKBACK - i),
                    revision=1,
                    ingested_at=NOW,
                    open=100,
                    high=101,
                    low=99,
                    close=100 + i,
                    volume=1,
                    quality_score=1.0,
                )
            )
        session.flush()

        built, instant = forward.snapshot(session, as_of=NOW + timedelta(days=2))

        assert instant is not None
        assert instant <= NOW
        # Every instrument's history stops at or before the instant - checked
        # through the recorded last bar, which is what the ranking reads.
        for symbol, payload in built.items():
            assert payload["last_at"] <= instant, symbol


class TestTheTwoSeriesDoNotMix:
    """The same rule runs on the public feed and on the broker's own prices,
    and the two quote the same instrument 33-39% of a stop distance apart -
    measured over 490 shared hourly bars. The edge being looked for is 0.021 R.

    So a decision taken on one series and priced off the other does not lose a
    little accuracy; it starts a third of the way to its stop in a random
    direction, which is fifteen times the effect being measured. These tests
    are about the two series staying separate all the way through."""

    @pytest.fixture()
    def broker(self, session, market):
        """The same instruments, at the broker's prices - deliberately
        different, and displaced the opposite way so a leak is visible in the
        ranking rather than only in the numbers."""
        row = Provider(
            code=SOURCE_BROKER, name="MetaTrader bridge", capabilities={"ohlcv": True}
        )
        session.add(row)
        session.flush()

        from app.brain.crosssection import RANKED_UNIVERSE

        universe = sorted(RANKED_UNIVERSE)[:30]
        for n, symbol in enumerate(universe):
            instrument = session.query(Instrument).filter_by(symbol=symbol).one()
            for i in range(forward.LOOKBACK):
                close = 100.0 if i < forward.LOOKBACK - 1 else 100.0 + (14 - n)
                session.add(
                    Bar(
                        instrument_id=instrument.id,
                        timeframe=Timeframe.H1.value,
                        provider_id=row.id,
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
        return row

    def test_a_snapshot_reads_only_the_series_it_was_asked_for(self, session, broker):
        public, _ = forward.snapshot(session, as_of=NOW, provider_code=SOURCE_PUBLIC)
        broker_side, _ = forward.snapshot(
            session, as_of=NOW, provider_code=SOURCE_BROKER
        )

        from app.brain.crosssection import RANKED_UNIVERSE

        symbol = sorted(RANKED_UNIVERSE)[0]
        assert public[symbol]["closes"][-1] != broker_side[symbol]["closes"][-1]

    def test_each_series_ranks_on_its_own_prices(self, session, broker):
        """The broker fixture displaces every instrument the opposite way, so
        a recorder reading the wrong series produces the opposite book. Equal
        answers here would mean one series is being read for both."""
        public = forward.record_cycle(session, as_of=NOW, price_source=SOURCE_PUBLIC)
        broker_side = forward.record_cycle(
            session, as_of=NOW, price_source=SOURCE_BROKER
        )

        assert public["recorded"] > 0
        assert broker_side["recorded"] > 0
        assert set(public["longs"]) == set(broker_side["shorts"])

    def test_a_missing_series_records_nothing_rather_than_borrowing_one(
        self, session, market
    ):
        """The broker provider does not exist in this database. The recorder
        must decline, not fall through to whatever bars it can find - a
        broker-side series quietly built from public prices would be the one
        failure this whole design exists to prevent, and it would look like a
        successful measurement."""
        result = forward.record_cycle(session, as_of=NOW, price_source=SOURCE_BROKER)

        assert result["recorded"] == 0
        assert result["reason"]

    def test_the_series_is_stamped_on_every_row(self, session, broker):
        """So a series read back years later can be identified rather than
        inferred from which symbols happen to appear."""
        forward.record_cycle(session, as_of=NOW, price_source=SOURCE_BROKER)

        rows = session.query(JournalEntry).all()
        assert rows
        assert {r.price_source for r in rows} == {SOURCE_BROKER}
        assert all(r.before.get("price_source") == SOURCE_BROKER for r in rows)

    def test_the_same_bar_is_decided_on_twice_without_colliding(
        self, session, broker
    ):
        """One row per (symbol, bar, arm) was one row too few once there were
        two series. Both decisions about the same bar have to survive."""
        forward.record_cycle(session, as_of=NOW, price_source=SOURCE_PUBLIC)
        forward.record_cycle(session, as_of=NOW, price_source=SOURCE_BROKER)

        by_source = {SOURCE_PUBLIC: 0, SOURCE_BROKER: 0}
        for row in session.query(JournalEntry).filter_by(arm=ARM_RULE).all():
            by_source[row.price_source] += 1

        assert by_source[SOURCE_PUBLIC] > 0
        assert by_source[SOURCE_PUBLIC] == by_source[SOURCE_BROKER]


class TestTimeframesDoNotCollide:
    """Every hour, four bars close on the same timestamp.

    The journal's identity was `(symbol, opened_at, arm, price_source)`, and
    the forward measurement ran on hourly bars alone so nothing needed to say
    which timeframe an entry came from. Widening it to four made that omission
    a bug at exactly the instants the timeframes align: three of four entries
    collide on one key and are discarded as duplicates, and the measurement
    looks like it is recording four timeframes while recording roughly one.
    """

    def test_two_timeframes_at_one_timestamp_are_both_recorded(self, session):
        from datetime import UTC, datetime

        from app.services import journal_log

        moment = datetime(2026, 8, 26, 12, 0, tzinfo=UTC)
        common = dict(
            symbol="EURUSD", decision="long", at=moment, price=1.1,
            stop_distance=0.001,
        )

        hourly = journal_log.record_with_control(session, timeframe="H1", **common)
        minute = journal_log.record_with_control(session, timeframe="M1", **common)

        assert hourly["rule"]["new"] is True
        assert minute["rule"]["new"] is True, (
            "the one-minute entry was discarded as a duplicate of the hourly "
            "one, which is the whole defect"
        )
        assert hourly["rule"]["entry_id"] != minute["rule"]["entry_id"]

    def test_the_same_timeframe_twice_is_still_one_entry(self, session):
        """Idempotency survives. A cycle overlapping the previous one must not
        inflate the sample the measurement rests on."""
        from datetime import UTC, datetime

        from app.services import journal_log

        moment = datetime(2026, 8, 26, 12, 0, tzinfo=UTC)
        common = dict(
            symbol="EURUSD", decision="long", at=moment, price=1.1,
            stop_distance=0.001, timeframe="M5",
        )

        first = journal_log.record_with_control(session, **common)
        again = journal_log.record_with_control(session, **common)

        assert first["rule"]["new"] is True
        assert again["rule"]["new"] is False
        assert first["rule"]["entry_id"] == again["rule"]["entry_id"]

    def test_the_control_arm_carries_the_timeframe_too(self, session):
        """Otherwise the control lands in the hourly bucket while the rule is
        labelled correctly, and the comparison compares two different things."""
        from datetime import UTC, datetime

        from app.models.journal import ARM_CONTROL, JournalEntry
        from app.services import journal_log

        moment = datetime(2026, 8, 26, 12, 0, tzinfo=UTC)
        journal_log.record_with_control(
            session, symbol="EURUSD", decision="long", at=moment, price=1.1,
            stop_distance=0.001, timeframe="M15",
        )

        control = session.query(JournalEntry).filter(
            JournalEntry.arm == ARM_CONTROL
        ).one()
        assert control.timeframe == "M15"

    def test_an_entry_written_without_one_is_hourly(self, session):
        """Every caller that predates the fast timeframes keeps writing what it
        wrote before, rather than landing in an unlabelled bucket."""
        from datetime import UTC, datetime

        from app.models.journal import JournalEntry
        from app.services import journal_log

        moment = datetime(2026, 8, 26, 13, 0, tzinfo=UTC)
        result = journal_log.record_with_control(
            session, symbol="GBPUSD", decision="short", at=moment, price=1.3,
            stop_distance=0.001,
        )

        entry = session.get(JournalEntry, result["rule"]["entry_id"])
        assert entry.timeframe == "H1"


class TestEveryBrainRecords:
    """The candidates are recorded beside the incumbent, on the same
    snapshot - so a comparison between brains can never be a comparison of
    schedules."""

    def test_candidate_recording_is_reported(self, session):
        from app.workers import forward

        report = forward.record_cycle(session, as_of=NOW)

        # With no bars there is nothing to decide, but the field exists and
        # counts - a cycle that records no candidates and one that never
        # tried are different facts.
        assert "candidates_recorded" in report or "reason" in report

    def test_two_brains_disagreeing_are_two_rows(self, session):
        from app.services import journal_log

        first = journal_log.record_decision(
            session,
            symbol="EURUSD",
            decision="long",
            at=NOW,
            strategy="cross-sectional-stretch",
        )
        second = journal_log.record_decision(
            session,
            symbol="EURUSD",
            decision="short",
            at=NOW,
            strategy="short-horizon-reversal",
        )

        assert first.new and second.new
        assert first.entry_id != second.entry_id


class TestAnInstrumentTheMarketHasAnsweredIsNotDecidedOn:
    """Eight WTI and BRENT decisions were journalled on 7 September against a
    cross-section that had settled on Friday 19:00 while a 20:00 bar was
    already stored. Every one closed at exactly minus one R on that stored
    bar: a forward journal had acquired entries whose answer existed first.

    The resolver was not at fault - it refuses bars at or before the entry.
    The recorder was."""

    def late_bar(self, session, provider, symbol, at):
        """One bar for `symbol` after the cross-section instant."""
        from sqlalchemy import select as _select

        from app.models.instruments import Instrument

        row = session.scalar(_select(Instrument).where(Instrument.symbol == symbol))
        session.add(
            Bar(
                instrument_id=row.id,
                timeframe=Timeframe.H1.value,
                provider_id=provider.id,
                event_time=at,
                revision=1,
                ingested_at=at,
                open=100,
                high=101,
                low=99,
                close=100,
                volume=1,
                quality_score=1.0,
            )
        )
        session.flush()
        return row.symbol

    def test_it_is_left_out_of_the_ranking(self, market, session, provider):
        before = forward.record_cycle(session)
        assert before["already_answered"] == 0

        symbol = sorted(before["longs"] + before["shorts"])[0]
        instant = datetime.fromisoformat(before["at"])
        self.late_bar(session, provider, symbol, instant + timedelta(hours=1))

        after = forward.record_cycle(session)

        assert symbol in after["already_answered_names"]
        assert symbol not in after["longs"] + after["shorts"]

    def test_the_rest_of_the_book_still_ranks(self, market, session, provider):
        """One instrument moving on is not a reason to stop deciding."""
        before = forward.record_cycle(session)
        symbol = sorted(before["longs"] + before["shorts"])[0]
        instant = datetime.fromisoformat(before["at"])
        self.late_bar(session, provider, symbol, instant + timedelta(hours=1))

        after = forward.record_cycle(session)

        assert after["considered"] > 0
        assert after["longs"] or after["shorts"]

    def test_a_shut_market_is_not_an_answered_one(self, market, session):
        """The whole book being old together is a weekend. Nothing has moved
        past the instant, so nothing drops out and the cycle still ranks."""
        result = forward.record_cycle(session, as_of=NOW + timedelta(days=2))

        assert result["already_answered"] == 0
        assert result["considered"] > 0


class TestAFeedThatHasFallenBehindTheOtherIsRefused:
    """The terminal that supplies the whole broker series was restarted and
    took ten minutes to refetch its history. For that window the broker series
    sat hours behind the public one, every decision taken on it was born
    outside the freshness window, and the accounts waited on candidates that
    could never arrive. The cycle reported success throughout, because
    collecting had succeeded.

    Measured feed against feed, never against the clock: a shut market leaves
    both equally old, and ranking Friday's close on a Saturday has to keep
    working. Two earlier attempts to write this guard against wall-clock age
    broke exactly that."""

    def broker_ending_at(self, session, upto):
        """The same instruments at the broker's prices, ending where told."""
        row = Provider(
            code=SOURCE_BROKER, name="MetaTrader bridge", capabilities={"ohlcv": True}
        )
        session.add(row)
        session.flush()

        from app.brain.crosssection import RANKED_UNIVERSE

        for symbol in sorted(RANKED_UNIVERSE)[:30]:
            instrument = session.query(Instrument).filter_by(symbol=symbol).one()
            for i in range(forward.LOOKBACK):
                session.add(
                    Bar(
                        instrument_id=instrument.id,
                        timeframe=Timeframe.H1.value,
                        provider_id=row.id,
                        event_time=upto - timedelta(hours=forward.LOOKBACK - 1 - i),
                        revision=1,
                        ingested_at=upto,
                        open=100.0,
                        high=101.0,
                        low=99.0,
                        close=100.0 + i,
                        volume=100,
                        quality_score=1.0,
                    )
                )
        session.flush()
        return row

    def test_a_broker_series_hours_behind_the_public_one_is_refused(
        self, session, market
    ):
        self.broker_ending_at(session, NOW - timedelta(hours=4))

        result = forward.record_cycle(session, as_of=NOW, price_source=SOURCE_BROKER)

        assert result["recorded"] == 0
        assert "behind" in result["reason"]
        assert result["feed_lag_bars"] >= forward.MAX_FEED_LAG_BARS

    def test_one_bar_behind_is_structural_and_still_ranks(self, session, market):
        """MetaTrader publishes only closed bars while the public feed carries
        the forming one, so a single bar of difference is permanent. A guard
        that refused it would refuse every cycle forever."""
        self.broker_ending_at(session, NOW - timedelta(hours=1))

        result = forward.record_cycle(session, as_of=NOW, price_source=SOURCE_BROKER)

        assert result["recorded"] > 0

    def test_a_current_broker_series_ranks(self, session, market):
        self.broker_ending_at(session, NOW)

        result = forward.record_cycle(session, as_of=NOW, price_source=SOURCE_BROKER)

        assert result["recorded"] > 0

    def test_both_feeds_equally_old_still_rank(self, session, market):
        """A weekend. Nothing has moved on either side since Friday, and the
        book still has to be ranked - this is the case the two wrong versions
        of this guard broke."""
        self.broker_ending_at(session, NOW)

        result = forward.record_cycle(
            session, as_of=NOW + timedelta(days=2), price_source=SOURCE_BROKER
        )

        assert result["recorded"] > 0

    def test_the_public_series_is_never_judged_against_itself(self, session, market):
        """It is the reference. Compared with itself it could only ever refuse
        every cycle the moment the comparison rounded the wrong way."""
        result = forward.record_cycle(session, as_of=NOW, price_source=SOURCE_PUBLIC)

        assert result["recorded"] > 0
