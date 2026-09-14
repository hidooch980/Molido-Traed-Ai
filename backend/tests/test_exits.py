"""Trade management as a measurable walk: same rules as the live resolver."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.learning import exits
from app.workers.resolve import _outcome


def bars(*ranges):
    """(low, high[, close]) per bar."""
    out = []
    for r in ranges:
        low, high = r[0], r[1]
        close = r[2] if len(r) > 2 else (low + high) / 2
        out.append(SimpleNamespace(low=low, high=high, close=close))
    return out


LONG = dict(side=1, entry=100.0, stop=99.0, target=101.5)  # 1 R = 1.0, target 1.5 R


def test_the_fixed_policy_agrees_with_the_live_resolver():
    cases = [
        bars((99.5, 100.5), (100.2, 101.6)),
        bars((99.5, 100.5), (98.8, 99.9)),
        bars((98.5, 101.8)),
        bars((99.6, 100.4), (99.7, 100.3)),
    ]
    for case in cases:
        expected = _outcome(case, **LONG)
        got = exits.walk(case, **LONG)
        assert got == (None if expected is None else expected[1])


def test_the_trail_locks_profit_from_the_next_bar():
    # +1.2 R best, trail 0.6 behind -> stop at +0.6; next bar falls through it.
    path = bars((99.8, 101.2), (100.3, 100.9))
    result = exits.walk(path, **LONG, policy=exits.DEPLOYED)
    assert result == pytest.approx(0.6)


def test_the_bar_that_sets_the_best_cannot_fill_the_new_stop():
    # The first bar reaches +1.2 R and also dips to +0.1: the stop it moves (to
    # +0.6) is not in force inside that bar. The next bar stays above it and
    # reaches the target.
    path = bars((100.1, 101.2), (100.7, 101.6))
    assert exits.walk(path, **LONG, policy=exits.DEPLOYED) == pytest.approx(1.5)


def test_breakeven_turns_a_loser_into_a_scratch():
    path = bars((99.9, 100.6), (98.5, 99.9))
    assert exits.walk(path, **LONG) == -1.0
    assert exits.walk(path, **LONG, policy=exits.ExitPolicy(breakeven_at_r=0.5)) == 0.0


def test_a_short_is_managed_the_other_way():
    short = dict(side=-1, entry=100.0, stop=101.0, target=98.5)
    path = bars((98.8, 100.2), (99.1, 99.7))  # best +1.2 R, trail stop at 99.4
    assert exits.walk(path, **short, policy=exits.DEPLOYED) == pytest.approx(0.6)


def test_the_stop_never_moves_away_from_the_price():
    policy = exits.ExitPolicy(trail_start_r=0.1, trail_lag_r=5.0)  # trail would sit below the stop
    path = bars((99.5, 100.3), (98.9, 99.6))
    assert exits.walk(path, **LONG, policy=policy) == -1.0


def test_the_time_exit_closes_at_the_close():
    path = bars((99.7, 100.4, 100.2), (99.8, 100.5, 100.3))
    policy = exits.ExitPolicy(max_bars=2)
    assert exits.walk(path, **LONG, policy=policy) == pytest.approx(0.3)


def test_a_zero_risk_trade_is_no_evidence():
    assert exits.walk(bars((99, 101)), side=1, entry=100.0, stop=100.0, target=101.0) is None


def test_the_grid_carries_what_is_already_running():
    labels = {p.label for p in exits.POLICIES}
    assert exits.NONE.label in labels
    assert exits.DEPLOYED.label in labels
