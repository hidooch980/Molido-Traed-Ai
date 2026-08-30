"""Market session and holiday calendar endpoints."""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import Principal, require
from app.core.enums import Permission
from app.db.session import get_db
from app.models.calendar import MarketHoliday
from app.models.instruments import Instrument
from app.schemas.market import HolidayOut, SessionStatusOut
from app.services.instruments import get_instrument
from app.services.sessions import active_sessions, build_calendar

router = APIRouter(prefix="/sessions", tags=["sessions"])

READ = Depends(require(Permission.READ))


# Declared before `/{instrument_id}`, and it has to be: that route parses its
# path segment as a UUID, so a request for "status" would be refused as
# malformed rather than falling through to here.
@router.get("/status", response_model=list[SessionStatusOut])
def read_all_session_status(
    at: datetime | None = Query(
        default=None, description="UTC instant to evaluate. Defaults to now."
    ),
    session: Session = Depends(get_db),
    _: Principal = READ,
) -> list[SessionStatusOut]:
    """Every active instrument's market state, in one request.

    This exists because the alternative shaped a page. The markets table asked
    for one instrument's session at a time, so rendering it cost one HTTP
    round trip per row - and the page defended itself by showing only the
    first twenty-five. The API sorts alphabetically, so that cap silently hid
    everything from NZDCHF onwards: the metals, the energy contracts, the
    index futures and most of the crypto. Somebody looking for gold on a page
    headed "markets" could not find it, and nothing was broken.

    One evaluation instant for the whole list, rather than `now` per
    instrument. Two rows a few milliseconds apart could otherwise straddle an
    open or a close and report a market as both.
    """
    moment = (at or datetime.now(UTC)).astimezone(UTC) if at else datetime.now(UTC)

    instruments = session.scalars(
        select(Instrument).where(Instrument.is_active.is_(True)).order_by(Instrument.symbol)
    ).all()

    out: list[SessionStatusOut] = []
    for instrument in instruments:
        calendar = build_calendar(session, instrument)
        local_date = moment.astimezone(calendar.zone).date()
        holiday = calendar.holidays.get(local_date)
        out.append(
            SessionStatusOut(
                instrument_id=instrument.id,
                symbol=instrument.symbol,
                at=moment,
                is_open=calendar.is_open(moment),
                timezone=calendar.timezone,
                market_code=instrument.market_code,
                active_sessions=[s.value for s in active_sessions(moment)],
                holiday=holiday.name or holiday.kind.value if holiday else None,
                next_open=calendar.next_open(moment),
                next_close=calendar.next_close(moment),
            )
        )
    return out


@router.get("/{instrument_id}", response_model=SessionStatusOut)
def read_session_status(
    instrument_id: uuid.UUID,
    at: datetime | None = Query(
        default=None, description="UTC instant to evaluate. Defaults to now."
    ),
    session: Session = Depends(get_db),
    _: Principal = READ,
) -> SessionStatusOut:
    instrument = get_instrument(session, instrument_id)
    moment = (at or datetime.now(UTC)).astimezone(UTC) if at else datetime.now(UTC)

    calendar = build_calendar(session, instrument)
    local_date = moment.astimezone(calendar.zone).date()
    holiday = calendar.holidays.get(local_date)

    return SessionStatusOut(
        instrument_id=instrument.id,
        symbol=instrument.symbol,
        at=moment,
        is_open=calendar.is_open(moment),
        timezone=calendar.timezone,
        market_code=instrument.market_code,
        active_sessions=[s.value for s in active_sessions(moment)],
        holiday=holiday.name or holiday.kind.value if holiday else None,
        next_open=calendar.next_open(moment),
        next_close=calendar.next_close(moment),
    )


@router.get("", response_model=list[HolidayOut])
def list_holidays(
    market_code: str | None = None,
    start: date | None = None,
    end: date | None = None,
    limit: int = Query(default=200, ge=1, le=1000),
    session: Session = Depends(get_db),
    _: Principal = READ,
) -> list[MarketHoliday]:
    query = select(MarketHoliday)
    if market_code:
        query = query.where(MarketHoliday.market_code == market_code.upper())
    if start:
        query = query.where(MarketHoliday.holiday_date >= start)
    if end:
        query = query.where(MarketHoliday.holiday_date <= end)
    query = query.order_by(MarketHoliday.holiday_date).limit(limit)
    return list(session.scalars(query))
