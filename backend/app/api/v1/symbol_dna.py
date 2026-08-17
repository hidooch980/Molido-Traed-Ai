"""Symbol DNA endpoints."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.api.deps import Principal, require
from app.core.enums import Permission, Timeframe
from app.db.session import get_db
from app.schemas.market import SymbolDnaResponse, SymbolProfileOut
from app.services import symbol_dna
from app.services.instruments import get_instrument

router = APIRouter(prefix="/symbol-dna", tags=["symbol-dna"])

READ = Depends(require(Permission.READ))


@router.get("/{instrument_id}", response_model=SymbolDnaResponse)
def read_symbol_dna(
    instrument_id: uuid.UUID,
    timeframe: Timeframe = Query(default=Timeframe.H1),
    as_of: datetime | None = Query(
        default=None, description="Knowledge cutoff. Defaults to now."
    ),
    live: bool = Query(
        default=False,
        description="Compute on demand instead of reading the stored snapshot.",
    ),
    session: Session = Depends(get_db),
    _: Principal = READ,
) -> SymbolDnaResponse:
    instrument = get_instrument(session, instrument_id)
    cutoff = (as_of or datetime.now(UTC)).astimezone(UTC)

    if live:
        computed = symbol_dna.compute_dna(session, instrument_id, timeframe, cutoff)
        profiles = [
            SymbolProfileOut(
                kind=kind,
                profile_version=symbol_dna.PROFILE_VERSION,
                as_of=cutoff,
                computed_at=datetime.now(UTC),
                sample_size=profile.sample_size,
                coverage_start=profile.coverage_start,
                coverage_end=profile.coverage_end,
                data=profile.data,
                warnings=profile.warnings,
            )
            for kind, profile in computed.items()
        ]
    else:
        stored = symbol_dna.latest_dna(session, instrument_id, timeframe, cutoff)
        profiles = [
            SymbolProfileOut(
                kind=row.kind,
                profile_version=row.profile_version,
                as_of=row.as_of,
                computed_at=row.computed_at,
                sample_size=row.sample_size,
                coverage_start=row.coverage_start,
                coverage_end=row.coverage_end,
                data={k: v for k, v in row.data.items() if k != "_warnings"},
                warnings=row.data.get("_warnings", []),
            )
            for row in stored.values()
        ]

    return SymbolDnaResponse(
        instrument_id=instrument.id,
        symbol=instrument.symbol,
        timeframe=timeframe,
        as_of=cutoff,
        profiles=sorted(profiles, key=lambda p: p.kind),
        # Named explicitly so a consumer sees the gap instead of assuming the
        # facet was computed and came back empty.
        unavailable=symbol_dna.UNAVAILABLE,
    )
