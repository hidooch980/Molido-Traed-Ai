"""Service tiers, and what each one unlocks (spec §45, §68).

Two questions decide every request and they are not the same question. A
permission asks *may this principal act* - read, simulate, execute - and comes
from their role. A plan asks *does this tenant's subscription include the
feature at all*, and comes from what they signed up for. An admin on the free
tier holds EXECUTE and still cannot reach live execution; a viewer on the paid
tier can reach every page and still cannot place an order. Collapsing the two
into one check is how a billing tier ends up granting authority, or a role ends
up granting a paid feature.

The three tiers are deliberately not "small, medium, large":

  FREE        everything that costs this deployment nothing to answer, which
              is most of it. The measurement tooling is here on purpose - the
              part of this system worth trusting is the part that says "no
              proven edge", and putting that behind a paywall would sell
              confidence rather than evidence.

  CONDITIONAL unlocked by meeting a condition rather than by paying: a
              connected broker account, a completed challenge rulebook, a
              minimum number of resolved trades. The condition is the product.
              A feature that needs fifty resolved outcomes to mean anything is
              not withheld to extract money; it is withheld because it would
              lie with forty-nine.

  PAID        features with a marginal cost per tenant - live execution, a
              broker connection this deployment maintains, storage that grows
              with use.

Nothing here charges anybody. There is no payment processor, no card handling
and no invoice: this module records which tier a tenant is on and refuses
features outside it. Wiring money to it is a separate decision with its own
consequences, and it belongs to whoever owns the business rather than to a
gate.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class Plan(StrEnum):
    """What a tenant's subscription includes."""

    FREE = "free"
    CONDITIONAL = "conditional"
    PAID = "paid"


class Feature(StrEnum):
    """A capability a plan may or may not include.

    Named for what the user gets rather than for the module behind it. A
    feature called `execution_api` tells a reader nothing about whether their
    account can trade.
    """

    # --- free
    MARKET_DATA = "market_data"
    DATA_QUALITY = "data_quality"
    SYMBOL_DNA = "symbol_dna"
    MARKET_MEMORY = "market_memory"
    DECISION_CHAIN = "decision_chain"
    RISK_LIMITS = "risk_limits"
    MEASUREMENT = "measurement"
    SECURITY_POSTURE = "security_posture"

    # --- conditional
    CHALLENGE_TRACKING = "challenge_tracking"
    BROKER_MIRROR = "broker_mirror"
    JOURNAL = "journal"
    MODEL_REGISTRY = "model_registry"

    # --- paid
    LIVE_EXECUTION = "live_execution"
    HOSTED_BROKER = "hosted_broker"
    EXTENDED_HISTORY = "extended_history"
    ALERTS = "alerts"


class Condition(StrEnum):
    """What unlocks a conditional feature.

    Each is checkable from data this system already holds, which is the test a
    condition has to pass to belong here. A condition nobody can evaluate is a
    a promise, and this module does not make promises.
    """

    BROKER_CONNECTED = "broker_connected"
    RULEBOOK_CONFIRMED = "rulebook_confirmed"
    FIFTY_RESOLVED_TRADES = "fifty_resolved_trades"
    CALIBRATED = "calibrated"


@dataclass(frozen=True)
class FeatureSpec:
    """One feature, its tier, and why it sits there.

    `why` is required rather than optional. A tier boundary without a stated
    reason gets moved by whoever wants it moved, and the first thing to drift
    across is always the measurement tooling.
    """

    feature: Feature
    plan: Plan
    why: str
    condition: Condition | None = None

    def as_dict(self) -> dict[str, str | None]:
        return {
            "feature": self.feature.value,
            "plan": self.plan.value,
            "why": self.why,
            "condition": self.condition.value if self.condition else None,
        }


#: Every feature this system knows about. A feature absent from this table is
#: refused rather than allowed - the same direction the execution gate fails
#: in, and for the same reason: a capability nobody classified is a capability
#: nobody thought about.
CATALOG: tuple[FeatureSpec, ...] = (
    FeatureSpec(
        Feature.MARKET_DATA,
        Plan.FREE,
        "bars this deployment already collects; serving them costs a query",
    ),
    FeatureSpec(
        Feature.DATA_QUALITY,
        Plan.FREE,
        "a feed's defects belong to whoever is reading it, not to a tier",
    ),
    FeatureSpec(
        Feature.SYMBOL_DNA,
        Plan.FREE,
        "computed once daily for every instrument regardless of who asks",
    ),
    FeatureSpec(
        Feature.MARKET_MEMORY,
        Plan.FREE,
        "derived from stored bars; no per-tenant cost",
    ),
    FeatureSpec(
        Feature.DECISION_CHAIN,
        Plan.FREE,
        "seeing which gate refused is how the system is understood, and a "
        "system nobody understands is one nobody should trust with money",
    ),
    FeatureSpec(
        Feature.RISK_LIMITS,
        Plan.FREE,
        "a limit nobody can see is a limit nobody can plan against",
    ),
    FeatureSpec(
        Feature.MEASUREMENT,
        Plan.FREE,
        "the scorecard, breakeven and walk-forward tooling. The part of this "
        "system worth trusting is the part that says 'no proven edge'; behind "
        "a paywall it would be selling confidence rather than evidence",
    ),
    FeatureSpec(
        Feature.SECURITY_POSTURE,
        Plan.FREE,
        "how a system is secured is not a premium disclosure",
    ),
    FeatureSpec(
        Feature.CHALLENGE_TRACKING,
        Plan.CONDITIONAL,
        "tracking a challenge against rules nobody confirmed produces a "
        "verdict about the wrong rulebook",
        Condition.RULEBOOK_CONFIRMED,
    ),
    FeatureSpec(
        Feature.BROKER_MIRROR,
        Plan.CONDITIONAL,
        "comparing what a broker holds against what this system believes "
        "requires a broker to compare with",
        Condition.BROKER_CONNECTED,
    ),
    FeatureSpec(
        Feature.JOURNAL,
        Plan.CONDITIONAL,
        "a journal of nothing is a blank page with statistics attached",
        Condition.FIFTY_RESOLVED_TRADES,
    ),
    FeatureSpec(
        Feature.MODEL_REGISTRY,
        Plan.CONDITIONAL,
        "promoting a model needs resolved outcomes to promote it against",
        Condition.CALIBRATED,
    ),
    FeatureSpec(
        Feature.LIVE_EXECUTION,
        Plan.PAID,
        "orders reaching a real broker, which carries real cost and real risk",
    ),
    FeatureSpec(
        Feature.HOSTED_BROKER,
        Plan.PAID,
        "a terminal this deployment runs and maintains per tenant",
    ),
    FeatureSpec(
        Feature.EXTENDED_HISTORY,
        Plan.PAID,
        "history beyond the rolling window, which grows storage per tenant",
    ),
    FeatureSpec(
        Feature.ALERTS,
        Plan.PAID,
        "outbound messages this deployment sends and pays for",
    ),
)

BY_FEATURE: dict[Feature, FeatureSpec] = {spec.feature: spec for spec in CATALOG}

#: Which plans include which tiers. A paid tenant gets everything below it;
#: `conditional` still has to satisfy its condition, because paying does not
#: create the fifty resolved trades a statistic needs.
_INCLUDES: dict[Plan, frozenset[Plan]] = {
    Plan.FREE: frozenset({Plan.FREE}),
    Plan.CONDITIONAL: frozenset({Plan.FREE, Plan.CONDITIONAL}),
    Plan.PAID: frozenset({Plan.FREE, Plan.CONDITIONAL, Plan.PAID}),
}


@dataclass(frozen=True)
class Verdict:
    """Whether a feature is available, and what is missing if it is not."""

    feature: Feature
    allowed: bool
    reason: str
    required_plan: Plan | None = None
    unmet_condition: Condition | None = None

    def as_dict(self) -> dict[str, object]:
        return {
            "feature": self.feature.value,
            "allowed": self.allowed,
            "reason": self.reason,
            "required_plan": self.required_plan.value if self.required_plan else None,
            "unmet_condition": self.unmet_condition.value if self.unmet_condition else None,
        }


def evaluate(
    feature: Feature,
    plan: Plan,
    *,
    satisfied: frozenset[Condition] = frozenset(),
) -> Verdict:
    """Is this feature available to a tenant on `plan` who meets `satisfied`?

    An unknown feature is refused. The alternative - allowing anything not
    explicitly listed - means every capability added from now on ships
    unclassified and available, which is the failure this table exists to
    prevent.
    """
    spec = BY_FEATURE.get(feature)
    if spec is None:
        return Verdict(
            feature=feature,
            allowed=False,
            reason="this feature is not in the catalogue, so no tier includes it",
        )

    if spec.plan not in _INCLUDES[plan]:
        return Verdict(
            feature=feature,
            allowed=False,
            reason=f"included from the {spec.plan.value} tier; this tenant is on {plan.value}",
            required_plan=spec.plan,
        )

    if spec.condition is not None and spec.condition not in satisfied:
        # Reached only when the plan already covers the tier, so this is never
        # a disguised upsell: the tenant has paid for it and the data has not
        # arrived.
        return Verdict(
            feature=feature,
            allowed=False,
            reason=spec.why,
            required_plan=spec.plan,
            unmet_condition=spec.condition,
        )

    return Verdict(feature=feature, allowed=True, reason="included", required_plan=spec.plan)


def features_for(
    plan: Plan, *, satisfied: frozenset[Condition] = frozenset()
) -> dict[str, list[str]]:
    """Split the catalogue into what a tenant has, what a condition is holding
    back, and what a different tier would include.

    Three lists rather than two. "Locked because you have not traded yet" and
    "locked because you have not paid" are different sentences to read, and
    merging them makes the first look like the second.
    """
    included: list[str] = []
    awaiting: list[str] = []
    beyond: list[str] = []
    for spec in CATALOG:
        verdict = evaluate(spec.feature, plan, satisfied=satisfied)
        if verdict.allowed:
            included.append(spec.feature.value)
        elif verdict.unmet_condition is not None:
            awaiting.append(spec.feature.value)
        else:
            beyond.append(spec.feature.value)
    return {"included": included, "awaiting_condition": awaiting, "beyond_plan": beyond}
