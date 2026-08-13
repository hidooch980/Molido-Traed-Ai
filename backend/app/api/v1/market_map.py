"""Market map and scanner (spec §43).

I told the owner these two had nothing behind them and stayed grey honestly.
That was wrong, and worth recording rather than quietly fixing: the audit that
produced it matched menu keys against *router* names, so two features whose
backing lives in a service rather than a router of the same name came back as
"nothing". `correlation_profile` has computed time-aligned cross-instrument
correlation since phase 8, and `regime.classify` has named regimes since 13.

Both routes read stored snapshots rather than recomputing.
`correlation_profile` reads a thousand bars per pair and the scanner would run
the classifier forty-nine times; either would make a page that takes a minute
to answer, and a page nobody waits for is a page nobody opens. The cost of that
choice is that both are as fresh as the last snapshot, so both report when the
snapshot was taken instead of implying it is now.

**The map is not a diversification score.** It reports measured pairs and names
the ones it could not measure. Two instruments with different trading calendars
share fewer aligned bars, and a pair below the sample floor is reported as
unmeasured rather than as uncorrelated - which is the whole reason the
portfolio brain treats those two as different facts.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.api.deps import Principal, require

# Above this absolute correlation two instruments are substantially one bet.
# Imported from the portfolio brain rather than retyped, so the map and the
# risk layer cannot drift into disagreeing about what "correlated" means.
from app.brain.portfolio import CORRELATION_CLUSTER
from app.core.enums import Permission, Timeframe
from app.db.session import get_db
from app.models.instruments import Instrument
from app.services import symbol_dna

router = APIRouter(prefix="/market-map", tags=["market-map"])

READ = Depends(require(Permission.READ))


def _instruments(session: Session, limit: int) -> list[Instrument]:
    """Active instruments, ordered so the map is stable between requests.

    Ordered by symbol rather than by insertion: a map whose rows move between
    refreshes is a map nobody can compare against the one they saw yesterday.
    """
    from sqlalchemy import select

    return list(
        session.scalars(
            select(Instrument)
            .where(Instrument.is_active.is_(True))
            .order_by(Instrument.symbol)
            .limit(limit)
        )
    )


@router.get("")
def read_market_map(
    timeframe: Timeframe = Query(default=Timeframe.H1),
    as_of: datetime | None = Query(default=None),
    limit: int = Query(default=25, ge=2, le=60),
    _: Principal = READ,
    session: Session = Depends(get_db),
) -> dict[str, Any]:
    """Measured correlation between instruments, and the pairs nobody measured.

    Built from stored DNA snapshots. A pair appears here only if enough bars
    lined up in time for the correlation to mean something; everything else is
    listed as unmeasured, because an absent pair and an uncorrelated pair are
    opposite facts and collapsing them is how a book looks diversified while it
    is one position.
    """
    cutoff = (as_of or datetime.now(UTC)).astimezone(UTC)
    instruments = _instruments(session, limit)

    pairs: list[dict[str, Any]] = []
    unmeasured: list[str] = []
    seen: set[tuple[str, str]] = set()
    snapshots = 0
    oldest: datetime | None = None

    for instrument in instruments:
        profiles = symbol_dna.latest_dna(session, instrument.id, timeframe, cutoff)
        profile = profiles.get("correlation")
        if profile is None:
            unmeasured.append(f"{instrument.symbol}: no stored correlation snapshot")
            continue

        snapshots += 1
        if oldest is None or profile.as_of < oldest:
            oldest = profile.as_of

        for peer, detail in ((profile.data or {}).get("pairs") or {}).items():
            key = tuple(sorted((instrument.symbol, peer)))
            if key in seen:
                continue
            seen.add(key)
            value = detail.get("correlation")
            if value is None:
                continue
            pairs.append(
                {
                    "a": key[0],
                    "b": key[1],
                    "correlation": value,
                    "aligned_bars": detail.get("aligned_bars"),
                    "clustered": abs(value) >= CORRELATION_CLUSTER,
                }
            )

    pairs.sort(key=lambda p: -abs(p["correlation"]))
    clustered = [p for p in pairs if p["clustered"]]

    return {
        "timeframe": timeframe.value,
        "as_of": cutoff.isoformat(),
        "instruments_considered": len(instruments),
        "snapshots_used": snapshots,
        "oldest_snapshot": oldest.isoformat() if oldest else None,
        "measured_pairs": len(pairs),
        "pairs": pairs[:200],
        "clustered_pairs": len(clustered),
        "cluster_threshold": CORRELATION_CLUSTER,
        "unmeasured": unmeasured,
        "note": (
            "an unmeasured pair is not an uncorrelated pair; the portfolio "
            "brain treats the two as different facts and so does this map"
        ),
        "freshness": (
            "read from stored snapshots, not recomputed — a live computation "
            "reads a thousand bars per pair and no page is worth that wait"
        ),
    }


@router.get("/scanner")
def read_scanner(
    timeframe: Timeframe = Query(default=Timeframe.H1),
    as_of: datetime | None = Query(default=None),
    limit: int = Query(default=25, ge=1, le=60),
    _: Principal = READ,
    session: Session = Depends(get_db),
) -> dict[str, Any]:
    """Every instrument's regime and data health, side by side.

    Deliberately *not* a signal list. It reports what each instrument is doing
    and whether its data can be trusted; deciding what to do about that is the
    chain's job, and a scanner that ranked instruments by conviction would be
    publishing the one number this system has measured to be uninformative.
    """
    cutoff = (as_of or datetime.now(UTC)).astimezone(UTC)
    instruments = _instruments(session, limit)

    from app.services import point_in_time

    rows: list[dict[str, Any]] = []
    for instrument in instruments:
        profiles = symbol_dna.latest_dna(session, instrument.id, timeframe, cutoff)
        volatility = profiles.get("volatility")
        structure = profiles.get("structure")

        try:
            age = point_in_time.data_freshness_seconds(
                session, instrument.id, timeframe, now=cutoff
            )
        except Exception:  # noqa: BLE001 - an unreadable feed is reported as unknown
            age = None

        rows.append(
            {
                "instrument_id": str(instrument.id),
                "symbol": instrument.symbol,
                "asset_class": instrument.asset_class.value
                if hasattr(instrument.asset_class, "value")
                else str(instrument.asset_class),
                # None rather than a default: not knowing how old a feed is is
                # not the same as it being fresh, and the risk brain blocks on
                # exactly this distinction.
                "data_age_seconds": age,
                "volatility_snapshot": volatility.as_of.isoformat() if volatility else None,
                "tendency": (structure.data or {}).get("tendency") if structure else None,
                "autocorrelation": (structure.data or {}).get(
                    "return_autocorrelation_lag1"
                )
                if structure
                else None,
                "profiles_available": sorted(profiles),
            }
        )

    unmeasured = [r["symbol"] for r in rows if not r["profiles_available"]]
    return {
        "timeframe": timeframe.value,
        "as_of": cutoff.isoformat(),
        "instruments": rows,
        "without_profiles": unmeasured,
        "not_a_signal_list": True,
        "note": (
            "this reports what instruments are doing, not what to do about it. "
            "Ranking by conviction would publish the one number this system has "
            "measured to carry almost no information"
        ),
    }
