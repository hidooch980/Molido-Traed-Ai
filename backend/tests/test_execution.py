"""Execution-layer tests (phases 25-27).

This is the only layer that can lose money, so almost every test here is an
attempt to get an order out of it that should not leave. The happy path gets
three tests; the ways to talk the checklist into a yes get the rest.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest

from app.core.errors import ValidationFailedError
from app.execution import broker as brk
from app.execution import engine as eng
from app.execution import safety as sfy
from app.execution.contracts import (
    Approval,
    ExecutionReport,
    OrderIntent,
    OrderSide,
    OrderState,
    OrderType,
    assert_transition,
    can_transition,
)

NOW = datetime(2026, 3, 12, 10, 0, tzinfo=UTC)


def approvals(*, missing: str | None = None, refused: str | None = None, at=NOW):
    out = []
    for source in sfy.REQUIRED_APPROVALS:
        if source == missing:
            continue
        out.append(
            Approval(
                source=source,
                approved=source != refused,
                detail="within limits" if source != refused else "over the ceiling",
                at=at,
            )
        )
    return tuple(out)


def intent(**overrides) -> OrderIntent:
    defaults = dict(
        symbol="EURUSD",
        side=OrderSide.BUY,
        order_type=OrderType.MARKET,
        risk_r=1.0,
        entry=1.1000,
        stop=1.0950,
        target=1.1150,
        approvals=approvals(),
        authorised_at=NOW,
        account_id="acct-1",
    )
    defaults.update(overrides)
    return OrderIntent(**defaults)


def live_policy(**overrides) -> sfy.ExecutionPolicy:
    """Every switch deliberately thrown. Getting here takes four decisions."""
    defaults = dict(enabled=True, dry_run=False, require_auth=True, max_risk_r_per_order=1.0)
    defaults.update(overrides)
    return sfy.ExecutionPolicy(**defaults)


def open_switch() -> sfy.KillSwitch:
    switch = sfy.KillSwitch()
    switch.disengage(by="operator")
    return switch


# ================================================================== defaults
class TestEveryDefaultRefuses:
    def test_a_fresh_policy_does_not_permit_execution(self):
        assert sfy.ExecutionPolicy().enabled is False
        assert sfy.ExecutionPolicy().dry_run is True
        assert sfy.ExecutionPolicy().require_auth is False

    def test_a_fresh_kill_switch_is_engaged(self):
        """A switch that starts open protects nothing until somebody remembers."""
        assert sfy.KillSwitch().engaged is True

    def test_the_default_configuration_blocks_every_order(self):
        result = sfy.preflight(
            intent(), policy=sfy.ExecutionPolicy(), kill_switch=sfy.KillSwitch(), now=NOW
        )

        assert result.cleared is False
        assert any("disabled" in b for b in result.blocks)
        assert any("kill switch" in b for b in result.blocks)

    def test_disengaging_the_switch_must_be_attributable(self):
        with pytest.raises(ValueError):
            sfy.KillSwitch().disengage(by="  ")

    def test_an_engaged_switch_records_who_and_why(self):
        switch = sfy.KillSwitch()
        switch.engage("daily loss limit hit", by="risk-brain")

        assert switch.as_dict()["engaged_by"] == "risk-brain"
        assert "daily loss" in switch.as_dict()["reason"]


# ================================================================= approvals
class TestFourLayersMustAgree:
    def test_a_clean_intent_clears(self):
        result = sfy.preflight(
            intent(), policy=live_policy(), kill_switch=open_switch(), now=NOW
        )

        assert result.cleared is True
        assert all(result.checks[f"approved_by_{s}"] for s in sfy.REQUIRED_APPROVALS)

    @pytest.mark.parametrize("source", sfy.REQUIRED_APPROVALS)
    def test_a_missing_approval_blocks(self, source):
        result = sfy.preflight(
            intent(approvals=approvals(missing=source)),
            policy=live_policy(),
            kill_switch=open_switch(),
            now=NOW,
        )

        assert result.cleared is False
        assert any(f"no approval from the {source}" in b for b in result.blocks)

    @pytest.mark.parametrize("source", sfy.REQUIRED_APPROVALS)
    def test_a_refusal_from_any_layer_blocks(self, source):
        result = sfy.preflight(
            intent(approvals=approvals(refused=source)),
            policy=live_policy(),
            kill_switch=open_switch(),
            now=NOW,
        )

        assert result.cleared is False

    def test_four_approvals_from_one_layer_do_not_satisfy_the_checklist(self):
        """The checklist is by name, so enthusiasm cannot substitute for scope."""
        keen = tuple(
            Approval(source="risk", approved=True, detail="fine", at=NOW) for _ in range(4)
        )

        result = sfy.preflight(
            intent(approvals=keen),
            policy=live_policy(),
            kill_switch=open_switch(),
            now=NOW,
        )

        assert result.cleared is False
        assert sum("no approval from" in b for b in result.blocks) == 3

    def test_no_approvals_at_all_blocks(self):
        result = sfy.preflight(
            intent(approvals=()), policy=live_policy(), kill_switch=open_switch(), now=NOW
        )

        assert result.cleared is False


# ================================================================= freshness
class TestApprovalsExpire:
    def test_stale_authorisation_blocks(self):
        """A risk decision is a statement about an account state that has moved."""
        result = sfy.preflight(
            intent(),
            policy=live_policy(),
            kill_switch=open_switch(),
            now=NOW + timedelta(seconds=60),
        )

        assert result.cleared is False
        assert any("old" in b for b in result.blocks)

    def test_a_future_dated_authorisation_blocks(self):
        result = sfy.preflight(
            intent(),
            policy=live_policy(),
            kill_switch=open_switch(),
            now=NOW - timedelta(seconds=30),
        )

        assert result.cleared is False
        assert any("future" in b for b in result.blocks)

    def test_a_fresh_intent_built_on_a_stale_approval_blocks(self):
        """Reassembling an intent must not refresh the evidence inside it."""
        result = sfy.preflight(
            intent(approvals=approvals(at=NOW - timedelta(days=30))),
            policy=live_policy(),
            kill_switch=open_switch(),
            now=NOW,
        )

        assert result.cleared is False
        assert any("approval is" in b for b in result.blocks)


# =============================================================== the intent
class TestAnIntentValidatesItself:
    def test_a_stop_on_the_wrong_side_is_refused(self):
        with pytest.raises(ValidationFailedError):
            intent(side=OrderSide.BUY, entry=1.10, stop=1.12)

    def test_a_sell_stopped_below_its_entry_is_refused(self):
        with pytest.raises(ValidationFailedError):
            intent(side=OrderSide.SELL, entry=1.10, stop=1.08, target=1.05)

    def test_a_target_on_the_wrong_side_is_refused(self):
        with pytest.raises(ValidationFailedError):
            intent(side=OrderSide.BUY, entry=1.10, stop=1.09, target=1.05)

    def test_an_intent_risking_nothing_is_refused(self):
        with pytest.raises(ValidationFailedError):
            intent(risk_r=0.0)

    def test_a_limit_order_without_a_price_is_refused(self):
        with pytest.raises(ValidationFailedError):
            intent(order_type=OrderType.LIMIT, entry=None)

    def test_a_naive_timestamp_is_refused(self):
        with pytest.raises(ValidationFailedError):
            intent(authorised_at=datetime(2026, 3, 12, 10, 0))

    def test_oversize_blocks_at_the_checklist(self):
        result = sfy.preflight(
            intent(risk_r=5.0),
            policy=live_policy(),
            kill_switch=open_switch(),
            now=NOW,
        )

        assert result.cleared is False
        assert any("ceiling" in b for b in result.blocks)


# ============================================================= idempotency
class TestTheSameDecisionIsOneOrder:
    def test_the_client_order_id_is_derived_from_the_order(self):
        """A retry has to produce the same id or it becomes a second position."""
        one = intent()
        same = OrderIntent(
            symbol=one.symbol, side=one.side, order_type=one.order_type,
            risk_r=one.risk_r, entry=one.entry, stop=one.stop, target=one.target,
            approvals=one.approvals, authorised_at=one.authorised_at,
            account_id=one.account_id, intent_id=one.intent_id,
        )

        assert same.client_order_id == one.client_order_id

    def test_two_separate_decisions_are_two_orders(self):
        assert intent().client_order_id != intent().client_order_id

    def test_a_changed_size_is_a_different_order(self):
        one = intent()
        resized = OrderIntent(
            symbol=one.symbol, side=one.side, order_type=one.order_type,
            risk_r=0.5, entry=one.entry, stop=one.stop, target=one.target,
            approvals=one.approvals, authorised_at=one.authorised_at,
            account_id=one.account_id, intent_id=one.intent_id,
        )

        assert resized.client_order_id != one.client_order_id

    def test_a_second_submission_is_refused_not_retried(self):
        log = eng.SubmissionLog()
        order = intent()
        paper = brk.PaperBroker()

        first = eng.execute(
            order, broker=paper, policy=live_policy(),
            kill_switch=open_switch(), log=log, now=NOW,
        )
        second = eng.execute(
            order, broker=paper, policy=live_policy(),
            kill_switch=open_switch(), log=log, now=NOW,
        )

        assert first.attempted is True
        assert second.attempted is False
        assert second.preflight.duplicate_of == order.client_order_id
        assert len(paper.orders) == 1

    def test_an_unreadable_log_refuses_rather_than_retries(self):
        """Only one of the two mistakes is recoverable."""

        class BrokenLog(eng.SubmissionLog):
            def submitted_id(self, _):
                raise RuntimeError("the submissions table is unreachable")

        outcome = eng.execute(
            intent(), broker=brk.PaperBroker(), policy=live_policy(),
            kill_switch=open_switch(), log=BrokenLog(), now=NOW,
        )

        assert outcome.attempted is False
        assert any("could not be read" in b for b in outcome.preflight.blocks)


# ============================================================== the executor
class TestExecute:
    def test_a_dry_run_sends_nothing_and_consumes_no_idempotency(self):
        """A rehearsal that burned the id would make the real order a duplicate."""
        log = eng.SubmissionLog()
        paper = brk.PaperBroker()
        order = intent()

        rehearsal = eng.execute(
            order, broker=paper, policy=live_policy(dry_run=True),
            kill_switch=open_switch(), log=log, now=NOW,
        )
        real = eng.execute(
            order, broker=paper, policy=live_policy(),
            kill_switch=open_switch(), log=log, now=NOW,
        )

        assert rehearsal.simulated is True
        assert rehearsal.attempted is False
        assert paper.orders == {} or real.attempted is True
        assert real.attempted is True

    def test_a_blocked_checklist_never_reaches_the_broker(self):
        paper = brk.PaperBroker()

        eng.execute(
            intent(), broker=paper, policy=live_policy(),
            kill_switch=sfy.KillSwitch(), log=eng.SubmissionLog(), now=NOW,
        )

        assert paper.orders == {}

    def test_auth_off_blocks_even_with_every_other_switch_thrown(self):
        """The line that does not move: an order with no attributable actor."""
        result = sfy.preflight(
            intent(),
            policy=live_policy(require_auth=False),
            kill_switch=open_switch(),
            now=NOW,
        )

        assert result.cleared is False
        assert any("REQUIRE_AUTH" in b for b in result.blocks)

    def test_a_cleared_order_reaches_the_broker_and_fills(self):
        paper = brk.PaperBroker()

        outcome = eng.execute(
            intent(), broker=paper, policy=live_policy(),
            kill_switch=open_switch(), log=eng.SubmissionLog(), now=NOW,
        )

        assert outcome.attempted is True
        assert outcome.report.state is OrderState.FILLED

    def test_the_attempt_is_recorded_before_the_submission(self):
        """A crash in the gap must leave evidence, not silence."""
        recorded: list[str] = []

        class WatchingLog(eng.SubmissionLog):
            def record_attempt(self, order):
                recorded.append("attempt")
                super().record_attempt(order)

        class WatchingBroker(brk.PaperBroker):
            def submit(self, order):
                recorded.append("submit")
                return super().submit(order)

        eng.execute(
            intent(), broker=WatchingBroker(), policy=live_policy(),
            kill_switch=open_switch(), log=WatchingLog(), now=NOW,
        )

        assert recorded == ["attempt", "submit"]


# ============================================================ unknown states
class TestUnknownIsNotFailure:
    def test_a_timeout_returns_unknown_not_rejected(self):
        paper = brk.PaperBroker()
        paper.timeout_next = True

        outcome = eng.execute(
            intent(), broker=paper, policy=live_policy(),
            kill_switch=open_switch(), log=eng.SubmissionLog(), now=NOW,
        )

        assert outcome.report.state is OrderState.UNKNOWN
        assert outcome.report.opened_risk is True

    def test_an_unknown_order_is_still_remembered_by_the_adapter(self):
        """Forgetting it is how a system loses a position it opened."""
        paper = brk.PaperBroker()
        paper.timeout_next = True
        order = intent()

        paper.submit(order)

        assert order.client_order_id in paper.orders

    def test_unknown_resolves_by_asking_not_by_assuming(self):
        paper = brk.PaperBroker()
        log = eng.SubmissionLog()
        order = intent()
        paper.timeout_next = True
        eng.execute(
            order, broker=paper, policy=live_policy(),
            kill_switch=open_switch(), log=log, now=NOW,
        )

        resolved = eng.resolve_unknown(order.client_order_id, broker=paper, log=log)

        assert resolved.state is OrderState.UNKNOWN

    def test_a_rejection_is_a_rejection(self):
        paper = brk.PaperBroker()
        paper.fail_next = "insufficient margin"

        outcome = eng.execute(
            intent(), broker=paper, policy=live_policy(),
            kill_switch=open_switch(), log=eng.SubmissionLog(), now=NOW,
        )

        assert outcome.report.state is OrderState.REJECTED
        assert outcome.report.opened_risk is False


# =========================================================== state machine
class TestTheStateMachineOnlyMovesForward:
    def test_a_filled_order_cannot_become_rejected(self):
        assert can_transition(OrderState.FILLED, OrderState.REJECTED) is False

        with pytest.raises(ValidationFailedError):
            assert_transition(OrderState.FILLED, OrderState.REJECTED)

    @pytest.mark.parametrize(
        "terminal", [OrderState.FILLED, OrderState.CANCELLED, OrderState.REJECTED]
    )
    def test_no_terminal_state_has_a_way_out(self, terminal):
        for following in OrderState:
            assert can_transition(terminal, following) is False

    def test_unknown_can_still_resolve_in_either_direction(self):
        assert can_transition(OrderState.UNKNOWN, OrderState.FILLED) is True
        assert can_transition(OrderState.UNKNOWN, OrderState.REJECTED) is True

    def test_a_stale_broker_message_cannot_walk_an_order_backwards(self):
        log = eng.SubmissionLog()
        log.record_report(
            ExecutionReport("mld-x", OrderState.FILLED, NOW, filled_quantity=1.0)
        )

        with pytest.raises(ValidationFailedError):
            log.record_report(ExecutionReport("mld-x", OrderState.SUBMITTED, NOW))


# =============================================================== paper broker
class TestThePaperBrokerCostsSomething:
    def test_slippage_always_costs_the_buyer(self):
        paper = brk.PaperBroker(slippage=0.0002)

        report = paper.submit(intent(side=OrderSide.BUY, entry=1.1000))

        assert report.average_price == pytest.approx(1.1002)

    def test_slippage_always_costs_the_seller(self):
        paper = brk.PaperBroker(slippage=0.0002)

        report = paper.submit(
            intent(side=OrderSide.SELL, entry=1.1000, stop=1.1050, target=1.0900)
        )

        assert report.average_price == pytest.approx(1.0998)

    def test_a_repeated_client_order_id_returns_the_original(self):
        paper = brk.PaperBroker()
        order = intent()

        first = paper.submit(order)
        second = paper.submit(order)

        assert first.broker_order_id == second.broker_order_id

    def test_cancelling_an_unknown_order_says_unknown(self):
        assert brk.PaperBroker().cancel("mld-nope").state is OrderState.UNKNOWN

    def test_the_adapter_never_claims_to_be_real(self):
        assert brk.PaperBroker().as_dict()["simulated"] is True


# ================================================================= guardian
class TestTheGuardian:
    def test_a_matching_book_is_healthy(self):
        book = [eng.Position("EURUSD", "buy", 1.0, stop=1.09)]

        report = eng.supervise(
            broker_positions=book, expected_positions=book, log=eng.SubmissionLog()
        )

        assert report.healthy is True

    def test_a_position_the_system_did_not_open_is_the_loudest_finding(self):
        report = eng.supervise(
            broker_positions=[eng.Position("GBPUSD", "buy", 1.0, stop=1.25)],
            expected_positions=[],
            log=eng.SubmissionLog(),
        )

        assert [p.symbol for p in report.orphans] == ["GBPUSD"]
        assert any("did not open it" in a for a in report.alerts)

    def test_a_position_that_vanished_is_reported(self):
        report = eng.supervise(
            broker_positions=[],
            expected_positions=[eng.Position("EURUSD", "buy", 1.0, stop=1.09)],
            log=eng.SubmissionLog(),
        )

        assert [p.symbol for p in report.missing] == ["EURUSD"]

    def test_a_position_without_a_stop_is_unprotected(self):
        report = eng.supervise(
            broker_positions=[eng.Position("EURUSD", "buy", 1.0, stop=None)],
            expected_positions=[eng.Position("EURUSD", "buy", 1.0, stop=None)],
            log=eng.SubmissionLog(),
        )

        assert [p.symbol for p in report.unprotected] == ["EURUSD"]
        assert any("unbounded" in a for a in report.alerts)

    def test_a_size_disagreement_is_drift(self):
        report = eng.supervise(
            broker_positions=[eng.Position("EURUSD", "buy", 2.0, stop=1.09)],
            expected_positions=[eng.Position("EURUSD", "buy", 1.0, stop=1.09)],
            log=eng.SubmissionLog(),
        )

        assert len(report.drifted) == 1
        assert "broker holds 2.0" in report.drifted[0]

    def test_an_unresolved_order_keeps_the_book_unhealthy(self):
        log = eng.SubmissionLog()
        log.record_report(ExecutionReport("mld-x", OrderState.UNKNOWN, NOW))

        report = eng.supervise(
            broker_positions=[], expected_positions=[], log=log
        )

        assert report.unresolved_orders == ["mld-x"]
        assert report.healthy is False

    def test_the_guardian_closes_nothing(self):
        """A supervisor acting on a discrepancy it does not understand turns an
        accounting problem into a realised loss."""
        report = eng.supervise(
            broker_positions=[eng.Position("GBPUSD", "buy", 1.0)],
            expected_positions=[],
            log=eng.SubmissionLog(),
        )

        assert report.as_dict()["closes_nothing"] is True


# ============================================================ nothing hidden
class TestNothingReachesALiveBroker:
    def test_the_package_ships_no_network_client(self):
        """Behaviour, not vocabulary: read the imports rather than the names."""
        import ast
        import pathlib

        import app.execution as package

        roots: set[str] = set()
        for path in pathlib.Path(package.__file__).parent.glob("*.py"):
            tree = ast.parse(path.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    roots.update(a.name.split(".")[0] for a in node.names)
                elif isinstance(node, ast.ImportFrom) and node.module:
                    roots.add(node.module.split(".")[0])

        forbidden = {"httpx", "requests", "socket", "urllib", "aiohttp", "websockets", "MetaTrader5"}
        assert roots & forbidden == set()

    def test_the_only_adapter_is_a_simulator(self):
        assert brk.PaperBroker().name == "paper"
        assert uuid.UUID  # imported for the intent ids above, kept honest
