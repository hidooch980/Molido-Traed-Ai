"""A recorded signal cannot consume an open bar or a later correction."""

from datetime import UTC, datetime, timedelta

import pytest

from app.core.enums import AssetClass, Timeframe
from app.learning.rules import Picks
from app.models.instruments import Instrument, Provider
from app.models.market_data import Bar
from app.workers import forward

NOW = datetime(2026, 11, 2, 12, tzinfo=UTC)


@pytest.fixture
def visible_market(session, monkeypatch):
    monkeypatch.setattr(forward, "MIN_FOR_INSTANT", 2)
    monkeypatch.setattr(forward, "LOOKBACK", 3)
    provider = Provider(code="metatrader", name="Fixture", capabilities={})
    session.add(provider)
    instruments = [Instrument(symbol=s, name=s, asset_class=AssetClass.FOREX)
                   for s in ("EURUSD", "GBPUSD")]
    session.add_all(instruments)
    session.flush()
    def put(instrument, hours, *, ingested=None, revision=1, close=10):
        session.add(Bar(instrument_id=instrument.id, provider_id=provider.id,
                        timeframe="H1", event_time=NOW-timedelta(hours=hours),
                        ingested_at=ingested or NOW, revision=revision,
                        open=close, high=close+1, low=close-1, close=close,
                        quality_score=1))
    for instrument in instruments:
        for hours in (1, 2, 3, 4):
            put(instrument, hours)
    session.flush()
    return instruments, put


def snapshot(session):
    return forward.snapshot(session, as_of=NOW, provider_code="metatrader", lookback=3)


def test_a_forming_bar_cannot_move_the_shared_instant(session, visible_market):
    instruments, put = visible_market
    for instrument in instruments:
        put(instrument, 0, close=999)
    session.flush()
    built, instant = snapshot(session)
    assert instant == NOW-timedelta(hours=1)
    assert all(v["closes"] == [10, 10, 10] for v in built.values())


def test_a_later_revision_does_not_replace_the_known_price(session, visible_market):
    instruments, put = visible_market
    for instrument in instruments:
        put(instrument, 1, ingested=NOW+timedelta(seconds=1), revision=2, close=999)
    session.flush()
    built, instant = snapshot(session)
    assert instant == NOW-timedelta(hours=1)
    assert all(v["closes"][-1] == 10 for v in built.values())


def test_a_later_ingested_timestamp_cannot_select_the_instant(session, visible_market):
    session.query(Bar).filter(Bar.event_time == NOW-timedelta(hours=1)).update(
        {"ingested_at": NOW+timedelta(seconds=1)}
    )
    session.flush()
    built, instant = snapshot(session)
    assert instant == NOW-timedelta(hours=2)
    assert all(v["last_at"] == NOW-timedelta(hours=2) for v in built.values())


def test_a_revision_known_exactly_at_the_cutoff_is_visible(session, visible_market):
    instruments, put = visible_market
    for instrument in instruments:
        put(instrument, 1, ingested=NOW, revision=2, close=11)
    session.flush()
    built, _ = snapshot(session)
    assert all(v["closes"][-1] == 11 for v in built.values())


def test_a_deep_candidate_keeps_observation_time_and_shared_bar(monkeypatch):
    calls = []
    def capture(*args, **kwargs):
        calls.append(kwargs)
        return {}, kwargs.get("event_cutoff")
    class Rule:
        lookback = 101
        def __call__(self, *args, **kwargs):
            return Picks()
    from app.learning import rules
    monkeypatch.setattr(rules, "CANDIDATES", {"fixture": Rule()})
    monkeypatch.setattr(forward, "snapshot", capture)
    monkeypatch.setattr(forward, "_pickable", lambda: None)
    bar = NOW-timedelta(hours=1)
    forward._record_candidates(None, {}, at=bar, known_at=NOW,
                               timeframe=Timeframe.H1, price_source="metatrader",
                               account_key=None)
    assert len(calls) == 1
    assert calls[0]["as_of"] == NOW
    assert calls[0]["event_cutoff"] == bar
