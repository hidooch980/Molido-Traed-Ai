"""Writing down how strongly a rule wanted each pick.

Every rule computed a number to choose by and then discarded it, which left
`app.brain.calibration` with nothing to measure - so `calibrated` stayed
false, and the risk brain halved every order for it twice over. A penalty
that cannot be worked off is not a penalty, it is a constant, and the
evidence that would lift it was the one thing nothing was recording.

Strength rather than conviction, deliberately: `app.execution.conviction`
already owns that word for the multiplier that shrinks a permitted order at
execution time, and this is a different thing at a different moment - what
the rule saw, before any gate had an opinion.

These tests are about the number being *right*, not about it being present.
A strength that is backwards is worse than none at all: it enters the
reliability curve as evidence and takes a hundred resolved trades to unwind.
"""

from __future__ import annotations

from app.learning import rules as rules_module
from app.learning.rules import (
    STRETCH_FULL_AT,
    Picks,
    _strength,
    _tail_strength,
    scaled_strength,
    strength_from,
)

SCORED = [(0.1, "A"), (0.3, "D"), (0.5, "B"), (0.9, "C")]


class TestPositionInTheCrossSection:
    def test_the_extreme_pick_scores_full(self):
        assert _tail_strength(SCORED, picked=("C",), strong_when_high=True)["C"] == 1.0

    def test_the_orientation_follows_the_rule_not_the_list(self):
        """A rule that buys the bottom must score the bottom as strong.

        Read with the wrong orientation, a reversal's best pick reports as its
        weakest - a number exactly backwards, which is the one kind a
        measurement cannot recover from.
        """
        momentum = _tail_strength(SCORED, picked=("A",), strong_when_high=True)
        reversal = _tail_strength(SCORED, picked=("A",), strong_when_high=False)

        assert momentum["A"] == 0.0
        assert reversal["A"] == 1.0

    def test_both_sides_of_one_ranking_score_from_their_own_end(self):
        """A momentum short taken from the bottom is a strong short, not a
        weak long."""
        out = _strength(SCORED, longs=("C",), shorts=("A",), buy_high=True)

        assert out["C"] == 1.0
        assert out["A"] == 1.0

    def test_ties_score_the_same(self):
        """Two instruments reading identically must not be separated by
        whatever order the sort happened to leave them in."""
        tied = [(0.5, "A"), (0.5, "B"), (0.1, "C"), (0.9, "D")]
        out = _tail_strength(tied, picked=("A", "B"), strong_when_high=True)

        assert out["A"] == out["B"]

    def test_a_cross_section_of_one_reports_nothing(self):
        """There is no position to read, and 1.0 would be a claim."""
        assert _tail_strength([(0.5, "A")], picked=("A",), strong_when_high=True) == {}


class TestTheFixedScale:
    def test_it_saturates_rather_than_normalising_to_the_best_of_the_day(self):
        """Normalising by the strongest pick would make the best pick of every
        cycle exactly 1.0 however weak the day was, and a forecast whose
        meaning moves from cycle to cycle cannot be calibrated against
        anything."""
        weak = scaled_strength({"A": 0.1, "B": 0.2}, full_at=2.0)
        strong = scaled_strength({"A": 1.0, "B": 4.0}, full_at=2.0)

        assert weak["B"] == 0.1
        assert strong["A"] == 0.5
        assert strong["B"] == 1.0

    def test_direction_does_not_change_strength(self):
        """Stretch is signed. How far from the mean is the strength; which
        side of it is the decision."""
        assert strength_from(-1.0, full_at=2.0) == strength_from(1.0, full_at=2.0)

    def test_the_scale_is_named_once(self):
        """The incumbent is scored in the rule and again in the forward
        recorder. Two copies of a scale become two scales the moment one is
        edited."""
        assert STRETCH_FULL_AT == 2.0


class TestEveryRuleThatPicksAlsoScores:
    """A rule that silently stops reporting is a strategy that leaves the
    calibration sample while carrying on trading."""

    @staticmethod
    def snapshot(instruments: int = 12, bars: int = 300):
        from datetime import UTC, datetime

        out = {}
        for i in range(instruments):
            symbol = f"SYM{i:02d}"
            closes = [100.0 + i * 0.5 + (j % 7) * 0.3 for j in range(bars)]
            out[symbol] = {
                "closes": closes,
                "bars": [(c + 1.0, c - 1.0, c) for c in closes],
                "last_at": datetime(2026, 9, 4, 12, 0, tzinfo=UTC),
            }
        return out

    def test_a_rule_that_picks_also_scores(self):
        snap = self.snapshot()
        covered = {}
        for name, rule in rules_module.CANDIDATES.items():
            picks = rule(snap, universe=None)
            if picks.empty:
                continue
            covered[name] = set(picks.longs) | set(picks.shorts) <= set(picks.scores)

        assert covered, "no rule produced a pick on this snapshot"
        assert all(covered.values()), [n for n, ok in covered.items() if not ok]

    def test_every_score_is_a_probability_shaped_number(self):
        snap = self.snapshot()
        for rule in rules_module.CANDIDATES.values():
            for value in rule(snap, universe=None).scores.values():
                assert 0.0 <= value <= 1.0


class TestAbsentIsNotAMiddle:
    def test_a_rule_with_no_strength_reports_no_score(self):
        assert Picks(longs=("A",)).scores == {}

    def test_unscored_entries_are_counted_rather_than_defaulted(self):
        """A decision with no strength attached was not made at 0.5. Feeding
        a made-up middle into the reliability curve would manufacture the
        evidence the report exists to wait for."""
        from app.ops import calibration_report

        out = calibration_report.assess(
            _FakeSession(
                [
                    ("trend-following", "win", {"strength": 0.9}),
                    ("trend-following", "loss", {}),
                    ("trend-following", "loss", {"strength": "nonsense"}),
                ]
            )
        )
        row = next(r for r in out["per_strategy"] if r["strategy"] == "trend-following")

        assert row["scored"] == 1
        assert row["unscored"] == 2
        assert row["calibrated"] is False

    def test_no_calibration_is_claimed_below_the_minimum(self):
        from app.brain import calibration
        from app.ops import calibration_report

        out = calibration_report.assess(
            _FakeSession(
                [("trend-following", "win", {"strength": 0.8})]
                * (calibration.MIN_FORECASTS - 1)
            )
        )

        assert out["any_calibrated"] is False
        assert out["closest_gap"] == 1


class TestItChangesNoSizing:
    def test_the_risk_brain_still_halves_twice(self):
        """The report is a distance, not a permission. Lifting either flag
        quadruples live risk, and that is not a decision a report gets to
        make."""
        from app.brain.risk import AccountState, DataHealth, authorise

        decision = authorise(
            requested_risk_r=1.0,
            account=AccountState(
                equity=10_000.0,
                balance=10_000.0,
                peak_equity=10_000.0,
                daily_pnl_r=0.0,
                open_positions=0,
                used_margin=0.0,
                free_margin=10_000.0,
            ),
            health=DataHealth(data_age_bars=0.0),
        )

        assert any("calibrated" in reason for reason in decision.reductions)
        assert any("quality gate" in reason for reason in decision.reductions)


class _FakeSession:
    """Just enough session to hand `assess` a fixed set of rows."""

    def __init__(self, rows):
        self._rows = rows

    def execute(self, _statement):
        rows = self._rows

        class Result:
            def all(self):
                return rows

        return Result()
