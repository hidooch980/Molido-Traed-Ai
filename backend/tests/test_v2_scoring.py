"""Combined V2 adapter: off by default, no double-count, no Risk Brain override."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from app.agents.risk_gate import RiskContext, Verdict, review_signal
from app.agents.v2.scoring import (
    CONSUMERS,
    ENV_FLAG,
    is_enabled,
    merge_into_extras,
    read_only_v2_input,
)
from tests.v2_bars import bull_spike_bars, ny, three_weekdays_oct2026

AS_OF = datetime(2026, 10, 21, 12, 0, tzinfo=UTC)


class TestV2Scoring:
    def test_flag_off_by_default(self, monkeypatch):
        monkeypatch.delenv(ENV_FLAG, raising=False)
        assert is_enabled() is False
        payload = read_only_v2_input("rocket_trade_hunter", bull_spike_bars(), as_of=AS_OF)
        assert payload.enabled is False and payload.score is None
        assert payload.may_override_risk_brain is False
        assert payload.pro_btb is None

    def test_enabled_runs_all_four_engines(self, monkeypatch):
        monkeypatch.setenv(ENV_FLAG, "1")
        payload = read_only_v2_input(
            "hybrid_ai_brain", three_weekdays_oct2026(), as_of=ny(2026, 10, 21, 12),
        )
        assert payload.enabled is True
        assert payload.key_levels and payload.sp2l and payload.spike_imbalance and payload.pro_btb
        assert payload.may_override_risk_brain is False
        assert payload.as_dict()["score_status"] == "RESEARCH"

    def test_spike_family_is_counted_once_with_both_sources(self, monkeypatch):
        monkeypatch.setenv(ENV_FLAG, "true")
        payload = read_only_v2_input("rocket_trade_hunter", bull_spike_bars(), as_of=AS_OF)
        spike = next(f for f in payload.features if f.family == "spike")
        assert spike.present
        # Both engines may see the same impulse; it still counts as one family.
        assert len(spike.sources) == len(set(spike.sources))
        if len(spike.sources) > 1:
            assert set(spike.sources) <= {"sp2l", "spike_imbalance"}
        families = [f.family for f in payload.features if f.present]
        assert families.count("spike") == 1

    def test_unknown_consumer_rejected(self):
        with pytest.raises(ValueError):
            read_only_v2_input("not-a-consumer", bull_spike_bars(), as_of=AS_OF, enabled=True)

    def test_named_consumers_match_the_pro_btb_set(self):
        assert "rocket_trade_hunter" in CONSUMERS and "hybrid_ai_brain" in CONSUMERS

    def test_merge_preserves_a_risk_block(self, monkeypatch):
        monkeypatch.setenv(ENV_FLAG, "1")
        payload = read_only_v2_input("adaptive_risk", bull_spike_bars(), as_of=AS_OF)
        extras = merge_into_extras(
            {"risk_verdict": "BLOCK", "risk_decision": {"verdict": "BLOCK"}},
            payload,
        )
        assert extras["risk_verdict"] == "BLOCK"
        assert extras["v2_engines"]["may_override_risk_brain"] is False

    def test_adapter_does_not_call_the_risk_gate(self, monkeypatch):
        def boom(*_a, **_k):
            raise AssertionError("risk gate must not be invoked")

        monkeypatch.setattr("app.agents.risk_gate.review_signal", boom)
        read_only_v2_input("rocket_trade_hunter", bull_spike_bars(), as_of=AS_OF, enabled=True)
        decision = review_signal({}, RiskContext())
        assert decision.verdict is Verdict.BLOCK
