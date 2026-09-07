"""Section 16 of the brief: what the same edge looks like when the order or
the sample changes, and section 21's risk-adjusted readings over it."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from app.learning import montecarlo as mc

NOW = datetime(2020, 1, 1, tzinfo=UTC)


def rows(values, *, control=0.0):
    """One row per instant, as `measure` keeps them."""
    return [
        (NOW + timedelta(hours=i), value + control, control)
        for i, value in enumerate(values)
    ]


class TestTheCurve:
    def test_drawdown_is_measured_from_the_peak_not_the_start(self):
        """A strategy that doubles and then halves has halved. Measuring from
        the start would call it flat and describe nothing."""
        shape = mc.curve([1.0, 1.0, 1.0, -1.0, -1.0])

        assert shape.total_r == 1.0
        assert shape.max_drawdown_r == 2.0

    def test_the_longest_cold_run_is_the_one_to_sit_through(self):
        shape = mc.curve([-1.0, 1.0, -1.0, -1.0, -1.0, 1.0, -1.0])

        assert shape.longest_losing_run == 3

    def test_a_run_that_only_rises_has_no_drawdown(self):
        assert mc.curve([0.5, 0.5, 0.5]).max_drawdown_r == 0.0


class TestReshuffling:
    """Expectancy is a property of the trades; drawdown is a property of their
    order, and only one of the two was observed."""

    def test_the_total_is_untouched_and_only_the_path_moves(self):
        values = [1.5, -1.0, -1.0, 1.5, -1.0] * 20
        result = mc.reshuffled(rows(values), draws=200)

        assert result is not None
        # Every draw holds the same multiset, so no reordering can make the
        # sum differ - only the depth of the hole on the way.
        assert result.worst_r >= result.p95_r >= result.median_r

    def test_a_tidy_order_is_flattered_and_the_test_says_so(self):
        """The clearest demonstration of why this exists: a perfectly
        alternating sequence never has a long cold run, so its observed
        drawdown sits at the bottom of the distribution of orders the same
        trades could have arrived in."""
        values = [1.5, -1.0, -1.0, 1.5, -1.0] * 20
        result = mc.reshuffled(rows(values), draws=400)

        assert result.percentile_of_observed < 5.0
        assert result.p95_r > result.observed_r * 2

    def test_two_runs_with_the_same_seed_agree(self):
        """Section 28 asks for reproducibility. A robustness number that moves
        each time it is run is weather, not evidence."""
        values = [1.5, -1.0, -1.0, 1.5, -1.0] * 20

        first = mc.reshuffled(rows(values), draws=200, seed=7)
        second = mc.reshuffled(rows(values), draws=200, seed=7)

        assert first.as_dict() == second.as_dict()

    def test_it_declines_rather_than_resampling_one_instant(self):
        assert mc.reshuffled(rows([1.0])) is None


class TestRandomOmission:
    """An edge carried by six moments out of four hundred is a story about
    those six moments."""

    def test_an_edge_spread_across_the_sample_survives_losing_a_fifth(self):
        values = [0.4] * 100 + [-0.2] * 100
        result = mc.with_random_omission(rows(values), draws=300)

        assert result.share_positive > 0.99

    def test_an_edge_carried_by_a_few_instants_does_not(self):
        """Same total, concentrated. Ninety-five losers of -0.1 and five
        winners of +2.0: positive overall, and mostly not positive once a
        fifth of the sample is gone."""
        values = [-0.1] * 95 + [2.0] * 5
        result = mc.with_random_omission(rows(values), draws=500)

        assert sum(values) > 0
        assert result.share_positive < 0.9

    def test_the_sample_is_smaller_by_the_fraction_dropped(self):
        result = mc.with_random_omission(rows([0.1] * 100), fraction=0.25, draws=50)

        assert result.kept == 75


class TestTheRatios:
    def test_sortino_ignores_upside_variance(self):
        """A rule whose variance is mostly upside should not be punished for
        it, which is the whole reason Sortino exists beside Sharpe."""
        values = [0.1, 0.1, 0.1, 3.0, 0.1, -0.1]
        read = mc.ratios(rows(values))

        assert read.sortino > read.sharpe

    def test_calmar_and_recovery_are_none_without_a_drawdown(self):
        """A strategy that never fell has no ratio to a fall. Printing a large
        number there would be inventing one."""
        read = mc.ratios(rows([0.5, 0.5, 0.5]))

        assert read.calmar is None
        assert read.recovery_factor is None

    def test_profit_factor_is_none_when_nothing_lost(self):
        read = mc.ratios(rows([0.5, 0.5]))

        assert read.profit_factor is None

    def test_the_edge_is_read_not_the_raw_return(self):
        """Both arms shifted by the same amount is the same edge. A reading
        taken on the rule's raw return would move with the market instead."""
        plain = mc.ratios(rows([1.0, -1.0, 1.0, -0.5]))
        shifted = mc.ratios(rows([1.0, -1.0, 1.0, -0.5], control=5.0))

        assert plain.as_dict() == shifted.as_dict()

    def test_it_says_the_numbers_are_not_annualised(self):
        """The instants are not evenly spaced - the rule fires when it fires
        and markets shut at weekends - so annualising would compare two rules
        to a convention rather than to each other."""
        read = mc.ratios(rows([1.0, -1.0, 0.5]))

        assert "not annualised" in read.as_dict()["note"]


class TestTheReport:
    def test_it_renders_every_section(self):
        values = [1.5, -1.0, -1.0, 1.5, -1.0] * 20
        lines = mc.render(mc.report(rows(values), draws=200))
        text = "\n".join(lines)

        assert "drawdown observed" in text
        assert "percentile of orders" in text
        assert "at random leaves a positive edge" in text
        assert "sharpe" in text

    def test_too_few_instants_says_so_rather_than_printing_nothing(self):
        lines = mc.render(mc.report(rows([1.0])))

        assert any("too few instants" in line for line in lines)


class TestTheBlockLengthIsTheWholeTest:
    """Consecutive instants are not independent: a decision at one instant and
    the next both resolve over the bars that follow, so they share outcome
    bars and their edges move together.

    The first version of this module shuffled them one at a time. Run across
    four live rules it put every single one at the 99th or 100th percentile -
    which is what a test says when it is measuring itself rather than the
    strategy. The block length is the fix and it is not a refinement."""

    def autocorrelated(self, *, run=60):
        """Losses arriving together, the way an overlapping horizon makes them
        arrive: a good stretch, one bad regime, a good stretch."""
        return rows([0.2] * 100 + [-0.5] * run + [0.2] * 100)

    def test_one_at_a_time_cannot_reproduce_the_observed_depth(self):
        """The bug, kept as a test. Dealing an autocorrelated series as if it
        were independent spreads the losing stretch out, so no draw gets near
        the hole that actually happened and the real path is condemned by
        construction."""
        result = mc.reshuffled(self.autocorrelated(), block=1, draws=300)

        assert result.percentile_of_observed > 95.0
        assert result.median_r < result.observed_r * 0.5

    def test_blocks_the_length_of_the_run_reproduce_it(self):
        """Same series, blocks that keep the stretch together. Now a typical
        draw is as deep as the one that happened, which is what it means for
        the observed path to be ordinary rather than extreme."""
        loose = mc.reshuffled(self.autocorrelated(), block=1, draws=300)
        tight = mc.reshuffled(self.autocorrelated(), block=60, draws=300)

        assert tight.median_r > loose.median_r
        assert tight.median_r >= tight.observed_r * 0.6

    def test_a_block_longer_than_the_sample_is_clamped(self):
        result = mc.reshuffled(rows([0.5, -0.5, 0.5]), block=99, draws=10)

        assert result is not None

    def test_the_report_says_what_block_it_used(self):
        """A percentile without its block length is not interpretable, and
        this module has already been wrong about exactly that."""
        payload = mc.report(self.autocorrelated(), block=60, draws=100)

        assert payload["block_instants"] == 60
        assert "blocks of 60 instants" in mc.render(payload)[0]
