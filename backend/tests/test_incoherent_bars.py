"""Removing rows that contradict themselves, and refusing to remove anything else.

The risk in a sweep that deletes market data is not that it misses a bad row.
It is that it takes a good one, or that it runs at all without leaving a way
back - and neither failure announces itself, because the evidence is what got
deleted.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from app.core.enums import Timeframe
from app.models.instruments import Instrument, Provider
from app.models.market_data import Bar
from app.ops import incoherent_bars

AT = datetime(2026, 9, 1, 12, 0, tzinfo=UTC)


@pytest.fixture()
def feed(session):
    provider = Provider(code="testing", name="Testing")
    instrument = Instrument(
        symbol="EURUSD",
        asset_class="forex",
        base_currency="EUR",
        quote_currency="USD",
        timezone="UTC",
    )
    session.add_all([provider, instrument])
    session.flush()
    return instrument, provider


def store(session, instrument, provider, *, at, o, h, low, c, revision=1):
    session.add(
        Bar(
            instrument_id=instrument.id,
            provider_id=provider.id,
            timeframe=Timeframe.D1,
            event_time=at,
            revision=revision,
            open=o,
            high=h,
            low=low,
            close=c,
            volume=1.0,
            ingested_at=at,
        )
    )
    session.flush()


class TestWhatItFinds:
    def test_a_close_below_the_low_is_found(self, session, feed):
        instrument, provider = feed
        store(session, instrument, provider, at=AT, o=1.10, h=1.12, low=1.09, c=1.08)

        sweep = incoherent_bars.find(session)

        assert len(sweep.found) == 1

    def test_a_close_above_the_high_is_found(self, session, feed):
        instrument, provider = feed
        store(session, instrument, provider, at=AT, o=1.10, h=1.12, low=1.09, c=1.13)

        assert len(incoherent_bars.find(session).found) == 1

    def test_an_open_outside_the_range_is_found(self, session, feed):
        instrument, provider = feed
        store(session, instrument, provider, at=AT, o=1.20, h=1.12, low=1.09, c=1.10)

        assert len(incoherent_bars.find(session).found) == 1

    def test_an_inverted_bar_is_found(self, session, feed):
        instrument, provider = feed
        store(session, instrument, provider, at=AT, o=1.10, h=1.05, low=1.15, c=1.10)

        sweep = incoherent_bars.find(session)

        assert len(sweep.found) == 1
        assert sweep.found[0].inverted is True

    def test_a_coherent_bar_is_left_alone(self, session, feed):
        instrument, provider = feed
        store(session, instrument, provider, at=AT, o=1.10, h=1.12, low=1.09, c=1.11)

        assert incoherent_bars.find(session).found == []

    def test_a_doji_is_coherent(self, session, feed):
        """All four prices equal is a bar that did not move, not a broken one.
        A comparison written with strict inequalities would take every one."""
        instrument, provider = feed
        store(session, instrument, provider, at=AT, o=1.1, h=1.1, low=1.1, c=1.1)

        assert incoherent_bars.find(session).found == []

    def test_only_the_newest_revision_is_judged(self, session, feed):
        """A superseded row being wrong is what revisions are for. Judging it
        would delete history the provider has already corrected."""
        instrument, provider = feed
        store(session, instrument, provider, at=AT, o=1.10, h=1.12, low=1.09, c=1.30)
        store(
            session, instrument, provider,
            at=AT, o=1.10, h=1.12, low=1.09, c=1.11, revision=2,
        )

        assert incoherent_bars.find(session).found == []

    def test_a_broken_newest_revision_is_still_found(self, session, feed):
        instrument, provider = feed
        store(session, instrument, provider, at=AT, o=1.10, h=1.12, low=1.09, c=1.11)
        store(
            session, instrument, provider,
            at=AT, o=1.10, h=1.12, low=1.09, c=1.30, revision=2,
        )

        found = incoherent_bars.find(session).found

        assert len(found) == 1
        assert found[0].revision == 2


class TestHowBadIsIt:
    def test_the_breach_is_reported_against_the_bars_own_range(self, session, feed):
        """Absolute price distance means nothing across instruments quoted in
        different units. The share of the bar's range is what separates a
        rounding artefact from a wrong row."""
        instrument, provider = feed
        # range 0.02, close one tenth of that below the low
        store(session, instrument, provider, at=AT, o=1.10, h=1.12, low=1.10, c=1.098)

        row = incoherent_bars.find(session).found[0]

        assert row.breach == pytest.approx(0.002)
        assert row.breach_share == pytest.approx(0.1)

    def test_a_zero_range_bar_reports_an_infinite_share(self, session, feed):
        """Dividing by the range would raise. A bar with no range whose close
        sits outside it is maximally wrong, not undefined."""
        instrument, provider = feed
        store(session, instrument, provider, at=AT, o=1.10, h=1.10, low=1.10, c=1.20)

        assert incoherent_bars.find(session).found[0].breach_share == float("inf")


class TestItCannotDeleteWithoutAWayBack:
    def test_remove_refuses_without_an_export(self, session, feed):
        instrument, provider = feed
        store(session, instrument, provider, at=AT, o=1.10, h=1.12, low=1.09, c=1.08)
        sweep = incoherent_bars.find(session)

        with pytest.raises(ValueError, match="exported"):
            incoherent_bars.remove(session, sweep)

        assert session.query(Bar).count() == 1, "nothing may be deleted"

    def test_the_export_carries_every_price(self, session, feed, tmp_path):
        """Re-fetching does not bring these back - the provider returns the
        same broken row - so the file has to be enough to restore from."""
        import json

        instrument, provider = feed
        store(session, instrument, provider, at=AT, o=1.10, h=1.12, low=1.09, c=1.08)
        sweep = incoherent_bars.find(session)

        path = incoherent_bars.export(sweep, tmp_path / "broken.jsonl")
        lines = [json.loads(line) for line in open(path, encoding="utf-8")]

        assert lines[0]["rows"] == 1
        row = lines[1]
        for field in ("open", "high", "low", "close", "event_time", "revision"):
            assert field in row
        assert row["close"] == 1.08

    def test_after_an_export_it_deletes_exactly_the_found_rows(
        self, session, feed, tmp_path
    ):
        instrument, provider = feed
        store(session, instrument, provider, at=AT, o=1.10, h=1.12, low=1.09, c=1.08)
        store(
            session, instrument, provider,
            at=AT + timedelta(days=1), o=1.10, h=1.12, low=1.09, c=1.11,
        )
        sweep = incoherent_bars.find(session)
        incoherent_bars.export(sweep, tmp_path / "broken.jsonl")

        removed = incoherent_bars.remove(session, sweep)

        assert removed == 1
        assert session.query(Bar).count() == 1, "the coherent bar stays"
        assert incoherent_bars.find(session).found == []
