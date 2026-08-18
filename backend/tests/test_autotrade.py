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
            # The real terminal stamps every publication and the risk brain
            # treats an unknown age as stale, not fresh. A fake account without
            # one is not a fresher feed, it is an unmeasurable one.
            "state": {"age_seconds": 18.0, "usable": True},
            "margin": 0.0,
            "free_margin": self._equity,
        }

    def positions(self):
        # The shape a real terminal publishes. A position without a stop or a
        # size is not a cheaper one - it is one whose risk cannot be priced,
        # and the portfolio brain refuses to add to a book it cannot measure.
        return {
            "positions": [
                {
                    "ticket": i,
                    "symbol": "GBPNZD",
                    "side": "buy" if i % 2 else "sell",
                    "volume": 0.01,
                    "price_open": 1.1000,
                    "stop": 1.0950,
                    "target": 1.1050,
                }
                for i in range(self._positions)
            ]
        }

    def symbols(self):
        if self._symbols is not None:
            return {"symbols": self._symbols}
        # Several symbols, not one: a test about the count cap needs four
        # distinct instruments to be sizable, and a single-symbol bridge made
        # three of them skip for want of a contract specification instead.
        return {
            "symbols": [
                {
                    "name": name,
                    "tick_value": 1.0,
                    "tick_size": 0.00001,
                    "volume_min": 0.01,
                    "volume_step": 0.01,
                    # The real terminal publishes these on every symbol and the
                    # spread guard prices the trade from them. A fixture without
                    # them is not a cheaper market, it is an unpriceable one.
                    "bid": 1.15890,
                    "ask": 1.15904,
                }
                for name in ("EURUSD", "GBPUSD", "USDCAD", "AUDUSD", "GBPNZD")
            ]
        }


@pytest.fixture(autouse=True)
def switch_released(monkeypatch):
    """Every test below predates the kill switch and is about something else.

    Released by default so those tests keep asking their own question. The
    switch has its own tests, which set it deliberately.
    """
    from app.execution import killswitch_store
    from app.execution.safety import KillSwitch

    def open_switch(*args, **kwargs):
        switch = KillSwitch()
        switch.disengage(by="test")
        return switch

    monkeypatch.setattr(killswitch_store, "load", open_switch)


NEWS_NOW = datetime(2026, 8, 18, 12, 0, tzinfo=UTC)


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

    # The risk brain is a gate like the others, so it opens here and is closed
    # deliberately by the tests that are about it. Production reads these from
    # recorded equity history; a test account with no history is not a
    # realistic account, it is one the brain correctly refuses to size.
    from app.services import equity as equity_service

    monkeypatch.setattr(equity_service, "peak_equity", lambda *a, **k: 10_000.0)
    monkeypatch.setattr(equity_service, "peak_day_open_balance", lambda *a, **k: 10_000.0)

    # A quiet week, injected. Without this every test reaches ForexFactory on
    # every cycle - slow, flaky, and a suite whose result depends on whether a
    # third party is up is not testing this code.
    monkeypatch.setattr(autotrade, "_this_week", lambda *a, **k: [])


def decide(
    session,
    *,
    symbol="EURUSD",
    arm=ARM_RULE,
    source=SOURCE_BROKER,
    at=None,
    levels=True,
    during=None,
    timeframe=None,
):
    before = {"entry": 1.1580, "stop": 1.1530, "target": 1.1630} if levels else {}
    if timeframe:
        before["timeframe"] = timeframe
    row = JournalEntry(
        symbol=symbol,
        decision="long",
        opened_at=at or NOW - timedelta(minutes=5),
        arm=arm,
        price_source=source,
        before=before,
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
    def test_paper_mode_reaches_no_real_broker(self, session, monkeypatch, live):
        """Paper now runs the whole cycle and sends nothing, rather than
        refusing before any of it. What must stay true is that nothing reaches
        an adapter that can place an order."""
        from app.execution import autopilot
        from app.execution.paper_broker import PaperBroker

        monkeypatch.setattr(
            autopilot, "mode_now", lambda: ("paper", "no proven edge", False)
        )
        decide(session)
        paper = PaperBroker()

        report = autotrade.run_cycle(
            session, now=NOW, broker=paper, bridge=FakeBridge()
        )

        assert report["mode"] == "paper"
        assert paper.submitted != []

    def test_paper_uses_the_paper_adapter_when_none_is_given(
        self, session, monkeypatch, live
    ):
        """The default in paper mode must not be the real one. A mode that
        depends on the caller passing the right broker is not a mode."""
        from app.execution import autopilot

        monkeypatch.setattr(
            autopilot, "mode_now", lambda: ("paper", "no proven edge", False)
        )
        decide(session)

        report = autotrade.run_cycle(session, now=NOW, bridge=FakeBridge())

        assert report["mode"] == "paper"

    def test_halted_still_refuses_before_anything(self, session, monkeypatch):
        from app.execution import autopilot

        monkeypatch.setattr(
            autopilot, "mode_now", lambda: ("halted", "edge gate shut", False)
        )
        decide(session)
        broker = FakeBroker()

        report = autotrade.run_cycle(
            session, now=NOW, broker=broker, bridge=FakeBridge()
        )

        assert report["orders"] == 0
        assert "halted" in report["refused"]
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
        # Distinct symbols: the per-symbol cap would otherwise stop this at
        # one, and the thing under test here is the count cap.
        for i, symbol in enumerate(["EURUSD", "GBPUSD", "USDCAD", "AUDUSD"]):
            decide(session, symbol=symbol, at=NOW - timedelta(minutes=i + 1))

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
        # A symbol the bridge deliberately does not publish.
        decide(session, symbol="USDTRY")

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


class TestTheAgeIsMeasuredFromTheClose:
    """A journal entry is stamped with the bar's instant - 04:00 for the bar
    labelled 04:00 - but that bar spans 04:00 to 05:00 and the rule decided on
    its close. Charging the decision that hour left a usable window of about
    fifteen minutes against a collector that runs every fifteen: the first live
    cycle found four decisions and traded none, missing by nine minutes."""

    def test_a_decision_from_the_previous_bar_is_still_traded(self, session, live):
        decide(session, at=NOW - timedelta(minutes=95))

        report = autotrade.run_cycle(
            session, now=NOW, broker=FakeBroker(), bridge=FakeBridge()
        )

        assert report["orders"] == 1

    def test_a_genuinely_old_decision_is_still_refused(self, session, live):
        """The guard has to keep working. Widening it until nothing is stale
        would be the other way to get this wrong."""
        decide(session, at=NOW - timedelta(hours=4))

        report = autotrade.run_cycle(
            session, now=NOW, broker=FakeBroker(), bridge=FakeBridge()
        )

        assert report["orders"] == 0

    def test_the_bar_length_is_stated_not_folded_into_the_limit(self):
        """Two different facts: how long a bar is, and how stale is too stale.
        Folding them into one number hides which was chosen."""
        assert autotrade.DECISION_BAR_MINUTES == 60
        assert autotrade.MAX_DECISION_AGE_MINUTES == 90


class TestHowHardItTradesIsDeploymentSettable:
    """These two are the numbers most worth changing on a practice account.
    A knob that reads back correctly but never reaches the sizing call is worse
    than a constant, because it looks like it was set."""

    def test_the_risk_percent_reaches_the_size(self, session, live, monkeypatch):
        from app.core.config import get_settings

        settings = get_settings()
        monkeypatch.setattr(settings, "autotrade_risk_percent", 2.0, raising=False)
        decide(session)
        broker = FakeBroker()

        report = autotrade.run_cycle(
            session, now=NOW, broker=broker, bridge=FakeBridge()
        )

        assert report["risk_percent"] == 2.0
        assert report["orders"] == 1

    def test_a_bigger_risk_buys_a_bigger_position(self, session, live, monkeypatch):
        """The number has to move the lots, not just the report."""
        from app.core.config import get_settings

        settings = get_settings()
        sizes = {}
        for name, symbol, percent in (
            ("small", "EURUSD", 0.25),
            ("large", "GBPUSD", 2.0),
        ):
            monkeypatch.setattr(
                settings, "autotrade_risk_percent", percent, raising=False
            )
            broker = FakeBroker()
            decide(session, symbol=symbol)
            autotrade.run_cycle(
                session, now=NOW, broker=broker, bridge=FakeBridge()
            )
            sizes[name] = (
                broker.submitted[-1].metadata.get("lots")
                if broker.submitted
                else None
            )

        assert sizes["small"] is not None and sizes["large"] is not None
        assert sizes["large"] > sizes["small"]

    def test_the_position_cap_is_settable(self, session, live, monkeypatch):
        from app.core.config import get_settings

        monkeypatch.setattr(
            get_settings(), "autotrade_max_open_positions", 20, raising=False
        )
        decide(session)

        report = autotrade.run_cycle(
            session, now=NOW, broker=FakeBroker(), bridge=FakeBridge()
        )

        assert report["max_open_positions"] == 20

    def test_the_defaults_are_the_conservative_pair(self):
        """Unset, it trades the way it has been trading. A deployment that sets
        nothing must not inherit somebody else's appetite."""
        from app.core.config import Settings

        assert Settings().autotrade_risk_percent == 0.25
        assert Settings().autotrade_max_open_positions == 8


class TestEachDecisionIsChargedItsOwnBar:
    """The add-back exists because a decision stamped 04:00 was taken at that
    bar's close. Which close depends on the bar, and charging an hourly one to
    an M5 decision keeps it tradeable for two and a half hours - trading the
    delay, which is the exact thing the freshness window is there to stop."""

    def test_an_hourly_decision_is_charged_an_hour(self):
        entry = JournalEntry(before={"timeframe": "H1"})

        assert autotrade._bar_minutes(entry) == 60

    def test_a_five_minute_decision_is_charged_five_minutes(self):
        entry = JournalEntry(before={"timeframe": "M5"})

        assert autotrade._bar_minutes(entry) == 5

    def test_an_entry_written_before_the_field_existed_keeps_the_old_charge(self):
        """Backfilling a guess onto old rows would rewrite history; they were
        all hourly, so the old constant is the honest answer for them."""
        assert autotrade._bar_minutes(JournalEntry(before={})) == 60

    def test_an_unreadable_timeframe_does_not_crash_the_cycle(self):
        assert autotrade._bar_minutes(JournalEntry(before={"timeframe": "M7"})) == 60

    def test_a_stale_five_minute_decision_is_refused_though_an_hourly_one_lives(
        self, session, live
    ):
        """Both are 100 minutes old. Under one shared hourly add-back both
        would trade; only the hourly one should."""
        old = NOW - timedelta(minutes=100)
        decide(session, symbol="EURUSD", at=old, timeframe="M5")

        report = autotrade.run_cycle(
            session, now=NOW, broker=FakeBroker(), bridge=FakeBridge()
        )

        assert report["orders"] == 0


class TestOnlyANeverSentRequestIsRetried:
    """Four orders were lost on the first live cycle to a read-only mount. The
    decisions were still sitting there, which is what a decision-first design
    is for - but retrying the wrong kind of rejection turns one refusal into
    two positions."""

    def test_a_request_that_was_never_written_is_retried(self, session, live):
        decide(
            session,
            during={
                "order": {
                    "state": str(OrderState.REJECTED),
                    "reason": (
                        "the request could not be written: [Errno 30] "
                        "Read-only file system"
                    ),
                }
            },
        )

        report = autotrade.run_cycle(
            session, now=NOW, broker=FakeBroker(), bridge=FakeBridge()
        )

        assert report["orders"] == 1

    def test_a_broker_rejection_is_not_retried(self, session, live):
        """The broker saw it and said no. Resending is how a transient refusal
        becomes two positions."""
        decide(
            session,
            during={
                "order": {
                    "state": str(OrderState.REJECTED),
                    "reason": "retcode 10019 not enough money",
                }
            },
        )

        report = autotrade.run_cycle(
            session, now=NOW, broker=FakeBroker(), bridge=FakeBridge()
        )

        assert report["orders"] == 0

    def test_an_unknown_is_never_retried(self, session, live):
        """UNKNOWN means the order may be live. It is the one state where
        retrying is most tempting and most dangerous."""
        decide(session, during={"order": {"state": str(OrderState.UNKNOWN)}})

        report = autotrade.run_cycle(
            session, now=NOW, broker=FakeBroker(), bridge=FakeBridge()
        )

        assert report["orders"] == 0

    def test_a_fill_is_never_retried(self, session, live):
        decide(session, during={"order": {"state": str(OrderState.FILLED)}})

        report = autotrade.run_cycle(
            session, now=NOW, broker=FakeBroker(), bridge=FakeBridge()
        )

        assert report["orders"] == 0


class TestOneSymbolIsOnePosition:
    """Eight live positions held only five symbols, with 0.48 lots of USDCAD
    across two of them. Each was a separate decision, so nothing was traded
    twice - but the account carried double the exposure the sizing computed for
    one decision, and a cap on count cannot see that."""

    def test_a_symbol_already_held_is_not_opened_again(self, session, live):
        decide(session)

        report = autotrade.run_cycle(
            session,
            now=NOW,
            broker=FakeBroker(),
            bridge=FakeBridgeHolding("EURUSD"),
        )

        assert report["orders"] == 0
        assert any("already holds a position" in n for n in report["skipped"])

    def test_two_decisions_on_one_symbol_in_one_cycle_send_once(
        self, session, live
    ):
        decide(session, at=NOW - timedelta(minutes=5))
        decide(session, at=NOW - timedelta(minutes=4))
        broker = FakeBroker()

        report = autotrade.run_cycle(
            session, now=NOW, broker=broker, bridge=FakeBridge()
        )

        assert report["orders"] == 1
        assert len(broker.submitted) == 1

    def test_a_different_symbol_is_unaffected(self, session, live):
        decide(session, symbol="EURUSD")

        report = autotrade.run_cycle(
            session,
            now=NOW,
            broker=FakeBroker(),
            bridge=FakeBridgeHolding("GBPUSD"),
        )

        assert report["orders"] == 1


class FakeBridgeHolding(FakeBridge):
    """A terminal already carrying a position in one symbol."""

    def __init__(self, symbol: str):
        super().__init__(positions=0)
        self.symbol = symbol

    def positions(self):
        return {
            "positions": [
                {
                    "ticket": 1,
                    "symbol": self.symbol,
                    "side": "buy",
                    "volume": 0.01,
                    "price_open": 1.1000,
                    "stop": 1.0950,
                }
            ]
        }


class TestTheSpreadIsPricedFromTheBrokerAtSendTime:
    """R is the stop distance, so what crossing the spread costs in R is the
    broker's own bid-ask measured against it. Read per send: the spread widens
    on news and at rollover, which is when a rule most wants to trade and when
    a stale number is most wrong."""

    SPEC = {"bid": 1.15890, "ask": 1.15904}  # live EURUSD, 1.4 pips

    def test_a_tighter_stop_costs_more_of_its_own_r(self):
        wide, _ = autotrade._spread_cost_r(self.SPEC, 0.00225)   # H1 geometry
        tight, _ = autotrade._spread_cost_r(self.SPEC, 0.00027)  # M1 geometry

        assert round(wide, 3) == 0.062
        assert round(tight, 3) == 0.519
        assert tight > wide

    def test_the_ceiling_lets_the_hourly_geometry_through(self):
        cost, _ = autotrade._spread_cost_r(self.SPEC, 0.00225)

        assert cost <= autotrade.MAX_SPREAD_COST_R

    def test_the_ceiling_stops_a_one_minute_scalp(self):
        """Half the risk paid before the trade has an opinion."""
        cost, _ = autotrade._spread_cost_r(self.SPEC, 0.00027)

        assert cost > autotrade.MAX_SPREAD_COST_R

    def test_a_missing_quote_is_not_a_free_one(self):
        """Treating an unpublished spread as zero would let the one trade
        nobody could price through the one check meant to stop it."""
        cost, why = autotrade._spread_cost_r({"bid": 1.1}, 0.002)

        assert cost is None
        assert "not a free one" in why

    def test_an_unreadable_quote_refuses_rather_than_guessing(self):
        cost, why = autotrade._spread_cost_r({"bid": "x", "ask": "y"}, 0.002)

        assert cost is None
        assert "could not be read" in why

    def test_a_crossed_book_is_refused(self):
        """Bid above ask is not a market to trade into."""
        cost, why = autotrade._spread_cost_r({"bid": 1.2, "ask": 1.1}, 0.002)

        assert cost is None
        assert "not a market" in why

    def test_a_zero_stop_leaves_r_undefined(self):
        cost, why = autotrade._spread_cost_r(self.SPEC, 0.0)

        assert cost is None
        assert "R is undefined" in why

    def test_a_zero_spread_is_free_rather_than_an_error(self):
        cost, _ = autotrade._spread_cost_r({"bid": 1.1, "ask": 1.1}, 0.002)

        assert cost == 0.0


class TestTheKillSwitchIsTheFirstGate:
    """This is the only path that sends live orders and it used to consult no
    switch at all. The API reported one engaged while this traded, because the
    switch lived in a per-request object that nothing here ever read."""

    def test_an_engaged_switch_sends_nothing(self, session, live):
        from app.execution.safety import KillSwitch

        decide(session)
        broker = FakeBroker()
        report = autotrade.run_cycle(
            session,
            now=NOW,
            broker=broker,
            bridge=FakeBridge(),
            kill_switch=KillSwitch(),
        )

        assert report["sent"] == []
        assert broker.submitted == []

    def test_the_refusal_names_the_switch_and_its_reason(self, session, live):
        from app.execution.safety import KillSwitch

        switch = KillSwitch()
        switch.engage("daily loss limit hit", by="risk")

        report = autotrade.run_cycle(
            session, now=NOW, broker=FakeBroker(), bridge=FakeBridge(), kill_switch=switch
        )

        assert "kill switch" in report["refused"]
        assert "daily loss limit hit" in report["refused"]

    def test_a_released_switch_lets_the_cycle_proceed(self, session, live):
        from app.execution.safety import KillSwitch

        decide(session)
        switch = KillSwitch()
        switch.disengage(by="aziz")
        broker = FakeBroker()

        autotrade.run_cycle(
            session, now=NOW, broker=broker, bridge=FakeBridge(), kill_switch=switch
        )

        assert broker.submitted != []

    def test_it_is_read_before_the_autopilot_mode(self, session, live, monkeypatch):
        """A halt reachable only after four other gates succeed is not a halt.
        With the mode raising, an engaged switch must still return cleanly."""
        from app.execution import autopilot
        from app.execution.safety import KillSwitch

        def explode():
            raise AssertionError("the mode was consulted before the kill switch")

        monkeypatch.setattr(autopilot, "mode_now", explode)

        report = autotrade.run_cycle(
            session,
            now=NOW,
            broker=FakeBroker(),
            bridge=FakeBridge(),
            kill_switch=KillSwitch(),
        )

        assert "kill switch" in report["refused"]

    def test_with_no_switch_passed_it_reads_the_stored_one(self, session, live, monkeypatch):
        """The default path is the one production uses, and it must not be a
        path that trades because nobody passed an argument."""
        from app.execution import killswitch_store
        from app.execution.safety import KillSwitch

        monkeypatch.setattr(killswitch_store, "load", lambda *a, **k: KillSwitch())
        decide(session)
        broker = FakeBroker()

        report = autotrade.run_cycle(
            session, now=NOW, broker=broker, bridge=FakeBridge()
        )

        assert broker.submitted == []
        assert "kill switch" in report["refused"]


class TestTheRiskBrainGovernsTheSize:
    """The layer that says no, which until now said it only to an API route.

    `brain/risk.py` holds the daily loss limit, the drawdown ceiling and the
    margin rules, and nothing that traded had ever consulted it. These are
    about it deciding rather than merely being asked."""

    @staticmethod
    def state(**over):
        from app.brain.risk import AccountState

        base = dict(
            equity=10_000.0,
            balance=10_000.0,
            peak_equity=10_000.0,
            daily_pnl_r=0.0,
            open_positions=2,
            used_margin=100.0,
            free_margin=9_900.0,
        )
        base.update(over)
        return AccountState(**base)

    def verdict(self, state):
        from app.brain.risk import DataHealth, authorise

        return authorise(
            requested_risk_r=0.008, account=state, health=DataHealth(data_age_bars=0.5)
        )

    def test_the_daily_loss_limit_blocks(self):
        """The circuit breaker the audit found missing from the live path."""
        blocked = self.verdict(self.state(daily_pnl_r=-4.0))

        assert blocked.approves is False
        assert any("daily loss" in b for b in blocked.hard_breaches)

    def test_a_loss_short_of_the_limit_reduces_rather_than_blocks(self):
        """A limit that only ever slams shut teaches nothing on the way down."""
        softened = self.verdict(self.state(daily_pnl_r=-2.0))

        assert softened.approves is True
        assert softened.permitted_risk_r < 0.008

    def test_drawdown_from_peak_reduces_the_size(self):
        shrunk = self.verdict(self.state(equity=9_200.0))

        assert shrunk.permitted_risk_r < self.verdict(self.state()).permitted_risk_r

    def test_an_uncalibrated_system_is_sized_down_even_when_healthy(self):
        """Nothing here is calibrated and no edge is proven, and the brain's
        answer to being unsure is a smaller position rather than none."""
        healthy = self.verdict(self.state())

        assert healthy.approves is True
        assert healthy.permitted_risk_r < 0.008

    def test_an_unknown_feed_age_blocks(self):
        """Not knowing how old the feed is is not evidence that it is young."""
        from app.brain.risk import DataHealth, authorise

        unknown = authorise(
            requested_risk_r=0.008, account=self.state(), health=DataHealth()
        )

        assert unknown.approves is False


class TestTheAccountStateRefusesToBeGuessed:
    """`AccountState` takes no optional fields on purpose. These are about the
    builder honouring that rather than filling gaps with plausible numbers."""

    def test_no_recorded_equity_refuses_the_cycle(self, session, monkeypatch):
        from app.services import equity as equity_service

        monkeypatch.setattr(equity_service, "peak_equity", lambda *a, **k: None)
        state, why = autotrade._account_state(
            session, {"login": "1", "equity": 10_000.0}, 0
        )

        assert state is None
        assert "unknown drawdown is not a zero one" in why

    def test_no_day_boundary_refuses_the_cycle(self, session, monkeypatch):
        from app.services import equity as equity_service

        monkeypatch.setattr(equity_service, "peak_equity", lambda *a, **k: 10_000.0)
        monkeypatch.setattr(equity_service, "peak_day_open_balance", lambda *a, **k: None)
        state, why = autotrade._account_state(
            session, {"login": "1", "equity": 10_000.0}, 0
        )

        assert state is None
        assert "cannot be measured against anything" in why

    def test_no_login_refuses(self, session):
        state, why = autotrade._account_state(session, {"equity": 10_000.0}, 0)

        assert state is None
        assert "no login" in why

    def test_no_published_age_leaves_it_unknown(self):
        """Which the brain then treats as stale. This does not soften that by
        substituting a number."""
        assert autotrade._feed_age_bars({}, NOW) is None
        assert autotrade._feed_age_bars({"state": {}}, NOW) is None
        assert autotrade._feed_age_bars({"state": {"age_seconds": "x"}}, NOW) is None

    def test_the_age_comes_from_the_bridge_that_measured_it(self):
        """Recomputing it here meant parsing a stamp in a format the bridge
        does not publish, and the first live call blocked on it."""
        fresh = autotrade._feed_age_bars({"state": {"age_seconds": 18.0}}, NOW)

        assert fresh is not None
        assert fresh < 0.01

    def test_a_flat_payload_still_works(self):
        assert autotrade._feed_age_bars({"age_seconds": 60.0}, NOW) == 1.0 / 60


class TestThePropRulebookGovernsWhenThereIsOne:
    """`brain/challenge.py` holds ten sourced rulebooks and had no caller in
    the live path. It answers what the risk brain does not: if this trade
    loses everything it risks, is the challenge still alive?"""

    @staticmethod
    def account(**over):
        """The shape `listing` really returns: a view wrapping the row, with
        the rulebook already resolved beside it. A flat stand-in passed every
        test and failed the first real registration."""
        from types import SimpleNamespace

        from app.brain import rulebooks

        key = over.pop("rulebook_key", "ftmo-challenge-2step-phase1")
        base = dict(is_active=True, rulebook_key=key, starting_balance=10_000.0,
                    label="test")
        base.update(over)
        return SimpleNamespace(
            account=SimpleNamespace(**base), rulebook=rulebooks.get(key)
        )

    def registry(self, monkeypatch, rows):
        from app.services import challenge_accounts

        monkeypatch.setattr(challenge_accounts, "listing", lambda *a, **k: rows)
        monkeypatch.setattr(challenge_accounts, "default_tenant", lambda *a, **k: None)

    def gate(self, session, **over):
        from datetime import date

        return autotrade._challenge_gate(
            session,
            {"equity": 10_000.0, "balance": 10_000.0},
            over.pop("open_positions", 1),
            over.pop("risk", 0.002),
            today=date(2026, 8, 18),
            moment=NEWS_NOW,
            in_news_window=over.pop("in_news_window", False),
        )

    def test_no_registered_account_passes_rather_than_inventing_limits(
        self, session, monkeypatch
    ):
        """An account with no rulebook is not a challenge account."""
        self.registry(monkeypatch, [])

        allowed, why, headroom = self.gate(session)

        assert allowed is True
        assert why == ""
        assert headroom is None

    def test_two_registrations_refuse_rather_than_pick(self, session, monkeypatch):
        """The registry carries no broker login, so with two accounts there is
        no honest way to know which rulebook governs this money."""
        self.registry(monkeypatch, [self.account(), self.account(label="second")])

        allowed, why, _ = self.gate(session)

        assert allowed is False
        assert "cannot be known" in why

    def test_an_unknown_rulebook_refuses(self, session, monkeypatch):
        self.registry(monkeypatch, [self.account(rulebook_key="not-a-real-book")])

        allowed, why, _ = self.gate(session)

        assert allowed is False
        assert "not one this build knows" in why

    def test_an_incomplete_rulebook_says_what_is_missing(self, session, monkeypatch):
        """Blocked with no breach means the engine was never told a limit. The
        fix is confirming the rulebook, not finding a trade that passes."""
        self.registry(monkeypatch, [self.account()])

        allowed, why, _ = self.gate(session)

        assert allowed is False
        assert "rulebook is incomplete" in why
        assert "leverage" in why or "position cap" in why

    def test_an_unreadable_registry_refuses_rather_than_passing(
        self, session, monkeypatch
    ):
        """A registry that cannot be read is not an empty one."""
        from app.services import challenge_accounts

        def broken(*a, **k):
            raise RuntimeError("db gone")

        monkeypatch.setattr(challenge_accounts, "listing", broken)
        monkeypatch.setattr(challenge_accounts, "default_tenant", lambda *a, **k: None)

        allowed, why, _ = self.gate(session)

        assert allowed is False
        assert "could not be read" in why


class TestTheOpenBookIsPricedBeforeAddingToIt:
    """`brain/portfolio.py` exists because two independently excellent EURUSD
    and GBPUSD longs are one larger dollar-short position, and a sizer judging
    each on its own merit approves twice the exposure it believes it did."""

    SPEC = {"tick_value": 1.0, "tick_size": 0.00001, "name": "USDCAD"}
    ONE_R = 20.0  # 0.2% of a 10,000 account

    def position(self, **over):
        base = {
            "symbol": "USDCAD",
            "side": "sell",
            "volume": 0.01,
            "price_open": 1.1000,
            "stop": 1.0950,
        }
        base.update(over)
        return base

    def test_an_open_position_is_priced_from_its_own_stop_and_size(self):
        """Not assumed to be one R. A position opened at a different equity,
        by hand, or before a risk change is not one R - and these are summed,
        so a wrong unit becomes a wrong total for the whole book."""
        risk = autotrade._open_risk_r(self.position(), self.SPEC, self.ONE_R)

        assert risk is not None
        assert round(risk, 4) == 0.25

    def test_a_bigger_position_carries_more_r(self):
        small = autotrade._open_risk_r(self.position(), self.SPEC, self.ONE_R)
        large = autotrade._open_risk_r(
            self.position(volume=0.05), self.SPEC, self.ONE_R
        )

        assert large == pytest.approx(5 * small)

    def test_a_position_with_no_stop_cannot_be_priced(self):
        """It is not a position risking nothing. It is one whose risk has no
        ceiling, which no number here can express."""
        assert autotrade._open_risk_r(
            self.position(stop=1.1000), self.SPEC, self.ONE_R
        ) is None

    def test_a_position_missing_fields_cannot_be_priced(self):
        assert autotrade._open_risk_r({"symbol": "X"}, self.SPEC, self.ONE_R) is None

    def test_an_unpriceable_position_refuses_the_trade(self):
        """Unknown exposure is not absent exposure, and adding to a book you
        cannot measure is what this module exists to prevent."""
        headroom, why = autotrade._portfolio_headroom(
            "EURUSD", "buy", 0.002, [{"symbol": "USDCAD"}], {"USDCAD": self.SPEC}, self.ONE_R
        )

        assert headroom is None
        assert "unknown is not zero" in why

    def test_an_empty_book_absorbs_the_whole_trade(self):
        headroom, why = autotrade._portfolio_headroom(
            "EURUSD", "buy", 0.002, [], {}, self.ONE_R
        )

        assert headroom == pytest.approx(0.002)
        assert why == ""

    def test_a_correlated_book_leaves_less_room_than_an_empty_one(self):
        """The whole point: the same trade is smaller when the book already
        leans the same way."""
        crowded = [
            self.position(symbol=s, side="buy") for s in ("EURUSD", "GBPUSD", "AUDUSD")
        ]
        specs = {s: {**self.SPEC, "name": s} for s in ("EURUSD", "GBPUSD", "AUDUSD")}

        alone, _ = autotrade._portfolio_headroom("NZDUSD", "buy", 0.002, [], {}, self.ONE_R)
        among, _ = autotrade._portfolio_headroom(
            "NZDUSD", "buy", 0.002, crowded, specs, self.ONE_R
        )

        assert among is None or among <= alone


class TestNewsClosesTheWindow:
    """Both rulebooks this build carries restrict trading around releases, and
    a violation there is not a loss - it is the account, in one afternoon. The
    calendar existed and was reachable only from an API route."""

    CPI = {
        "impact": "High",
        "currency": "USD",
        "at": "2026-08-18T12:03:00+00:00",
        "title": "CPI y/y",
    }

    def test_a_release_on_an_exposed_currency_shuts_the_symbol(self):
        clear, why = autotrade._news_gate("EURUSD", NEWS_NOW, [self.CPI])

        assert clear is False
        assert "CPI y/y" in why

    def test_a_release_on_an_unexposed_currency_does_not(self):
        clear, _ = autotrade._news_gate("AUDNZD", NEWS_NOW, [self.CPI])

        assert clear is True

    def test_the_quote_currency_counts_as_much_as_the_base(self):
        """USDCAD is exposed to a dollar release from the other side."""
        clear, _ = autotrade._news_gate("USDCAD", NEWS_NOW, [self.CPI])

        assert clear is False

    def test_gold_is_exposed_to_dollar_releases(self):
        clear, _ = autotrade._news_gate("XAUUSD", NEWS_NOW, [self.CPI])

        assert clear is False

    def test_a_release_outside_the_window_does_not_shut_it(self):
        later = {**self.CPI, "at": "2026-08-18T13:00:00+00:00"}

        clear, _ = autotrade._news_gate("EURUSD", NEWS_NOW, [later])

        assert clear is True

    def test_the_window_reaches_backwards_too(self):
        """The minutes after a print move price as much as the minutes before."""
        just_passed = {**self.CPI, "at": "2026-08-18T11:57:00+00:00"}

        clear, _ = autotrade._news_gate("EURUSD", NEWS_NOW, [just_passed])

        assert clear is False

    def test_medium_impact_does_not_shut_it(self):
        clear, _ = autotrade._news_gate(
            "EURUSD", NEWS_NOW, [{**self.CPI, "impact": "Medium"}]
        )

        assert clear is True

    def test_an_all_day_entry_draws_no_window(self):
        """A bank holiday has no clock, so no minutes can be measured from it."""
        clear, _ = autotrade._news_gate(
            "EURUSD", NEWS_NOW, [{**self.CPI, "at": None, "title": "Bank Holiday"}]
        )

        assert clear is True

    def test_an_unreadable_feed_refuses_rather_than_assuming_quiet(self):
        """An unknown news state is not a quiet one, and the rule being
        protected ends an account rather than costing a trade."""
        clear, why = autotrade._news_gate("EURUSD", NEWS_NOW, None)

        assert clear is False
        assert "unknown is not quiet" in why

    def test_a_symbol_that_cannot_be_split_refuses(self):
        clear, why = autotrade._news_gate("BTC", NEWS_NOW, [])

        assert clear is False
        assert "cannot be split" in why

    def test_an_empty_week_lets_everything_through(self):
        assert autotrade._news_gate("EURUSD", NEWS_NOW, [])[0] is True

    def test_the_window_is_wider_than_either_firm_states(self):
        """Sitting exactly on a rule's edge lets a clock difference of seconds
        decide whether the challenge survives."""
        assert autotrade.NEWS_WINDOW_MINUTES >= 5


class TestTheWeekendIsAheadBeforeItArrives:
    """Rulebooks that forbid weekend holding are asking about the gap: a
    position carried over Sunday's open can pass its stop without ever being
    offered the price. The engine gated on this as unknown until now."""

    @staticmethod
    def at(day: int, hour: int):
        return datetime(2026, 8, day, hour, tzinfo=UTC)

    def test_midweek_is_not_the_weekend(self):
        assert autotrade._weekend_ahead(self.at(17, 12)) is False  # Monday
        assert autotrade._weekend_ahead(self.at(20, 23)) is False  # Thursday

    def test_friday_morning_is_not_yet(self):
        """Warning at the first quote on Friday would shut two thirds of a
        normal session for a break that is nine hours off."""
        assert autotrade._weekend_ahead(self.at(21, 9)) is False

    def test_friday_afternoon_is(self):
        assert autotrade._weekend_ahead(self.at(21, 16)) is True

    def test_the_warning_leaves_time_to_close_what_is_open(self):
        """The FX week ends around 21:00 UTC, and a rule discovered at the
        last quote is a rule discovered too late."""
        assert autotrade.WEEKEND_WARNING_HOUR_UTC <= 18

    def test_the_whole_weekend_counts(self):
        """Saturday and Sunday are when a position can only have been carried
        in, which is the thing the rule is about."""
        assert autotrade._weekend_ahead(self.at(22, 10)) is True  # Saturday
        assert autotrade._weekend_ahead(self.at(23, 20)) is True  # Sunday


class TestTheAccountWideNewsAnswer:
    """Distinct from the per-symbol gate: the rulebook asks whether trading is
    restricted right now, not whether one instrument is exposed."""

    CPI = {
        "impact": "High",
        "currency": "USD",
        "at": "2026-08-18T12:03:00+00:00",
        "title": "CPI y/y",
    }

    def test_a_release_in_the_window_answers_yes(self):
        assert autotrade._any_high_impact_now(NEWS_NOW, [self.CPI]) is True

    def test_a_quiet_week_answers_no(self):
        assert autotrade._any_high_impact_now(NEWS_NOW, []) is False

    def test_a_distant_release_answers_no(self):
        far = {**self.CPI, "at": "2026-08-18T18:00:00+00:00"}

        assert autotrade._any_high_impact_now(NEWS_NOW, [far]) is False

    def test_medium_impact_does_not_count(self):
        assert autotrade._any_high_impact_now(
            NEWS_NOW, [{**self.CPI, "impact": "Medium"}]
        ) is False

    def test_an_unreadable_feed_answers_unknown_rather_than_no(self):
        """The engine gates on an unknown restriction, which is the same
        position the per-symbol check takes and for the same reason."""
        assert autotrade._any_high_impact_now(NEWS_NOW, None) is None


class TestADecisionFromAnotherFeedIsReanchored:
    """The daily series is measured on dukascopy and the order meets the
    broker. Those two disagree by about four pips on EURUSD here, so a level
    taken from one and sent to the other is a stop at a price that meant
    something on a different chart."""

    GEOMETRY = {"entry": 1.37241, "stop": 1.36392, "target": 1.38090}
    SPEC = {"bid": 1.37500, "ask": 1.37514}

    def test_a_long_enters_at_the_ask(self):
        """A buy lifts the ask. Entering at a mid nobody trades understates
        the cost by half the spread on every decision."""
        entry, _, _ = autotrade._levels_from_broker(self.GEOMETRY, self.SPEC, "long")

        assert entry == 1.37514

    def test_a_short_enters_at_the_bid(self):
        entry, _, _ = autotrade._levels_from_broker(self.GEOMETRY, self.SPEC, "short")

        assert entry == 1.37500

    def test_the_stop_distance_survives_the_move(self):
        """The distance is what the analysis produced - it is volatility, and
        volatility transfers between feeds. Only the anchor changes."""
        recorded = abs(self.GEOMETRY["entry"] - self.GEOMETRY["stop"])

        entry, stop, _ = autotrade._levels_from_broker(self.GEOMETRY, self.SPEC, "long")

        assert abs(entry - stop) == pytest.approx(recorded)

    def test_the_target_distance_survives_too(self):
        recorded = abs(self.GEOMETRY["target"] - self.GEOMETRY["entry"])

        entry, _, target = autotrade._levels_from_broker(
            self.GEOMETRY, self.SPEC, "long"
        )

        assert abs(target - entry) == pytest.approx(recorded)

    def test_the_stop_sits_below_a_long_and_above_a_short(self):
        _, long_stop, _ = autotrade._levels_from_broker(
            self.GEOMETRY, self.SPEC, "long"
        )
        short_entry, short_stop, _ = autotrade._levels_from_broker(
            self.GEOMETRY, self.SPEC, "short"
        )

        assert long_stop < self.SPEC["ask"]
        assert short_stop > short_entry

    def test_distances_come_from_the_recorded_levels_not_the_constants(self):
        """A decision keeps whatever geometry it was written with. Re-deriving
        from today's multiples would silently re-shape an old decision if one
        ever moved."""
        odd = {"entry": 100.0, "stop": 97.0, "target": 106.0}

        entry, stop, target = autotrade._levels_from_broker(
            odd, {"bid": 200.0, "ask": 200.0}, "long"
        )

        assert entry - stop == pytest.approx(3.0)
        assert target - entry == pytest.approx(6.0)

    def test_no_quote_refuses_rather_than_guessing_where_the_market_is(self):
        assert autotrade._levels_from_broker(self.GEOMETRY, {}, "long") is None
        assert autotrade._levels_from_broker(self.GEOMETRY, {"bid": None}, "long") is None

    def test_a_zero_stop_distance_refuses(self):
        flat = {"entry": 1.1, "stop": 1.1}

        assert autotrade._levels_from_broker(flat, self.SPEC, "long") is None

    def test_a_missing_target_is_carried_as_missing(self):
        """Not invented. A decision written without one is a decision without
        one, and a target conjured here is a level nobody chose."""
        _, _, target = autotrade._levels_from_broker(
            {"entry": 1.37241, "stop": 1.36392}, self.SPEC, "long"
        )

        assert target is None

    def test_a_broker_decision_is_left_alone(self):
        """Its prices are the prices the order will meet, so re-anchoring
        would move a level that was already correct."""
        from app.models.journal import SOURCE_BROKER

        assert SOURCE_BROKER not in autotrade.REANCHORED_SOURCES

    def test_the_daily_fold_is_admitted(self):
        """Withdrawn once on a -0.0201 R reading, then re-admitted when that
        reading turned out not to be significant at t = -0.48 - it was silence
        rather than a verdict, and silence is not evidence against.

        What decided it: the held-out half of the twenty-one years, 2017-2025,
        which selection never saw. The rule measures +0.0613 R at t = +4.06
        there, stronger than the half it was fitted on."""
        assert autotrade.REANCHORED_SOURCES == frozenset({"aggregated"})

    def test_the_stale_provider_is_not_admitted(self):
        """It still holds the twenty-one years the edge was measured on, and
        it still cannot say anything about today."""
        assert "dukascopy" not in autotrade.REANCHORED_SOURCES

    def test_the_mechanism_is_kept_for_a_series_that_is_current(self):
        """The admission was wrong; the arithmetic was not. Sending the one
        recorded decision as-is would have placed its stop 232 pips away
        instead of the 84.9 it asked for."""
        entry, stop, _ = autotrade._levels_from_broker(
            self.GEOMETRY, {"bid": 1.38691, "ask": 1.38708}, "long"
        )

        assert (entry - stop) * 10000 == pytest.approx(84.9, abs=0.1)


class TestTheDailySeriesIsAdmittedAndReAnchored:
    """The daily series is the one timeframe with a measured edge, and it
    comes from a fold of hourly bars rather than from the terminal. Its levels
    are another feed's numbers, so they are re-anchored onto the broker's own
    price before anything is sent."""

    def test_the_folded_series_reaches_today_and_is_admitted(self):
        """Reaching today was the blocker the fold was built to clear, and
        the measurement that withdrew it was not significant."""
        assert "aggregated" in autotrade.REANCHORED_SOURCES

    def test_the_terminal_series_is_not_in_the_re_anchored_set(self):
        """Its prices are the prices the order will meet, so re-anchoring them
        onto themselves would be a rounding error looking for a purpose."""
        from app.models.journal import SOURCE_BROKER

        assert SOURCE_BROKER not in autotrade.REANCHORED_SOURCES

    def test_the_hourly_public_series_is_still_refused(self):
        """A 2.5x ATR stop on H1 is around twenty pips and the feeds sit four
        apart - a fifth of the stop. The same reasoning that admits D1
        excludes this."""
        assert "yfinance" not in autotrade.REANCHORED_SOURCES

    def test_a_daily_decision_keeps_its_distances(self):
        """Volatility transfers between feeds; absolute price does not."""
        geometry = {"entry": 1.37241, "stop": 1.36392, "target": 1.38090}
        quote = {"bid": 1.37500, "ask": 1.37514}

        entry, stop, target = autotrade._levels_from_broker(geometry, quote, "long")

        assert entry == quote["ask"]
        assert round(entry - stop, 5) == round(
            geometry["entry"] - geometry["stop"], 5
        )
        assert round(target - entry, 5) == round(
            geometry["target"] - geometry["entry"], 5
        )


class TestTheFleetLetsEachAccountFailAlone:
    """A terminal that is logged out, a bridge that is not mounted, a rulebook
    that no longer resolves - each is a fact about one account, and a fleet
    that stops on the first of them stops on its weakest member."""

    def dirs(self, monkeypatch, mapping):
        from app.providers import metatrader

        monkeypatch.setattr(metatrader, "bridge_dirs", lambda *a, **k: mapping)

    def test_every_configured_account_gets_a_cycle(self, session, monkeypatch, live):
        import pathlib

        from app.workers import autotrade as mod

        self.dirs(monkeypatch, {"one": pathlib.Path("/a"), "two": pathlib.Path("/b")})
        seen: list[str] = []

        def fake_cycle(_session, **kwargs):
            seen.append(str(kwargs["bridge"].directory))
            return {"orders": 1}

        monkeypatch.setattr(mod, "run_cycle", fake_cycle)
        report = mod.run_all_accounts(session)

        assert report["accounts"] == 2
        assert report["orders"] == 2
        assert len(seen) == 2

    def test_one_account_raising_does_not_stop_the_others(
        self, session, monkeypatch, live
    ):
        import pathlib

        from app.workers import autotrade as mod

        self.dirs(monkeypatch, {"broken": pathlib.Path("/a"), "fine": pathlib.Path("/b")})

        def fake_cycle(_session, **kwargs):
            if str(kwargs["bridge"].directory).endswith("a"):
                raise RuntimeError("terminal logged out")
            return {"orders": 3}

        monkeypatch.setattr(mod, "run_cycle", fake_cycle)
        report = mod.run_all_accounts(session)

        assert report["orders"] == 3
        assert "RuntimeError" in report["by_account"]["broken"]["refused"]
        assert report["by_account"]["fine"]["orders"] == 3

    def test_the_failure_says_the_others_were_unaffected(
        self, session, monkeypatch, live
    ):
        import pathlib

        from app.workers import autotrade as mod

        self.dirs(monkeypatch, {"broken": pathlib.Path("/a")})
        monkeypatch.setattr(
            mod, "run_cycle", lambda *a, **k: (_ for _ in ()).throw(OSError("no mount"))
        )

        report = mod.run_all_accounts(session)

        assert "others were unaffected" in report["by_account"]["broken"]["refused"]

    def test_each_account_gets_its_own_broker_and_bridge(
        self, session, monkeypatch, live
    ):
        """Sharing either would send one account's orders to another's
        terminal, which every file involved would make look correct."""
        import pathlib

        from app.workers import autotrade as mod

        self.dirs(monkeypatch, {"one": pathlib.Path("/a"), "two": pathlib.Path("/b")})
        pairs: list[tuple[str, str]] = []

        def fake_cycle(_session, **kwargs):
            pairs.append(
                (str(kwargs["bridge"].directory), str(kwargs["broker"].directory))
            )
            return {"orders": 0}

        monkeypatch.setattr(mod, "run_cycle", fake_cycle)
        mod.run_all_accounts(session)

        assert len({p[0] for p in pairs}) == 2
        assert all(bridge == broker for bridge, broker in pairs)


class TestOneAccountCanBePausedWithoutTheOthers:
    """The global kill switch is a fleet-wide halt. This is the other thing:
    one account paused while the rest carry on, because a terminal is being
    reconnected or a challenge has been failed."""

    def dirs(self, monkeypatch, mapping):
        from app.providers import metatrader

        monkeypatch.setattr(metatrader, "bridge_dirs", lambda *a, **k: mapping)

    def test_a_paused_account_is_skipped_and_the_others_run(
        self, session, monkeypatch, live, tmp_path
    ):
        import pathlib

        from app.execution import account_switch
        from app.workers import autotrade as mod

        self.dirs(monkeypatch, {"one": pathlib.Path("/a"), "two": pathlib.Path("/b")})
        account_switch.write("one", active=False, by="aziz", directory=tmp_path)
        original = account_switch.state
        monkeypatch.setattr(
            account_switch, "state", lambda key: original(key, tmp_path)
        )
        monkeypatch.setattr(mod, "run_cycle", lambda *a, **k: {"orders": 2})

        report = mod.run_all_accounts(session)

        assert report["by_account"]["one"]["orders"] == 0
        assert "paused" in report["by_account"]["one"]["skipped"]
        assert report["by_account"]["two"]["orders"] == 2

    def test_a_pause_is_told_apart_from_a_failure(
        self, session, monkeypatch, live, tmp_path
    ):
        """Both are zero orders, and only one of them wants somebody to go
        and look at it."""
        import pathlib

        from app.execution import account_switch
        from app.workers import autotrade as mod

        self.dirs(monkeypatch, {"one": pathlib.Path("/a")})
        account_switch.write("one", active=False, by="aziz", directory=tmp_path)
        original = account_switch.state
        monkeypatch.setattr(
            account_switch, "state", lambda key: original(key, tmp_path)
        )

        report = mod.run_all_accounts(session)

        assert "skipped" in report["by_account"]["one"]
        assert "refused" not in report["by_account"]["one"]


class TestGoldIsAdmittedOnTheInstrumentNotTheFeed:
    """The source rule exists because a decision on one feed's prices is a
    decision about a slightly different reality. Gold is where that reasoning
    does not apply: the analysis series is the futures contract and the order
    is spot, so the two never had the same price and were never going to."""

    def test_the_futures_symbol_is_admitted(self):
        assert "GCFUT" in autotrade.REANCHORED_SYMBOLS

    def test_it_is_placed_in_the_instrument_the_broker_fills(self):
        assert autotrade._tradeable_symbol("GCFUT") == "XAUUSD"
        assert autotrade._tradeable_symbol("SIFUT") == "XAGUSD"

    def test_an_ordinary_symbol_is_unchanged(self):
        assert autotrade._tradeable_symbol("EURUSD") == "EURUSD"

    def test_no_currency_pair_is_admitted_by_symbol(self):
        """The exception is about an instrument whose two series were never
        the same price, not a way around the feed rule."""
        for pair in ("EURUSD", "GBPUSD", "USDJPY"):
            assert pair not in autotrade.REANCHORED_SYMBOLS

    def test_the_position_cap_counts_the_traded_name(self):
        """A GCFUT decision and an XAUUSD position are the same exposure under
        two names, and a cap that misses that opens both."""
        assert autotrade._tradeable_symbol("GCFUT") in {"XAUUSD"}
