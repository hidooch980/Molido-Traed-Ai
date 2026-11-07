"""Derived candles must not count revisions as extra trading hours."""

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select

from app.core.enums import AssetClass, Timeframe
from app.models.instruments import Instrument, Provider
from app.models.market_data import Bar
from app.services.bar_revisions import append_only_bars
from app.workers import live_bars

NOW = datetime(2026, 11, 2, 6, tzinfo=UTC)


@pytest.fixture
def observed(session):
    instrument = Instrument(symbol="EURUSD", name="Fixture", asset_class=AssetClass.FOREX)
    provider = Provider(code="metatrader", name="Fixture", capabilities={})
    session.add_all([instrument, provider])
    session.flush()
    rows = [dict(instrument_id=instrument.id, provider_id=provider.id, timeframe="H1",
                 event_time=NOW.replace(hour=hour), ingested_at=NOW-timedelta(hours=2),
                 open=10, high=12, low=9, close=10, volume=10, quality_score=1,
                 source_ref="fixture") for hour in (0, 1, 2)]
    append_only_bars(session, rows)
    return rows


def derived(session):
    provider = session.scalar(select(Provider.id).where(Provider.code == live_bars.DERIVED_PROVIDER))
    return session.scalars(select(Bar).where(Bar.provider_id == provider).order_by(Bar.revision)).all()


def test_revised_hour_does_not_double_volume_or_parts(session, observed):
    append_only_bars(session, [{**observed[0], "high": 15, "ingested_at": NOW}])
    result = live_bars.derive(session, Timeframe.H3, now=NOW, shift_hours=0)
    assert result["derived"] == 1
    row = derived(session)[0]
    assert float(row.high) == 15 and float(row.volume) == 30
    assert float(row.quality_score) == 1


def test_unchanged_derivation_preserves_original_receipt(session, observed):
    live_bars.derive(session, Timeframe.H3, now=NOW, shift_hours=0)
    result = live_bars.derive(session, Timeframe.H3, now=NOW+timedelta(minutes=1), shift_hours=0)
    assert result["derived"] == 0
    rows = derived(session)
    assert len(rows) == 1 and rows[0].ingested_at == NOW


def test_derived_correction_preserves_prior_version(session, observed):
    live_bars.derive(session, Timeframe.H3, now=NOW, shift_hours=0)
    append_only_bars(session, [{**observed[0], "high": 15, "ingested_at": NOW+timedelta(minutes=1)}])
    live_bars.derive(session, Timeframe.H3, now=NOW+timedelta(minutes=2), shift_hours=0)
    rows = derived(session)
    assert [float(r.high) for r in rows] == [12, 15]
    assert [r.revision for r in rows] == [1, 2]
    assert rows[0].ingested_at == NOW


def test_unknown_later_correction_is_excluded_from_derivation(session, observed):
    append_only_bars(session, [{**observed[0], "high": 50, "ingested_at": NOW+timedelta(hours=1)}])
    live_bars.derive(session, Timeframe.H3, now=NOW, shift_hours=0)
    assert float(derived(session)[0].high) == 12
