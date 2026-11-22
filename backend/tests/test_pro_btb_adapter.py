"""Read-only adapter: off by default, never overrides Risk Brain."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from app.agents.pro_btb.adapter import (
    CONSUMERS,
    ENV_FLAG,
    is_enabled,
    merge_into_extras,
    read_only_input,
)
from app.agents.risk_gate import RiskContext, Verdict, review_signal
from tests.pro_btb_bars import bull_bars

AS_OF = datetime(2026, 11, 4, tzinfo=UTC)


class TestAdapter:
    def test_flag_is_off_by_default(self, monkeypatch):
        monkeypatch.delenv(ENV_FLAG, raising=False)
        assert is_enabled() is False

    def test_disabled_payload_has_no_trace(self, monkeypatch):
        monkeypatch.delenv(ENV_FLAG, raising=False)
        payload = read_only_input("rocket_trade_hunter", bull_bars(), as_of=AS_OF, symbol="XAUUSD")
        assert payload.enabled is False
        assert payload.trace is None
        assert payload.may_override_risk_brain is False

    def test_enabled_payload_is_read_only(self, monkeypatch):
        monkeypatch.setenv(ENV_FLAG, "1")
        payload = read_only_input("hybrid_ai_brain", bull_bars(), as_of=AS_OF, symbol="XAUUSD")
        assert payload.enabled is True
        assert payload.trace is not None
        assert payload.may_override_risk_brain is False
        assert payload.as_dict()["may_override_risk_brain"] is False

    def test_unknown_consumer_is_rejected(self):
        with pytest.raises(ValueError):
            read_only_input("not-a-consumer", bull_bars(), as_of=AS_OF, enabled=True)

    def test_all_named_consumers_are_supported(self):
        assert {
            "rocket_trade_hunter", "hybrid_ai_brain", "market_key_levels", "sp2l",
            "spike_and_imbalance", "multi_timeframe", "ai_validation_scoring",
            "adaptive_risk",
        } <= CONSUMERS
        for consumer in sorted(CONSUMERS):
            payload = read_only_input(consumer, bull_bars(), as_of=AS_OF, enabled=True)
            assert payload.consumer == consumer and payload.trace is not None

    def test_merge_does_not_rewrite_a_risk_block(self, monkeypatch):
        monkeypatch.setenv(ENV_FLAG, "true")
        payload = read_only_input("adaptive_risk", bull_bars(), as_of=AS_OF, enabled=True)
        extras = merge_into_extras(
            {"risk_verdict": "BLOCK", "risk_decision": {"verdict": "BLOCK"}, "other": 1},
            payload,
        )
        assert extras["risk_verdict"] == "BLOCK"
        assert extras["risk_decision"] == {"verdict": "BLOCK"}
        assert extras["pro_btb"]["enabled"] is True
        assert extras["pro_btb"]["may_override_risk_brain"] is False

        # Mutating the payload dict cannot flip the contract field on the object.
        extras["pro_btb"]["may_override_risk_brain"] = True
        assert payload.may_override_risk_brain is False

    def test_adapter_does_not_call_the_risk_gate(self, monkeypatch):
        called = {"n": 0}

        def boom(*_args, **_kwargs):
            called["n"] += 1
            raise AssertionError("risk gate must not be invoked")

        monkeypatch.setattr("app.agents.risk_gate.review_signal", boom)
        read_only_input("rocket_trade_hunter", bull_bars(), as_of=AS_OF, enabled=True)
        assert called["n"] == 0
        # The real gate remains independently callable and still BLOCKs on missing inputs.
        decision = review_signal({}, RiskContext())
        assert decision.verdict is Verdict.BLOCK
