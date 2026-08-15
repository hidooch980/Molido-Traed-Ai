"""The only rule in this project that has cleared a significance bar.

Measured over 601,300 bars, clustered by instant so overlapping trades are not
counted as independent evidence: +0.0212 R over a random control at t = 3.69,
+0.0112 R net of a round trip.

It is not a proven edge - both halves of that series were searched before it
was tested - and these tests are not about the result. They are about the three
details that carry it, because each one is the kind of thing a later refactor
removes without noticing.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from app.brain import crosssection as cs

NOW = datetime(2026, 8, 15, 12, 0, tzinfo=UTC)


def series(last: float, *, mean: float = 100.0, spread: float = 1.0, n: int = 60):
    """A history whose mean is `mean` and whose last close is `last`."""
    closes = [mean] * n + [last]
    bars = [(c + spread / 2, c - spread / 2, c) for c in closes]
    return {"closes": closes, "bars": bars}


def snapshot(values: dict[str, float], **kwargs):
    return {symbol: series(last, **kwargs) for symbol, last in values.items()}


class TestTheScaleIsShared:
    def test_stretch_is_measured_in_atrs_not_price(self):
        """Gold at 2,400 and EURUSD at 1.09 cannot be ranked on raw distance -
        that ranks price levels, not signals."""
        cheap = cs.stretch_of([1.0] * 51 + [1.1], atr=0.1)
        dear = cs.stretch_of([2400.0] * 51 + [2640.0], atr=240.0)

        assert cheap == pytest.approx(dear)

    def test_a_zero_volatility_instrument_is_refused(self):
        """It would divide into infinity and sit at the top of every ranking
        forever."""
        assert cs.stretch_of([100.0] * 60, atr=0.0) is None

    def test_too_little_history_returns_none_rather_than_a_guess(self):
        assert cs.stretch_of([100.0] * 10, atr=1.0) is None


class TestTheCrossSectionMustBeWideEnough:
    def test_a_thin_cross_section_proposes_nothing(self):
        """Eight instruments always have a most-extended member. Calling it a
        signal is calling the shape of a small sample a signal."""
        result = cs.rank(snapshot({f"S{i}": 100 + i for i in range(8)}), at=NOW)

        assert result.available is False
        assert "thin" in result.reason or "needs" in result.reason

    def test_a_wide_enough_one_proposes_both_tails(self):
        result = cs.rank(snapshot({f"S{i}": 100 + i for i in range(30)}), at=NOW)

        assert result.available is True
        assert result.longs
        assert result.shorts

    def test_the_minimum_is_the_tested_one(self):
        """Changing it makes this a different rule with no evidence behind
        it."""
        assert cs.MIN_CROSS_SECTION == 20
        assert cs.MEAN_WINDOW == 50
        assert cs.TAIL_FRACTION == 0.10


class TestBothLegsAlways:
    def test_the_most_extended_downward_are_longs(self):
        values = {f"S{i}": 100 - i for i in range(30)}
        result = cs.rank(snapshot(values), at=NOW)

        # S29 is furthest below its mean, so it is the strongest long.
        assert result.longs[0].symbol == "S29"

    def test_the_most_extended_upward_are_shorts(self):
        values = {f"S{i}": 100 + i for i in range(30)}
        result = cs.rank(snapshot(values), at=NOW)

        assert result.shorts[0].symbol == "S29"

    def test_the_two_legs_are_the_same_size(self):
        """The long and short legs are what make the rule market-neutral.
        Taking one turns it back into a directional bet on the market, which is
        exactly what it was built not to be."""
        result = cs.rank(snapshot({f"S{i}": 100 + i for i in range(37)}), at=NOW)

        assert len(result.longs) == len(result.shorts)

    def test_a_market_that_moved_together_still_produces_both_legs(self):
        """The case the rule exists for. Every instrument is far above its own
        mean - a time-series rule would call all thirty a short. The
        cross-section still finds who is extended *relative to peers*."""
        values = {f"S{i}": 200 + i for i in range(30)}
        result = cs.rank(snapshot(values), at=NOW)

        assert result.available is True
        assert result.longs and result.shorts
        # Everything is stretched upward, so every stretch is positive - and
        # the rule still goes long the least-stretched of them.
        assert all(r.stretch > 0 for r in result.longs)
        assert result.longs[0].stretch < result.shorts[0].stretch


class TestNothingDropsOutSilently:
    def test_a_skipped_instrument_is_named(self):
        """One that vanishes from every ranking looks exactly like one the rule
        simply never picks."""
        data = snapshot({f"S{i}": 100 + i for i in range(30)})
        data["BROKEN"] = {"closes": [1.0, 2.0], "bars": []}

        result = cs.rank(data, at=NOW)

        assert any("BROKEN" in note for note in result.skipped)

    def test_the_payload_carries_the_count_it_ranked(self):
        result = cs.rank(snapshot({f"S{i}": 100 + i for i in range(30)}), at=NOW)

        assert result.as_dict()["considered"] == 30


class TestTheRuleIsDeterministic:
    def test_the_same_snapshot_gives_the_same_answer(self):
        """A rule whose output depends on dictionary order would produce a
        different forward series on every restart, and the measurement would be
        of the restart schedule."""
        data = snapshot({f"S{i}": 100 + (i * 7 % 13) for i in range(30)})

        first = cs.rank(data, at=NOW)
        second = cs.rank(dict(reversed(list(data.items()))), at=NOW)

        assert [r.symbol for r in first.longs] == [r.symbol for r in second.longs]
        assert [r.symbol for r in first.shorts] == [r.symbol for r in second.shorts]
