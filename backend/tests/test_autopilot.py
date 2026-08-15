"""The loop that trades without being asked, and the order of its gates.

Nothing here places an order. `decide` and `execute` are injected recording
functions, so what is tested is this loop's control flow - which gate refuses
first, what happens when one raises, whether paper mode can ever send - with
the real functions in production. A loop that could only be tested by placing
orders would be a loop nobody tested.

The gate that matters most is the edge gate, and most of this file is about
it staying shut. The measured edge over a random control is z = 1.10 against a
required 1.96; live trading on that pays the spread on every round trip for a
return of about zero, and the resulting slow bleed looks like an execution
problem for months.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import pytest

from app.execution import autopilot
from app.learning import edge as edge_registry

NOW = datetime(2026, 8, 14, 12, 0, tzinfo=UTC)
INSTRUMENTS = [(uuid.uuid4(), "EURUSD"), (uuid.uuid4(), "GBPUSD")]


class FakeTrace:
    def __init__(self, cleared=True, stopped_at="", reason=""):
        self.cleared = cleared
        self.stopped_at = stopped_at
        self.reason = reason
        self.side = "long"
        self.entry = 1.1
        self.stop = 1.09
        self.target = 1.12
        self.risk_r = 1.0
        self.conviction = 0.6


class FakeOutcome:
    def __init__(self, submitted=True, reason="sent"):
        self.submitted = submitted
        self.reason = reason


@pytest.fixture()
def executed():
    """Records every send. Must stay empty in paper mode."""
    return []


@pytest.fixture()
def sending(executed):
    def execute(session, trace, **kwargs):
        executed.append(trace)
        return FakeOutcome()

    return execute


def clearing(session, instrument_id, timeframe, **kwargs):
    return FakeTrace(cleared=True)


def refusing(session, instrument_id, timeframe, **kwargs):
    return FakeTrace(cleared=False, stopped_at="risk", reason="daily loss cap reached")


@pytest.fixture()
def execution_on(monkeypatch):
    from app.core.config import get_settings

    settings = get_settings()
    monkeypatch.setattr(settings, "enable_execution", True, raising=False)
    monkeypatch.setattr(settings, "execution_dry_run", False, raising=False)
    monkeypatch.setattr(settings, "trade_without_proven_edge", False, raising=False)
    return settings


class TestTheEdgeGate:
    def test_no_proven_edge_means_no_live_trading(self):
        """PROVEN is empty because nothing has met the bar, not because nobody
        filled it in.

        The message changed once a claim started clearing four of the five
        requirements, and this test changed with it deliberately rather than
        being loosened: the assertion is now that the refusal names what is
        still missing. A test that only checked `allowed is False` would keep
        passing if the reason became "no".
        """
        allowed, why = edge_registry.live_trading_allowed()

        assert allowed is False
        assert "no registered edge clears the bar" in why
        # And it names what is still missing rather than stopping at "no".
        assert "held-out history" in why or "not distinguishable from noise" in why

    def test_the_rejected_claim_is_kept_with_its_numbers(self):
        """"We tried nothing" and "we tried this and it failed" are different
        facts, and keeping the second stops the same rule being re-proposed next
        month as a new idea."""
        assert edge_registry.REJECTED
        claim = edge_registry.REJECTED[0]

        assert claim.verdict.proven is False
        assert claim.evidence.z_score < claim.evidence.required_z

    def test_beating_breakeven_is_not_beating_the_control(self):
        """The exact mistake this file exists to prevent: the script compared
        the rule against 0.5 and printed CONFIRMED, when the control on the same
        bars had scored 0.5032."""
        from datetime import date

        beats_breakeven_only = edge_registry.Evidence(
            trials=22454,
            hit_rate=0.5084,
            control_hit_rate=0.5084,   # control did exactly as well
            expectancy_r=0.0167,
            control_expectancy_r=0.0167,
            comparisons=1,
            cost_r=0.0,
            registered_on=date(2026, 8, 1),
            data_ends=date(2026, 8, 14),
        )
        verdict = edge_registry.assess(beats_breakeven_only, pre_registered=True)

        assert verdict.proven is False
        assert any("beating nothing" in f for f in verdict.failures)

    def test_a_sweep_needs_a_higher_bar_than_one_hypothesis(self):
        """Being chosen from 612 candidates is what the correction exists to
        punish."""
        from datetime import date

        common = dict(
            trials=22454,
            hit_rate=0.52,
            control_hit_rate=0.50,
            expectancy_r=0.03,
            control_expectancy_r=0.0,
            cost_r=0.001,
            registered_on=date(2026, 8, 1),
            data_ends=date(2026, 8, 14),
        )
        one = edge_registry.Evidence(comparisons=1, **common)
        many = edge_registry.Evidence(comparisons=612, **common)

        assert many.required_z > one.required_z

    def test_an_edge_smaller_than_the_spread_is_refused(self):
        """Not a small edge. A loss."""
        from datetime import date

        thin = edge_registry.Evidence(
            trials=100000,
            hit_rate=0.53,
            control_hit_rate=0.50,
            expectancy_r=0.004,
            control_expectancy_r=0.0,
            comparisons=1,
            cost_r=0.01,          # the round trip costs more than it earns
            registered_on=date(2026, 8, 1),
            data_ends=date(2026, 8, 14),
        )
        verdict = edge_registry.assess(thin, pre_registered=True)

        assert verdict.proven is False
        assert any("is not a small edge" in f for f in verdict.failures)

    def test_held_out_history_is_not_forward_evidence(self):
        from datetime import date

        backtest_only = edge_registry.Evidence(
            trials=100000,
            hit_rate=0.55,
            control_hit_rate=0.50,
            expectancy_r=0.08,
            control_expectancy_r=0.0,
            comparisons=1,
            cost_r=0.001,
            registered_on=date(2026, 8, 14),
            data_ends=date(2026, 8, 14),   # same day: nothing new arrived
        )
        verdict = edge_registry.assess(backtest_only, pre_registered=True)

        assert verdict.proven is False
        assert any("substitute" in f for f in verdict.failures)

    def test_every_failure_is_reported_not_just_the_first(self):
        """A claim that fails on three counts and is fixed on one is still not
        an edge, and reporting them one at a time invites exactly that loop."""
        from datetime import date

        bad = edge_registry.Evidence(
            trials=100,
            hit_rate=0.50,
            control_hit_rate=0.52,
            expectancy_r=0.0,
            control_expectancy_r=0.01,
            comparisons=500,
            cost_r=0.01,
            registered_on=date(2026, 8, 14),
            data_ends=date(2026, 8, 14),
        )
        verdict = edge_registry.assess(bad, pre_registered=False)

        assert len(verdict.failures) >= 4


class TestTheModeIsDecidedOncePerPass:
    def test_execution_off_halts_before_anything_is_considered(self, session, monkeypatch):
        from app.core.config import get_settings

        monkeypatch.setattr(get_settings(), "enable_execution", False, raising=False)

        result = autopilot.run_once(
            session, instruments=INSTRUMENTS, now=NOW, decide_fn=clearing
        )

        assert result.mode == autopilot.HALTED
        assert result.intents == []

    def test_dry_run_is_paper_regardless_of_the_edge(self, session, monkeypatch):
        """Two switches, not one. Turning execution on and turning simulation
        off are separate decisions."""
        from app.core.config import get_settings

        settings = get_settings()
        monkeypatch.setattr(settings, "enable_execution", True, raising=False)
        monkeypatch.setattr(settings, "execution_dry_run", True, raising=False)
        monkeypatch.setattr(settings, "trade_without_proven_edge", True, raising=False)

        result = autopilot.run_once(
            session, instruments=INSTRUMENTS, now=NOW, decide_fn=clearing
        )

        assert result.mode == autopilot.PAPER

    def test_no_proven_edge_falls_back_to_paper(self, session, execution_on):
        """Execution on, dry-run off, and it still does not send - because
        nothing has been proven worth sending."""
        result = autopilot.run_once(
            session, instruments=INSTRUMENTS, now=NOW, decide_fn=clearing
        )

        assert result.mode == autopilot.PAPER
        # The reason travels with the mode. Which requirement is unmet changes
        # as claims are registered; that one is named does not.
        assert "no registered edge clears the bar" in result.reason


class TestPaperModeNeverSends:
    def test_nothing_reaches_execute(self, session, execution_on, sending, executed):
        result = autopilot.run_once(
            session,
            instruments=INSTRUMENTS,
            now=NOW,
            decide_fn=clearing,
            execute_fn=sending,
        )

        assert result.mode == autopilot.PAPER
        assert executed == [], "paper mode sent an order"

    def test_it_still_records_what_it_would_have_done(self, session, execution_on):
        """The point of paper mode is the record. An intent with no detail
        cannot be scored later, which makes the whole forward measurement
        worthless."""
        result = autopilot.run_once(
            session, instruments=INSTRUMENTS, now=NOW, decide_fn=clearing
        )

        acted = [i for i in result.intents if i.acted]
        assert len(acted) == 2
        assert acted[0].detail["entry"] == 1.1
        assert acted[0].detail["stop"] == 1.09

    def test_a_refused_decision_records_where_it_stopped(self, session, execution_on):
        """"It did not trade" is not an answer. Which gate stopped it is."""
        result = autopilot.run_once(
            session, instruments=INSTRUMENTS, now=NOW, decide_fn=refusing
        )

        assert all(not i.acted for i in result.intents)
        assert result.intents[0].stage == "risk"
        assert "daily loss cap" in result.intents[0].reason


class TestTheOverrideIsPossibleButNeverQuiet:
    def test_it_permits_live_trading(self, session, execution_on, monkeypatch, sending, executed):
        """The account holder's money and their decision. This does not block
        it - it refuses to let it happen silently."""
        monkeypatch.setattr(
            execution_on, "trade_without_proven_edge", True, raising=False
        )

        result = autopilot.run_once(
            session,
            instruments=INSTRUMENTS,
            now=NOW,
            decide_fn=clearing,
            execute_fn=sending,
        )

        assert result.mode == autopilot.LIVE
        assert len(executed) == 2

    def test_the_response_says_it_is_on_every_single_time(
        self, session, execution_on, monkeypatch, sending
    ):
        """A switch that goes quiet once flipped is a switch nobody remembers
        flipping."""
        monkeypatch.setattr(
            execution_on, "trade_without_proven_edge", True, raising=False
        )

        result = autopilot.run_once(
            session,
            instruments=INSTRUMENTS,
            now=NOW,
            decide_fn=clearing,
            execute_fn=sending,
        )

        assert result.edge_override is True
        assert result.as_dict()["edge_override_in_use"] is True
        assert "deliberate bet that the measurement is wrong" in result.reason

    def test_it_is_off_by_default(self):
        from app.core.config import get_settings

        assert getattr(get_settings(), "trade_without_proven_edge", False) is False


class TestOneBadSymbolDoesNotStopTheSweep:
    def test_a_raising_instrument_is_recorded_and_the_rest_continue(
        self, session, execution_on
    ):
        """A loop that dies on the first error trades nothing all day and
        reports nothing about why."""
        calls = {"n": 0}

        def sometimes_raises(sess, instrument_id, timeframe, **kwargs):
            calls["n"] += 1
            if calls["n"] == 1:
                raise RuntimeError("provider timed out")
            return FakeTrace(cleared=True)

        result = autopilot.run_once(
            session, instruments=INSTRUMENTS, now=NOW, decide_fn=sometimes_raises
        )

        assert len(result.intents) == 2
        assert result.intents[0].acted is False
        assert "RuntimeError" in result.intents[0].reason
        assert result.intents[1].acted is True

    def test_an_error_message_does_not_carry_the_exception_text(
        self, session, execution_on
    ):
        """The type, not the message. A provider exception can quote a URL with
        a key in it."""

        def raises_with_secret(sess, instrument_id, timeframe, **kwargs):
            raise RuntimeError("failed calling https://api.example.com?key=SECRET123")

        result = autopilot.run_once(
            session, instruments=INSTRUMENTS, now=NOW, decide_fn=raises_with_secret
        )

        assert "SECRET123" not in str(result.as_dict())


class TestTheEmptyWatchlistIsNotAnError:
    def test_no_instruments_reports_a_pass_that_did_nothing(self, session, execution_on):
        result = autopilot.run_once(session, instruments=[], now=NOW, decide_fn=clearing)

        assert result.intents == []
        assert result.as_dict()["considered"] == 0


class TestTheLoopRefusesWhatItCannotDo:
    """mypy caught this before it shipped: the loop called `decide` with four
    of its required arguments missing. Every test passed, because every test
    injects a decision function - so the only broken path was production.

    Refused with the reason now, rather than defaulted to something that would
    raise at the first instrument of the first live pass."""

    def test_no_decision_function_is_refused_not_guessed(self, session, execution_on):
        result = autopilot.run_once(session, instruments=INSTRUMENTS, now=NOW)

        assert result.intents == []
        assert "no decision function was supplied" in result.reason
        assert "context.build" in result.reason


class TestTheAccountGate:
    """Whether live orders may reach *this* account, whatever the deployment
    switches say. The bridge has published the account type since it was built
    and nothing read it - so one deployment-wide flag would have sent orders to
    a funded account exactly the way it sends them to a practice one."""

    DEMO = {"available": True, "is_real_money": False, "trade_mode": 0}
    REAL = {"available": True, "is_real_money": True, "trade_mode": 2}

    def test_a_demo_account_is_allowed(self):
        allowed, why = autopilot.account_gate(self.DEMO)

        assert allowed is True
        assert "demo" in why

    def test_a_real_account_is_refused_by_default(self):
        allowed, why = autopilot.account_gate(self.REAL)

        assert allowed is False
        assert "real-money orders are switched off" in why

    def test_an_undescribable_account_is_treated_as_real(self):
        """The safe direction. Treating an unknown account as practice is the
        mistake that costs money; the opposite costs a confirmation."""
        for unknown in (None, {}, {"available": False}):
            allowed, _ = autopilot.account_gate(unknown)

            assert allowed is False

    def test_the_server_name_is_never_used_to_decide(self):
        """"RoboForex-Pro" is a demo server and "…-Demo" is not a naming rule
        any broker is obliged to follow."""
        looks_like_a_demo = {
            "available": True,
            "is_real_money": True,
            "trade_mode": 2,
            "server": "SomeBroker-Demo",
        }

        allowed, _ = autopilot.account_gate(looks_like_a_demo)

        assert allowed is False, "the name was believed over the terminal"

    def test_the_real_money_switch_is_separate_from_the_others(self, monkeypatch):
        """Enabling execution, leaving dry-run, ignoring the edge gate and
        trading real money are four decisions. Collapsing any two means the
        person who makes the first makes the second without noticing."""
        from app.core.config import get_settings

        settings = get_settings()
        monkeypatch.setattr(settings, "enable_execution", True, raising=False)
        monkeypatch.setattr(settings, "execution_dry_run", False, raising=False)
        monkeypatch.setattr(settings, "trade_without_proven_edge", True, raising=False)

        allowed, _ = autopilot.account_gate(self.REAL)

        assert allowed is False, "three unrelated switches opened the fourth"

    def test_it_can_be_permitted_explicitly(self, monkeypatch):
        from app.core.config import get_settings

        monkeypatch.setattr(
            get_settings(), "allow_real_money_orders", True, raising=False
        )

        allowed, why = autopilot.account_gate(self.REAL)

        assert allowed is True
        assert "Every order sent is real" in why

    def test_it_is_off_by_default(self):
        from app.core.config import get_settings

        assert getattr(get_settings(), "allow_real_money_orders", False) is False


class TestThePendingClaimIsNotTreatedAsProven:
    """A claim clearing four of five is the most dangerous state in this
    registry: the numbers look convincing and the one missing requirement is
    the one that takes months. These tests keep the gate shut anyway."""

    def test_it_is_registered_but_not_proven(self):
        assert edge_registry.PENDING_FORWARD
        claim = edge_registry.PENDING_FORWARD[0]

        assert claim.verdict.proven is False
        assert claim not in edge_registry.PROVEN

    def test_it_fails_only_on_forward_evidence(self):
        """Stated as a test so that if it ever starts failing on something
        else, somebody has to look at why rather than assume it is the same
        gap."""
        failures = edge_registry.PENDING_FORWARD[0].verdict.failures

        assert len(failures) == 1
        assert "forward" in failures[0] or "held-out history" in failures[0]

    def test_the_gate_stays_shut(self):
        allowed, _ = edge_registry.live_trading_allowed()

        assert allowed is False

    def test_a_measured_z_must_say_how_it_was_measured(self):
        """An unexplained significance figure is exactly what this registry
        exists to stop being believed."""
        from datetime import date

        with pytest.raises(ValueError):
            edge_registry.Evidence(
                trials=100,
                hit_rate=0.55,
                control_hit_rate=0.50,
                expectancy_r=0.05,
                control_expectancy_r=0.0,
                comparisons=1,
                cost_r=0.001,
                registered_on=date(2026, 1, 1),
                data_ends=date(2026, 6, 1),
                measured_z=9.9,
            )

    def test_the_measured_figure_is_used_over_the_derived_one(self):
        """Deriving z from hit rates assumes a difference of proportions on
        independent trials. This claim was a paired mean-R test clustered by
        instant - a different statistic on a different unit, and the derivation
        gave 1.30 where the measurement gave 3.69."""
        evidence = edge_registry.PENDING_FORWARD[0].evidence

        assert evidence.z_score == 3.69
        assert evidence.measured_z_method
        assert "clustered" in evidence.as_dict()["z_method"]
