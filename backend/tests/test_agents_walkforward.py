"""Stage 11: extra derived periods (flagged), rocket memory and walk-forward."""

from __future__ import annotations

import random
from datetime import UTC, datetime, timedelta

from app.agents.analyzers.bars import Candle
from app.agents.messages import Market
from app.agents.walkforward import walk_forward
from app.core.enums import Timeframe
from app.services import agent_scan, agent_walkforward
from app.workers import live_bars
from tests.conftest import insert_bar

H = timedelta(hours=1)
T0 = datetime(2026, 1, 5, tzinfo=UTC)


def walk(n, seed=1):
    rnd, p, out = random.Random(seed), 1.1, []
    for i in range(n):
        c = p + rnd.gauss(0, 0.001)
        if i % 97 == 0 and i:
            c = p + 0.006
        out.append(Candle(T0 + i * H, p, max(p, c) + 0.0005, min(p, c) - 0.0005, c, 100))
        p = c
    return out


def test_extra_derivations_are_off_by_default(monkeypatch):
    monkeypatch.delenv(live_bars.EXTRA_FLAG, raising=False)
    assert set(live_bars.derived_targets()) == set(live_bars.DERIVED)
    monkeypatch.setenv(live_bars.EXTRA_FLAG, "1")
    targets = live_bars.derived_targets()
    assert {Timeframe.M2, Timeframe.H12} <= set(targets)
    for tf, (src, parts) in live_bars.EXTRA_DERIVED.items():
        assert tf.delta == src.delta * parts  # every part required
        assert tf in live_bars.DERIVE_LOOKBACK


def test_fold_builds_m2_from_m1_and_skips_a_partial_bucket():
    m = timedelta(minutes=1)
    rows = [{"event_time": T0 + i * m, "open": 1.0, "high": 1.1, "low": 0.9,
             "close": 1.0 + 0.01 * i}
            for i in range(5)]
    built = live_bars.fold(rows, target=Timeframe.M2, source=Timeframe.M1, shift_hours=0,
                           now=T0 + 5 * m, min_parts=2)
    assert len(built) == 2  # the bucket at 4 minutes holds one part and is open


def test_walk_forward_is_point_in_time_and_folded():
    bars = walk(700)
    out = walk_forward(bars, "EURUSD", Market.FOREX, "H1", H, folds=4)
    assert len(out["folds"]) == 4 and out["bars"] == 700
    assert sum(f["n"] for f in out["folds"]) == out["overall"]["n"]
    trimmed = walk_forward(bars[:400], "EURUSD", Market.FOREX, "H1", H, folds=2)
    full = walk_forward(bars, "EURUSD", Market.FOREX, "H1", H, folds=2)
    early = [r for r in trimmed["folds"]][0]
    assert early["n"] <= full["overall"]["n"]


def test_walk_forward_short_history():
    out = walk_forward(walk(100), "EURUSD", Market.FOREX, "H1", H)
    assert out["signals"] == 0 and out["overall"]["n"] == 0


def test_record_resolve_and_summary(session, instrument, provider):
    now = datetime.now(UTC).replace(minute=0, second=0, microsecond=0)
    rnd, price = random.Random(3), 1.10
    for i in range(300, 1, -1):
        t = now - i * H
        nxt = price + rnd.gauss(0, 0.0005)
        insert_bar(session, instrument.id, provider.id, event_time=t, ingested_at=t + H,
                   close=nxt, open_=price)
        price = nxt
    insert_bar(session, instrument.id, provider.id, event_time=now - H, ingested_at=now,
               close=price + 0.006, open_=price)
    scan = agent_scan.scan(session, Timeframe.H1, as_of=now)
    assert agent_walkforward.record_signals(session, scan) == len(scan["signals"]) >= 1
    assert agent_walkforward.record_signals(session, scan) == 0
    sig = scan["signals"][0]
    insert_bar(session, instrument.id, provider.id, event_time=now, ingested_at=now + H,
               close=sig["take_profit"] + 0.01, open_=price + 0.006)
    assert agent_walkforward.resolve_recorded(session, now=now + H) == 1
    assert agent_walkforward.resolve_recorded(session, now=now + H) == 0
    summary = agent_walkforward.forward_summary(session)
    assert summary["recorded"] == 1 and summary["resolved"] == 1
    assert summary["overall"]["n"] == 1


def test_historical_endpoint_unknown_symbol(session):
    assert agent_walkforward.historical(session, "NOPE", Timeframe.H1)["error"]
