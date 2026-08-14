"""Assembling what a decision needs, and refusing to invent what is missing.

The first version of `peak_equity` queried the wrong column with the wrong
type: it compared a UUID primary key against the string "metatrader", which
Postgres refused, and had the types matched it would have returned the starting
balance as though it were the peak. The endpoint 500'd, which is how it was
found - and the quieter failure would have been worse, because a trailing
drawdown floor placed from a starting balance is a floor in the wrong place and
nothing about it looks wrong.

So these tests are mostly about the difference between "we measured this" and
"nobody measured this", and about that difference surviving.
"""

from __future__ import annotations

from datetime import UTC, datetime

from app.execution import context

NOW = datetime(2026, 8, 14, 12, 0, tzinfo=UTC)


class FakeBridge:
    """Publishes what a connected terminal publishes, and nothing more."""

    def __init__(self, available=True, equity=10000.0, balance=10000.0, positions=True):
        self._available = available
        self._equity = equity
        self._balance = balance
        self._positions = positions

    def account(self, **kwargs):
        if not self._available:
            return {"available": False, "reason": "no account is logged in"}
        return {
            "available": True,
            "equity": self._equity,
            "balance": self._balance,
            "margin": 0.0,
            "free_margin": self._balance,
        }

    def positions(self, **kwargs):
        if not self._positions:
            return {"available": False, "reason": "unreadable"}
        return {"available": True, "positions": []}


class TestNoAccountMeansNoContext:
    def test_a_disconnected_bridge_returns_none(self, session):
        """None rather than a Context full of zeros. Zeros would flow into a
        drawdown check and produce a confident verdict about an account nobody
        is connected to."""
        built = context.build(session, bridge=FakeBridge(available=False), now=NOW)

        assert built is None


class TestWhatCannotBeMeasuredIsSaidSoNotGuessed:
    def test_peak_equity_is_unmeasured_because_nothing_records_it(self, session):
        """Nothing in this system stores an equity series - the bridge publishes
        a snapshot and nothing keeps it. Reporting today's equity as the peak
        would put a trailing floor at today's level and report rope the account
        does not have."""
        built = context.build(session, bridge=FakeBridge(), now=NOW)

        assert built is not None
        assert built.complete is False
        assert any("peak equity" in gap for gap in built.unmeasured)

    def test_peak_equity_returns_none_rather_than_a_wrong_number(self, session):
        """It used to query max(starting_balance), which is not the peak and
        would have been quietly believed."""
        assert context.peak_equity(session, "metatrader") is None

    def test_the_daily_pnl_gap_is_stated(self, session):
        """"No loss today" and "nobody measured today" are opposite inputs to a
        daily-loss check."""
        built = context.build(session, bridge=FakeBridge(), now=NOW)

        assert any("realised P&L" in gap for gap in built.unmeasured)

    def test_unreadable_positions_are_flagged(self, session):
        built = context.build(session, bridge=FakeBridge(positions=False), now=NOW)

        assert any("open positions" in gap for gap in built.unmeasured)

    def test_calibration_is_reported_as_unscored(self, session):
        """A confidence never scored against outcomes is not a confidence."""
        built = context.build(session, bridge=FakeBridge(), now=NOW)

        assert built.calibration.calibrated is False
        assert built.calibration.reason


class TestWhatCanBeMeasuredIsCarriedThrough:
    def test_equity_and_balance_come_from_the_terminal(self, session):
        built = context.build(
            session, bridge=FakeBridge(equity=9800.0, balance=10000.0), now=NOW
        )

        assert built.account.equity == 9800.0
        assert built.account.balance == 10000.0

    def test_the_payload_names_every_gap(self, session):
        """A caller may proceed without one, but it has to decide - which is
        the difference between a known gap and an invisible one."""
        built = context.build(session, bridge=FakeBridge(), now=NOW)
        payload = built.as_dict()

        assert payload["complete"] is False
        assert len(payload["unmeasured"]) >= 2
