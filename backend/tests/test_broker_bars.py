"""Reading the bars the broker publishes, under their own provider.

The bridge wrote forty-six bar files every twenty seconds from the day it was
built and nothing read them. Every bar in this database came from Yahoo, which
means the system researched on one price series and would trade on another.

Spreads differ, session boundaries differ, weekend gaps land in different
places, and the same instrument is quoted differently at every broker. A rule
measured on one and executed against the other has been measured on something
adjacent to what it will do.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from app.core.enums import Timeframe
from app.models.instruments import Instrument
from app.models.market_data import Bar
from app.workers import broker_bars

NOW = datetime(2026, 8, 17, 12, 0, tzinfo=UTC)


@pytest.fixture()
def bridge(tmp_path):
    """A bridge directory with one symbol's bars, as the expert writes them."""

    def write(symbol="XAUUSD", timeframe="H1", rows=3, base=2300.0):
        lines = ["event_time,open,high,low,close,volume"]
        for hour in range(rows):
            price = base + hour
            lines.append(
                f"2026.08.17 0{hour}:00:00,{price},{price + 1},{price - 1},{price},100"
            )
        (tmp_path / f"molido_bars_{symbol}_{timeframe}.csv").write_text(
            "\n".join(lines), encoding="utf-8"
        )

    write.directory = tmp_path
    return write


class TestTheBrokerSeriesArrives:
    def test_bars_are_read_into_the_database(self, session, bridge):
        bridge()

        result = broker_bars.ingest(session, directory=bridge.directory, now=NOW)

        assert result["ingested"] == 3
        assert session.query(Bar).count() == 3

    def test_an_unknown_symbol_gets_an_instrument(self, session, bridge):
        """The broker offers instruments the public feed does not, and refusing
        to record them means the only series for gold is the one the account
        does not trade."""
        bridge(symbol="XAUEUR")

        broker_bars.ingest(session, directory=bridge.directory, now=NOW)

        assert session.query(Instrument).filter_by(symbol="XAUEUR").one()

    def test_the_prices_are_the_broker_s(self, session, bridge):
        bridge(base=2350.0)

        broker_bars.ingest(session, directory=bridge.directory, now=NOW)
        first = session.query(Bar).order_by(Bar.event_time).first()

        assert float(first.open) == 2350.0


class TestItStaysSeparateFromThePublicFeed:
    def test_it_records_under_its_own_provider(self, session, bridge):
        """Two sources writing one series means the last writer wins and the
        disagreement is never seen."""
        from app.models.instruments import Provider

        bridge()
        broker_bars.ingest(session, directory=bridge.directory, now=NOW)

        provider = session.query(Provider).filter_by(code="metatrader").one()
        assert session.query(Bar).filter_by(provider_id=provider.id).count() == 3

    def test_the_public_series_is_untouched(self, session, bridge, provider, instrument):
        """A yfinance bar for the same instrument and hour must survive - the
        two are different measurements of the same market, and the comparison
        between them is the point."""
        session.add(
            Bar(
                instrument_id=instrument.id,
                timeframe=Timeframe.H1.value,
                provider_id=provider.id,
                event_time=datetime(2026, 8, 17, 0, tzinfo=UTC),
                revision=1,
                ingested_at=NOW,
                open=1.0,
                high=1.1,
                low=0.9,
                close=1.0,
                volume=1,
                quality_score=1.0,
            )
        )
        session.flush()
        bridge(symbol=instrument.symbol)

        broker_bars.ingest(session, directory=bridge.directory, now=NOW)

        public = session.query(Bar).filter_by(provider_id=provider.id).one()
        assert float(public.open) == 1.0


class TestRepublishingDoesNotMultiplyTheSeries:
    def test_running_twice_updates_rather_than_duplicating(self, session, bridge):
        """The bridge republishes the same 500 bars every cycle. Inserting them
        each time would multiply the series by the number of cycles."""
        bridge()
        broker_bars.ingest(session, directory=bridge.directory, now=NOW)
        broker_bars.ingest(session, directory=bridge.directory, now=NOW)

        assert session.query(Bar).count() == 3

    def test_a_revised_price_overwrites(self, session, bridge):
        bridge(base=2300.0)
        broker_bars.ingest(session, directory=bridge.directory, now=NOW)
        bridge(base=2400.0)
        broker_bars.ingest(session, directory=bridge.directory, now=NOW)

        first = session.query(Bar).order_by(Bar.event_time).first()
        assert float(first.open) == 2400.0


class TestNothingFailsQuietly:
    def test_a_missing_directory_says_so(self, session, tmp_path):
        result = broker_bars.ingest(session, directory=tmp_path / "absent", now=NOW)

        assert result["ingested"] == 0
        assert "not mounted" in result["reason"]

    def test_an_unreadable_file_is_named(self, session, bridge):
        """A symbol that silently stops arriving looks identical to one the
        broker stopped quoting."""
        bridge()
        (bridge.directory / "molido_bars_BROKEN_H1.csv").write_text(
            "event_time,open\nnot a date,x", encoding="utf-8"
        )

        result = broker_bars.ingest(session, directory=bridge.directory, now=NOW)

        assert any("BROKEN" in note for note in result["failures"])
        # And the good file still landed.
        assert result["ingested"] == 3
