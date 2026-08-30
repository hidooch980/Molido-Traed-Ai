"""The third brain: slow context, and the right to say "not now".

The first brain proposes (council, meta, adversary - fast, per bar). The second
permits (risk limits - hard, arithmetic). This one reads what both are too fast
to see: where the speculative crowd already sits, what holding the position
costs in policy-rate terms, and whether the market is about to close on a gap.

**It can only make things more conservative.** Its verdict is a scale of 1.0,
0.5 or 0.0 on whatever size the other two brains would otherwise allow - never
more, never a direction, never a new trade. That invariant is the whole
contract: a layer that can push in both directions is a second opinion to be
argued with, a layer that can only stand aside is a brake, and brakes do not
need to be right about upside to be worth having.

**It abstains per signal, like the council.** A missing COT report is not a
flat crowd, a missing policy rate is not a zero differential, and the verdict
says which inputs it never saw. Absence of caution is not clearance when the
absence is of data.

**It is advisory in the pipeline and binding only at the order gate.** The
forward journal measures the first brain's arms; letting this brain scale
those entries mid-measurement would mix two regimes into one series and
neither number would mean anything afterwards - the same reason the journal
grew a timeframe column. Orders are where conservatism belongs, and orders
are already behind the edge gate.

Rule-based and versioned, like the council: `method` says what this is, and
the day a learned model replaces a rule, the version changes in the audit
trail rather than quietly.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

from app.core.enums import Decision

METHOD = "rule_based"
VERSION = 1

#: Crowd tilt (difference of normalised net positions, -1..1) beyond which a
#: same-direction entry is joining a crowded trade. The exit from a crowded
#: trade is narrow precisely when everybody needs it at once.
CROWDED = 0.55
#: Beyond this the crowd is about as one-sided as the CFTC series ever gets,
#: and joining it is the textbook unwind casualty.
EXTREME = 0.75

#: Policy-rate differential (percentage points) against the position beyond
#: which the daily cost of being in the trade is working against the edge
#: rather than beside it.
CARRY_AGAINST = 1.5

#: Within this many seconds of a close that is followed by a long gap
#: (weekend, holiday), a new position is mostly a bet on the reopening print.
CLOSING_SOON = 2 * 3600.0
#: A gap longer than this is not an overnight pause but a weekend or holiday.
LONG_GAP = 24 * 3600.0


class Stance(StrEnum):
    CLEAR = "clear"
    CAUTION = "caution"
    STAND_ASIDE = "stand_aside"


#: The only scales this brain may emit, keyed by stance. A table rather than
#: arithmetic so the monotone-conservatism invariant is visible at a glance
#: and a future rule cannot accidentally emit 1.2.
SCALES: dict[Stance, float] = {
    Stance.CLEAR: 1.0,
    Stance.CAUTION: 0.5,
    Stance.STAND_ASIDE: 0.0,
}


@dataclass(frozen=True)
class ContextVerdict:
    """What the slow context has to say about one proposed position."""

    stance: Stance
    scale: float
    reasons: list[str] = field(default_factory=list)
    #: Signals this brain wanted and never saw. Reported so that "clear"
    #: because nothing was visible cannot be mistaken for "clear" because
    #: everything was checked.
    abstained: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "stance": self.stance.value,
            "scale": self.scale,
            "reasons": self.reasons,
            "abstained": self.abstained,
            "method": METHOD,
            "version": VERSION,
        }


def _worse(a: Stance, b: Stance) -> Stance:
    order = [Stance.CLEAR, Stance.CAUTION, Stance.STAND_ASIDE]
    return max(a, b, key=order.index)


def read(
    decision: Decision,
    *,
    crowd_tilt: float | None = None,
    rate_differential: float | None = None,
    seconds_to_close: float | None = None,
    gap_seconds: float | None = None,
) -> ContextVerdict:
    """The context verdict for one proposed direction.

    `crowd_tilt` is positioning.pair_tilt's number: positive means the crowd
    is longer the base than the quote. `rate_differential` is
    policy_rates.differential: positive means being long the base is paid.
    `seconds_to_close` and `gap_seconds` describe the next session boundary.
    None anywhere means the signal was unavailable, and the verdict records
    the abstention instead of inventing an opinion.
    """
    if decision is Decision.WAIT:
        # Nothing to scale. Not an abstention - a WAIT needs no brake, and
        # reporting one would read as the brain having been consulted about a
        # position that does not exist.
        return ContextVerdict(
            stance=Stance.CLEAR,
            scale=SCALES[Stance.CLEAR],
            reasons=["no position proposed, nothing to scale"],
        )

    stance = Stance.CLEAR
    reasons: list[str] = []
    abstained: list[str] = []
    # +1 for a buy, -1 for a sell: the sign that turns "the crowd is long"
    # into "the crowd is with us" or "against us".
    side = 1.0 if decision is Decision.BUY else -1.0

    # --- crowding ---------------------------------------------------------
    if crowd_tilt is None:
        abstained.append("positioning")
    else:
        with_crowd = crowd_tilt * side
        if with_crowd >= EXTREME:
            stance = _worse(stance, Stance.STAND_ASIDE)
            reasons.append(
                f"the speculative crowd is extremely one-sided in this "
                f"direction (tilt {crowd_tilt:+.2f}); joining it now is "
                "buying the unwind"
            )
        elif with_crowd >= CROWDED:
            stance = _worse(stance, Stance.CAUTION)
            reasons.append(
                f"the crowd already leans this way (tilt {crowd_tilt:+.2f}); "
                "the exit is narrow when everybody needs it at once"
            )
        # Entering against a crowded trade is not penalised in v1, and that
        # is a decision rather than an oversight: contrarian entries against
        # extremes are a strategy of their own, and this brain's mandate is
        # to brake, not to trade.

    # --- carry ------------------------------------------------------------
    if rate_differential is None:
        abstained.append("policy_rates")
    else:
        paid = rate_differential * side
        if paid <= -CARRY_AGAINST:
            stance = _worse(stance, Stance.CAUTION)
            reasons.append(
                f"the policy-rate differential runs {paid:+.2f}pp against "
                "this position; every day in it is paid for out of the edge"
            )

    # --- the closing bell -------------------------------------------------
    if seconds_to_close is None or gap_seconds is None:
        abstained.append("calendar")
    elif seconds_to_close <= CLOSING_SOON and gap_seconds >= LONG_GAP:
        stance = _worse(stance, Stance.CAUTION)
        reasons.append(
            "the market closes within two hours and stays shut for more than "
            "a day; a fresh position here is mostly a bet on the reopening "
            "print"
        )

    return ContextVerdict(
        stance=stance,
        scale=SCALES[stance],
        reasons=reasons,
        abstained=abstained,
    )
