"""The daily brain proposal: qualifies after cost and over its control, moves only losers."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from app.learning import brain_selection as bs
from app.models.journal import ARM_CONTROL, ARM_RULE, JournalEntry

START = datetime(2026, 9, 1, tzinfo=UTC)


def _rows(session, strategy, rs, *, arm=ARM_RULE, source="metatrader"):
    for i, r in enumerate(rs):
        session.add(
            JournalEntry(
                symbol=f"S{i}",
                decision="long",
                opened_at=START + timedelta(hours=i),
                closed_at=START + timedelta(hours=i, minutes=30),
                arm=arm,
                strategy=strategy,
                r_multiple=r,
                price_source=source,
                during={},
            )
        )
    session.flush()


def _standing(name, positions, mean, control):
    return bs.Standing(strategy=name, positions=positions, mean_r=mean, control_mean_r=control)


def test_standings_charge_cost_and_compare_to_the_control(session):
    _rows(session, "good", [1.5] * 80 + [-1.0] * 40)
    _rows(session, "good", [0.0] * 120, arm=ARM_CONTROL)
    _rows(session, "thin", [1.5] * 10)
    _rows(session, "public-only", [1.5] * 80, source="yfinance")

    ranked = {s.strategy: s for s in bs.standings(session)}

    assert "public-only" not in ranked
    good = ranked["good"]
    assert good.positions == 120
    assert good.net_r == good.mean_r - bs.COST_R
    assert good.qualifies
    assert not ranked["thin"].qualifies


def test_a_brain_needs_a_hundred_positions():
    assert not _standing("x", 99, 0.9, 0.0).qualifies
    assert _standing("x", 100, 0.9, 0.0).qualifies


def test_a_brain_under_its_cost_does_not_qualify():
    assert not _standing("x", 100, bs.COST_R - 0.01, -0.5).qualifies


def test_a_brain_under_its_control_does_not_qualify():
    assert not _standing("x", 100, 0.5, 0.6).qualifies


def test_only_accounts_without_a_qualifying_brain_move_and_moves_spread():
    ranked = [
        _standing("a", 100, 0.9, 0.0),
        _standing("b", 100, 0.6, 0.0),
        _standing("loser", 100, -0.4, 0.0),
    ]
    accounts = {
        "1": frozenset({"loser"}),
        "2": frozenset({"a"}),
        "3": frozenset({"loser"}),
        "4": None,
        "5": frozenset({"loser"}),
    }

    changes = bs.propose(ranked, accounts, keep=frozenset({"5"}))

    assert [(c["account"], c["to"]) for c in changes] == [("1", "a"), ("3", "b"), ("4", "a")]


def test_apply_moves_one_account_keeps_its_risk_and_waits_a_week(session):
    from app.models.account_policy import AccountPolicy

    session.add(
        AccountPolicy(login="1", strategies=["loser"], risk_percent=2.0, changed_by="owner")
    )
    session.flush()
    changes = [
        {"account": "1", "from": ["loser"], "to": "a", "why": ""},
        {"account": "3", "from": ["loser"], "to": "b", "why": ""},
    ]

    applied = bs.apply(session, changes, now=START)

    assert applied is not None and applied["account"] == "1"
    assert applied["before"]["strategies"] == ["loser"]
    row = session.query(AccountPolicy).filter_by(login="1").one()
    assert row.strategies == ["a"] and row.risk_percent == 2.0 and row.changed_by == bs.APPLIER
    assert session.query(AccountPolicy).filter_by(login="3").first() is None

    assert bs.apply(session, changes[1:], now=START + timedelta(days=6)) is None
    assert bs.apply(session, changes[1:], now=START + timedelta(days=7)) is not None


def test_apply_writes_nothing_without_a_proposal(session):
    assert bs.apply(session, [], now=START) is None


def test_nothing_is_proposed_when_no_brain_qualifies():
    ranked = [_standing("loser", 100, -0.4, 0.0)]
    assert bs.propose(ranked, {"1": frozenset({"loser"})}) == []
