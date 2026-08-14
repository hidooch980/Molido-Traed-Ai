"""The random control, and the three properties that make it worth trusting.

This exists because a script printed CONFIRMED on a result whose edge over a
random control was 0.0052 at z = 1.10. The rule scored 50.84% against a 50.00%
breakeven; the control on the same bars scored 50.32%. Over half the apparent
edge belonged to no information, and without the control there was nothing to
notice.

The live system records a decision every cycle from tonight. In three months
there will be a hit rate, and a benchmark invented at that point is a benchmark
chosen to make the answer come out a particular way. So the control is recorded
from the first cycle, and these tests keep it honest.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from app.learning import control


class TestTheControlHasNoEdgeOfItsOwn:
    def test_the_split_is_even_over_a_large_sample(self):
        """A control that is 50.4% long is a control with its own edge, and
        every measurement taken against it inherits that."""
        start = datetime(2026, 1, 1, tzinfo=UTC)
        sides = [
            control.side_for("EURUSD", start + timedelta(minutes=i))
            for i in range(20000)
        ]
        longs = sum(1 for s in sides if s > 0)

        share = longs / len(sides)
        # Three standard errors at n=20000 is about 0.010. Wider than that and
        # the derivation is biased rather than merely unlucky.
        assert 0.49 < share < 0.51, f"control split is {share:.4f}"

    def test_it_takes_one_bit_rather_than_a_modulo(self):
        """A modulo of a larger range biases the split when the range does not
        divide evenly - the classic way a coin flip stops being one."""
        start = datetime(2026, 1, 1, tzinfo=UTC)
        sides = {
            control.side_for("X", start + timedelta(seconds=i)) for i in range(500)
        }

        assert sides == {1, -1}

    def test_different_instruments_do_not_move_together(self):
        """Correlated controls would understate the variance of the benchmark
        and make a rule look more distinguishable than it is."""
        moment = datetime(2026, 8, 15, 12, tzinfo=UTC)
        pairs = [
            (control.side_for(a, moment), control.side_for(b, moment))
            for a, b in (
                ("EURUSD", "GBPUSD"),
                ("USDJPY", "AUDUSD"),
                ("XAUUSD", "USDCAD"),
                ("EURJPY", "NZDUSD"),
            )
        ]

        assert any(x != y for x, y in pairs), "every pair agreed - they are not independent"


class TestItReproducesExactly:
    def test_the_same_bar_always_gives_the_same_side(self):
        """A benchmark that changes on a re-run is not a benchmark. Derived
        from a hash rather than a generator seeded from the clock."""
        moment = datetime(2026, 8, 15, 9, 30, tzinfo=UTC)

        first = control.side_for("EURUSD", moment)
        second = control.side_for("EURUSD", moment)

        assert first == second

    def test_the_seed_is_part_of_the_record(self):
        """Changing it rewrites every control side ever derived, which would
        silently move the benchmark the live results are measured against."""
        assert control.SEED == "molido-control-v1"


class TestTheGeometryMirrorsTheRealTrade:
    def test_only_the_direction_differs(self):
        """A control entering at a different price or distance would measure
        the timing or the sizing, not the direction - and direction is what the
        brain claims to know."""
        moment = datetime(2026, 8, 15, 12, tzinfo=UTC)

        entry = control.entry_for(
            symbol="EURUSD", at=moment, price=1.1000, stop_distance=0.0025
        )

        assert entry is not None
        assert entry.entry == 1.1000
        assert abs(abs(entry.entry - entry.stop) - 0.0025) < 1e-9
        assert abs(abs(entry.target - entry.entry) - 0.0025) < 1e-9

    def test_the_stop_and_target_sit_on_opposite_sides(self):
        moment = datetime(2026, 8, 15, 12, tzinfo=UTC)
        entry = control.entry_for(
            symbol="EURUSD", at=moment, price=1.1000, stop_distance=0.0025
        )

        assert (entry.target - entry.entry) * (entry.stop - entry.entry) < 0

    def test_an_unusable_geometry_returns_none_rather_than_a_default(self):
        """A control with a zero stop is not a coin flip - it resolves
        instantly and flatters or ruins the benchmark on the next tick."""
        moment = datetime(2026, 8, 15, 12, tzinfo=UTC)

        assert (
            control.entry_for(
                symbol="EURUSD", at=moment, price=1.1, stop_distance=0.0
            )
            is None
        )
        assert (
            control.entry_for(symbol="EURUSD", at=moment, price=0.0, stop_distance=0.1)
            is None
        )


class TestTheComparisonMeasuresAgainstTheControl:
    def test_it_reproduces_the_result_that_was_wrongly_confirmed(self):
        """The exact numbers from the run that printed CONFIRMED. The edge over
        the control is 0.53 percentage points at z = 1.11 - not significant,
        which is what the original comparison against breakeven missed."""
        measured = control.Comparison(
            rule_wins=11417,
            rule_losses=11037,
            control_wins=11299,
            control_losses=11155,
        )

        assert round(measured.edge, 4) == 0.0053
        assert measured.z_score < 1.96
        assert measured.as_dict()["significant"] is False

    def test_beating_breakeven_while_matching_the_control_is_no_edge(self):
        """Both arms at 50.84%. Against breakeven that is an edge; against the
        control it is nothing, and the second reading is the true one."""
        matched = control.Comparison(
            rule_wins=11417, rule_losses=11037, control_wins=11417, control_losses=11037
        )

        assert matched.edge == 0.0
        assert matched.as_dict()["significant"] is False

    def test_a_real_edge_is_detected(self):
        """The measure has to be able to say yes, or it is not a measure."""
        real = control.Comparison(
            rule_wins=5600, rule_losses=4400, control_wins=5000, control_losses=5000
        )

        assert real.edge > 0
        assert real.as_dict()["significant"] is True

    def test_no_trials_reports_nothing_rather_than_zero(self):
        """An empty measurement is not a measurement of zero."""
        empty = control.Comparison(
            rule_wins=0, rule_losses=0, control_wins=0, control_losses=0
        )

        assert empty.edge is None
        assert empty.z_score is None
        assert empty.as_dict()["significant"] is False

    def test_it_publishes_how_long_the_wait_will_be(self):
        """So the wait is a number rather than a feeling. Half a percentage
        point needs about 77,000 trials per arm, which on a handful of daily
        decisions is longer than anybody will wait - and that is worth knowing
        in advance rather than in a year."""
        measured = control.Comparison(
            rule_wins=10, rule_losses=10, control_wins=10, control_losses=10
        )

        assert measured.trials_needed(for_edge=0.02) == 4802
        assert measured.trials_needed(for_edge=0.005) > 70000
