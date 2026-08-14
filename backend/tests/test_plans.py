"""Service tiers, and the two questions they must not merge.

A permission asks whether a principal may act; a plan asks whether the tenant's
subscription includes the capability at all. An admin on the free tier holds
EXECUTE and still must not reach live execution. These tests hold that line,
because the moment a role can buy a feature or a tier can grant authority, both
checks stop meaning anything.
"""

from __future__ import annotations

import pytest

from app.core.plans import (
    BY_FEATURE,
    CATALOG,
    Condition,
    Feature,
    Plan,
    evaluate,
    features_for,
)

ALL_CONDITIONS = frozenset(Condition)


class TestTheCatalogueDescribesEverything:
    def test_every_feature_is_classified(self):
        """A feature missing from the catalogue is refused, so an omission is a
        silent outage rather than a silent grant - but it is still an outage."""
        missing = [f for f in Feature if f not in BY_FEATURE]

        assert not missing, f"features with no tier: {missing}"

    @pytest.mark.parametrize("spec", CATALOG, ids=lambda s: s.feature.value)
    def test_every_entry_states_why(self, spec):
        """A tier boundary without a stated reason gets moved by whoever wants
        it moved."""
        assert len(spec.why) > 20

    @pytest.mark.parametrize("spec", CATALOG, ids=lambda s: s.feature.value)
    def test_only_conditional_entries_carry_a_condition(self, spec):
        """A condition on a paid feature would be an upsell wearing a
        requirement's clothes."""
        if spec.plan is Plan.CONDITIONAL:
            assert spec.condition is not None
        else:
            assert spec.condition is None

    def test_an_unknown_feature_is_refused_not_allowed(self):
        verdict = evaluate("not_a_feature", Plan.PAID, satisfied=ALL_CONDITIONS)  # type: ignore[arg-type]

        assert verdict.allowed is False
        assert "not in the catalogue" in verdict.reason


class TestMeasurementIsFree:
    """The load-bearing product decision in this module.

    The part of this system worth trusting is the part that says "no proven
    edge". Behind a paywall it would be selling confidence rather than
    evidence, and the free tier would be the one that only ever agrees with
    you.
    """

    @pytest.mark.parametrize(
        "feature",
        [
            Feature.MEASUREMENT,
            Feature.DECISION_CHAIN,
            Feature.RISK_LIMITS,
            Feature.DATA_QUALITY,
            Feature.SECURITY_POSTURE,
        ],
    )
    def test_it_is_included_at_the_free_tier(self, feature):
        assert evaluate(feature, Plan.FREE).allowed is True


class TestPayingDoesNotCreateEvidence:
    def test_a_paid_tenant_still_waits_for_the_condition(self):
        """The journal needs fifty resolved trades to mean anything. Money does
        not produce them, and a journal that opened on payment would publish
        statistics about nothing."""
        verdict = evaluate(Feature.JOURNAL, Plan.PAID)

        assert verdict.allowed is False
        assert verdict.unmet_condition is Condition.FIFTY_RESOLVED_TRADES

    def test_meeting_the_condition_opens_it(self):
        verdict = evaluate(
            Feature.JOURNAL, Plan.PAID, satisfied=frozenset({Condition.FIFTY_RESOLVED_TRADES})
        )

        assert verdict.allowed is True

    def test_the_free_tier_cannot_unlock_a_conditional_feature_by_meeting_it(self):
        """A condition is necessary, not sufficient. Fifty resolved trades on
        the free tier is still the free tier."""
        verdict = evaluate(Feature.JOURNAL, Plan.FREE, satisfied=ALL_CONDITIONS)

        assert verdict.allowed is False
        assert verdict.required_plan is Plan.CONDITIONAL
        assert verdict.unmet_condition is None


class TestTiersInclude:
    def test_paid_includes_the_free_tier(self):
        assert evaluate(Feature.MARKET_DATA, Plan.PAID).allowed is True

    def test_conditional_includes_the_free_tier(self):
        assert evaluate(Feature.MARKET_DATA, Plan.CONDITIONAL).allowed is True

    def test_conditional_does_not_include_paid(self):
        verdict = evaluate(Feature.LIVE_EXECUTION, Plan.CONDITIONAL)

        assert verdict.allowed is False
        assert verdict.required_plan is Plan.PAID

    def test_free_reaches_nothing_above_it(self):
        for spec in CATALOG:
            if spec.plan is Plan.FREE:
                continue
            assert evaluate(spec.feature, Plan.FREE, satisfied=ALL_CONDITIONS).allowed is False


class TestTheSplitIsThreeWays:
    def test_a_condition_and_a_paywall_are_reported_apart(self):
        """"Locked because you have not traded yet" and "locked because you
        have not paid" are different sentences. Merging them makes the first
        look like the second."""
        split = features_for(Plan.CONDITIONAL)

        assert Feature.JOURNAL.value in split["awaiting_condition"]
        assert Feature.LIVE_EXECUTION.value in split["beyond_plan"]
        assert Feature.MEASUREMENT.value in split["included"]

    def test_every_feature_lands_in_exactly_one_list(self):
        split = features_for(Plan.CONDITIONAL, satisfied=frozenset({Condition.CALIBRATED}))
        total = sum(len(v) for v in split.values())
        seen = {name for names in split.values() for name in names}

        assert total == len(CATALOG)
        assert len(seen) == len(CATALOG)

    def test_a_paid_tenant_meeting_everything_is_beyond_nothing(self):
        split = features_for(Plan.PAID, satisfied=ALL_CONDITIONS)

        assert split["beyond_plan"] == []
        assert split["awaiting_condition"] == []
        assert len(split["included"]) == len(CATALOG)


class TestExecutionIsNotSoldByRole:
    def test_live_execution_is_paid_and_nothing_else_reaches_it(self):
        """The one line that must not move. A role grants authority to act; a
        plan grants access to the capability. If the free tier could reach live
        execution because its user is an admin, the two checks would have
        collapsed into one and the safer one would have lost."""
        assert BY_FEATURE[Feature.LIVE_EXECUTION].plan is Plan.PAID
        assert evaluate(Feature.LIVE_EXECUTION, Plan.FREE, satisfied=ALL_CONDITIONS).allowed is False
        assert evaluate(Feature.LIVE_EXECUTION, Plan.CONDITIONAL, satisfied=ALL_CONDITIONS).allowed is False
