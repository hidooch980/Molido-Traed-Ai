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


def quote_currency(symbol: str) -> str | None:
    """The currency a price of this symbol is expressed in, or None.

    Six alphabetic characters is the only shape this can be read from with
    certainty - EURUSD, XAUUSD, CADJPY - and an index or a CFD with a broker's
    own naming is left as None rather than guessed. A guess here would be a
    guess about how much money a position risks.
    """
    name = str(symbol or "").upper()
    return name[3:] if len(name) == 6 and name.isalpha() else None


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
    contract_size: float | None = None,
    account_currency: str | None = None,
) -> dict[str, Any]:
    """How many lots put exactly `risk_percent` of equity behind this stop.

    Rounded **down** to the broker's volume step, always. Rounding up to the
    nearest tradeable size silently exceeds the risk the caller asked for, and
    it does so on every trade rather than occasionally.

    **The tick value is checked against the contract size, because a broker
    can publish a wrong one.** On 2026-09-02 this account's terminal reported
    XAUUSD `tick_value` 0.1 per 0.01 tick - ten dollars per point per lot -
    while the position's own profit and loss proved a hundred. The system
    sized 1.22 lots believing it risked $373; it risked $3,731, which is 1.87%
    of a 200k account against a configured 0.75%. CADJPY and XAUEUR on the
    same terminal read correctly to four figures, so this is one symbol's
    specification being wrong rather than a formula being wrong.

    The cross-check works because of an identity, not a heuristic: when the
    price is quoted in the account's own currency, one whole unit of price
    movement is worth exactly `contract_size` of that currency per lot. That
    is what a contract size *is*. So for XAUUSD on a USD account the honest
    figure is 100, whatever the tick value says.

    It applies only when the quote currency is the account currency. CADJPY
    pays in yen and XAUEUR in euro, and their contract sizes say nothing about
    dollars without a conversion this function does not have - so for those,
    the tick value stands.

    And it only ever *raises* the loss per lot, never lowers it: a disagreement
    resolves toward the smaller position. If the currency reading above is ever
    wrong, the cost is a position smaller than intended, which is the direction
    a sizing bug should fail in.
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

    # The cross-check. Only where the identity holds, and only upward.
    spec_disagreement: str | None = None
    quote = quote_currency(symbol)
    same_currency = bool(
        quote and account_currency and quote == str(account_currency).upper()
    )
    if same_currency and contract_size and contract_size > 0:
        from_contract = stop_distance_price * float(contract_size)
        # Five per cent of slack for rounding and for a broker that quotes a
        # tick value including a fee. Ten times is not slack.
        if from_contract > loss_per_lot * 1.05:
            spec_disagreement = (
                f"the broker's tick value implies {loss_per_lot:.2f} "
                f"{account_currency} per lot behind this stop, and its own "
                f"contract size implies {from_contract:.2f}. The price is quoted "
                f"in {quote}, so one unit of price is worth exactly the contract "
                f"size per lot - the tick value is understated by "
                f"{from_contract / loss_per_lot:.1f}x. Sized on the larger figure"
            )
            loss_per_lot = from_contract

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
        # Named when the broker's two published figures did not agree, so the
        # smaller position has a reason attached rather than looking arbitrary.
        "spec_disagreement": spec_disagreement,
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
