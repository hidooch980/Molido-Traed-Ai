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
from sqlalchemy import select

from app.core.enums import Timeframe
from app.models.instruments import Instrument, Provider
from app.models.market_data import Bar
from app.workers import broker_bars

NOW = datetime(2026, 8, 17, 12, 0, tzinfo=UTC)


def _write_reference(directory, hours: int = 3, bars: int = 400):
    """EURUSD as the bridge would publish it, on a clock `hours` ahead of UTC.

    Mirrors the public series the `alignable` fixture writes, so the alignment
    has a real peak to find.
    """
    from datetime import UTC, datetime, timedelta

    start = datetime(2026, 5, 1, tzinfo=UTC)
    price = 1.10
    lines = ["event_time,open,high,low,close,volume"]
    for i in range(bars):
        price += 0.0009 if (i * 7 + i // 3) % 5 else -0.0013
        stamped = start + timedelta(hours=i + hours)
        lines.append(
            f"{stamped:%Y.%m.%d %H:%M:%S},{price:.5f},{price + 0.0005:.5f},"
            f"{price - 0.0005:.5f},{price:.5f},1"
        )
    (directory / "molido_bars_EURUSD_H1.csv").write_text(
        "\n".join(lines) + "\n", encoding="utf-8"
    )


@pytest.fixture()
def bridge(tmp_path):
    """A bridge directory with one symbol's bars, as the expert writes them."""

    def write(symbol="XAUUSD", timeframe="H1", rows=3, base=2300.0):
        # The reference file the offset is aligned from. Published alongside
        # whatever the test asked for, because the ingest now measures the
        # broker's clock from what the bridge publishes rather than from what
        # is already stored - which is what lets a first run work at all.
        _write_reference(tmp_path)

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


@pytest.fixture(autouse=True)
def alignable(session):
    """A public series for the ingest to measure the broker's clock against.

    The ingest used to stamp the terminal's local time as UTC, which put every
    bar three hours in the future on this broker. It now measures the offset by
    alignment and refuses to store anything when it cannot - so every test here
    needs a public series to align against, exactly as production does.

    Autouse because the alternative is remembering it in nine places, and the
    one that gets forgotten fails with "ingested 0" rather than anything that
    points at the cause.
    """
    from datetime import UTC, datetime, timedelta

    from app.core.enums import AssetClass
    from app.models.instruments import Instrument, Provider
    from app.models.market_data import Bar

    public = session.scalar(select(Provider).where(Provider.code == "yfinance"))
    if public is None:
        public = Provider(code="yfinance", name="Public", capabilities={})
        session.add(public)
        session.flush()

    instrument = session.scalar(select(Instrument).where(Instrument.symbol == "EURUSD"))
    if instrument is None:
        instrument = Instrument(
            symbol="EURUSD", name="Euro", asset_class=AssetClass.FOREX
        )
        session.add(instrument)
        session.flush()

    start = datetime(2026, 5, 1, tzinfo=UTC)
    price = 1.10
    for i in range(400):
        # A walk, so the alignment has a sharp peak. A flat series matches
        # equally well at every lag and is correctly reported as unknown.
        price += 0.0009 if (i * 7 + i // 3) % 5 else -0.0013
        session.add(
            Bar(
                instrument_id=instrument.id,
                timeframe=Timeframe.H1.value,
                provider_id=public.id,
                event_time=start + timedelta(hours=i),
                revision=1,
                ingested_at=start,
                open=price,
                high=price + 0.0005,
                low=price - 0.0005,
                close=price,
                volume=1.0,
                quality_score=1.0,
            )
        )
    session.flush()
    return instrument


def broker_bars_for(session, symbol: str) -> int:
    """How many bars this symbol has under the broker's provider.

    Counted per symbol rather than globally: the bridge also publishes the
    EURUSD reference file the clock offset is aligned from, and that is real
    data the ingest should store. A global count would make every assertion
    here depend on the size of a fixture that exists for another reason.
    """
    from app.models.instruments import Provider

    return (
        session.query(Bar)
        .join(Instrument, Instrument.id == Bar.instrument_id)
        .join(Provider, Provider.id == Bar.provider_id)
        .filter(Instrument.symbol == symbol, Provider.code == broker_bars.PROVIDER_CODE)
        .count()
    )


class TestTheBrokerSeriesArrives:
    def test_bars_are_read_into_the_database(self, session, bridge):
        bridge()

        result = broker_bars.ingest(session, directory=bridge.directory, now=NOW)

        assert result["ingested"] > 0
        assert broker_bars_for(session, "XAUUSD") == 3

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
        first = (
            session.query(Bar)
            .join(Instrument, Instrument.id == Bar.instrument_id)
            .filter(Instrument.symbol == "XAUUSD")
            .order_by(Bar.event_time)
            .first()
        )

        assert float(first.open) == 2350.0


class TestItStaysSeparateFromThePublicFeed:
    def test_it_records_under_its_own_provider(self, session, bridge):  # noqa: D

        """Two sources writing one series means the last writer wins and the
        disagreement is never seen."""
        from app.models.instruments import Provider

        bridge()
        broker_bars.ingest(session, directory=bridge.directory, now=NOW)

        provider = session.query(Provider).filter_by(code="metatrader").one()
        assert session.query(Bar).filter_by(provider_id=provider.id).count() > 0
        assert broker_bars_for(session, "XAUUSD") == 3

    def test_the_public_series_is_untouched(self, session, bridge, alignable):
        """A public bar for the same instrument and hour must survive - the two
        are different measurements of the same market, and the comparison
        between them is the point.

        Uses the alignment fixture's own public series rather than the shared
        one: the offset is measured against yfinance, so a second public
        provider for the same instrument would be a second answer to the
        question this ingest has to settle first."""
        public_before = (
            session.query(Bar)
            .join(Provider, Provider.id == Bar.provider_id)
            .filter(Provider.code == "yfinance")
            .count()
        )
        bridge(symbol=alignable.symbol)

        broker_bars.ingest(session, directory=bridge.directory, now=NOW)

        public_after = (
            session.query(Bar)
            .join(Provider, Provider.id == Bar.provider_id)
            .filter(Provider.code == "yfinance")
            .count()
        )
        assert public_after == public_before


class TestRepublishingDoesNotMultiplyTheSeries:
    def test_running_twice_updates_rather_than_duplicating(self, session, bridge):
        """The bridge republishes the same 500 bars every cycle. Inserting them
        each time would multiply the series by the number of cycles."""
        bridge()
        broker_bars.ingest(session, directory=bridge.directory, now=NOW)
        broker_bars.ingest(session, directory=bridge.directory, now=NOW)

        assert broker_bars_for(session, "XAUUSD") == 3

    def test_a_revised_price_overwrites(self, session, bridge):
        bridge(base=2300.0)
        broker_bars.ingest(session, directory=bridge.directory, now=NOW)
        bridge(base=2400.0)
        broker_bars.ingest(session, directory=bridge.directory, now=NOW)

        first = (
            session.query(Bar)
            .join(Instrument, Instrument.id == Bar.instrument_id)
            .filter(Instrument.symbol == "XAUUSD")
            .order_by(Bar.event_time)
            .first()
        )
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
        # And the good file still landed. Counted per symbol: the reference
        # file the clock is aligned from is ingested too, and it is real data.
        assert broker_bars_for(session, "XAUUSD") == 3
