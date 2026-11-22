"""Rule catalog: one status each, no VERIFIED claims, placement rules stay RESEARCH."""

from __future__ import annotations

from app.agents.pro_btb.rules import RULE_BY_ID, RULES, placement_rules_ready, status_counts
from app.agents.pro_btb.status import RuleStatus


class TestRules:
    def test_ids_are_unique_and_each_has_one_status(self):
        ids = [rule.id for rule in RULES]
        assert len(ids) == len(set(ids))
        assert set(RULE_BY_ID) == set(ids)
        for rule in RULES:
            assert rule.status in RuleStatus

    def test_no_rule_is_verified(self):
        assert status_counts()[RuleStatus.VERIFIED.value] == 0
        assert not any(rule.status is RuleStatus.VERIFIED for rule in RULES)

    def test_placement_definitions_stay_research(self):
        for rid in ("DEF_ENTRY_PRICE", "DEF_STOP_LOSS", "DEF_TAKE_PROFIT",
                    "DEF_BO_CANDLE", "DEF_GAP", "DEF_FOLLOW_THROUGH",
                    "DEF_BTB_ZONE_CONSTRUCTION"):
            assert RULE_BY_ID[rid].status is RuleStatus.RESEARCH
        assert placement_rules_ready() is False

    def test_specified_process_rules_are_tested(self):
        for rid in (
            "STRONG_LEG_ASSESS", "BO_CHECK_GAP", "BO_CHECK_FT", "BO_CHECK_CLOSE_EXTREME",
            "BO_MISSING_GAP_FT_RAISES_RISK", "BE_ZONE_LEG1_START", "BE_ZONE_LEG2_START",
            "BE_ZONE_SPIKE_TOP", "BE_ZONE_CHANNEL_TOP", "BE_ZONES_COMPARABLE",
            "BTB_ZONE_IS_PRICE_RANGE", "RETEST_WAIT_FOR_RETURN", "RETEST_MICROCHANNEL",
            "RETEST_SP_CH_TR", "CONFIRM_OR_WAIT", "ENTRY_BULL_AND_BEAR",
            "ENTRY_SL_TP_ONLY_SPECIFIED", "ENTRY_LOG_RR_INVALIDATION",
            "NO_GUESSED_RULE_AS_FINAL", "ADAPTER_OFF_BY_DEFAULT", "ADAPTER_NO_RISK_OVERRIDE",
        ):
            assert RULE_BY_ID[rid].status is RuleStatus.TESTED

    def test_counts_sum_to_catalog(self):
        counts = status_counts()
        assert sum(counts.values()) == len(RULES)
        assert counts[RuleStatus.TESTED.value] > 0
        assert counts[RuleStatus.RESEARCH.value] > 0
