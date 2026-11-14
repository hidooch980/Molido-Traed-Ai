"""Stage 7: full MT5 period list, Native/Derived labels, lookahead-free resampling."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

import pytest

from app.core.enums import Timeframe
from app.core.timeframes import (
    MT5_BRIDGE_NATIVE,
    Source,
    catalogue,
    derivation_base,
    resample,
    source_kind,
)

NEW = ("M2", "M3", "M4", "M6", "M10", "M12", "M20", "H2", "H6", "H8", "H12")
T0 = datetime(2026, 11, 2, tzinfo=UTC)
M1 = timedelta(minutes=1)


@dataclass(frozen=True)
class Bar:
    open_time: datetime
    open: float
    high: float
    low: float
    close: float
    volume: float | None = 1.0


def minutes(n: int, start: datetime = T0) -> list[Bar]:
    return [Bar(start + i * M1, 100 + i, 100.5 + i, 99.5 + i, 100.2 + i) for i in range(n)]


def test_every_requested_period_exists_with_a_duration():
    for name in NEW:
        tf = Timeframe(name)
        assert tf.delta > timedelta(0)
    assert all(tf.delta for tf in Timeframe)


def test_labels_follow_what_the_bridge_publishes():
    ea = open("../infra/mql5/MolidoBridge.mq5", encoding="utf-8", errors="ignore").read()
    for tf in MT5_BRIDGE_NATIVE:
        assert f'return "{tf.value}";' in ea
    assert source_kind(Timeframe.H4) is Source.NATIVE
    for name in NEW:
        assert source_kind(Timeframe(name)) is Source.DERIVED


@pytest.mark.parametrize(
    ("tf", "base"),
    [("M2", "M1"), ("M10", "M5"), ("M20", "M5"), ("H2", "H1"), ("H8", "H4"),
     ("H12", "H4"), ("H6", "H1"), ("H3", "H1"), ("W1", "D1")],
)
def test_derivation_base(tf, base):
    got = derivation_base(Timeframe(tf))
    assert (got.value if got else None) == base


def test_catalogue_covers_all_members():
    rows = catalogue()
    assert len(rows) == len(Timeframe)
    assert {r["source"] for r in rows} == {"native", "derived"}


def test_resample_values():
    out = resample(minutes(10), Timeframe.M1, Timeframe.M5, T0 + 10 * M1)
    assert len(out) == 2
    first = out[0]
    assert (first.open, first.high, first.low, first.close) == (100, 104.5, 99.5, 104.2)
    assert first.complete and first.volume == 5 and first.source is Source.DERIVED


def test_forming_bucket_is_never_emitted():
    bars = minutes(13)
    out = resample(bars, Timeframe.M1, Timeframe.M5, T0 + 13 * M1)
    assert [b.open_time for b in out] == [T0, T0 + 5 * M1]


def test_future_source_bars_change_nothing():
    as_of = T0 + 7 * M1
    past = resample(minutes(7), Timeframe.M1, Timeframe.M5, as_of)
    full = resample(minutes(60), Timeframe.M1, Timeframe.M5, as_of)
    assert past == full


def test_unclosed_source_bar_is_ignored():
    bars = minutes(5)
    assert resample(bars, Timeframe.M1, Timeframe.M5, T0 + 4 * M1 + M1 / 2) == []


def test_gaps_are_reported():
    bars = [b for i, b in enumerate(minutes(5)) if i != 2]
    (only,) = resample(bars, Timeframe.M1, Timeframe.M5, T0 + 5 * M1)
    assert only.bar_count == 4 and not only.complete


def test_broker_shift_aligns_buckets():
    bars = [Bar(T0 + timedelta(hours=h), 1, 2, 0, 1) for h in range(48)]
    out = resample(bars, Timeframe.H1, Timeframe.H12, T0 + timedelta(hours=48), shift_hours=2)
    # broker midnight (UTC+2) is 22:00 UTC: the first bucket holds only 10 hours
    assert out[0].open_time == T0 - timedelta(hours=2)
    assert out[0].bar_count == 10 and not out[0].complete
    assert all(b.complete for b in out[1:])


def test_refusals():
    with pytest.raises(ValueError):
        resample([], Timeframe.M1, Timeframe.W1, T0)
    with pytest.raises(ValueError):
        resample([], Timeframe.M5, Timeframe.M12, T0)
    with pytest.raises(ValueError):
        resample([], Timeframe.M1, Timeframe.M5, datetime(2026, 1, 1))


def test_timeframes_endpoint():
    from fastapi.testclient import TestClient

    from app.main import app

    with TestClient(app) as client:
        res = client.get("/api/v1/agents/timeframes")
    assert res.status_code == 200
    names = {r["timeframe"] for r in res.json()["timeframes"]}
    assert set(NEW) <= names
