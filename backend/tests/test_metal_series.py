"""Futures bars filed under the spot instrument they are not.

`autotrade` was written for a split the watchlist never made: it ranks
`GCFUT` and sends to `XAUUSD`, re-anchoring the level onto the venue. The
configuration mapped `XAUUSD:GC=F`, so the futures prices went into the spot
instrument, the re-anchoring exception never matched, and every gold decision
taken on the public series was silently dropped before it could be sent.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from app.core.enums import DataQualityIssue, Severity, Timeframe
from app.models.ingestion import DataQualityFinding
from app.models.instruments import Instrument, Provider
from app.models.market_data import Bar
from app.ops import metal_series

AT = datetime(2026, 9, 4, 18, 0, tzinfo=UTC)


@pytest.fixture()
def gold(session):
    yf = Provider(code="yfinance", name="Yahoo")
    mt = Provider(code="metatrader", name="Terminal")
    spot = Instrument(
        symbol="XAUUSD",
        asset_class="metal",
        base_currency="XAU",
        quote_currency="USD",
        timezone="UTC",
    )
    session.add_all([yf, mt, spot])
    session.flush()

    def bar(provider, close, at=AT):
        session.add(
            Bar(
                instrument_id=spot.id,
                provider_id=provider.id,
                timeframe=Timeframe.H1,
                event_time=at,
                revision=1,
                open=close,
                high=close,
                low=close,
                close=close,
                volume=1.0,
                ingested_at=at,
            )
        )

    bar(yf, 4471.30)  # the futures contract
    bar(mt, 4423.95)  # what the broker quotes
    session.flush()
    return spot, yf, mt


class TestTheSplit:
    def test_a_dry_run_changes_nothing(self, session, gold):
        spot, yf, _mt = gold

        result = metal_series.split(session, dry_run=True)

        assert result.as_dict()["bars_moved"] == 1
        assert session.query(Bar).filter(Bar.instrument_id == spot.id).count() == 2
        assert (
            session.query(Instrument).filter(Instrument.symbol == "GCFUT").count() == 0
        )

    def test_the_futures_bars_move_and_the_broker_bars_stay(self, session, gold):
        """The broker's bars are spot and belong to the instrument it quotes
        them for. Moving those would take the venue's own prices away from
        the thing being traded."""
        spot, yf, mt = gold

        metal_series.split(session, dry_run=False)

        futures = session.query(Instrument).filter(Instrument.symbol == "GCFUT").one()
        assert session.query(Bar).filter(Bar.instrument_id == futures.id).count() == 1
        remaining = session.query(Bar).filter(Bar.instrument_id == spot.id).all()
        assert len(remaining) == 1
        assert remaining[0].provider_id == mt.id

    def test_nothing_is_deleted(self, session, gold):
        before = session.query(Bar).count()

        metal_series.split(session, dry_run=False)

        assert session.query(Bar).count() == before

    def test_the_new_instrument_copies_the_spot_one(self, session, gold):
        """A futures contract on gold is not gold, but it is quoted in the
        same units on the same clock. Inventing different answers here would
        be inventing them."""
        spot, _yf, _mt = gold

        metal_series.split(session, dry_run=False)

        futures = session.query(Instrument).filter(Instrument.symbol == "GCFUT").one()
        assert futures.quote_currency == spot.quote_currency
        assert futures.timezone == spot.timezone
        assert futures.asset_class == spot.asset_class

    def test_it_is_safe_to_run_twice(self, session, gold):
        metal_series.split(session, dry_run=False)
        second = metal_series.split(session, dry_run=False)

        assert second.as_dict()["bars_moved"] == 0

    def test_the_conflict_findings_are_resolved(self, session, gold):
        """Their cause is gone: the spot instrument no longer holds two feeds
        pricing different contracts."""
        spot, _yf, _mt = gold
        session.add(
            DataQualityFinding(
                instrument_id=spot.id,
                provider_id=_mt.id,
                timeframe=Timeframe.H1,
                issue=DataQualityIssue.PROVIDER_CONFLICT,
                severity=Severity.ERROR,
                window_start=AT,
                window_end=AT,
                detected_at=AT,
                affected_rows=1,
            )
        )
        session.flush()

        metal_series.split(session, dry_run=False)

        finding = session.query(DataQualityFinding).one()
        assert finding.resolved_at is not None

    def test_other_findings_are_left_alone(self, session, gold):
        """Only the conflict was caused by the mixing. A broken bar is still
        broken wherever it is filed."""
        spot, _yf, mt = gold
        session.add(
            DataQualityFinding(
                instrument_id=spot.id,
                provider_id=mt.id,
                timeframe=Timeframe.H1,
                issue=DataQualityIssue.INVALID_OHLC_RELATION,
                severity=Severity.ERROR,
                window_start=AT,
                window_end=AT,
                detected_at=AT,
                affected_rows=1,
            )
        )
        session.flush()

        metal_series.split(session, dry_run=False)

        assert session.query(DataQualityFinding).one().resolved_at is None


class TestItAgreesWithTheTradingCode:
    def test_the_pairs_come_from_autotrade(self):
        """Two copies of "which contract stands for which metal" is two
        copies that can disagree, and the disagreement would route a gold
        order to silver."""
        from app.workers.autotrade import EXECUTION_SYMBOL

        assert metal_series.pairs() == EXECUTION_SYMBOL

    def test_every_futures_symbol_is_one_autotrade_will_re_anchor(self):
        """Moving bars under a symbol the sender does not admit would leave
        the decisions dropped exactly as they are now."""
        from app.workers.autotrade import REANCHORED_SYMBOLS

        assert set(metal_series.pairs()) <= set(REANCHORED_SYMBOLS)
