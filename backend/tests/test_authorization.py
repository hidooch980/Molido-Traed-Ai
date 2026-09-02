"""Engine running is not order authorised, and nothing here can stop the engine.

Three states used to be read as one, and the failure was symmetrical: a
readiness failure was answered by proposing to stop the engine, and "the
engine is on" was read as "orders are flowing". Every test below holds the
engine RUNNING and varies one blocker at a time; the invariant checked every
time is that the engine state never moves.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from app.ops import authorization as auth
from app.ops.authorization import (
    EngineState,
    Facts,
    KillSwitchState,
    OrderAuthorizationState,
    decide,
)

NOW = datetime(2026, 9, 2, 20, 0, tzinfo=UTC)


def facts(**over) -> Facts:
    """A LIVE deployment with every gate open. Each test closes one."""
    base = dict(
        engine_running=True,
        kill_switch_engaged=False,
        kill_switch_reason="disengaged by operator",
        readiness_blocking_failures=[],
        readiness_important_failures=[],
        data_age_bars=0.4,
        account_available=True,
        account_reason="a demo account, described by the terminal",
        proven_edge=True,
        proven_edge_reason="1 registered edge(s) clear the bar",
        risk_approved=True,
        execution_mode="live",
        execution_mode_consistent=True,
    )
    base.update(over)
    return Facts(**base)


def engine_still_running(decision: auth.Decision) -> None:
    assert decision.engine is EngineState.RUNNING


# ------------------------------------------------------------ the matrix
class TestLiveEngineWithOneBlockerEach:
    def test_kill_switch_engaged_blocks_orders_and_not_the_engine(self):
        decision = decide(
            facts(kill_switch_engaged=True, kill_switch_reason="engaged by aziz"), now=NOW
        )

        engine_still_running(decision)
        assert decision.kill_switch is KillSwitchState.ENGAGED
        assert decision.authorization is OrderAuthorizationState.BLOCKED
        assert any("kill switch is engaged: engaged by aziz" in r for r in decision.blocking_reasons)

    def test_an_unreadable_kill_switch_is_engaged(self):
        decision = decide(facts(kill_switch_engaged=None), now=NOW)

        engine_still_running(decision)
        assert decision.kill_switch is KillSwitchState.ENGAGED
        assert not decision.order_authorized

    def test_a_blocking_readiness_failure_blocks(self):
        decision = decide(facts(readiness_blocking_failures=["no_secrets_in_repository"]), now=NOW)

        engine_still_running(decision)
        assert not decision.order_authorized
        assert any("no_secrets_in_repository" in r for r in decision.blocking_reasons)

    def test_stale_data_blocks(self):
        decision = decide(facts(data_age_bars=7.0), now=NOW)

        engine_still_running(decision)
        assert not decision.order_authorized
        assert any("beyond the 3-bar limit" in r for r in decision.blocking_reasons)

    def test_unknown_data_age_is_stale(self):
        decision = decide(facts(data_age_bars=None), now=NOW)

        assert not decision.order_authorized
        assert any("unknown is stale" in r for r in decision.blocking_reasons)

    def test_a_missing_account_blocks(self):
        decision = decide(facts(account_available=False, account_reason=""), now=NOW)

        engine_still_running(decision)
        assert not decision.order_authorized
        assert any("treated as real money and refused" in r for r in decision.blocking_reasons)

    def test_an_unobserved_account_blocks_and_says_it_was_not_looked_at(self):
        """A report from a process that never asked a bridge must not print a
        diagnosis about the bridge. Both still block; they say which is which."""
        decision = decide(facts(account_available=None, risk_approved=None), now=NOW)

        assert not decision.order_authorized
        assert any("not observed here" in r for r in decision.blocking_reasons)
        assert not any("cannot describe the account" in r for r in decision.blocking_reasons)
        assert decision.gate("account_known").observed is None
        assert decision.gate("risk_approved").observed is None

    def test_no_proven_edge_blocks(self):
        decision = decide(
            facts(proven_edge=False, proven_edge_reason="no registered edge clears the bar"),
            now=NOW,
        )

        engine_still_running(decision)
        assert not decision.order_authorized
        assert any("no registered edge clears the bar" in r for r in decision.blocking_reasons)

    def test_disk_failure_blocks_even_though_readiness_grades_it_important(self):
        decision = decide(facts(readiness_important_failures=["disk_headroom"]), now=NOW)

        engine_still_running(decision)
        assert not decision.order_authorized
        assert any("disk_headroom" in r for r in decision.blocking_reasons)

    def test_audit_failure_blocks(self):
        decision = decide(facts(readiness_important_failures=["audit_chain_intact"]), now=NOW)

        engine_still_running(decision)
        assert not decision.order_authorized

    def test_an_expired_restore_drill_blocks(self):
        decision = decide(facts(readiness_blocking_failures=["restore_drill_recent"]), now=NOW)

        engine_still_running(decision)
        assert not decision.order_authorized
        assert any("restore_drill_recent" in r for r in decision.blocking_reasons)

    def test_risk_not_approved_blocks(self):
        decision = decide(facts(risk_approved=False, risk_reason="daily loss limit reached"), now=NOW)

        assert not decision.order_authorized
        assert any("daily loss limit reached" in r for r in decision.blocking_reasons)

    def test_an_unlabelled_simulated_broker_blocks(self):
        decision = decide(
            facts(execution_mode="simulated", execution_mode_consistent=False), now=NOW
        )

        assert not decision.order_authorized
        assert any("simulated fills would not be labelled" in r for r in decision.blocking_reasons)


class TestEverythingPasses:
    def test_all_mandatory_gates_open_authorises(self):
        decision = decide(facts(), now=NOW)

        engine_still_running(decision)
        assert decision.kill_switch is KillSwitchState.RELEASED
        assert decision.authorization is OrderAuthorizationState.AUTHORIZED
        assert decision.blocking_reasons == []

    def test_an_important_non_input_failure_is_advisory_not_blocking(self):
        """`at_least_one_calibrated_source` is about the deployment, not this
        order's inputs. Reported, not a block."""
        decision = decide(
            facts(readiness_important_failures=["at_least_one_calibrated_source"]), now=NOW
        )

        assert decision.order_authorized
        assert any("at_least_one_calibrated_source" in a for a in decision.advisories)

    def test_the_override_authorises_and_says_so_every_time(self):
        decision = decide(
            facts(
                proven_edge=False,
                proven_edge_reason="no registered edge clears the bar",
                trade_without_proven_edge=True,
            ),
            now=NOW,
        )

        assert decision.order_authorized
        gate = decision.gate("proven_edge")
        assert gate is not None and gate.passed
        assert "MOLIDO_TRADE_WITHOUT_PROVEN_EDGE" in gate.reason
        assert gate.observed == {"proven": False, "override": True}


class TestNothingIsInferredOrRemembered:
    def test_a_stopped_engine_is_reported_as_stopped_and_blocks(self):
        decision = decide(facts(engine_running=False), now=NOW)

        assert decision.engine is EngineState.STOPPED
        assert not decision.order_authorized

    def test_unassessed_readiness_blocks(self):
        decision = decide(facts(readiness_blocking_failures=None), now=NOW)

        assert not decision.order_authorized
        assert any("not assessed" in r for r in decision.blocking_reasons)

    def test_recovery_is_just_the_next_call(self):
        """Disk low blocks; disk recovered authorises; nothing to reset."""
        blocked = decide(facts(readiness_important_failures=["disk_headroom"]), now=NOW)
        recovered = decide(facts(), now=NOW)

        assert not blocked.order_authorized
        assert recovered.order_authorized
        engine_still_running(blocked)
        engine_still_running(recovered)

    def test_the_dictionary_spells_out_every_state(self):
        payload = decide(facts(kill_switch_engaged=True), now=NOW).as_dict()

        assert payload["engine_state"] == "running"
        assert payload["kill_switch_state"] == "engaged"
        assert payload["order_authorization_state"] == "blocked"
        assert payload["engine_running"] is True
        assert payload["order_authorized"] is False
        assert isinstance(payload["blocking_reasons"], list) and payload["blocking_reasons"]
        assert "engine running is not order authorized" in payload["note"]

    def test_there_is_no_way_to_stop_the_engine_from_here(self):
        """By construction: no field, no function."""
        assert not hasattr(auth, "stop_engine")
        assert "engine_running" in Facts.__dataclass_fields__
        assert all(
            name not in Facts.__dataclass_fields__ for name in ("stop", "halt_engine", "shutdown")
        )


@pytest.mark.parametrize(
    "name",
    sorted(auth.IMPORTANT_THAT_BLOCK),
)
def test_each_input_check_is_about_this_orders_inputs(name):
    assert name in {"data_is_fresh", "disk_headroom", "audit_chain_intact"}
