"""Getting a green verdict out of this module should be hard.

Every test below builds a sample whose answer is known - an edge that lives
in one year, an edge that is one instrument, an edge smaller than its cost,
an edge that is pure noise - and checks that the module says so. The tests
that matter most are the ones where the headline number looks good.
"""

from __future__ import annotations

import random
from datetime import UTC, datetime, timedelta

import pytest

from app.learning import robustness as rb
from app.learning.measure import Measurement

START = datetime(2024, 1, 1, tzinfo=UTC)


def rows(edges, *, start=START, step=timedelta(hours=1)):
    """One row per edge value: (stamp, rule R, control R) with control at 0."""
    return [(start + step * i, float(e), 0.0) for i, e in enumerate(edges)]


def measurement(rs, **over):
    edge = sum(r - c for _a, r, c in rs) / len(rs) if rs else 0.0
    t, _ = rb._paired_t([r - c for _a, r, c in rs]) if rs else (0.0, 0.0)
    base = dict(
        instants=len(rs),
        trades=len(rs) * 4,
        rule_r=edge,
        control_r=0.0,
        spread_r=1.0,
        t_statistic=t,
        unclustered_t=t,
        dropped_undecided=0,
        window=(rs[0][0], rs[-1][0]) if rs else None,
        instant_rows=tuple(rs),
    )
    base.update(over)
    return Measurement(**base)


# ------------------------------------------------------------------ the maths
class TestThePairedArithmeticIsRecomputedNotInherited:
    def test_a_slice_scores_from_its_own_rows(self):
        sample = rows([1.0] * 50 + [-1.0] * 50)
        early, late = sample[:50], sample[50:]

        assert rb.paired(early)[0] == pytest.approx(1.0)
        assert rb.paired(late)[0] == pytest.approx(-1.0)
        assert rb.paired(sample)[0] == pytest.approx(0.0)

    def test_an_empty_slice_is_zero_rather_than_an_error(self):
        assert rb.paired([]) == (0.0, 0.0, 0)


class TestSegmentsCutOnTheDecisionInstant:
    def test_a_year_that_holds_the_whole_edge_is_visible_as_one(self):
        good = [(datetime(2023, 6, 1, tzinfo=UTC) + timedelta(hours=i), 0.5, 0.0) for i in range(200)]
        flat = [(datetime(2024, 6, 1, tzinfo=UTC) + timedelta(hours=i), 0.0, 0.0) for i in range(200)]

        found = {s.name: s for s in rb.by_year(good + flat)}

        assert found["year:2023"].edge_r == pytest.approx(0.5)
        assert found["year:2024"].edge_r == pytest.approx(0.0)

    def test_sessions_split_by_utc_hour(self):
        sample = [(START + timedelta(hours=i), 1.0, 0.0) for i in range(48)]

        names = {s.name for s in rb.by_session(sample)}

        assert names == {"session:tokyo", "session:london", "session:overlap", "session:new-york"}

    def test_a_thin_slice_is_marked_rather_than_dropped(self):
        sample = rows([1.0] * 10)

        [only] = rb.by_period(sample, parts=1) or [rb.Slice("x", 10, 1.0, 1.0)]

        assert rb.Slice(name="x", instants=10, edge_r=1.0, t=1.0).thin is True
        assert rb.Slice(name="x", instants=rb.MIN_SLICE, edge_r=1.0, t=1.0).thin is False
        assert only is not None

    def test_periods_are_equal_counts_not_equal_spans(self):
        dense = [(START + timedelta(minutes=i), 1.0, 0.0) for i in range(300)]
        sparse = [(START + timedelta(days=30 + i), 1.0, 0.0) for i in range(30)]

        parts = rb.by_period(dense + sparse)

        assert [p.instants for p in parts] == [110, 110, 110]


class TestRegimesAreTakenAsDataNotDerived:
    def test_instants_with_no_regime_are_counted_as_unknown(self):
        """Dropping them would let a label that only exists in calm periods
        make the whole sample look calm."""
        sample = rows([1.0] * 4)
        known = {sample[0][0]: "trending", sample[1][0]: "trending"}

        found = {s.name: s.instants for s in rb.regime_segments(sample, known)}

        assert found == {"regime:trending": 2, "regime:unknown": 2}


# ------------------------------------------------------------------- costs
class TestCostStress:
    def test_an_edge_below_the_extreme_cost_is_reported_as_not_surviving(self):
        levels = rb.cost_stress(0.02)

        assert [level.survives for level in levels] == [True, False, False]

    def test_a_large_edge_survives_all_three(self):
        assert all(level.survives for level in rb.cost_stress(0.5))

    def test_the_cost_is_charged_once_against_the_edge_over_the_control(self):
        [base, *_] = rb.cost_stress(0.10)

        assert base.net_r == pytest.approx(0.10 - rb.COST_R)


# ----------------------------------------------------------------- placebo
class TestThePermutationNull:
    def test_pure_noise_is_not_separated_from_its_placebo(self):
        rng = random.Random(7)
        noise = rows([rng.gauss(0, 1) for _ in range(400)])

        result = rb.permutation_test(noise, draws=1000)

        assert result.p_value > 0.05

    def test_a_real_edge_is_separated(self):
        rng = random.Random(7)
        real = rows([rng.gauss(0.4, 1) for _ in range(400)])

        result = rb.permutation_test(real, draws=1000)

        assert result.p_value < 0.01
        assert result.at_least_as_extreme < 10

    def test_the_p_value_can_never_be_zero(self):
        """Zero claims the observed value is impossible under the null, and a
        finite number of draws never supports that."""
        result = rb.permutation_test(rows([5.0] * 300), draws=200)

        assert result.p_value > 0
        assert result.p_value == pytest.approx(1 / 201)

    def test_it_reproduces_on_a_re_run(self):
        sample = rows([0.3, -0.1, 0.5, -0.2] * 60)

        first = rb.permutation_test(sample, draws=500)
        second = rb.permutation_test(sample, draws=500)

        assert first.p_value == second.p_value


# --------------------------------------------------------------- bootstrap
class TestTheBlockBootstrap:
    def test_a_clear_edge_gives_an_interval_above_zero(self):
        rng = random.Random(3)
        sample = rows([rng.gauss(0.5, 0.5) for _ in range(400)])

        result = rb.block_bootstrap(sample, block=20, draws=500)

        assert result.lower > 0 and result.excludes_zero

    def test_noise_gives_an_interval_containing_zero(self):
        rng = random.Random(3)
        drawn = [rng.gauss(0.0, 1.0) for _ in range(400)]
        # Centred, so the sample's own mean is zero rather than whatever this
        # seed happened to produce. A bootstrap interval is about the sample
        # it was given, and asserting on an uncentred draw tests the seed.
        middle = sum(drawn) / len(drawn)
        sample = rows([d - middle for d in drawn])

        result = rb.block_bootstrap(sample, block=20, draws=500)

        assert result.lower < 0 < result.upper
        assert not result.excludes_zero

    def test_blocks_widen_the_interval_when_the_data_is_serially_correlated(self):
        """Which is the case this exists for: entries opened within one
        horizon of each other resolve on overlapping bars.

        On independent data blocks buy nothing and the two intervals are
        about the same width - that is not a failure of the method, it is
        what independence means. The property worth testing is that when the
        dependence is really there, resampling single instants reports an
        interval narrower than the data supports.
        """
        rng = random.Random(3)
        runs: list[float] = []
        while len(runs) < 600:
            # One shared shock per horizon, exactly the shape of overlapping
            # trades: 30 consecutive instants that mostly move together.
            shock = rng.gauss(0.1, 1.0)
            runs.extend(shock + rng.gauss(0, 0.05) for _ in range(30))
        sample = rows(runs[:600])

        blocked = rb.block_bootstrap(sample, block=30, draws=400)
        singles = rb.block_bootstrap(sample, block=1, draws=400)

        assert (blocked.upper - blocked.lower) > 1.5 * (singles.upper - singles.lower)

    def test_a_block_longer_than_the_sample_is_clamped(self):
        result = rb.block_bootstrap(rows([1.0] * 10), block=500, draws=50)

        assert result.block == 10


# --------------------------------------------------------- leave one out
class TestLeaveOneOut:
    def test_an_edge_that_is_one_instrument_is_named_fragile(self):
        universe = frozenset({"EURUSD", "GBPUSD", "XAUUSD"})

        def run(remaining):
            edge = 0.0 if "XAUUSD" not in remaining else 0.3
            return measurement(rows([edge] * 200))

        runs, fragile = rb.leave_one_out(run, universe=universe, full_edge=0.3)

        assert fragile == ["XAUUSD"]
        assert len(runs) == 3

    def test_an_edge_spread_across_instruments_names_nobody(self):
        universe = frozenset({"EURUSD", "GBPUSD", "XAUUSD"})

        runs, fragile = rb.leave_one_out(
            lambda remaining: measurement(rows([0.25] * 200)),
            universe=universe,
            full_edge=0.3,
        )

        assert fragile == []
        assert all(run.edge_r > 0 for run in runs)


# ------------------------------------------------------------------ verdict
class TestTheVerdict:
    def build(self, values, **over):
        return rb.assess(measurement(rows(values)), horizon_instants=20, **over)

    def test_a_real_edge_across_the_sample_is_robust(self):
        rng = random.Random(11)
        report = self.build([rng.gauss(0.5, 0.4) for _ in range(600)])

        assert report.verdict == "ROBUST_ON_THIS_SAMPLE"
        assert report.findings == []

    def test_noise_is_not(self):
        rng = random.Random(11)
        report = self.build([rng.gauss(0.0, 1.0) for _ in range(600)])

        assert report.verdict == "NOT_ROBUST"
        assert any("sign-flipped" in f for f in report.findings)

    def test_an_edge_smaller_than_the_extreme_cost_is_reported(self):
        rng = random.Random(11)
        report = self.build([rng.gauss(0.02, 0.05) for _ in range(600)])

        assert any("four times" in f for f in report.findings)

    def test_a_fragile_edge_is_fragile_whatever_else_passed(self):
        rng = random.Random(11)
        report = self.build(
            [rng.gauss(0.5, 0.4) for _ in range(600)],
            excluded=[rb.Excluded("XAUUSD", 400, -0.01, -0.4)],
            fragile_on=["XAUUSD"],
        )

        assert report.verdict == "FRAGILE"

    def test_a_sweep_raises_the_bar_it_has_to_clear(self):
        rng = random.Random(11)
        values = [rng.gauss(0.08, 1.0) for _ in range(600)]

        alone = self.build(values, hypotheses_tested=1)
        from_a_sweep = self.build(values, hypotheses_tested=64)

        assert from_a_sweep.required_t > alone.required_t
        assert any("64 hypothesis" in f for f in from_a_sweep.findings)

    def test_it_never_says_proven(self):
        rng = random.Random(11)
        report = self.build([rng.gauss(2.0, 0.1) for _ in range(600)])

        assert "PROVEN" not in report.verdict
        assert "no amount of re-cutting the same history" in report.as_dict()["note"]

    def test_a_measurement_without_rows_refuses_rather_than_reporting_nothing(self):
        bare = measurement(rows([1.0] * 10), instant_rows=None)

        with pytest.raises(ValueError, match="keep_instants=True"):
            rb.assess(bare, horizon_instants=5)
