"""Closing the entries the market has answered.

Without a resolver the journal fills up and never produces a number: every
entry open, `resolved` at zero, and the comparison the project rests on
reporting nothing for months in a way that looks like patience rather than
silence. That is the failure these tests exist to prevent.

The rest of them are about scoring the forward series under exactly the rules
the historical measurement used. A forward series scored differently is not a
confirmation of the backtest; it is a second unrelated measurement wearing the
same name.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from app.core.enums import AssetClass, Timeframe
from app.models.instruments import Instrument, Provider
from app.models.journal import ARM_RULE, SOURCE_BROKER, SOURCE_PUBLIC, JournalEntry
from app.models.market_data import Bar
from app.workers import resolve

NOW = datetime(2026, 8, 15, 12, 0, tzinfo=UTC)


@pytest.fixture()
def provider(session):
    """The public feed, under its own name.

    Shadows the shared fixture. An entry is now scored on the series it was
    decided on, so bars written under a provider called "test" are bars no
    decision will ever be resolved against.
    """
    row = Provider(code=SOURCE_PUBLIC, name="Public feed", capabilities={"ohlcv": True})
    session.add(row)
    session.flush()
    return row


@pytest.fixture()
def symbol(session, provider):
    row = Instrument(symbol="TESTFX", name="Test", asset_class=AssetClass.FOREX)
    session.add(row)
    session.flush()
    return row


def bars(session, provider, instrument, prices, *, start=NOW):
    """One bar per hour, each spanning (low, high) around its price."""
    for i, (low, high) in enumerate(prices, start=1):
        session.add(
            Bar(
                instrument_id=instrument.id,
                timeframe=Timeframe.H1.value,
                provider_id=provider.id,
                event_time=start + timedelta(hours=i),
                revision=1,
                ingested_at=start,
                open=(low + high) / 2,
                high=high,
                low=low,
                close=(low + high) / 2,
                volume=1,
                quality_score=1.0,
            )
        )
    session.flush()


def entry(
    session,
    *,
    side="long",
    price=100.0,
    stop=97.5,
    target=102.5,
    at=NOW,
    price_source=SOURCE_PUBLIC,
):
    row = JournalEntry(
        symbol="TESTFX",
        decision=side,
        opened_at=at,
        arm=ARM_RULE,
        price_source=price_source,
        before={
            "entry": price,
            "stop": stop,
            "target": target,
            "atr": 1.0,
            "stop_multiple": 2.5,
        },
    )
    session.add(row)
    session.flush()
    return row


class TestItProducesNumbersAtAll:
    def test_a_target_hit_closes_as_a_win(self, session, provider, symbol):
        row = entry(session)
        bars(session, provider, symbol, [(99.0, 101.0), (101.0, 103.0)])

        report = resolve.resolve_open(session, now=NOW + timedelta(hours=5))

        assert report["resolved"] == 1
        assert row.outcome == "win"
        assert row.r_multiple == pytest.approx(1.0)

    def test_a_stop_hit_closes_as_a_loss(self, session, provider, symbol):
        row = entry(session)
        bars(session, provider, symbol, [(99.0, 101.0), (97.0, 99.0)])

        resolve.resolve_open(session, now=NOW + timedelta(hours=5))

        assert row.outcome == "loss"
        assert row.r_multiple == -1.0

    def test_a_short_is_scored_the_other_way(self, session, provider, symbol):
        row = entry(session, side="short", stop=102.5, target=97.5)
        bars(session, provider, symbol, [(97.0, 99.0)])

        resolve.resolve_open(session, now=NOW + timedelta(hours=5))

        assert row.outcome == "win"


class TestTheRefusals:
    def test_a_bar_that_touched_both_is_dropped_not_guessed(
        self, session, provider, symbol
    ):
        """Which came first is unknowable at this resolution, and the
        convention that picks one is a thumb on the scale that shows up as an
        edge. The historical test dropped these too."""
        row = entry(session)
        bars(session, provider, symbol, [(97.0, 103.0)])

        report = resolve.resolve_open(session, now=NOW + timedelta(hours=5))

        assert report["resolved"] == 0
        assert row.closed_at is None

    def test_an_undecided_entry_stays_open(self, session, provider, symbol):
        """A trade still running is not a trade that broke even, and counting
        it as one makes every measurement pessimistic exactly when the market
        was trending."""
        row = entry(session)
        bars(session, provider, symbol, [(99.5, 100.5), (99.0, 101.0)])

        report = resolve.resolve_open(session, now=NOW + timedelta(hours=5))

        assert report["still_open"] == 1
        assert row.outcome is None
        assert row.closed_at is None

    def test_the_entry_bar_itself_is_never_used(self, session, provider, symbol):
        """Its own high and low say nothing about what happened next, and using
        them is lookahead wearing the costume of a fill."""
        row = entry(session)
        # A bar AT the entry instant that would have hit the target.
        bars(session, provider, symbol, [(99.0, 105.0)], start=NOW - timedelta(hours=1))

        report = resolve.resolve_open(session, now=NOW + timedelta(hours=5))

        assert report["resolved"] == 0
        assert row.outcome is None

    def test_the_horizon_drops_rather_than_scoring_breakeven(
        self, session, provider, symbol
    ):
        """Scoring these as breakeven would make the forward series measure
        something the backtest never did."""
        row = entry(session)
        bars(session, provider, symbol, [(99.9, 100.1)] * (resolve.HORIZON + 5))

        report = resolve.resolve_open(session, now=NOW + timedelta(days=30))

        assert report["abandoned"] == 1
        assert row.outcome == "abandoned"
        assert row.r_multiple is None


class TestNothingDisappearsQuietly:
    def test_an_entry_with_no_levels_is_named_when_it_is_retired(
        self, session, provider, symbol
    ):
        """One that can never resolve shrinks the sample every measurement
        rests on, and it must not do that silently.

        It is counted and given a written reason on the row, once, rather than
        listed as unresolvable on every cycle forever - see
        `TestAnEntryThatCanNeverResolveIsRetiredOnce`. Naming it once is what
        keeps it from disappearing quietly; naming it forever is what stops
        anybody reading the list."""
        row = JournalEntry(
            symbol="TESTFX", decision="long", opened_at=NOW, arm=ARM_RULE, before={}
        )
        session.add(row)
        session.flush()

        report = resolve.resolve_open(session, now=NOW + timedelta(hours=5))

        assert report["excluded_unscoreable"] == 1
        assert "no geometry to score it against" in (
            session.get(JournalEntry, row.id).after["reason"]
        )

    def test_an_entry_for_a_missing_instrument_is_named(self, session):
        row = JournalEntry(
            symbol="GONE",
            decision="long",
            opened_at=NOW,
            arm=ARM_RULE,
            before={"entry": 1.0, "stop": 0.9, "target": 1.1},
        )
        session.add(row)
        session.flush()

        report = resolve.resolve_open(session, now=NOW + timedelta(hours=5))

        assert "GONE" in report["unresolvable"]

    def test_a_closed_entry_is_not_reopened(self, session, provider, symbol):
        row = entry(session)
        bars(session, provider, symbol, [(101.0, 103.0)])
        resolve.resolve_open(session, now=NOW + timedelta(hours=5))
        first = row.outcome

        report = resolve.resolve_open(session, now=NOW + timedelta(hours=9))

        assert report["considered"] == 0
        assert row.outcome == first


class TestItFeedsTheComparison:
    def test_resolved_entries_reach_the_journal_summary(self, session, provider, symbol):
        from app.services import journal_log

        entry(session)
        bars(session, provider, symbol, [(101.0, 103.0)])
        resolve.resolve_open(session, now=NOW + timedelta(hours=5))

        described = journal_log.summary(session)

        assert described["arms"][SOURCE_PUBLIC][ARM_RULE]["resolved"] == 1


class TestAnEntryIsScoredOnTheSeriesItWasDecidedOn:
    """Both series run in parallel and they price the same instrument 33-39%
    of a stop distance apart. An entry whose levels came from one and whose
    fills are read off the other is not slightly noisy - it starts a third of
    the way to its stop in a random direction, which is fifteen times the edge
    being measured, and it would corrupt both series at once."""

    @pytest.fixture()
    def broker(self, session):
        row = Provider(
            code=SOURCE_BROKER, name="MetaTrader bridge", capabilities={"ohlcv": True}
        )
        session.add(row)
        session.flush()
        return row

    def test_the_other_series_cannot_close_it(self, session, symbol, provider, broker):
        """The broker's bars run straight through the target. The entry was
        decided on the public feed, which never moves, so it must stay open."""
        bars(session, provider, symbol, [(99.5, 100.5)] * 5)
        bars(session, broker, symbol, [(102.0, 103.0)] * 5)
        entry(session, price_source=SOURCE_PUBLIC)

        report = resolve.resolve_open(session, now=NOW + timedelta(hours=10))

        assert report["resolved"] == 0
        assert report["still_open"] == 1

    def test_its_own_series_closes_it(self, session, symbol, provider, broker):
        """The mirror of the test above, and the reason it is not just a test
        that nothing resolves."""
        bars(session, provider, symbol, [(99.5, 100.5)] * 5)
        bars(session, broker, symbol, [(102.0, 103.0)] * 5)
        entry(session, price_source=SOURCE_BROKER)

        report = resolve.resolve_open(session, now=NOW + timedelta(hours=10))

        assert report["resolved"] == 1
        assert report["resolved_by_source"] == {SOURCE_BROKER: 1}
        assert session.query(JournalEntry).one().outcome == "win"

    def test_an_unreadable_series_is_named_not_left_open_forever(
        self, session, symbol, provider
    ):
        """An entry recorded against a series this deployment cannot read will
        otherwise sit open for the life of the deployment, shrinking the sample
        every measurement rests on without ever saying why."""
        bars(session, provider, symbol, [(102.0, 103.0)] * 5)
        entry(session, price_source=SOURCE_BROKER)

        report = resolve.resolve_open(session, now=NOW + timedelta(hours=10))

        assert report["resolved"] == 0
        assert any(SOURCE_BROKER in note for note in report["unresolvable"])


class TestAnEntryThatCanNeverResolveIsRetiredOnce:
    """Nineteen entries on the live deployment were recorded before the
    recorder stored its levels. They cannot be scored at any future time, so
    leaving them open put them in `unresolvable` on every cycle for the life of
    the deployment - and a warning that is permanently on is a warning nobody
    reads. This project has already had one of those."""

    def bare(self, session, symbol="TESTFX"):
        row = JournalEntry(
            symbol=symbol,
            decision="long",
            opened_at=NOW,
            arm=ARM_RULE,
            price_source=SOURCE_PUBLIC,
            before={"rule": "cross-sectional-stretch"},
        )
        session.add(row)
        session.flush()
        return row

    def test_it_is_closed_rather_than_reported_forever(
        self, session, symbol, provider
    ):
        row = self.bare(session)

        first = resolve.resolve_open(session, now=NOW + timedelta(hours=2))
        second = resolve.resolve_open(session, now=NOW + timedelta(hours=3))

        assert first["excluded_unscoreable"] == 1
        assert second["excluded_unscoreable"] == 0
        assert second["unresolvable"] == []
        assert session.get(JournalEntry, row.id).closed_at is not None

    def test_it_is_kept_not_deleted(self, session, symbol, provider):
        """The decision was really made. What is retired is only the claim
        that the market might still answer it."""
        row = self.bare(session)

        resolve.resolve_open(session, now=NOW + timedelta(hours=2))

        stored = session.get(JournalEntry, row.id)
        assert stored is not None
        assert stored.outcome == "excluded"
        assert "no geometry to score it against" in stored.after["reason"]

    def test_it_never_counts_toward_the_comparison(self, session, symbol, provider):
        """An r_multiple of None keeps it out of both arms. Scoring it as zero
        would put a breakeven into a measurement it was never part of."""
        from app.services import journal_log

        self.bare(session)
        resolve.resolve_open(session, now=NOW + timedelta(hours=2))

        stored = session.query(JournalEntry).one()
        assert stored.r_multiple is None
        assert journal_log.comparison(session).rule_trials == 0

    def test_an_entry_with_levels_is_untouched_by_this(
        self, session, symbol, provider
    ):
        """The guard must retire only what cannot be scored, never a live
        entry the market has simply not answered yet."""
        row = entry(session)
        bars(session, provider, symbol, [(99.5, 100.5)])

        report = resolve.resolve_open(session, now=NOW + timedelta(hours=2))

        assert report["excluded_unscoreable"] == 0
        assert report["still_open"] == 1
        assert session.get(JournalEntry, row.id).closed_at is None
