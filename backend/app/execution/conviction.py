"""How sure the system is, expressed so that it can only ever trade smaller.

Everything upstream of this decides *whether* an order may go: the kill
switch, the account, the risk brain, the challenge rulebook, the news window,
the portfolio limit, the cost ceiling. Each is a gate and each returns yes or
no. What none of them expresses is the difference between an order the
evidence barely permits and one it positively supports, and that difference
was being thrown away - every permitted order was sized identically.

This module scores that difference, under one constraint that shapes the
whole design:

    **The multiplier this produces is at most 1.0.**

Not a convention, an invariant with a test. Conviction may shrink a position
and may block it; it may never enlarge one, and there is no arithmetic path
here that returns more than the risk the gates already permitted. The reason
is the failure this system has already had once: a number that looked like an
edge was believed, and the thing that made it expensive was position size. A
conviction model that can multiply upward turns a measurement error into a
loss proportional to how wrong it was.

**Missing is not neutral, and it is certainly not good.** A factor the system
cannot observe lowers confidence, because "we did not check" and "we checked
and it was fine" differ exactly where it matters. Nothing here substitutes a
default for an unavailable reading.

**STRONG requires a proven edge, and there is not one.** The registry is
empty and honestly so, so the top tier is unreachable today. That is the
correct behaviour, not a gap: a tier that says "high conviction" while no
registered edge clears the bar would be conviction about nothing.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import IntEnum
from typing import Any


class Tier(IntEnum):
    """What the evidence supports. Ordered, so comparisons read naturally."""

    NONE = 0
    WEAK = 1
    VALID = 2
    STRONG = 3

    @property
    def label(self) -> str:
        return {0: "no edge", 1: "weak", 2: "valid", 3: "strong"}[int(self)]


#: Score boundaries. Stated as one table so the tiers and the score cannot
#: drift apart, and deliberately not tunable from settings: a threshold an
#: operator can lower during a drawdown is a threshold that gets lowered
#: during a drawdown.
TIER_FLOORS: tuple[tuple[int, Tier], ...] = (
    (85, Tier.STRONG),
    (70, Tier.VALID),
    (40, Tier.WEAK),
    (0, Tier.NONE),
)

#: The smallest share of the permitted risk a trade can be reduced to.
#:
#: **Conviction sizes; it does not veto.** The first version of this module
#: refused anything scoring under 40, and on this deployment's current
#: evidence that is every trade: no score source is calibrated on its forward
#: record yet, and no regime filter has been confirmed out of sample, so
#: confidence tops out around a third however unanimous the brains are. A
#: conviction model that blocks every order is not a filter, it is a halt
#: wearing one - and the halt already exists, deliberately, in the kill
#: switch, where a person operates it.
#:
#: So the score scales the size between this floor and the full permitted
#: risk, and the only things that refuse outright are the factors that were
#: already gates upstream: data too stale to size against, and an execution
#: cost above what the measured edge supports. Those two block here for the
#: same reason they block there, and blocking twice costs nothing.
MIN_MULTIPLIER = 0.25


@dataclass(frozen=True)
class Factor:
    """One observation, its strength, and whether it was observed at all.

    `score` runs 0..1 and means "how far this factor supports the trade".
    `available` False means the system could not read it; `score` is then
    ignored and the factor counts against confidence.
    """

    name: str
    score: float
    available: bool
    detail: str
    #: Whether a bad reading blocks rather than merely reduces. Reserved for
    #: the factors that describe whether the trade is *possible* to do well -
    #: stale data, cost above the edge - rather than how good it looks.
    blocking: bool = False
    #: Whether this reading can differ between two candidates in one cycle.
    #:
    #: The agreement behind EURUSD and the agreement behind USDCHF are two
    #: different facts; how many score sources are calibrated is one fact
    #: about the deployment, identical for both. A factor that is the same
    #: for every candidate cannot tell one from another, so it belongs in the
    #: report and the tier and not in the multiplier - putting it there would
    #: not rank anything, it would just scale the whole account down.
    per_trade: bool = True

    @property
    def blocks(self) -> bool:
        return self.blocking and (not self.available or self.score <= 0.0)

    def as_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "score": round(self.score, 3) if self.available else None,
            "available": self.available,
            "blocking": self.blocking,
            "per_trade": self.per_trade,
            "detail": self.detail,
        }


@dataclass
class Conviction:
    """The whole judgement, and every reason behind it."""

    #: Signed, -1..+1. The sign is the side; the magnitude is how much the
    #: brains agree. Zero means no usable signal.
    signal_strength: float
    #: 0..1. How much of what should have been observed actually was, weighted
    #: by how well each observation went.
    confidence: float
    factors: list[Factor] = field(default_factory=list)
    proven_edge: bool = False
    blocked_reasons: list[str] = field(default_factory=list)

    @property
    def unavailable(self) -> list[Factor]:
        return [f for f in self.factors if not f.available]

    @property
    def score(self) -> int:
        """0..100. Strength and confidence, neither able to rescue the other.

        Multiplied rather than averaged: a strong signal nobody could verify
        and a verified signal that says nothing are both weak trades, and an
        average lets either one carry the other.
        """
        return int(round(abs(self.signal_strength) * self.confidence * 100))

    @property
    def tier(self) -> Tier:
        floor = next(t for score, t in TIER_FLOORS if self.score >= score)
        # The ceiling that makes the registry mean something. Without a
        # registered edge that clears its bar, nothing here is STRONG - it is
        # at best VALID, whatever the arithmetic says.
        if floor is Tier.STRONG and not self.proven_edge:
            return Tier.VALID
        return floor

    @property
    def blocks(self) -> list[str]:
        """Only the factors that were already gates upstream.

        A low score is not here. It shrinks the position instead, because on
        this deployment's current evidence every score is low and a veto on
        that would halt trading - see `MIN_MULTIPLIER`.
        """
        return list(self.blocked_reasons) + [
            f"{f.name}: {f.detail}" for f in self.factors if f.blocks
        ]

    @property
    def allowed(self) -> bool:
        return not self.blocks

    @property
    def risk_multiplier(self) -> float:
        """What fraction of the permitted risk this trade deserves.

        **At most 1.0, always.** The gates above decided how much risk this
        account may take; conviction can decline some of it and can decline
        all of it, and cannot ask for more. `min` is doing load-bearing work
        here and is covered by its own test.

        Blocked trades return 0.0 rather than a small number, because "do not
        trade" and "trade a little" are different instructions and rounding
        one into the other is how a blocked signal reaches the broker.
        """
        if not self.allowed:
            return 0.0
        # Built from the factors that can differ between candidates, not from
        # the whole score. The account-wide ones - calibration, regime,
        # proven edge - are identical for every trade in the cycle, so
        # including them here would not rank anything; it would silently
        # move the account's risk level, which is the operator's decision and
        # the risk brain's, not this module's.
        scaled = MIN_MULTIPLIER + (1.0 - MIN_MULTIPLIER) * (
            self.differentiating_score / 100.0
        )
        return min(1.0, max(MIN_MULTIPLIER, scaled))

    @property
    def differentiating_score(self) -> int:
        """0..100 from the per-trade factors alone. What sizes the position."""
        varying = [f for f in self.factors if f.per_trade]
        observed = [f for f in varying if f.available]
        if not varying:
            return 0
        mean = sum(f.score for f in observed) / len(observed) if observed else 0.0
        confidence = mean * (len(observed) / len(varying))
        return int(round(min(1.0, abs(self.signal_strength)) * confidence * 100))

    def as_dict(self) -> dict[str, Any]:
        return {
            "signal_strength": round(self.signal_strength, 3),
            "confidence": round(self.confidence, 3),
            "trade_power_score": self.score,
            "sizing_score": self.differentiating_score,
            "tier": int(self.tier),
            "tier_label": self.tier.label,
            "proven_edge": self.proven_edge,
            "allowed": self.allowed,
            "risk_multiplier": round(self.risk_multiplier, 3),
            "blocking_reasons": self.blocks,
            "unobserved": [f.name for f in self.unavailable],
            "factors": [f.as_dict() for f in self.factors],
            "note": (
                "conviction can shrink a position or refuse it, never enlarge "
                "one: the multiplier is capped at the risk the gates already "
                "permitted"
            ),
        }


# ------------------------------------------------------------------ factors
def agreement_factor(*, agreeing: int, opposing: int, council: int = 0) -> Factor:
    """How much of the opinion on this symbol supports this side.

    **The denominator is the brains that spoke, not the register of names.**
    A brain that decided nothing about EURUSD has not disagreed about EURUSD;
    it was looking elsewhere. Dividing by the whole council would score a lone
    unopposed decision as weak evidence when what it actually is is
    unopposed - and the codebase already holds this line where it matters
    most, in `crosssection.rank`: no confirmation offered is not the same as
    confirmation withheld. Whether one voice is enough to trade on is the
    consensus rule's question, and it is the operator's to set.

    The measure is the margin as a share of the voters: unanimous is 1.0,
    three-to-one is 0.5, a tie is 0. An earlier version counted opposition
    double, which scored a solid three-to-one majority at 0.25 - near
    worthless - and that factor of two was invented rather than derived. A
    margin is the ordinary way to express a vote and needs no such constant.

    `council` is accepted and unused, kept so callers that pass it read the
    same as before; the electorate that matters is the one that voted.
    """
    voted = agreeing + opposing
    if voted <= 0:
        return Factor(
            "council_agreement", 0.0, False, "no brain expressed a view on this symbol"
        )
    score = max(0.0, min(1.0, (agreeing - opposing) / voted))
    return Factor(
        "council_agreement",
        score,
        True,
        f"{agreeing} for, {opposing} against, of {voted} that spoke",
    )


def cost_factor(*, cost_r: float, ceiling_r: float | None) -> Factor:
    """How much of the edge execution will take.

    Blocking: a trade whose cost meets or exceeds the ceiling is not a weak
    trade, it is a trade whose expected value is negative before it starts.
    """
    if ceiling_r is None:
        return Factor(
            "execution_cost",
            0.0,
            False,
            "no measured ceiling yet, so the cost cannot be judged",
            blocking=True,
        )
    if ceiling_r <= 0:
        return Factor(
            "execution_cost",
            0.0,
            True,
            f"the measured edge supports no cost at all at this timeframe "
            f"(ceiling {ceiling_r:.3f} R)",
            blocking=True,
        )
    headroom = max(0.0, 1.0 - cost_r / ceiling_r)
    return Factor(
        "execution_cost",
        headroom,
        True,
        f"{cost_r:.3f} R against a {ceiling_r:.3f} R ceiling",
        blocking=True,
    )


def freshness_factor(*, age_bars: float | None, limit_bars: float = 3.0) -> Factor:
    """How current the data behind this decision is.

    Blocking, and unknown blocks: not knowing the age of a feed is not
    evidence that it is young.
    """
    if age_bars is None:
        return Factor(
            "data_freshness",
            0.0,
            False,
            "the age of the feed is unknown, and unknown is stale",
            blocking=True,
        )
    if age_bars > limit_bars:
        return Factor(
            "data_freshness",
            0.0,
            True,
            f"{age_bars:.1f} bars old, beyond the {limit_bars:.0f}-bar limit",
            blocking=True,
        )
    return Factor(
        "data_freshness",
        max(0.0, 1.0 - age_bars / limit_bars),
        True,
        f"{age_bars:.1f} bars old",
        blocking=True,
    )


def calibration_factor(*, calibrated_sources: int | None) -> Factor:
    """Whether any score source has earned the right to be believed.

    Not blocking. An uncalibrated source is a reason to trade smaller, and
    making it a block would stop the system producing the very record that
    calibration is measured from.
    """
    if calibrated_sources is None:
        return Factor(
            "calibration", 0.0, False, "calibration was not read", per_trade=False
        )
    if calibrated_sources <= 0:
        return Factor(
            "calibration",
            0.0,
            True,
            "no score source is calibrated on its forward record",
            per_trade=False,
        )
    return Factor(
        "calibration",
        1.0,
        True,
        f"{calibrated_sources} calibrated source(s)",
        per_trade=False,
    )


def regime_factor(*, aligned: bool | None, detail: str = "") -> Factor:
    """Whether the current regime is one the edge was shown to survive.

    Unavailable by default, and honestly so: the dispersion hypothesis was
    tested on 21 years of daily bars and did not confirm out of sample
    (separation t 1.82 against a required 1.96), so there is no validated
    regime rule to align against. It is a factor rather than nothing because
    the reading exists and lowers confidence by its absence, which is the
    truthful effect of not knowing.
    """
    if aligned is None:
        return Factor(
            "regime_alignment",
            0.0,
            False,
            detail or "no regime filter has been confirmed out of sample",
            per_trade=False,
        )
    return Factor(
        "regime_alignment", 1.0 if aligned else 0.0, True, detail, per_trade=False
    )


def assess(
    *,
    side: str,
    factors: list[Factor],
    proven_edge: bool,
    council_agreement: float | None = None,
) -> Conviction:
    """Combine the factors into one judgement.

    `signal_strength` is signed by `side` and sized by the council's
    agreement, which is the only genuinely directional evidence the system
    has: the brains each say a side, and how many say the same one is how
    strong the signal is. A rule that returned a magnitude would be better and
    none of them does, so this does not invent one.

    `confidence` is the mean of the available factors' scores, multiplied by
    the share of factors that were available at all. Unobserved factors
    therefore cost twice - once by not contributing, once by shrinking the
    share - which is the intended weight: a judgement made on half the
    evidence should not be as confident as one made on all of it.
    """
    direction = {"long": 1.0, "buy": 1.0, "short": -1.0, "sell": -1.0}.get(
        str(side).lower(), 0.0
    )
    strength = direction * (
        council_agreement
        if council_agreement is not None
        else next(
            (f.score for f in factors if f.name == "council_agreement" and f.available),
            0.0,
        )
    )

    observed = [f for f in factors if f.available]
    if not factors:
        confidence = 0.0
    else:
        mean = sum(f.score for f in observed) / len(observed) if observed else 0.0
        confidence = mean * (len(observed) / len(factors))

    return Conviction(
        signal_strength=max(-1.0, min(1.0, strength)),
        confidence=max(0.0, min(1.0, confidence)),
        factors=list(factors),
        proven_edge=proven_edge,
    )


__all__ = [
    "MIN_MULTIPLIER",
    "TIER_FLOORS",
    "Conviction",
    "Factor",
    "Tier",
    "agreement_factor",
    "assess",
    "calibration_factor",
    "cost_factor",
    "freshness_factor",
    "regime_factor",
]
