"""Give the metal futures series the instrument it was always meant to have.

`app.workers.autotrade` was written for a split that the configuration never
made. It carries `REANCHORED_SYMBOLS = {"GCFUT", "SIFUT"}` and
`EXECUTION_SYMBOL = {"GCFUT": "XAUUSD", "SIFUT": "XAGUSD"}`, and its comment
says plainly what the arrangement is: *the public feed carries the futures
contract (GC=F, stored as GCFUT) and the terminal trades spot XAUUSD*. The
shape crosses over, the level does not, and re-anchoring is what bridges
them.

The watchlist never made that split. It maps `XAUUSD:GC=F`, so eleven and a
half thousand hours of COMEX futures prices were written into the *spot*
instrument, beside six hundred and fifty-eight bars the broker published for
the thing it actually trades. Two consequences, and the quieter one is
worse:

  * 604 of the 619 open `provider_conflict` findings are these two symbols.
    They are not a feed disagreement. They are futures priced against spot,
    which is a carry basis of about 1.1% and is supposed to be there.
  * The re-anchoring exception keys on the symbol `GCFUT`, and these rows say
    `XAUUSD`. So gold decisions taken on the public series were never
    admitted for sending at all - the analysis ran every cycle and was
    discarded, and nothing said so.

This moves the futures bars to their own instrument rather than deleting
them. They are correct data about a real contract; only the label was wrong.
Once they sit under `GCFUT`, the code that was written for this arrangement
starts working: the rule ranks the futures series, `EXECUTION_SYMBOL` sends
the order to spot, and re-anchoring puts the level where the order will
actually be filled.

**Reversible.** Nothing is deleted; a row's `instrument_id` is rewritten, and
running this with the symbols swapped would put it back.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import select, update
from sqlalchemy.orm import Session


#: The spot instrument each futures series was wrongly filed under, and the
#: instrument it belongs to. Taken from `autotrade.EXECUTION_SYMBOL` rather
#: than restated, so the two cannot drift into disagreeing about which
#: contract stands for which metal.
def pairs() -> dict[str, str]:
    """{futures symbol: spot symbol}, from the module that trades them."""
    from app.workers.autotrade import EXECUTION_SYMBOL

    return dict(EXECUTION_SYMBOL)


#: Which feed carries the futures. The broker's own bars are spot and must
#: stay where they are - moving those would take the venue's own prices away
#: from the instrument it quotes them for.
FUTURES_PROVIDER = "yfinance"


@dataclass
class Move:
    futures_symbol: str
    spot_symbol: str
    created_instrument: bool = False
    bars_moved: int = 0
    findings_resolved: int = 0
    note: str = ""


@dataclass
class Result:
    moves: list[Move] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "moves": [
                {
                    "futures": m.futures_symbol,
                    "spot": m.spot_symbol,
                    "created_instrument": m.created_instrument,
                    "bars_moved": m.bars_moved,
                    "findings_resolved": m.findings_resolved,
                    "note": m.note,
                }
                for m in self.moves
            ],
            "bars_moved": sum(m.bars_moved for m in self.moves),
        }


def split(session: Session, *, dry_run: bool = True) -> Result:
    """Move the futures-priced bars onto their own instrument."""
    from datetime import UTC, datetime

    from app.core.enums import DataQualityIssue
    from app.models.ingestion import DataQualityFinding
    from app.models.instruments import Instrument, Provider
    from app.models.market_data import Bar

    result = Result()
    provider_id = session.scalar(
        select(Provider.id).where(Provider.code == FUTURES_PROVIDER)
    )
    if provider_id is None:
        return result

    for futures_symbol, spot_symbol in pairs().items():
        move = Move(futures_symbol=futures_symbol, spot_symbol=spot_symbol)
        result.moves.append(move)

        spot = session.scalar(
            select(Instrument).where(Instrument.symbol == spot_symbol)
        )
        if spot is None:
            move.note = f"no {spot_symbol} instrument to move bars off"
            continue

        futures = session.scalar(
            select(Instrument).where(Instrument.symbol == futures_symbol)
        )
        if futures is None:
            # Modelled on the spot instrument it was filed under: same asset
            # class, same quote currency, same trading hours. A futures
            # contract on gold is not gold, but it is quoted in the same
            # units and trades on the same clock, and inventing different
            # answers here would be inventing them.
            futures = Instrument(
                symbol=futures_symbol,
                asset_class=spot.asset_class,
                base_currency=spot.base_currency,
                quote_currency=spot.quote_currency,
                timezone=spot.timezone,
                trading_hours=list(spot.trading_hours or []),
            )
            move.created_instrument = True
            if not dry_run:
                session.add(futures)
                session.flush()

        movable = session.scalar(
            select(Instrument.id).where(Instrument.symbol == futures_symbol)
        )
        count = (
            session.query(Bar)
            .filter(
                Bar.instrument_id == spot.id,
                Bar.provider_id == provider_id,
            )
            .count()
        )
        move.bars_moved = count
        if dry_run or not count or movable is None:
            continue

        session.execute(
            update(Bar)
            .where(Bar.instrument_id == spot.id, Bar.provider_id == provider_id)
            .values(instrument_id=movable)
        )

        # The conflict is gone because its cause is gone: the spot instrument
        # no longer holds two feeds pricing different contracts. Resolved
        # explicitly rather than left for the re-check, which would find
        # fewer than two feeds on the instant and correctly decline to judge
        # - that answer is right for a deleted feed and wrong here, where
        # what happened is known.
        moment = datetime.now(UTC)
        rows = session.scalars(
            select(DataQualityFinding).where(
                DataQualityFinding.instrument_id == spot.id,
                DataQualityFinding.resolved_at.is_(None),
                DataQualityFinding.issue
                == DataQualityIssue.PROVIDER_CONFLICT.value,
            )
        ).all()
        for finding in rows:
            finding.resolved_at = moment
        move.findings_resolved = len(rows)
        session.flush()

    return result


__all__ = ["FUTURES_PROVIDER", "Move", "Result", "pairs", "split"]
