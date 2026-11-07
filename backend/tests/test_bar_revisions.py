"""Preserve what was knowable before and after broker corrections."""

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import select

from app.core.enums import AssetClass, Timeframe
from app.models.instruments import Instrument, Provider
from app.models.market_data import Bar
from app.services.bar_revisions import append_only_bars, latest_bar_query
from app.services.point_in_time import get_bars

AT = datetime(2026, 11, 2, 12, tzinfo=UTC)


@pytest.fixture
def bar_row(session):
    instrument = Instrument(symbol="EURUSD", name="Fixture", asset_class=AssetClass.FOREX)
    provider = Provider(code="metatrader", name="Fixture", capabilities={})
    session.add_all([instrument, provider])
    session.flush()
    return dict(instrument_id=instrument.id, provider_id=provider.id, timeframe="H1",
                event_time=AT-timedelta(hours=1), ingested_at=AT, revision=1,
                open=1.1, high=1.3, low=1, close=1.2, volume=10,
                quality_score=1, source_ref="fixture")


def test_republishing_preserves_original_knowledge_time(session, bar_row):
    assert append_only_bars(session, [bar_row]) == 1
    assert append_only_bars(session, [{**bar_row, "ingested_at": AT+timedelta(hours=1)}]) == 0
    rows = session.scalars(select(Bar)).all()
    assert len(rows) == 1 and rows[0].revision == 1 and rows[0].ingested_at == AT


def test_correction_preserves_old_price_and_asof_views(session, bar_row):
    later = AT+timedelta(hours=1)
    append_only_bars(session, [bar_row])
    assert append_only_bars(session, [{**bar_row, "close": 1.25, "ingested_at": later}]) == 1
    old = get_bars(session, bar_row["instrument_id"], Timeframe.H1, AT,
                   provider_id=bar_row["provider_id"])
    new = get_bars(session, bar_row["instrument_id"], Timeframe.H1, later,
                   provider_id=bar_row["provider_id"])
    assert (old[0].close, old[0].revision) == (1.2, 1)
    assert (new[0].close, new[0].revision) == (1.25, 2)
    assert append_only_bars(session, [{**bar_row, "close": 1.25, "ingested_at": later}]) == 0


def test_serial_corrections_append_and_never_rewrite(session, bar_row):
    for index, close in enumerate([1.2, 1.25, 1.15]):
        append_only_bars(session, [{**bar_row, "close": close, "ingested_at": AT+timedelta(hours=index)}])
    rows = session.scalars(select(Bar).order_by(Bar.revision)).all()
    assert [float(r.close) for r in rows] == [1.2, 1.25, 1.15]
    assert [r.ingested_at for r in rows] == [AT+timedelta(hours=i) for i in range(3)]


def test_database_rounding_does_not_create_fake_revisions(session, bar_row):
    append_only_bars(session, [{**bar_row, "quality_score": 0.99999}])
    assert append_only_bars(session, [{**bar_row, "quality_score": Decimal("1.000")}]) == 0


def test_volume_correction_is_preserved(session, bar_row):
    append_only_bars(session, [bar_row])
    assert append_only_bars(session, [{**bar_row, "volume": 11, "ingested_at": AT+timedelta(seconds=1)}]) == 1


def test_conflicting_same_batch_is_rejected_before_any_insert(session, bar_row):
    with pytest.raises(ValueError, match="Conflicting"):
        append_only_bars(session, [bar_row, {**bar_row, "close": 1.25}])
    assert session.scalar(select(Bar)) is None


def test_identical_same_batch_only_inserts_once(session, bar_row):
    assert append_only_bars(session, [bar_row, bar_row]) == 1


def test_batch_duplicate_keeps_earliest_receipt(session, bar_row):
    later = {**bar_row, "ingested_at": AT+timedelta(hours=1)}
    assert append_only_bars(session, [later, bar_row, later]) == 1
    assert session.scalar(select(Bar.ingested_at)) == AT


def test_backdated_correction_is_refused(session, bar_row):
    append_only_bars(session, [bar_row])
    with pytest.raises(ValueError, match="predate"):
        append_only_bars(session, [{**bar_row, "close": 1.25, "ingested_at": AT-timedelta(seconds=1)}])
    assert session.scalar(select(Bar.close)) == Decimal("1.2")


def test_revision_cannot_consume_an_extra_horizon_slot(session, bar_row):
    append_only_bars(session, [bar_row])
    append_only_bars(session, [{**bar_row, "close": 1.25}])
    append_only_bars(session, [{**bar_row, "event_time": AT, "ingested_at": AT+timedelta(hours=1)}])
    rows = session.scalars(latest_bar_query(Bar.provider_id == bar_row["provider_id"]).limit(2)).all()
    assert len(rows) == 2
    assert [r.event_time for r in rows] == [AT-timedelta(hours=1), AT]
    assert rows[0].revision == 2


def test_visibility_filter_precedes_latest_revision_choice(session, bar_row):
    append_only_bars(session, [bar_row])
    append_only_bars(session, [{**bar_row, "close": 1.25, "ingested_at": AT+timedelta(hours=1)}])
    rows = session.scalars(latest_bar_query(Bar.ingested_at <= AT)).all()
    assert len(rows) == 1 and rows[0].revision == 1 and float(rows[0].close) == 1.2
