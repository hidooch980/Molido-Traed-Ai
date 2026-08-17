"""The broker's clock, measured instead of assumed.

`broker_bars.py` assumed GMT+0 and said so in a comment. Aligning EURUSD
against the public feed puts the best match at +3, where the mean absolute
difference falls from 8.67 pips to 3.99. Every bar ingested under the old
assumption sat three hours in the future.

Two things were reported as findings because of it before anybody checked: the
"33-39% of a stop distance" gap between the two venues, which justified running
the measurement on both price series at all, and an hour's difference in the
cross-section's instant that was explained as a real session boundary.

So these tests are about the two ways this goes wrong again: an offset believed
on thin evidence, and an offset written down instead of measured.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from app.core.enums import AssetClass, Timeframe
from app.models.instruments import Instrument, Provider
from app.models.market_data import Bar
from app.workers import broker_offset

START = datetime(2026, 5, 1, tzinfo=UTC)


@pytest.fixture()
def aligned(session):
    """Two series of the same market, the broker's stamped `shift` hours on."""

    def build(shift_hours: int, *, bars: int = 400, noise: float = 0.0):
        instrument = session.scalar(
            __import__("sqlalchemy").select(Instrument).where(
                Instrument.symbol == "EURUSD"
            )
        )
        if instrument is None:
            instrument = Instrument(
                symbol="EURUSD", name="Euro", asset_class=AssetClass.FOREX
            )
            session.add(instrument)
            session.flush()

        rows = {}
        for code in ("yfinance", "metatrader"):
            provider = session.scalar(
                __import__("sqlalchemy").select(Provider).where(Provider.code == code)
            )
            if provider is None:
                provider = Provider(code=code, name=code, capabilities={})
                session.add(provider)
                session.flush()
            rows[code] = provider

        # A deterministic random walk, not a periodic wave. A periodic series
        # aligns almost as well one lag either side, so the margin check
        # correctly calls it ambiguous - real prices do not repeat like that,
        # and the live alignment showed a sharp peak (3.99 pips against 5.61
        # at the next candidate).
        import random

        walk = random.Random(20260817)
        price = 1.10
        prices = []
        for _ in range(bars + 24):
            price += walk.uniform(-0.0015, 0.0015)
            prices.append(price)

        for i in range(bars):
            price = prices[i]
            for code, provider in rows.items():
                stamped = START + timedelta(hours=i)
                value = price
                if code == "metatrader":
                    stamped += timedelta(hours=shift_hours)
                    value = price + noise
                session.add(
                    Bar(
                        instrument_id=instrument.id,
                        timeframe=Timeframe.H1.value,
                        provider_id=provider.id,
                        event_time=stamped,
                        revision=1,
                        ingested_at=START,
                        open=value,
                        high=value + 0.0005,
                        low=value - 0.0005,
                        close=value,
                        volume=1.0,
                        quality_score=1.0,
                    )
                )
        session.flush()
        return instrument

    return build


def _publish_reference(directory, *, shift_hours: int, extra: str | None = None):
    """EURUSD as the bridge publishes it, on a clock `shift_hours` ahead.

    The ingest measures the offset from the files it is about to read rather
    than from stored bars, because on a fresh deployment nothing is stored yet
    and a database-only measurement can never succeed on the first pass.
    """
    import random

    walk = random.Random(20260817)
    price = 1.10
    lines = ["event_time,open,high,low,close,volume"]
    for i in range(400):
        price += walk.uniform(-0.0015, 0.0015)
        stamped = START + timedelta(hours=i + shift_hours)
        lines.append(
            f"{stamped:%Y.%m.%d %H:%M:%S},{price:.5f},{price + 0.0005:.5f},"
            f"{price - 0.0005:.5f},{price:.5f},1"
        )
    if extra:
        lines.append(f"{extra},1.15,1.16,1.14,1.155,100")
    (directory / "molido_bars_EURUSD_H1.csv").write_text(
        chr(10).join(lines) + chr(10), encoding="utf-8"
    )


class TestItFindsTheRealOffset:
    def test_a_three_hour_broker_clock_is_measured(self, session, aligned):
        """The live case. RoboForex runs GMT+3 in summer."""
        aligned(3)

        found = broker_offset.measure(session)

        assert found.hours == 3
        assert found.known is True

    def test_a_zero_offset_is_measured_as_zero(self, session, aligned):
        """A broker that really does run UTC must not be shifted."""
        aligned(0)

        assert broker_offset.measure(session).hours == 0

    def test_a_negative_offset_is_found_too(self, session, aligned):
        """Not every broker is east of London."""
        aligned(-5)

        assert broker_offset.measure(session).hours == -5

    def test_a_small_venue_difference_does_not_break_alignment(
        self, session, aligned
    ):
        """The two feeds genuinely differ by a few pips. That is the thing
        being measured around, not an obstacle to it."""
        aligned(3, noise=0.0004)

        assert broker_offset.measure(session).hours == 3


class TestItRefusesRatherThanGuessing:
    def test_a_flat_series_gives_no_answer(self, session, aligned):
        """Every lag aligns equally well, so the winner is noise. Picking the
        marginally lowest is how a wrong offset gets applied confidently."""
        aligned(3)
        # Overwrite both series with a constant price.
        for bar in session.query(Bar).all():
            bar.close = 1.1
        session.flush()

        found = broker_offset.measure(session)

        assert found.known is False
        assert "not clearly better" in found.reason

    def test_too_little_overlap_gives_no_answer(self, session, aligned):
        aligned(3, bars=20)

        found = broker_offset.measure(session)

        assert found.known is False
        assert "shared history" in found.reason

    def test_a_missing_series_gives_no_answer(self, session):
        found = broker_offset.measure(session)

        assert found.known is False
        assert found.reason

    def test_the_evidence_travels_with_the_answer(self, session, aligned):
        """So a surprising offset can be checked rather than believed."""
        aligned(3)

        described = broker_offset.measure(session).as_dict()

        assert described["overlap"] > broker_offset.MIN_OVERLAP
        assert described["error_pips"] is not None
        assert described["runner_up_pips"] is not None
        assert "daylight saving" in described["note"]


class TestTheIngestUsesIt:
    def test_no_offset_means_no_ingest(self, session, tmp_path):
        """A wrong offset corrupts every bar it touches and looks entirely
        normal doing it. Storing nothing is the safe failure."""
        from app.workers import broker_bars

        report = broker_bars.ingest(session, directory=tmp_path)

        # The directory is empty, so this reports the missing offset or the
        # missing files - either way it writes nothing.
        assert report["ingested"] == 0

    def test_the_offset_is_published_with_the_ingest(self, session, aligned, tmp_path):
        """Published rather than logged: an ingest that silently changed which
        clock it believed would move every future bar by an hour."""
        from app.workers import broker_bars

        aligned(3)
        _publish_reference(tmp_path, shift_hours=3)

        report = broker_bars.ingest(session, directory=tmp_path)

        assert report["clock_offset"]["hours"] == 3

    def test_a_bar_is_moved_back_to_utc(self, session, aligned, tmp_path):
        """The whole point. A bar the terminal stamps 03:00 on a GMT+3 clock
        is 00:00 UTC, not 03:00."""
        from app.workers import broker_bars

        aligned(3)
        _publish_reference(tmp_path, shift_hours=3, extra="2026.09.01 03:00:00")

        broker_bars.ingest(session, directory=tmp_path)

        stored = (
            session.query(Bar)
            .filter(Bar.event_time == datetime(2026, 9, 1, 0, 0, tzinfo=UTC))
            .all()
        )
        assert stored, "the 03:00 broker bar should land at 00:00 UTC"
