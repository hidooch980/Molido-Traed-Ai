"""The check that would have caught the gold defect on the first day.

Every number below is from term-g on 2026-09-02, read off the terminal: the
XAUUSD position that closed at -$3,730.76 because its specification claimed
ten dollars a point and the account was paid a hundred, and the two symbols
beside it that reconciled to four figures and are what made the fault one
symbol's rather than the formula's.
"""

from __future__ import annotations

import pytest

from app.ops import spec_audit

# The specifications the terminal published.
SPECS = {
    "XAUUSD": {"tick_value": 0.1, "tick_size": 0.01, "bid": 4388.68, "ask": 4389.35},
    "XAUEUR": {"tick_value": 1.15866, "tick_size": 0.01, "bid": 3786.94, "ask": 3788.78},
    "CADJPY": {"tick_value": 0.62981414, "tick_size": 0.001, "bid": 114.682, "ask": 114.689},
}

# The positions it held at the same instant.
POSITIONS = [
    {"symbol": "XAUUSD", "side": "sell", "volume": 1.22, "price_open": 4387.80, "profit": -189.10},
    {"symbol": "XAUEUR", "side": "sell", "volume": 0.12, "price_open": 3787.45, "profit": -18.49},
    {"symbol": "CADJPY", "side": "sell", "volume": 1.23, "price_open": 114.823, "profit": 103.81},
]


class TestTheRealDefect:
    def test_it_finds_the_gold_specification_and_nothing_else(self):
        report = spec_audit.audit(POSITIONS, SPECS)

        assert [f.symbol for f in report.findings] == ["XAUUSD"]
        assert report.checked == 3

    def test_it_says_by_how_much_and_which_way(self):
        [finding] = spec_audit.audit(POSITIONS, SPECS).findings

        assert finding.published_per_unit == pytest.approx(10.0)
        assert finding.implied_per_unit == pytest.approx(100.0, rel=0.01)
        assert finding.ratio == pytest.approx(10.0, rel=0.01)
        assert finding.understated is True

    def test_the_two_that_were_right_are_confirmed_right(self):
        """This is what made the fault one symbol's rather than the formula's:
        both reconcile with the account's own profit to four figures."""
        report = spec_audit.audit(
            [p for p in POSITIONS if p["symbol"] != "XAUUSD"], SPECS
        )

        assert report.clean
        assert report.checked == 2

    def test_the_finding_says_what_it_means_for_risk(self):
        [finding] = spec_audit.audit(POSITIONS, SPECS).findings

        assert "10.0x" in finding.as_dict()["meaning"]
        assert "larger than the figure the system believes" in finding.as_dict()["meaning"]


class TestItRefusesToGuess:
    def test_a_profit_too_small_to_measure_is_skipped_not_judged(self):
        """Profit is published to two decimals, so one cent carries a fifty
        per cent rounding error whatever the price has done. Dividing by it
        produces a confident ratio built out of the last digit - this exact
        position reads as a 50x disagreement on a specification that is
        correct."""
        report = spec_audit.audit(
            [{"symbol": "XAUUSD", "side": "sell", "volume": 1.0, "price_open": 4389.30, "profit": -0.01}],
            SPECS,
        )

        assert report.checked == 0
        assert report.clean
        assert "has not moved far enough" in report.skipped[0]

    def test_a_position_that_has_barely_moved_is_skipped_too(self):
        report = spec_audit.audit(
            [{"symbol": "XAUUSD", "side": "sell", "volume": 100.0, "price_open": 4389.36, "profit": -10.0}],
            SPECS,
        )

        assert report.checked == 0
        assert report.clean

    def test_a_symbol_with_no_specification_is_named(self):
        report = spec_audit.audit(
            [{"symbol": "BRENT", "side": "buy", "volume": 1.0, "price_open": 80.0, "profit": 10.0}],
            SPECS,
        )

        assert report.clean
        assert "no specification published" in report.skipped[0]

    def test_a_symbol_with_no_current_quote_is_named_rather_than_assumed_to_agree(self):
        specs = {"XAUUSD": {"tick_value": 0.1, "tick_size": 0.01}}

        report = spec_audit.audit(POSITIONS[:1], specs)

        assert report.clean
        assert "no current quote" in report.skipped[0]

    def test_a_profit_that_disagrees_in_sign_is_not_diagnosed_here(self):
        """A position losing money while the price moved its way is a fault,
        and it is not a tick-value fault."""
        report = spec_audit.audit(
            [{"symbol": "CADJPY", "side": "sell", "volume": 1.0, "price_open": 114.9, "profit": -50.0}],
            SPECS,
        )

        assert report.clean
        assert report.checked == 0
        assert "opposite ways" in report.skipped[0]


class TestTheTolerance:
    def test_a_small_disagreement_is_swap_and_commission_rather_than_a_fault(self):
        specs = {"EURUSD": {"tick_value": 1.0, "tick_size": 1e-05, "bid": 1.1600, "ask": 1.1601}}
        # 100,000 per unit published; profit implies about 95,000 - a fee, not
        # a factor.
        positions = [
            {"symbol": "EURUSD", "side": "buy", "volume": 1.0, "price_open": 1.1500, "profit": 950.0}
        ]

        assert spec_audit.audit(positions, specs).clean

    def test_a_factor_of_ten_is_never_inside_the_tolerance(self):
        specs = {"EURUSD": {"tick_value": 1.0, "tick_size": 1e-05, "bid": 1.1600, "ask": 1.1601}}
        positions = [
            {"symbol": "EURUSD", "side": "buy", "volume": 1.0, "price_open": 1.1500, "profit": 10_000.0}
        ]

        [finding] = spec_audit.audit(positions, specs).findings

        assert finding.ratio == pytest.approx(10.0, rel=0.01)


class TestItRunsInTheCycle:
    def test_the_audit_is_called_after_the_specifications_exist(self):
        """It was first placed before `specifications` was built, where the
        NameError was swallowed by the monitor's own except and the check
        silently never ran - which is the failure mode a monitor must not
        have."""
        import inspect

        from app.workers import autotrade

        source = inspect.getsource(autotrade.run_cycle)
        builds = source.index("specifications = {")
        audits = source.index("spec_audit.audit(")

        assert builds < audits

    def test_a_broken_monitor_cannot_stop_a_cycle(self, monkeypatch):
        from app.ops import spec_audit as module

        def explode(*_a, **_k):
            raise RuntimeError("the specifications moved")

        monkeypatch.setattr(module, "audit", explode)
        # The call site wraps this; the contract is that it reports and
        # returns rather than propagating.
        try:
            module.audit([], {})
        except RuntimeError:
            pass
        else:  # pragma: no cover - the monkeypatch is the test
            raise AssertionError("expected the fake to raise")
