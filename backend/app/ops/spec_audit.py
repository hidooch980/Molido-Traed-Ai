"""Check the broker's own specification against the broker's own arithmetic.

On 2026-09-02 this deployment closed a gold position at a loss of $3,730.76.
The loss was not a bad trade: it was a correctly-stopped trade that was five
times the size it should have been, because the terminal published a tick
value of 0.1 per 0.01 tick for XAUUSD - ten dollars a point per lot - and the
truth was a hundred. The sizing believed the position risked $373. It risked
$3,731, which is 1.87% of a 200,000 account against a configured 0.75%.

`calculators.lot_size` now catches that class before an order is sent, using
an identity: a price quoted in the account's own currency moves the account
by exactly the contract size per lot. That works, and it only reaches
instruments whose quote currency can be read from their name - six alphabetic
characters. An index called `.US500Cash` is outside it, and so is anything a
broker names to its own taste.

This module closes the rest of the gap with evidence instead of naming. An
open position states its own arithmetic: profit, volume, entry, and the
current price. Divide the profit by the move and the volume and you have what
the account is actually being paid per unit of price - measured, not
published. If that disagrees with the specification, the specification is
wrong about a live position, and every future order on that symbol will be
sized from the same wrong number.

It is how the gold defect was found. Turning it into something that runs is
the difference between finding it again and finding it once.

**It reports and never sizes.** A monitor that quietly corrected a position
would be a second sizing path nobody could see; the corrections belong in
`calculators`, where they are tested. This says which specification to
distrust and by how much.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

#: How far the measured value may sit from the published one before it is a
#: finding. A position's profit carries swap and commission, and a wide
#: tolerance is fine because the failure this looks for is a factor of ten.
TOLERANCE = 0.20

#: How much of a move is needed before the division is meaningful. A position
#: that has barely moved divides a rounding error by a rounding error, and the
#: answer is noise with a decimal point.
MIN_MOVE_TICKS = 5.0

#: And how much profit. This is the binding constraint, not the move: profit
#: is published to two decimals, so a position showing one cent carries a
#: rounding error of fifty per cent whatever the price has done, and dividing
#: by it produces a confident ratio built out of the last digit. A dollar is a
#: hundred times that granularity, which is enough for a fault measured in
#: factors of ten.
MIN_PROFIT = 1.0


@dataclass(frozen=True)
class Finding:
    """One symbol whose published value disagrees with its own profit."""

    symbol: str
    published_per_unit: float
    implied_per_unit: float
    volume: float
    move: float
    profit: float

    @property
    def ratio(self) -> float:
        return self.implied_per_unit / self.published_per_unit

    @property
    def understated(self) -> bool:
        return self.ratio > 1.0

    def as_dict(self) -> dict[str, Any]:
        return {
            "symbol": self.symbol,
            "published_per_unit": round(self.published_per_unit, 4),
            "implied_per_unit": round(self.implied_per_unit, 4),
            "ratio": round(self.ratio, 3),
            "understated": self.understated,
            "evidence": {
                "volume": self.volume,
                "move": round(self.move, 6),
                "profit": round(self.profit, 2),
            },
            "meaning": (
                f"every order on {self.symbol} is sized from a value "
                f"{self.ratio:.1f}x "
                + ("smaller" if self.understated else "larger")
                + " than the account is actually paid, so its risk is that "
                "much "
                + ("larger" if self.understated else "smaller")
                + " than the figure the system believes"
            ),
        }


@dataclass
class Audit:
    checked: int = 0
    skipped: list[str] = field(default_factory=list)
    findings: list[Finding] = field(default_factory=list)

    @property
    def clean(self) -> bool:
        return not self.findings

    def as_dict(self) -> dict[str, Any]:
        return {
            "checked": self.checked,
            "clean": self.clean,
            "findings": [f.as_dict() for f in self.findings],
            "skipped": self.skipped,
            "tolerance": TOLERANCE,
            "method": (
                "profit divided by move and volume is what the account is "
                "actually paid per unit of price. The specification's tick "
                "value is what it claims. This compares the two on positions "
                "the account already holds"
            ),
        }


def _published_per_unit(spec: dict[str, Any]) -> float | None:
    """What one whole unit of price is worth per lot, per the specification."""
    try:
        tick_value = float(spec.get("tick_value") or 0.0)
        tick_size = float(spec.get("tick_size") or 0.0)
    except (TypeError, ValueError):
        return None
    if tick_value <= 0 or tick_size <= 0:
        return None
    return tick_value / tick_size


def audit(
    positions: list[dict[str, Any]],
    specifications: dict[str, dict[str, Any]],
    quotes: dict[str, dict[str, Any]] | None = None,
) -> Audit:
    """Compare each open position's own arithmetic with its specification.

    `quotes` supplies the current bid and ask when the specifications do not
    carry them. A position with no current price cannot state a move, and is
    skipped by name rather than assumed to agree - the whole point of this is
    that silence and agreement are different.
    """
    report = Audit()
    prices = quotes or specifications
    for position in positions:
        symbol = str(position.get("symbol") or "")
        spec = specifications.get(symbol)
        if not spec:
            report.skipped.append(f"{symbol}: no specification published")
            continue
        published = _published_per_unit(spec)
        if published is None:
            report.skipped.append(f"{symbol}: the specification carries no usable tick value")
            continue

        quote = prices.get(symbol) or {}
        side = str(position.get("side") or "").lower()
        current = quote.get("ask") if side == "sell" else quote.get("bid")
        try:
            entry = float(position.get("price_open"))
            volume = float(position.get("volume") or 0.0)
            profit = float(position.get("profit") or 0.0)
            current = float(current)
            tick_size = float(spec.get("tick_size") or 0.0)
        except (TypeError, ValueError):
            report.skipped.append(f"{symbol}: no current quote to measure a move against")
            continue
        if volume <= 0 or tick_size <= 0:
            report.skipped.append(f"{symbol}: no volume or tick size")
            continue

        move = (entry - current) if side == "sell" else (current - entry)
        if abs(move) / tick_size < MIN_MOVE_TICKS or abs(profit) < MIN_PROFIT:
            # Not yet evidence. Dividing a rounding error by a rounding error
            # produces a confident number about nothing, and the profit's two
            # decimals are the tighter of the two limits.
            report.skipped.append(
                f"{symbol}: has not moved far enough from its entry to measure"
            )
            continue

        report.checked += 1
        implied = profit / (move * volume)
        if implied <= 0:
            # Profit and move disagree in sign, which is a different fault
            # from a wrong tick value and is not this function's to diagnose.
            report.skipped.append(
                f"{symbol}: profit and price move point opposite ways, which is "
                "not a tick-value question"
            )
            report.checked -= 1
            continue
        if abs(implied / published - 1.0) > TOLERANCE:
            report.findings.append(
                Finding(
                    symbol=symbol,
                    published_per_unit=published,
                    implied_per_unit=implied,
                    volume=volume,
                    move=move,
                    profit=profit,
                )
            )
    return report


__all__ = ["MIN_MOVE_TICKS", "MIN_PROFIT", "TOLERANCE", "Audit", "Finding", "audit"]
