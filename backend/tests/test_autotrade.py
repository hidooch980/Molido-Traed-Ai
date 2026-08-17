"""Joining decisions to orders, once each, behind every gate.

The rule had been writing decisions for days and the execution path existed;
nothing joined them, so the only position on the account was one sent by hand.

These tests are almost entirely about the ways the joining goes wrong. Every
other failure here ends in not trading. One ends in trading twice, and that is
the one no layer above can undo.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from app.execution.contracts import ExecutionReport, OrderState
from app.models.journal import (
    ARM_CONTROL,
    ARM_RULE,
    SOURCE_BROKER,
    SOURCE_PUBLIC,
    JournalEntry,
)
from app.workers import autotrade

NOW = datetime(2026, 8, 17, 12, 0, tzinfo=UTC)


class FakeBridge:
    """The terminal, as the bridge publishes it."""

    def __init__(self, *, positions=0, equity=10_000.0, trade_mode=0, symbols=None):
        self._positions = positions
        self._equity = equity
        self._trade_mode = trade_mode
        self._symbols = symbols

    def account(self):
        return {
            "available": True,
            "login": "68345601",
            "server": "RoboForex-Pro",
            "trade_mode": self._trade_mode,
            "equity": self._equity,
            "balance": self._equity,
        }

    def positions(self):
        return {"positions": [{"ticket": i} for i in range(self._positions)]}

    def symbols(self):
        if self._symbols is not None:
            return {"symbols": self._symbols}
        return {
            "symbols": [
                {
                    "name": "EURUSD",
                    "tick_value": 1.0,
                    "tick_size": 0.00001,
                    "volume_min": 0.01,
                    "volume_step": 0.01,
                }
            ]
        }


class FakeBroker:
    """Records what it was asked to send, and answers however the test wants."""

    name = "fake"

    def __init__(self, state=OrderState.FILLED, price=1.15855):
        self.state = state
        self.price = price
        self.submitted: list = []

    def submit(self, intent):
        self.submitted.append(intent)
        return ExecutionReport(
            client_order_id=str(intent.intent_id),
            state=self.state,
            at=NOW,
            broker_order_id="2373018703",
            average_price=self.price,
            reason="filled",
        )


@pytest.fixture()
def live(monkeypatch):
    """Every gate open, so a test can close exactly one."""
    from app.execution import autopilot

    monkeypatch.setattr(autopilot, "mode_now", lambda: ("live", "armed", True))
    monkeypatch.setattr(autopilot, "account_gate", lambda a: (True, "demo"))


def decide(
    session,
    *,
    symbol="EURUSD",
    arm=ARM_RULE,
    source=SOURCE_BROKER,
    at=None,
    levels=True,
    during=None,
):
    row = JournalEntry(
        symbol=symbol,
        decision="long",
        opened_at=at or NOW - timedelta(minutes=5),
        arm=arm,
        price_source=source,
        before=(
            {"entry": 1.1580, "stop": 1.1530, "target": 1.1630} if levels else {}
        ),
        during=during or {},
    )
    session.add(row)
    session.flush()
    return row


class TestItSendsAnOrderForAFreshDecision:
    def test_a_rule_decision_becomes_an_order(self, session, live):
        decide(session)
        broker = FakeBroker()

        report = autotrade.run_cycle(
            session, now=NOW, broker=broker, bridge=FakeBridge()
        )

        assert report["orders"] == 1
        assert report["filled"] == 1
        assert broker.submitted[0].symbol == "EURUSD"

    def test_the_side_follows_the_decision(self, session, live):
        row = decide(session)
        # Levels flipped with the side. The contract refuses a short whose stop
        # sits below its entry, and the recorder writes them together.
        row.decision = "short"
        row.before = {"entry": 1.1580, "stop": 1.1630, "target": 1.1530}
        session.flush()
        broker = FakeBroker()

        autotrade.run_cycle(session, now=NOW, broker=broker, bridge=FakeBridge())

        assert broker.submitted[0].side.value == "sell"

    def test_the_slippage_is_measured_per_order(self, session, live):
        """The number the whole dual-series argument was about, now measured
        against the price the rule actually decided on."""
        decide(session)

        report = autotrade.run_cycle(
            session,
            now=NOW,
            broker=FakeBroker(price=1.15855),
            bridge=FakeBridge(),
        )

        assert report["sent"][0]["slippage"] == pytest.approx(0.00055, abs=1e-5)


class TestItNeverTradesTheSameDecisionTwice:
    """Everything else here fails by not trading. This fails by trading twice,
    and no layer above can undo that."""

    def test_a_second_cycle_sends_nothing(self, session, live):
        decide(session)
        broker = FakeBroker()

        first = autotrade.run_cycle(
            session, now=NOW, broker=broker, bridge=FakeBridge()
        )
        second = autotrade.run_cycle(
            session, now=NOW, broker=broker, bridge=FakeBridge()
        )

        assert first["orders"] == 1
        assert second["orders"] == 0
        assert len(broker.submitted) == 1

    def test_the_order_is_written_onto_the_decision(self, session, live):
        row = decide(session)

        autotrade.run_cycle(session, now=NOW, broker=FakeBroker(), bridge=FakeBridge())

        assert row.during["order"]["ticket"] == "2373018703"
        assert row.during["order"]["state"] == str(OrderState.FILLED)

    def test_a_decision_already_marked_is_left_alone(self, session, live):
        """The mark is written before the order is sent, so a process that
        dies between the two loses an order rather than duplicating one."""
        decide(session, during={"order": {"state": "submitting"}})
        broker = FakeBroker()

        report = autotrade.run_cycle(
            session, now=NOW, broker=broker, bridge=FakeBridge()
        )

        assert report["orders"] == 0
        assert broker.submitted == []


class TestWhatIsNeverTraded:
    def test_the_control_arm_is_not_traded(self, session, live):
        """It is a coin flip written down so the rule has something to be
        measured against. Trading it would put money behind a random side."""
        decide(session, arm=ARM_CONTROL)
        broker = FakeBroker()

        report = autotrade.run_cycle(
            session, now=NOW, broker=broker, bridge=FakeBridge()
        )

        assert report["orders"] == 0
        assert broker.submitted == []

    def test_the_public_series_is_not_traded(self, session, live):
        """Both series decide on the same instruments at nearly the same
        instants. Trading both opens two positions for one market view."""
        decide(session, source=SOURCE_PUBLIC)

        report = autotrade.run_cycle(
            session, now=NOW, broker=FakeBroker(), bridge=FakeBridge()
        )

        assert report["orders"] == 0

    def test_a_stale_decision_is_not_traded(self, session, live):
        """An hour-old decision is about a price that has moved. Filling it
        now trades the delay rather than the rule."""
        decide(session, at=NOW - timedelta(hours=5))

        report = autotrade.run_cycle(
            session, now=NOW, broker=FakeBroker(), bridge=FakeBridge()
        )

        assert report["orders"] == 0

    def test_a_decision_with_no_levels_is_named_not_sized(self, session, live):
        decide(session, levels=False)

        report = autotrade.run_cycle(
            session, now=NOW, broker=FakeBroker(), bridge=FakeBridge()
        )

        assert report["orders"] == 0
        assert any("recorded no levels" in note for note in report["skipped"])


class TestTheGates:
    def test_paper_mode_sends_nothing(self, session, monkeypatch):
        from app.execution import autopilot

        monkeypatch.setattr(
            autopilot, "mode_now", lambda: ("paper", "no proven edge", False)
        )
        decide(session)
        broker = FakeBroker()

        report = autotrade.run_cycle(
            session, now=NOW, broker=broker, bridge=FakeBridge()
        )

        assert report["orders"] == 0
        assert "paper" in report["refused"]
        assert broker.submitted == []

    def test_a_closed_account_gate_sends_nothing(self, session, monkeypatch):
        from app.execution import autopilot

        monkeypatch.setattr(autopilot, "mode_now", lambda: ("live", "armed", True))
        monkeypatch.setattr(
            autopilot, "account_gate", lambda a: (False, "this is real money")
        )
        decide(session)

        report = autotrade.run_cycle(
            session, now=NOW, broker=FakeBroker(), bridge=FakeBridge()
        )

        assert report["orders"] == 0
        assert "real money" in report["refused"]


class TestTheCap:
    def test_a_full_book_sends_nothing(self, session, live):
        """A 10k account holding dozens of correlated FX positions is one
        market move from its own drawdown limit."""
        decide(session)

        report = autotrade.run_cycle(
            session,
            now=NOW,
            broker=FakeBroker(),
            bridge=FakeBridge(positions=autotrade.MAX_OPEN_POSITIONS),
        )

        assert report["orders"] == 0
        assert "cap is" in report["refused"]

    def test_the_cap_counts_the_terminal_not_this_system(self, session, live):
        """They disagree exactly when it matters, and the broker's answer is
        the one the account is judged on."""
        for i in range(4):
            decide(session, symbol="EURUSD", at=NOW - timedelta(minutes=i + 1))

        report = autotrade.run_cycle(
            session,
            now=NOW,
            broker=FakeBroker(),
            bridge=FakeBridge(positions=autotrade.MAX_OPEN_POSITIONS - 2),
        )

        assert report["orders"] == 2
        assert any("cap was reached" in note for note in report["skipped"])


class TestSizing:
    def test_no_tick_value_means_no_order(self, session, live):
        """A default size is a position whose risk nobody chose, and it would
        be wrong by a different factor on every symbol."""
        decide(session)
        bridge = FakeBridge(symbols=[{"name": "EURUSD", "tick_value": None}])

        report = autotrade.run_cycle(
            session, now=NOW, broker=FakeBroker(), bridge=bridge
        )

        assert report["orders"] == 0
        assert report["skipped"]

    def test_an_unpublished_symbol_is_named(self, session, live):
        decide(session, symbol="GBPNZD")

        report = autotrade.run_cycle(
            session, now=NOW, broker=FakeBroker(), bridge=FakeBridge()
        )

        assert report["orders"] == 0
        assert any("no contract" in note for note in report["skipped"])

    def test_the_risk_is_a_quarter_percent(self, session, live):
        """Small on purpose: the rule proposes several positions per instant
        and the edge is a fiftieth of a stop distance."""
        assert autotrade.RISK_PERCENT == 0.25


class TestOneBadDecisionDoesNotEndTheCycle:
    def test_a_side_and_stop_that_disagree_is_skipped_by_name(self, session, live):
        """The contract refuses a short stopped below its entry. Without a
        guard that refusal ends the cycle for every decision behind it."""
        broken = decide(session, at=NOW - timedelta(minutes=9))
        broken.decision = "short"  # levels still say long
        session.flush()
        decide(session, symbol="EURUSD", at=NOW - timedelta(minutes=8))
        broker = FakeBroker()

        report = autotrade.run_cycle(
            session, now=NOW, broker=broker, bridge=FakeBridge()
        )

        assert report["orders"] == 1
        assert any("is not a stop" in note for note in report["skipped"])
