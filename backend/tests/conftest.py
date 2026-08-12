"""Test fixtures.

The suite runs against in-memory SQLite so the point-in-time and ingestion
regression tests execute with no database container. The portable column types
in `app.db.types` and the window-function query in `point_in_time` exist for
exactly this reason. Postgres-specific behaviour (hypertables, retention) is
verified by running the migration against the real image, not here.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.enums import AssetClass, Timeframe
from app.models import Base
from app.models.instruments import Instrument, Provider
from app.models.market_data import Bar
from app.models.tenancy import Tenant
from app.providers.base import RawBar


@pytest.fixture()
def session() -> Iterator[Session]:
    # StaticPool + check_same_thread=False: FastAPI's TestClient serves requests
    # on a worker thread, and the default in-memory SQLite connection refuses
    # cross-thread use (and would be a different empty database anyway).
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        future=True,
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )

    @event.listens_for(engine, "connect")
    def _fk_on(dbapi_connection, _):
        dbapi_connection.execute("PRAGMA foreign_keys=ON")

    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False, future=True)
    db = factory()
    try:
        yield db
    finally:
        db.close()
        engine.dispose()


@pytest.fixture()
def tenant(session: Session) -> Tenant:
    row = Tenant(slug="acme", name="Acme Capital")
    session.add(row)
    session.flush()
    return row


@pytest.fixture()
def other_tenant(session: Session) -> Tenant:
    row = Tenant(slug="globex", name="Globex")
    session.add(row)
    session.flush()
    return row


@pytest.fixture()
def provider(session: Session) -> Provider:
    row = Provider(code="test", name="Test provider", capabilities={"ohlcv": True})
    session.add(row)
    session.flush()
    return row


@pytest.fixture()
def instrument(session: Session) -> Instrument:
    row = Instrument(
        symbol="EURUSD",
        name="Euro / US Dollar",
        asset_class=AssetClass.FOREX,
        base_currency="EUR",
        quote_currency="USD",
    )
    session.add(row)
    session.flush()
    return row


BASE_TIME = datetime(2024, 3, 4, 0, 0, tzinfo=UTC)  # a Monday


def make_bars(count: int, *, start: datetime = BASE_TIME, price: float = 1.10) -> list[RawBar]:
    """Clean, contiguous H1 bars. Tests corrupt copies of these deliberately."""
    bars = []
    for i in range(count):
        open_ = price + i * 0.0001
        close = open_ + 0.00005
        bars.append(
            RawBar(
                event_time=start + timedelta(hours=i),
                open=round(open_, 5),
                high=round(close + 0.0002, 5),
                low=round(open_ - 0.0002, 5),
                close=round(close, 5),
                volume=1000.0 + i,
            )
        )
    return bars


def insert_bar(
    session: Session,
    instrument_id: uuid.UUID,
    provider_id: uuid.UUID,
    *,
    event_time: datetime,
    ingested_at: datetime,
    close: float,
    revision: int = 1,
    timeframe: Timeframe = Timeframe.H1,
    open_: float | None = None,
) -> Bar:
    """Insert one bar.

    `open_` defaults to `close`, which makes a doji — fine for tests about
    timing and visibility, useless for tests about candle *shape*. Anything
    asserting on body ratio or up/down share must pass a real open.
    """
    open_price = close if open_ is None else open_
    bar = Bar(
        instrument_id=instrument_id,
        provider_id=provider_id,
        timeframe=timeframe,
        event_time=event_time,
        revision=revision,
        ingested_at=ingested_at,
        open=open_price,
        high=max(open_price, close) + 0.001,
        low=min(open_price, close) - 0.001,
        close=close,
        volume=1000.0,
    )
    session.add(bar)
    session.flush()
    return bar
