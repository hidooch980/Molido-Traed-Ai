"""Tighten the stop on a position that has gone the right way.

Until now a position carried its opening risk until it closed. The stop was
set once, at entry, 7.5 ATR away, and the only thing that could move it was
the market reaching it - so a trade that travelled most of the way to its
target still had the whole original loss in front of it if price turned.

**This is not the geometry changing.** The stop distance the risk brain
sized against, and the target the measurement is scored on, are both left
exactly where they were. What moves is the floor under a position that is
already ahead, and it only ever moves toward the price.

Three rules, and the first is the one that matters:

  * **A stop never widens.** Enforced twice - here, and again in the expert
    at the venue, where no mistake on this side can reach past it. That is
    not belt and braces for its own sake: a widening stop turns a bounded
    loss into an unbounded one, and it is the only way this worker could
    cost money rather than save it.
  * **Nothing moves until the trade has earned it.** Below `START_AT_R` the
    stop stays where the sizing put it. A trail that starts immediately is
    a tighter stop wearing the original stop's name, and it would be
    stopped out by the noise the 7.5 ATR distance was chosen to sit through.
  * **The trail lags by a fixed share of the original distance.** Not by a
    new ATR reading: re-measuring volatility on every pass makes the stop
    jump around for reasons that have nothing to do with the position, and
    a stop that moves when the trade has not is a stop nobody can reason
    about.

**Off unless an account asks for it.** The forward record measures a fixed
geometry, and trailing produces a different distribution of outcomes - so
turning it on everywhere at once would end the measurement and replace it
with an unmeasured one. Per-account, through the same policy table that
already carries risk and brains, so it can be run on one account and
compared against the others.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

#: How far a position must be ahead, in R, before its stop is touched.
#:
#: One R means the trade has made back what it was risking. Below that,
#: moving the stop is a claim about a move that has not happened yet.
START_AT_R = 1.0

#: Where the stop follows, as a share of the original stop distance behind
#: the best price seen. 0.6 leaves the trade room to breathe: at 1 R ahead
#: the stop lands at +0.4 R, locked in, rather than at break-even where the
#: next ordinary wobble ends it.
TRAIL_FRACTION = 0.6

#: The smallest move worth sending, as a share of the original distance.
#: Without it the worker rewrites the same stop every cycle - each one a
#: file, a claim, a venue round trip and a log line - for a few points that
#: change nothing.
MIN_STEP_FRACTION = 0.1

#: The one login that means every login.
#:
#: Named accounts go stale the moment the fleet changes: an account opened
#: today is not in yesterday's list, and it would run unprotected while the
#: setting still looked switched on. A wildcard cannot fall behind the fleet.
#:
#: It is deliberately still a setting rather than the default. Everything
#: this worker does is enabled by somebody writing it down.
EVERY_LOGIN = "*"


@dataclass
class Move:
    """One position's stop, and where it should be."""

    ticket: str
    symbol: str
    side: str
    entry: float
    stop: float
    price: float
    proposed: float
    reason: str = ""
    sent: bool = False
    result: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {
            "ticket": self.ticket,
            "symbol": self.symbol,
            "side": self.side,
            "entry": round(self.entry, 6),
            "stop": round(self.stop, 6),
            "price": round(self.price, 6),
            "proposed": round(self.proposed, 6),
            "reason": self.reason,
            "sent": self.sent,
            "result": self.result,
        }


@dataclass
class Report:
    considered: int = 0
    moves: list[Move] = field(default_factory=list)
    skipped: dict[str, int] = field(default_factory=dict)

    def skip(self, why: str) -> None:
        self.skipped[why] = self.skipped.get(why, 0) + 1

    def as_dict(self) -> dict[str, Any]:
        return {
            "considered": self.considered,
            "moved": sum(1 for m in self.moves if m.sent),
            "proposed": len(self.moves),
            "skipped": dict(self.skipped),
            "moves": [m.as_dict() for m in self.moves],
        }


def original_risk(*, entry: float, stop: float, target: float | None) -> float:
    """The distance the position was sized against, not the one it has now.

    This is the correction that makes a trail work at all. After the stop has
    been moved once, `entry - stop` is no longer the risk - it is the profit
    locked in - so measuring R against it makes every later pass think the
    trade is further ahead than it is, and the trail accelerates until it
    chokes the position it was meant to protect.

    The target is the one number on the position that never moves, and it was
    placed at a fixed multiple of the original stop distance. So it still
    carries that distance when the stop no longer does. Falling back to the
    stop when there is no target is correct only before the first move, which
    is the only case where there is nothing else to read.
    """
    from app.workers.forward import TARGET_MULTIPLE

    if target and TARGET_MULTIPLE > 0:
        implied = abs(target - entry) / TARGET_MULTIPLE
        if implied > 0:
            return implied
    return abs(entry - stop)


def proposed_stop(
    *,
    side: str,
    entry: float,
    stop: float,
    price: float,
    risk: float | None = None,
    start_at_r: float = START_AT_R,
    trail_fraction: float = TRAIL_FRACTION,
) -> tuple[float | None, str]:
    """Where this position's stop belongs now, or None and why not.

    `price` is the current market price on the side the position would close
    at - the bid for a long, the ask for a short. Using the other side would
    measure the trade's progress including a spread it has not paid.

    `risk` is the distance the position was sized against. Given explicitly
    because it is not `entry - stop` once the stop has moved; see
    `original_risk`.
    """
    distance = risk if risk is not None else abs(entry - stop)
    if distance <= 0:
        return None, "the position has no stop distance, so R is undefined"

    ahead = (price - entry) if side == "buy" else (entry - price)
    r = ahead / distance
    if r < start_at_r:
        return None, f"only {r:.2f} R ahead, below the {start_at_r:.2f} R start"

    lag = distance * trail_fraction
    candidate = (price - lag) if side == "buy" else (price + lag)

    # Never away from the price. Checked here as well as at the venue,
    # because a worker that proposes a widening stop is a worker with a bug
    # whether or not something downstream catches it.
    if side == "buy" and candidate <= stop:
        return None, "the trail sits below the stop already set"
    if side == "sell" and candidate >= stop:
        return None, "the trail sits above the stop already set"

    return candidate, f"{r:.2f} R ahead"


def closing_prices(bridge: Any) -> dict[str, tuple[float, float]]:
    """Every symbol's bid and ask, by name.

    The position payload carries no current price - it never has, and the
    first version of this worker read a `price_current` field that does not
    exist, so it examined twelve live positions and moved none of them while
    reporting success. The quote belongs here anyway: a long closes at the
    bid and a short at the ask, and taking both from the same published
    snapshot is what makes the two sides comparable.
    """
    try:
        payload = bridge.symbols()
    except Exception:  # noqa: BLE001 - an unreadable quote file is not the sweep
        return {}
    quotes: dict[str, tuple[float, float]] = {}
    for entry in payload.get("symbols") or []:
        name = str(entry.get("name") or "")
        bid = float(entry.get("bid") or 0.0)
        ask = float(entry.get("ask") or 0.0)
        if name and bid > 0 and ask > 0:
            quotes[name] = (bid, ask)
    return quotes


def run(
    bridge: Any,
    broker: Any,
    *,
    logins: set[str] | None = None,
    dry_run: bool = True,
) -> Report:
    """Walk this terminal's open positions and tighten what has earned it.

    `logins` names the accounts trailing is switched on for, or holds
    `EVERY_LOGIN` for the whole fleet. None means none: the default is off,
    because the measurement in flight is of a fixed geometry and this
    changes it.
    """
    report = Report()
    if not logins:
        report.skip("trailing is not enabled for any account")
        return report

    try:
        account = bridge.account()
    except Exception as problem:  # noqa: BLE001 - one unreadable bridge is not the sweep
        report.skip(f"the account could not be read: {type(problem).__name__}")
        return report

    login = str(account.get("login") or "")
    everywhere = EVERY_LOGIN in logins
    if not account.get("available") or not (everywhere or login in logins):
        report.skip("not an account trailing is enabled for")
        return report

    try:
        positions = bridge.positions().get("positions") or []
    except Exception as problem:  # noqa: BLE001
        report.skip(f"the positions could not be read: {type(problem).__name__}")
        return report

    quotes = closing_prices(bridge)

    for position in positions:
        report.considered += 1
        side = str(position.get("side") or "")
        entry = float(position.get("price_open") or 0)
        stop = float(position.get("stop") or 0)
        ticket = str(position.get("ticket") or "")

        # The price this position would close at, not the one it would open
        # at again: the other side of the book would count a spread the trade
        # has not paid, and count it as progress.
        bid, ask = quotes.get(str(position.get("symbol") or ""), (0.0, 0.0))
        price = float(position.get("price_current") or 0) or (
            bid if side == "buy" else ask
        )

        if not stop:
            # Nothing to tighten, and nothing this worker should invent - a
            # position with no stop is a separate defect with its own alarm.
            report.skip("no stop on the position")
            continue
        if not price or not entry or not ticket:
            report.skip("the bridge published no quote, entry or ticket")
            continue

        risk = original_risk(
            entry=entry, stop=stop, target=float(position.get("target") or 0) or None
        )
        candidate, why = proposed_stop(
            side=side, entry=entry, stop=stop, price=price, risk=risk
        )
        if candidate is None:
            report.skip(why)
            continue

        # Worth a round trip? A few points of improvement costs a file, a
        # claim, a venue call and a log line every cycle, forever.
        if abs(candidate - stop) < risk * MIN_STEP_FRACTION:
            report.skip("the improvement is smaller than one step")
            continue

        move = Move(
            ticket=ticket,
            symbol=str(position.get("symbol") or ""),
            side=side,
            entry=entry,
            stop=stop,
            price=price,
            proposed=candidate,
            reason=why,
        )
        report.moves.append(move)

        if dry_run:
            move.result = "dry run"
            continue
        if not hasattr(broker, "amend"):
            move.result = "this broker cannot amend a position"
            continue
        try:
            answer = broker.amend(ticket, stop=candidate)
            move.sent = True
            move.result = str(getattr(answer, "reason", "") or getattr(answer, "state", ""))
        except Exception as problem:  # noqa: BLE001 - one refusal is not the sweep
            move.result = f"{type(problem).__name__}: {problem}"

    return report


__all__ = [
    "closing_prices",
    "EVERY_LOGIN",
    "MIN_STEP_FRACTION",
    "original_risk",
    "START_AT_R",
    "TRAIL_FRACTION",
    "Move",
    "Report",
    "proposed_stop",
    "run",
]
