"""The trader's calculators, and the one rule that makes them worth trusting.

Pip value, lot size, volatility and the session clock. Ordinary tools, on every
broker's website, and the reason to build them again is the rule below.

**Nothing here computes from an assumed contract specification.** A pip value
needs the contract size and the tick value, and those come from the broker, per
symbol - they are not 10 dollars because gold is usually 100 ounces. Every one
of these functions refuses and says which number it was missing rather than
using a textbook default.

That refusal is the whole product. A lot-size calculator that silently assumes
a standard lot is the difference between risking 1% and risking 10% on anything
that is not one, and it looks correct in both cases. The person who trusts it
finds out on the trade that ends their account.

The volatility figures are ATR, and they are labelled as what they are: a
measure of recent range, not a forecast. A number that describes yesterday
presented as a number that predicts tomorrow is how a risk tool becomes a
source of confidence.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, time
from typing import Any

#: What a "pip" means, per quote currency convention. JPY pairs quote to three
#: decimals and move in hundredths; everything else quotes to five and moves in
#: ten-thousandths.
#:
#: This is a convention, not a fact about the instrument, so it is published
#: with the answer rather than hidden inside it - a caller whose broker
#: disagrees can see exactly what was assumed.
JPY_PIP = 0.01
STANDARD_PIP = 0.0001


@dataclass(frozen=True)
class Unavailable:
    """Why a number could not be produced. Never a zero."""

    reason: str
    missing: str

    def as_dict(self) -> dict[str, Any]:
        return {"available": False, "reason": self.reason, "missing": self.missing}


def pip_size(symbol: str) -> float:
    """The price increment one pip represents for this symbol."""
    return JPY_PIP if symbol.upper().endswith("JPY") else STANDARD_PIP


def pip_value(
    *,
    symbol: str,
    lots: float,
    contract_size: float | None,
    tick_value: float | None,
    tick_size: float | None,
) -> dict[str, Any]:
    """What one pip is worth, in the account's currency, for this position size.

    Computed from the broker's own tick value rather than from the contract
    size and a guessed quote rate. The tick value already carries the
    conversion into the account currency, which is the part a hand calculation
    gets wrong on any cross the account is not denominated in.
    """
    if tick_value is None or tick_value <= 0:
        return Unavailable(
            reason=(
                "the broker has not published a tick value for this symbol, so "
                "a pip cannot be priced. Sizing from an assumed one is the "
                "difference between risking 1% and 10% on anything that is not "
                "a standard lot"
            ),
            missing="tick_value",
        ).as_dict()
    if tick_size is None or tick_size <= 0:
        return Unavailable(
            reason="the broker has not published a tick size, so a pip cannot be "
            "converted into ticks",
            missing="tick_size",
        ).as_dict()
    if lots <= 0:
        return Unavailable(
            reason="a position size of zero has no pip value", missing="lots"
        ).as_dict()

    increment = pip_size(symbol)
    ticks_per_pip = increment / tick_size
    per_lot = tick_value * ticks_per_pip

    return {
        "available": True,
        "symbol": symbol,
        "lots": lots,
        "pip_size": increment,
        "ticks_per_pip": round(ticks_per_pip, 6),
        "value_per_lot": round(per_lot, 6),
        "value": round(per_lot * lots, 4),
        # Published, so a broker that disagrees is visible rather than silently
        # wrong.
        "assumed": (
            "a pip is 0.01 on JPY quotes and 0.0001 elsewhere. The tick value "
            "comes from the broker and already carries the conversion into the "
            "account currency"
        ),
        "contract_size": contract_size,
    }


def lot_size(
    *,
    symbol: str,
    equity: float,
    risk_percent: float,
    stop_distance_price: float,
    tick_value: float | None,
    tick_size: float | None,
    volume_min: float | None = None,
    volume_step: float | None = None,
) -> dict[str, Any]:
    """How many lots put exactly `risk_percent` of equity behind this stop.

    Rounded **down** to the broker's volume step, always. Rounding up to the
    nearest tradeable size silently exceeds the risk the caller asked for, and
    it does so on every trade rather than occasionally.
    """
    if tick_value is None or tick_value <= 0 or tick_size is None or tick_size <= 0:
        return Unavailable(
            reason=(
                "the broker has not published the tick value and size for this "
                "symbol, so a position cannot be sized. This refuses rather "
                "than assuming a standard lot - the assumption is invisible and "
                "wrong by a factor of ten on some instruments"
            ),
            missing="tick_value" if not tick_value else "tick_size",
        ).as_dict()
    if stop_distance_price <= 0:
        return Unavailable(
            reason="a stop at the entry price risks nothing and sizes to "
            "infinity",
            missing="stop_distance_price",
        ).as_dict()
    if equity <= 0 or risk_percent <= 0:
        return Unavailable(
            reason="equity and risk must both be positive",
            missing="equity" if equity <= 0 else "risk_percent",
        ).as_dict()

    money_at_risk = equity * (risk_percent / 100.0)
    ticks_at_risk = stop_distance_price / tick_size
    loss_per_lot = ticks_at_risk * tick_value
    if loss_per_lot <= 0:
        return Unavailable(
            reason="the stop distance is smaller than one tick",
            missing="stop_distance_price",
        ).as_dict()

    raw = money_at_risk / loss_per_lot

    step = volume_step or 0.01
    minimum = volume_min or step
    # Down, never up. Up exceeds the requested risk on every trade.
    rounded = (int(raw / step)) * step if step > 0 else raw
    rounded = round(rounded, 8)

    tradeable = rounded >= minimum
    return {
        "available": True,
        "symbol": symbol,
        "equity": equity,
        "risk_percent": risk_percent,
        "money_at_risk": round(money_at_risk, 2),
        "loss_per_lot": round(loss_per_lot, 4),
        "lots_exact": round(raw, 6),
        "lots": rounded if tradeable else 0.0,
        "tradeable": tradeable,
        # Both numbers, because the gap between them is the risk actually taken
        # versus the risk asked for, and a caller sizing near the minimum needs
        # to see it.
        "actual_risk": round(rounded * loss_per_lot, 2) if tradeable else 0.0,
        "actual_risk_percent": round(rounded * loss_per_lot / equity * 100, 4)
        if tradeable
        else 0.0,
        "reason": None
        if tradeable
        else (
            f"the calculated size {rounded} is below the broker's minimum "
            f"{minimum}. Taking the minimum instead would risk "
            f"{round(minimum * loss_per_lot / equity * 100, 2)}% rather than "
            f"{risk_percent}%, so this reports nothing tradeable instead"
        ),
        "rounding": "down to the broker's volume step, always - rounding up "
        "exceeds the requested risk on every trade",
    }


#: The four sessions, in UTC, as the market actually keeps them. Published as
#: data rather than hidden in a function so a reader can check them against
#: their broker's clock.
#:
#: These do not shift with daylight saving here. They are approximations of a
#: continuous market's busy hours, not exchange opening times, and presenting
#: them to the minute would claim a precision the concept does not have.
SESSIONS: tuple[tuple[str, time, time], ...] = (
    ("Sydney", time(21, 0), time(6, 0)),
    ("Tokyo", time(0, 0), time(9, 0)),
    ("London", time(7, 0), time(16, 0)),
    ("New York", time(12, 0), time(21, 0)),
)


def sessions_at(moment: datetime | None = None) -> dict[str, Any]:
    """Which sessions are open, and where the overlaps are.

    The overlap matters more than the individual sessions: London and New York
    together carry most of the day's volume, and a spread quoted during Tokyo
    on a European cross is not the spread the backtest assumed.
    """
    now = (moment or datetime.now(UTC)).astimezone(UTC)
    current = now.time()

    open_now = []
    for name, start, end in SESSIONS:
        # A session that crosses midnight is open if the time is after its
        # start or before its end - not between them.
        inside = start <= current < end if start < end else (current >= start or current < end)
        if inside:
            open_now.append(name)

    return {
        "at": now.isoformat(),
        "open": open_now,
        "overlap": len(open_now) > 1,
        "sessions": [
            {"name": n, "opens_utc": s.isoformat(), "closes_utc": e.isoformat()}
            for n, s, e in SESSIONS
        ],
        "note": (
            "approximate busy hours for a continuous market, not exchange "
            "opening times, and they do not shift with daylight saving. The "
            "London/New York overlap carries most of the day's volume - a "
            "spread quoted during Tokyo on a European cross is not the spread "
            "a backtest assumed"
        ),
    }


def volatility(
    *, symbol: str, atr: float | None, price: float | None, lookback: int = 14
) -> dict[str, Any]:
    """Recent range, expressed three ways. Not a forecast.

    ATR in price, in pips, and as a percentage of price - the third being the
    only one comparable across instruments, which is what somebody choosing
    between them actually needs.
    """
    if atr is None or atr <= 0:
        return Unavailable(
            reason=f"no volatility estimate is available for {symbol}",
            missing="atr",
        ).as_dict()
    if price is None or price <= 0:
        return Unavailable(
            reason="a price is needed to express volatility as a percentage",
            missing="price",
        ).as_dict()

    increment = pip_size(symbol)
    return {
        "available": True,
        "symbol": symbol,
        "lookback": lookback,
        "atr_price": atr,
        "atr_pips": round(atr / increment, 1),
        "atr_percent": round(atr / price * 100, 4),
        "note": (
            "this is a measure of the last "
            f"{lookback} periods' range, not a forecast of the next one. The "
            "percentage is the only figure comparable across instruments"
        ),
    }
