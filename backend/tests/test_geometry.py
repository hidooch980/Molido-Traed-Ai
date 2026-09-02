"""The sweep must be unable to manufacture a result that is not there.

A grid over twenty geometries, keep the best, publish it - that is the exact
machine for producing a discovery from noise, and it is what this module is.
So most of what is tested here is the refusing: that the choice is made on
training alone, that the held-out window is what decides, and that a geometry
which only wins where it was chosen comes back marked as a failure rather than
quietly dropped from the report.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from app.core.errors import ValidationFailedError
from app.learning import geometry
from app.learning.measure import Bar
from app.workers.forward import STOP_MULTIPLE, TARGET_MULTIPLE

START = datetime(2026, 1, 1, tzinfo=UTC)


def series(symbols=("A", "B", "C", "D", "E"), bars=400, step=timedelta(minutes=15)):
    """A flat, noiseless series. No rule can earn anything on it, which is what
    makes it useful: anything the sweep reports here it invented."""
    out = {}
    for index, symbol in enumerate(symbols):
        price = 100.0 + index
        out[symbol] = [
            Bar(
                at=START + step * i,
                open=price,
                high=price + 0.5,
                low=price - 0.5,
                close=price,
            )
            for i in range(bars)
        ]
    return out


class TestTheCostFallsAsTheStopWidens:
    """Cost in R is spread over stop distance, and the distance is the only
    term a geometry changes."""

    def test_twice_the_stop_is_half_the_cost(self):
        near = geometry.cost_for(STOP_MULTIPLE, cost_at_incumbent=0.19)
        far = geometry.cost_for(STOP_MULTIPLE * 2, cost_at_incumbent=0.19)

        assert near == pytest.approx(0.19)
        assert far == pytest.approx(0.095)

    def test_the_incumbent_costs_what_was_measured(self):
        assert geometry.cost_for(
            STOP_MULTIPLE, cost_at_incumbent=0.22
        ) == pytest.approx(0.22)

    def test_a_stop_of_nothing_is_refused(self):
        with pytest.raises(ValidationFailedError):
            geometry.cost_for(0.0, cost_at_incumbent=0.19)

    def test_entry_cannot_cost_less_than_nothing(self):
        with pytest.raises(ValidationFailedError):
            geometry.cost_for(2.5, cost_at_incumbent=-0.01)


class TestNetIsWhatTheAccountSees:
    def test_a_gross_edge_under_its_cost_is_a_loss(self):
        """0.108 R gross against 0.19 R of entry is not a small edge. It is a
        loss with a flattering description."""
        thin = geometry.Trial(
            stop_multiple=2.5,
            target_multiple=1.0,
            instants=500,
            trades=900,
            gross_r=0.108,
            cost_r=0.19,
            t_statistic=3.0,
        )

        assert thin.net_r == pytest.approx(-0.082)


class TestTheSplitIsByTimeAndSharedAcrossInstruments:
    def test_one_cut_serves_every_instrument(self):
        """Splitting per instrument would put the same afternoon in one
        symbol's training set and another's test set, and a cross-sectional
        rule reads them at the same instant."""
        start, cut, end = geometry.split(series())

        assert start == START
        assert start < cut < end

    def test_an_empty_series_has_no_cut(self):
        assert geometry.split({}) == (None, None, None)

    def test_a_split_has_to_leave_both_sides_something(self):
        with pytest.raises(ValidationFailedError):
            geometry.split(series(), fraction=1.0)


class TestASweepCannotManufactureAResult:
    """The whole point. Twenty geometries and keep the best is how a discovery
    gets made out of nothing."""

    def test_a_flat_market_produces_no_survivor(self):
        result = geometry.sweep(
            series(), bar_interval=timedelta(minutes=15), cost_at_incumbent=0.19
        )

        assert result.survived is False
        assert result.refusal

    def test_an_empty_series_refuses_rather_than_returning_zeroes(self):
        result = geometry.sweep(
            {}, bar_interval=timedelta(minutes=15), cost_at_incumbent=0.19
        )

        assert result.survived is False
        assert "empty" in result.refusal
        assert result.chosen is None

    def test_the_refusal_names_the_reason(self):
        """"It won in training" is the most common and most misleading way to
        fail, so it is said out loud rather than left to be inferred."""
        result = geometry.sweep(
            series(), bar_interval=timedelta(minutes=15), cost_at_incumbent=0.19
        )

        assert result.refusal != ""
        assert result.as_payload()["refusal"] == result.refusal


class TestSurvivalIsDecidedOnDataTheChoiceNeverSaw:
    """Winning in training is not on the list of conditions. That is the part
    a sweep produces for free."""

    @staticmethod
    def trial(net, instants=500):
        return geometry.Trial(
            stop_multiple=10.0,
            target_multiple=1.0,
            instants=instants,
            trades=instants * 2,
            gross_r=net + 0.05,
            cost_r=0.05,
            t_statistic=3.0,
        )

    def make(self, *, confirmed, incumbent_test):
        return geometry.Sweep(
            chosen=self.trial(0.5),
            confirmed=confirmed,
            incumbent_train=None,
            incumbent_test=incumbent_test,
            train_window=None,
            test_window=None,
        )

    def test_a_geometry_that_clears_its_cost_and_beats_the_incumbent_survives(self):
        result = self.make(
            confirmed=self.trial(0.20), incumbent_test=self.trial(0.05)
        )

        assert result.survived is True

    def test_a_geometry_that_loses_on_held_out_data_does_not(self):
        result = self.make(
            confirmed=self.trial(-0.01), incumbent_test=self.trial(-0.20)
        )

        assert result.survived is False

    def test_beating_a_worse_incumbent_is_not_enough_to_clear_zero(self):
        """Both losing money is not a reason to deploy the one losing less."""
        result = self.make(
            confirmed=self.trial(0.0), incumbent_test=self.trial(-0.30)
        )

        assert result.survived is False

    def test_a_geometry_that_does_not_beat_the_incumbent_does_not_survive(self):
        result = self.make(
            confirmed=self.trial(0.10), incumbent_test=self.trial(0.15)
        )

        assert result.survived is False

    def test_a_thin_held_out_window_cannot_confirm_anything(self):
        result = self.make(
            confirmed=self.trial(0.9, instants=geometry.MIN_INSTANTS - 1),
            incumbent_test=self.trial(0.05),
        )

        assert result.survived is False

    def test_nothing_chosen_is_not_a_survivor(self):
        result = geometry.Sweep(None, None, None, None, None, None)

        assert result.survived is False


class TestTheIncumbentIsAlwaysInTheGrid:
    def test_the_deployed_geometry_is_one_of_the_candidates(self):
        """A sweep whose grid excludes the thing it argues against cannot be
        read as a comparison."""
        assert STOP_MULTIPLE in geometry.STOP_MULTIPLES
        assert TARGET_MULTIPLE in geometry.TARGET_MULTIPLES


class TestOneSplitCanBeLuck:
    """A geometry that wins at one cut and loses at the next was read off the
    noise, and that is worth finding out before a live stop is widened six
    times."""

    @staticmethod
    def fold(stop, target, *, survived=True):
        won = geometry.Trial(
            stop_multiple=stop,
            target_multiple=target,
            instants=500,
            trades=900,
            gross_r=0.2 if survived else 0.0,
            cost_r=0.01,
            t_statistic=4.0,
        )
        return geometry.Sweep(
            chosen=won,
            confirmed=won if survived else None,
            incumbent_train=None,
            incumbent_test=None,
            train_window=None,
            test_window=None,
        )

    def test_a_geometry_chosen_at_every_cut_is_reported(self):
        rolled = geometry.Stability(
            folds=tuple(self.fold(7.5, 1.5) for _ in range(4)),
            tally={(7.5, 1.5): 4},
        )

        assert rolled.consistent == (7.5, 1.5)
        assert rolled.survivors == 4

    def test_a_majority_is_not_enough(self):
        """Three cuts of five is a geometry whose case rests on which three."""
        rolled = geometry.Stability(
            folds=tuple(self.fold(7.5, 1.5) for _ in range(4)),
            tally={(7.5, 1.5): 3, (15.0, 2.0): 1},
        )

        assert rolled.consistent is None

    def test_no_folds_means_nothing_held(self):
        assert geometry.Stability(folds=(), tally={}).consistent is None

    def test_the_payload_names_how_often_each_was_chosen(self):
        rolled = geometry.Stability(
            folds=tuple(self.fold(7.5, 1.5) for _ in range(3)),
            tally={(7.5, 1.5): 2, (15.0, 2.0): 1},
        )
        payload = rolled.as_payload()

        assert payload["chosen_every_fold"] is None
        assert payload["how_often_each_geometry_was_chosen"]["7.5/1.5"] == 2

    def test_every_test_window_follows_its_training_window(self):
        """Shuffled folds would train on next month and test on last, and
        report an edge that is only hindsight."""
        rolled = geometry.stability(
            series(), bar_interval=timedelta(minutes=15), cost_at_incumbent=0.19
        )

        for fold in rolled.folds:
            if fold.train_window and fold.test_window:
                assert fold.train_window[1] <= fold.test_window[0]

    def test_a_flat_market_holds_nothing_across_folds(self):
        rolled = geometry.stability(
            series(), bar_interval=timedelta(minutes=15), cost_at_incumbent=0.19
        )

        assert rolled.survivors == 0
