"""The six probes behind the real-money verdict, none of which were covered.

`test_real_money.py` tests the verdict arithmetic - how findings combine into
READY, MECHANICALLY_READY or NOT_READY. It does not touch the six functions
that produce those findings, which is where the module actually reads the
running system, and where a wrong answer is a wrong answer about whether to
connect somebody's money.

Two failure shapes get most of the attention here, because both have already
happened in this project:

**Unknown must not read as zero.** A terminal that stopped publishing has
positions nobody can see, and a probe that reports "no naked stops" because
it could not read any positions is worse than one that raises.

**A defect and an absent edge are different failures.** `blocks_connection`
is what keeps "no strategy has been shown to work" from being reported as
"something is broken", and every probe below is asserted on which of the two
it claims to be.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from app.models.journal import JournalEntry
from app.ops import real_money
from app.ops.real_money import PROVEN_PAIRS, PROVEN_T, Verdict

NOW = datetime(2026, 9, 9, 12, 0, tzinfo=UTC)


class FakeState:
    def __init__(self, *, usable: bool = True, age_seconds: float | None = 1.0):
        self.usable = usable
        self.age_seconds = age_seconds


class FakeBridge:
    """Stands in for one terminal's bridge directory."""

    def __init__(
        self,
        *,
        available: bool = True,
        usable: bool = True,
        age_seconds: float | None = 1.0,
        positions: list[dict] | None = None,
        raises: Exception | None = None,
    ):
        self._available = available
        self._state = FakeState(usable=usable, age_seconds=age_seconds)
        self._positions = positions or []
        self._raises = raises

    def state(self):
        if self._raises:
            raise self._raises
        return self._state

    def account(self):
        return {"available": self._available}

    def positions(self):
        if self._raises:
            raise self._raises
        return {"positions": self._positions}


@pytest.fixture()
def terminals(monkeypatch):
    """Install a fleet of fake bridges, keyed the way `bridge_dirs` keys them."""
    import app.providers.metatrader as mt

    fleet: dict[str, FakeBridge] = {}

    def install(**bridges: FakeBridge):
        fleet.clear()
        fleet.update(bridges)
        monkeypatch.setattr(mt, "bridge_dirs", lambda: {k: k for k in fleet})
        monkeypatch.setattr(mt, "MetaTraderBridge", lambda directory: fleet[directory])

    install()
    return install


def journal(session, *, strategy, arm, symbol, opened, r, timeframe="H1"):
    row = JournalEntry(
        symbol=symbol,
        decision="long",
        opened_at=opened,
        arm=arm,
        timeframe=timeframe,
        strategy=strategy,
        r_multiple=r,
        before={},
        during={},
    )
    session.add(row)
    session.flush()
    return row


def pairs(session, *, strategy, n, rule_r, control_r, symbol="EURUSD"):
    """`n` resolved rule/control pairs on one strategy, one per bar."""
    for i in range(n):
        at = NOW - timedelta(hours=i + 1)
        journal(session, strategy=strategy, arm="rule", symbol=symbol, opened=at, r=rule_r)
        journal(
            session, strategy=strategy, arm="control", symbol=symbol, opened=at, r=control_r
        )


class TestTerminalsAlive:
    def test_no_terminal_holding_an_account_is_a_defect(self, terminals):
        terminals()

        finding = real_money._terminals_alive()

        assert finding.passed is False
        assert finding.blocks_connection is True

    def test_it_says_there_is_nothing_to_trade_with(self, terminals):
        terminals()

        assert "nothing to trade with" in real_money._terminals_alive().detail

    def test_a_publishing_terminal_passes(self, terminals):
        terminals(**{"term-a": FakeBridge()})

        assert real_money._terminals_alive().passed is True

    def test_it_counts_the_accounts_it_found(self, terminals):
        terminals(**{"term-a": FakeBridge(), "term-b": FakeBridge()})

        assert "2 account(s)" in real_money._terminals_alive().detail

    def test_a_bridge_with_no_account_is_not_counted(self, terminals):
        terminals(
            **{"term-a": FakeBridge(), "term-b": FakeBridge(available=False)}
        )

        assert "1 account(s)" in real_money._terminals_alive().detail

    def test_a_fleet_of_accountless_bridges_fails(self, terminals):
        terminals(**{"term-a": FakeBridge(available=False)})

        assert real_money._terminals_alive().passed is False

    def test_an_unusable_state_is_not_asked_for_an_account(self, terminals):
        # `account()` is only called when the state is usable, so an unusable
        # bridge contributes nothing rather than a stale reading.
        terminals(**{"term-a": FakeBridge(usable=False)})

        assert real_money._terminals_alive().passed is False

    def test_a_stale_terminal_fails(self, terminals):
        terminals(**{"term-a": FakeBridge(age_seconds=121)})

        assert real_money._terminals_alive().passed is False

    def test_a_stale_terminal_is_named(self, terminals):
        terminals(
            **{"term-a": FakeBridge(), "term-b": FakeBridge(age_seconds=600)}
        )

        assert "term-b" in real_money._terminals_alive().detail

    def test_staleness_says_unknown_rather_than_zero(self, terminals):
        terminals(**{"term-a": FakeBridge(age_seconds=600)})

        detail = real_money._terminals_alive().detail
        assert "unknown rather than zero" in detail

    def test_exactly_at_the_threshold_is_still_alive(self, terminals):
        terminals(**{"term-a": FakeBridge(age_seconds=120)})

        assert real_money._terminals_alive().passed is True

    def test_an_unknown_age_is_not_treated_as_stale(self, terminals):
        terminals(**{"term-a": FakeBridge(age_seconds=None)})

        assert real_money._terminals_alive().passed is True

    def test_an_unreadable_bridge_is_a_defect_not_a_crash(self, terminals):
        terminals(**{"term-a": FakeBridge(raises=OSError("no such directory"))})

        finding = real_money._terminals_alive()

        assert finding.passed is False
        assert "could not be read" in finding.detail

    def test_an_unreadable_bridge_blocks_the_connection(self, terminals):
        terminals(**{"term-a": FakeBridge(raises=OSError("gone"))})

        assert real_money._terminals_alive().blocks_connection is True


class TestStopsReachTheBroker:
    def test_no_positions_passes(self, terminals):
        terminals(**{"term-a": FakeBridge(positions=[])})

        assert real_money._stops_reach_the_broker().passed is True

    def test_a_position_with_a_stop_passes(self, terminals):
        terminals(
            **{"term-a": FakeBridge(positions=[{"symbol": "EURUSD", "stop": 1.05}])}
        )

        assert real_money._stops_reach_the_broker().passed is True

    def test_it_counts_the_positions_it_checked(self, terminals):
        terminals(
            **{
                "term-a": FakeBridge(
                    positions=[
                        {"symbol": "EURUSD", "stop": 1.05},
                        {"symbol": "XAUUSD", "stop": 2400.0},
                    ]
                )
            }
        )

        assert "2 open position(s)" in real_money._stops_reach_the_broker().detail

    def test_a_position_with_no_stop_fails(self, terminals):
        terminals(
            **{"term-a": FakeBridge(positions=[{"symbol": "EURUSD", "stop": None}])}
        )

        assert real_money._stops_reach_the_broker().passed is False

    def test_a_zero_stop_is_no_stop(self, terminals):
        terminals(
            **{"term-a": FakeBridge(positions=[{"symbol": "EURUSD", "stop": 0}])}
        )

        assert real_money._stops_reach_the_broker().passed is False

    def test_a_missing_stop_key_is_no_stop(self, terminals):
        terminals(**{"term-a": FakeBridge(positions=[{"symbol": "EURUSD"}])})

        assert real_money._stops_reach_the_broker().passed is False

    def test_an_empty_string_stop_is_no_stop(self, terminals):
        terminals(
            **{"term-a": FakeBridge(positions=[{"symbol": "EURUSD", "stop": ""}])}
        )

        assert real_money._stops_reach_the_broker().passed is False

    def test_the_naked_position_is_named_with_its_terminal(self, terminals):
        terminals(
            **{"term-b": FakeBridge(positions=[{"symbol": "XAUUSD", "stop": 0}])}
        )

        assert "term-b:XAUUSD" in real_money._stops_reach_the_broker().detail

    def test_it_calls_the_risk_unbounded(self, terminals):
        terminals(
            **{"term-a": FakeBridge(positions=[{"symbol": "EURUSD", "stop": 0}])}
        )

        assert "unbounded risk" in real_money._stops_reach_the_broker().detail

    def test_a_naked_stop_blocks_the_connection(self, terminals):
        terminals(
            **{"term-a": FakeBridge(positions=[{"symbol": "EURUSD", "stop": 0}])}
        )

        assert real_money._stops_reach_the_broker().blocks_connection is True

    def test_one_naked_position_condemns_a_healthy_fleet(self, terminals):
        terminals(
            **{
                "term-a": FakeBridge(positions=[{"symbol": "EURUSD", "stop": 1.05}]),
                "term-b": FakeBridge(positions=[{"symbol": "XAUUSD", "stop": 0}]),
            }
        )

        assert real_money._stops_reach_the_broker().passed is False

    def test_unreadable_positions_fail_rather_than_report_none(self, terminals):
        # The failure this guards: a bridge that cannot be read has unknown
        # positions, and reporting "no naked stops" would be a pass earned by
        # not looking.
        terminals(**{"term-a": FakeBridge(raises=OSError("gone"))})

        finding = real_money._stops_reach_the_broker()

        assert finding.passed is False
        assert "could not be read" in finding.detail

    def test_an_empty_fleet_has_nothing_unbounded(self, terminals):
        terminals()

        assert real_money._stops_reach_the_broker().passed is True


class TestSizingCrossCheck:
    def test_the_cross_check_is_present_today(self):
        assert real_money._sizing_cross_check().passed is True

    def test_it_is_a_defect_when_absent(self, monkeypatch):
        import inspect

        monkeypatch.setattr(inspect, "getsource", lambda module: "def size(): pass")

        finding = real_money._sizing_cross_check()

        assert finding.passed is False
        assert finding.blocks_connection is True

    def test_the_absent_message_names_the_defect_that_happened(self, monkeypatch):
        import inspect

        monkeypatch.setattr(inspect, "getsource", lambda module: "")

        assert "five times its intended size" in real_money._sizing_cross_check().detail

    def test_contract_size_alone_satisfies_it(self, monkeypatch):
        import inspect

        monkeypatch.setattr(inspect, "getsource", lambda module: "contract_size = 100")

        assert real_money._sizing_cross_check().passed is True

    def test_spec_disagreement_alone_satisfies_it(self, monkeypatch):
        import inspect

        monkeypatch.setattr(inspect, "getsource", lambda module: "spec_disagreement()")

        assert real_money._sizing_cross_check().passed is True

    def test_the_present_message_describes_the_check(self):
        assert "tick value is checked against its contract size" in (
            real_money._sizing_cross_check().detail
        )


class TestGuardsArmed:
    def test_both_guards_are_armed_today(self):
        assert real_money._guards_armed().passed is True

    def test_a_missing_audit_is_reported_by_name(self, monkeypatch):
        import inspect

        monkeypatch.setattr(inspect, "getsource", lambda module: "")

        finding = real_money._guards_armed()

        assert finding.passed is False
        assert "specification audit" in finding.detail

    def test_a_missing_concentration_cap_is_reported_by_name(self, monkeypatch):
        from app.brain import portfolio

        monkeypatch.delattr(portfolio, "MAX_SAME_CURRENCY_POSITIONS", raising=False)

        finding = real_money._guards_armed()

        assert finding.passed is False
        assert "concentration cap" in finding.detail

    def test_a_missing_guard_blocks_the_connection(self, monkeypatch):
        from app.brain import portfolio

        monkeypatch.delattr(portfolio, "MAX_SAME_CURRENCY_POSITIONS", raising=False)

        assert real_money._guards_armed().blocks_connection is True

    def test_both_missing_are_reported_together(self, monkeypatch):
        import inspect

        from app.brain import portfolio

        monkeypatch.setattr(inspect, "getsource", lambda module: "")
        monkeypatch.delattr(portfolio, "MAX_SAME_CURRENCY_POSITIONS", raising=False)

        detail = real_money._guards_armed().detail
        assert "specification audit" in detail
        assert "concentration cap" in detail

    def test_the_cap_counts_positions_not_r(self):
        # Why the cap is stated the way it is: an R-denominated cap stops
        # binding the moment the system sizes down, which is exactly when
        # concentration matters most.
        assert "counts positions rather than R" in real_money._guards_armed().detail


class TestSomebodyIsTold:
    def test_a_configured_channel_passes(self, session, monkeypatch):
        from app.integrations import telegram

        monkeypatch.setattr(telegram, "configured", lambda s: (True, "env"))

        assert real_money._someone_is_told(session).passed is True

    def test_an_unconfigured_channel_fails(self, session, monkeypatch):
        from app.integrations import telegram

        monkeypatch.setattr(telegram, "configured", lambda s: (False, "nothing set"))

        assert real_money._someone_is_told(session).passed is False

    def test_it_never_blocks_the_connection(self, session, monkeypatch):
        from app.integrations import telegram

        monkeypatch.setattr(telegram, "configured", lambda s: (False, "no"))

        # It costs discovery time, not money in the trading path.
        assert real_money._someone_is_told(session).blocks_connection is False

    def test_it_stays_non_blocking_when_configured(self, session, monkeypatch):
        from app.integrations import telegram

        monkeypatch.setattr(telegram, "configured", lambda s: (True, "env"))

        assert real_money._someone_is_told(session).blocks_connection is False

    def test_a_raising_integration_reads_as_unconfigured(self, session, monkeypatch):
        from app.integrations import telegram

        def explode(s):
            raise RuntimeError("no table")

        monkeypatch.setattr(telegram, "configured", explode)

        assert real_money._someone_is_told(session).passed is False

    def test_the_unconfigured_message_names_the_cost(self, session, monkeypatch):
        from app.integrations import telegram

        monkeypatch.setattr(telegram, "configured", lambda s: (False, "no"))

        assert "twenty minutes of downtime" in (
            real_money._someone_is_told(session).detail
        )


class TestABrainBeatsItsControl:
    def test_an_empty_journal_has_measured_nothing(self, session):
        finding = real_money._a_brain_beats_its_control(session, NOW)

        assert finding.passed is False
        assert "no brain has resolved a paired trade" in finding.detail

    def test_an_empty_journal_is_not_a_defect(self, session):
        # Nothing is broken. There is simply no evidence yet, and the two
        # must not be reported as the same thing.
        assert (
            real_money._a_brain_beats_its_control(session, NOW).blocks_connection
            is False
        )

    def test_a_rule_arm_with_no_control_is_not_a_pair(self, session):
        for i in range(10):
            journal(
                session,
                strategy="trend",
                arm="rule",
                symbol="EURUSD",
                opened=NOW - timedelta(hours=i + 1),
                r=1.0,
            )

        assert "no brain has resolved a paired trade" in (
            real_money._a_brain_beats_its_control(session, NOW).detail
        )

    def test_a_single_pair_is_not_enough_to_compute_a_t(self, session):
        # One difference has no standard deviation; the probe requires two.
        pairs(session, strategy="trend", n=1, rule_r=1.0, control_r=0.0)

        assert "no brain has resolved a paired trade" in (
            real_money._a_brain_beats_its_control(session, NOW).detail
        )

    def test_too_few_pairs_does_not_pass(self, session):
        pairs(session, strategy="trend", n=10, rule_r=1.0, control_r=0.0)

        assert real_money._a_brain_beats_its_control(session, NOW).passed is False

    def test_too_few_pairs_is_not_a_defect(self, session):
        pairs(session, strategy="trend", n=10, rule_r=1.0, control_r=0.0)

        assert (
            real_money._a_brain_beats_its_control(session, NOW).blocks_connection
            is False
        )

    def test_it_names_the_best_brain_it_found(self, session):
        pairs(session, strategy="trend", n=10, rule_r=1.0, control_r=0.0)

        assert "trend" in real_money._a_brain_beats_its_control(session, NOW).detail

    def test_it_reports_how_many_pairs_the_best_had(self, session):
        pairs(session, strategy="trend", n=10, rule_r=1.0, control_r=0.0)

        assert "10 paired trades" in (
            real_money._a_brain_beats_its_control(session, NOW).detail
        )

    def test_an_identical_arm_scores_zero_not_infinity(self, session):
        # Zero variance and zero mean. A t of 0/0 must not become a pass.
        pairs(session, strategy="flat", n=10, rule_r=0.5, control_r=0.5)

        finding = real_money._a_brain_beats_its_control(session, NOW)

        assert finding.passed is False
        assert "t = 0.00" in finding.detail

    def test_a_constant_positive_edge_still_needs_the_pair_count(self, session):
        # Zero standard deviation is forced to t = 0 rather than infinity, so
        # a suspiciously perfect record cannot buy a pass.
        pairs(session, strategy="perfect", n=PROVEN_PAIRS + 10, rule_r=2.0, control_r=0.0)

        assert real_money._a_brain_beats_its_control(session, NOW).passed is False

    def test_enough_pairs_and_enough_t_passes(self, session):
        # Alternating differences of 1.0 and 1.2: a real mean, a small spread,
        # and enough of them to clear both bars.
        for i in range(PROVEN_PAIRS + 20):
            at = NOW - timedelta(hours=i + 1)
            journal(session, strategy="trend", arm="rule", symbol="EURUSD", opened=at,
                    r=1.0 if i % 2 else 1.2)
            journal(session, strategy="trend", arm="control", symbol="EURUSD", opened=at,
                    r=0.0)

        finding = real_money._a_brain_beats_its_control(session, NOW)

        assert finding.passed is True
        # `blocks_connection` is left at its default on the passing branch and
        # deliberately not asserted: a finding that passed is in neither
        # `defects` nor `unproven`, so the flag decides nothing here.

    def test_a_pass_reports_the_threshold_it_cleared(self, session):
        for i in range(PROVEN_PAIRS + 20):
            at = NOW - timedelta(hours=i + 1)
            journal(session, strategy="trend", arm="rule", symbol="EURUSD", opened=at,
                    r=1.0 if i % 2 else 1.2)
            journal(session, strategy="trend", arm="control", symbol="EURUSD", opened=at,
                    r=0.0)

        assert str(PROVEN_T) in real_money._a_brain_beats_its_control(session, NOW).detail

    def test_pairs_are_matched_on_the_same_bar(self, session):
        # A rule arm on one bar and a control arm on another are two
        # unmatched rows, not a pair.
        journal(session, strategy="trend", arm="rule", symbol="EURUSD",
                opened=NOW - timedelta(hours=1), r=1.0)
        journal(session, strategy="trend", arm="control", symbol="EURUSD",
                opened=NOW - timedelta(hours=2), r=0.0)

        assert "no brain has resolved a paired trade" in (
            real_money._a_brain_beats_its_control(session, NOW).detail
        )

    def test_pairs_are_matched_on_the_same_symbol(self, session):
        journal(session, strategy="trend", arm="rule", symbol="EURUSD",
                opened=NOW - timedelta(hours=1), r=1.0)
        journal(session, strategy="trend", arm="control", symbol="GBPUSD",
                opened=NOW - timedelta(hours=1), r=0.0)

        assert "no brain has resolved a paired trade" in (
            real_money._a_brain_beats_its_control(session, NOW).detail
        )

    def test_pairs_are_matched_on_the_same_timeframe(self, session):
        journal(session, strategy="trend", arm="rule", symbol="EURUSD",
                opened=NOW - timedelta(hours=1), r=1.0, timeframe="H1")
        journal(session, strategy="trend", arm="control", symbol="EURUSD",
                opened=NOW - timedelta(hours=1), r=0.0, timeframe="M15")

        assert "no brain has resolved a paired trade" in (
            real_money._a_brain_beats_its_control(session, NOW).detail
        )

    def test_brains_are_scored_separately(self, session):
        pairs(session, strategy="weak", n=5, rule_r=0.1, control_r=0.0)
        pairs(session, strategy="strong", n=5, rule_r=1.0, control_r=0.0,
              symbol="GBPUSD")

        # Both have zero spread and therefore t = 0, so the tie is resolved by
        # whichever came first - what matters is that one name is reported and
        # the two were not pooled into a single brain.
        detail = real_money._a_brain_beats_its_control(session, NOW).detail
        assert ("weak" in detail) != ("strong" in detail)

    def test_the_better_t_is_the_one_reported(self, session):
        for i in range(6):
            at = NOW - timedelta(hours=i + 1)
            journal(session, strategy="noisy", arm="rule", symbol="EURUSD",
                    opened=at, r=3.0 if i % 2 else -3.0)
            journal(session, strategy="noisy", arm="control", symbol="EURUSD",
                    opened=at, r=0.0)
            journal(session, strategy="steady", arm="rule", symbol="GBPUSD",
                    opened=at, r=1.0 if i % 2 else 1.1)
            journal(session, strategy="steady", arm="control", symbol="GBPUSD",
                    opened=at, r=0.0)

        assert "steady" in real_money._a_brain_beats_its_control(session, NOW).detail

    def test_an_unresolved_trade_is_not_counted(self, session):
        pairs(session, strategy="trend", n=5, rule_r=1.0, control_r=0.0)
        journal(session, strategy="trend", arm="rule", symbol="EURUSD",
                opened=NOW - timedelta(hours=99), r=None)

        assert "5 paired trades" in (
            real_money._a_brain_beats_its_control(session, NOW).detail
        )

    def test_an_unreadable_journal_is_not_a_defect(self, session, monkeypatch):
        def explode(*a, **k):
            raise RuntimeError("no such table")

        monkeypatch.setattr(session, "execute", explode)

        finding = real_money._a_brain_beats_its_control(session, NOW)

        assert finding.passed is False
        assert finding.blocks_connection is False
        assert "could not be read" in finding.detail

    def test_the_failure_message_explains_the_correction(self, session):
        pairs(session, strategy="trend", n=10, rule_r=1.0, control_r=0.0)

        assert "1.96 would find an edge in noise" in (
            real_money._a_brain_beats_its_control(session, NOW).detail
        )


class TestAssessPutsThemTogether:
    def test_it_runs_all_six_probes(self, session, terminals, monkeypatch):
        terminals(**{"term-a": FakeBridge()})
        from app.integrations import telegram

        monkeypatch.setattr(telegram, "configured", lambda s: (True, "env"))

        assert len(real_money.assess(session).findings) == 6

    def test_it_stamps_the_moment_it_was_asked(self, session, terminals, monkeypatch):
        terminals(**{"term-a": FakeBridge()})
        from app.integrations import telegram

        monkeypatch.setattr(telegram, "configured", lambda s: (True, "env"))

        assert real_money.assess(session, now=NOW).at == NOW

    def test_a_healthy_fleet_with_no_edge_is_mechanically_ready(
        self, session, terminals, monkeypatch
    ):
        terminals(**{"term-a": FakeBridge()})
        from app.integrations import telegram

        monkeypatch.setattr(telegram, "configured", lambda s: (True, "env"))

        assert real_money.assess(session, now=NOW).verdict is Verdict.MECHANICALLY_READY

    def test_a_silent_terminal_makes_it_not_ready(
        self, session, terminals, monkeypatch
    ):
        terminals(**{"term-a": FakeBridge(age_seconds=600)})
        from app.integrations import telegram

        monkeypatch.setattr(telegram, "configured", lambda s: (True, "env"))

        assert real_money.assess(session, now=NOW).verdict is Verdict.NOT_READY

    def test_a_naked_stop_makes_it_not_ready(self, session, terminals, monkeypatch):
        terminals(
            **{"term-a": FakeBridge(positions=[{"symbol": "XAUUSD", "stop": 0}])}
        )
        from app.integrations import telegram

        monkeypatch.setattr(telegram, "configured", lambda s: (True, "env"))

        assert real_money.assess(session, now=NOW).verdict is Verdict.NOT_READY

    def test_an_unconfigured_channel_alone_does_not_block(
        self, session, terminals, monkeypatch
    ):
        terminals(**{"term-a": FakeBridge()})
        from app.integrations import telegram

        monkeypatch.setattr(telegram, "configured", lambda s: (False, "no"))

        report = real_money.assess(session, now=NOW)

        assert report.verdict is Verdict.MECHANICALLY_READY
        assert report.defects == []

    def test_the_report_serialises(self, session, terminals, monkeypatch):
        terminals(**{"term-a": FakeBridge()})
        from app.integrations import telegram

        monkeypatch.setattr(telegram, "configured", lambda s: (True, "env"))

        body = real_money.assess(session, now=NOW).as_dict()

        assert body["verdict"] == Verdict.MECHANICALLY_READY.value
        assert len(body["findings"]) == 6

    def test_the_headline_refuses_to_read_as_a_yes(
        self, session, terminals, monkeypatch
    ):
        terminals(**{"term-a": FakeBridge()})
        from app.integrations import telegram

        monkeypatch.setattr(telegram, "configured", lambda s: (True, "env"))

        assert "the strategy is not" in real_money.assess(session, now=NOW).headline
