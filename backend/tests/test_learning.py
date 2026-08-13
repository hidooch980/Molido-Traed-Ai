"""Learning-lab, registry, drift and benchmark tests (phases 30-34).

The failure this whole block exists to prevent is a backtest that looks
excellent and a live system that does not work, so most of these tests are
about the ways a comparison flatters itself: a split that lets the model see
forward, a promotion decided on a sample too small to measure, a benchmark run
over a friendlier window than the strategy.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from app.core.errors import InsufficientDataError, ValidationFailedError
from app.learning import drift as dft
from app.learning import lab
from app.learning import registry as reg

START = datetime(2024, 1, 1, tzinfo=UTC)


def samples(count: int, *, maturity_hours: int = 4, spacing_hours: int = 1):
    return [
        lab.Sample(
            sample_id=f"s{i:04d}",
            event_time=START + timedelta(hours=i * spacing_hours),
            outcome_ready_at=START
            + timedelta(hours=i * spacing_hours + maturity_hours),
        )
        for i in range(count)
    ]


def lineage(**overrides) -> reg.Lineage:
    defaults = dict(
        feature_set=("atr_14", "rsi_14"),
        train_start=START,
        train_end=START + timedelta(days=90),
        as_of=START + timedelta(days=91),
        code_version="b72bcd9",
        dataset_quality_score=0.93,
    )
    defaults.update(overrides)
    return reg.Lineage(**defaults)


def evaluation(sample: int, hits: int, total_r: float, *, offset: int = 0) -> reg.Evaluation:
    return reg.Evaluation(
        decision_ids=tuple(f"d{i:04d}" for i in range(offset, offset + sample)),
        hits=hits,
        total_r=total_r,
    )


# ============================================================= walk-forward
class TestWalkForwardCannotLeak:
    def test_folds_move_forward_and_never_overlap(self):
        plan = lab.walk_forward(samples(400), folds=3, embargo=timedelta(hours=6))

        starts = [f.test_start for f in plan.folds]
        assert starts == sorted(starts)
        for fold in plan.folds:
            assert set(fold.train) & set(fold.test) == set()

    def test_a_sample_maturing_inside_the_test_window_is_purged(self):
        """The label it carries is a fact about the period being tested."""
        plan = lab.walk_forward(
            samples(400, maturity_hours=48), folds=2, embargo=timedelta(0)
        )

        assert all(fold.purged for fold in plan.folds)

    def test_longer_maturity_purges_more(self):
        short = lab.walk_forward(samples(400, maturity_hours=2), folds=2, embargo=timedelta(0))
        long = lab.walk_forward(samples(400, maturity_hours=72), folds=2, embargo=timedelta(0))

        assert sum(len(f.purged) for f in long.folds) > sum(
            len(f.purged) for f in short.folds
        )

    def test_the_embargo_drops_samples_next_to_the_boundary(self):
        without = lab.walk_forward(samples(400), folds=2, embargo=timedelta(0))
        with_embargo = lab.walk_forward(samples(400), folds=2, embargo=timedelta(hours=24))

        assert sum(len(f.embargoed) for f in with_embargo.folds) > 0
        assert sum(len(f.embargoed) for f in without.folds) == 0

    def test_no_embargo_is_reported_rather_than_silently_accepted(self):
        plan = lab.walk_forward(samples(400), folds=2, embargo=timedelta(0))

        assert any("no embargo" in n for n in plan.notes)

    def test_the_verification_is_independent_of_the_builder(self):
        plan = lab.walk_forward(samples(400), folds=3, embargo=timedelta(hours=6))

        lab.assert_no_leakage(plan, samples(400))

    def test_the_verification_catches_a_planted_leak(self):
        """Otherwise it would only be confirming the builder's own bookkeeping."""
        data = samples(400)
        plan = lab.walk_forward(data, folds=2, embargo=timedelta(hours=6))
        leaked = plan.folds[0]
        plan.folds[0] = lab.Fold(
            index=leaked.index,
            train_start=leaked.train_start,
            train_end=leaked.train_end,
            test_start=leaked.test_start,
            test_end=leaked.test_end,
            train=(*leaked.train, leaked.test[0]),
            test=leaked.test,
        )

        with pytest.raises(ValidationFailedError):
            lab.assert_no_leakage(plan, data)

    def test_too_little_data_refuses_rather_than_shrinking_the_folds(self):
        with pytest.raises(InsufficientDataError):
            lab.walk_forward(samples(50), folds=5, embargo=timedelta(hours=1))

    def test_an_embargo_that_eats_the_training_set_refuses(self):
        """A fold that cannot be made clean is not a fold."""
        with pytest.raises(InsufficientDataError):
            lab.walk_forward(samples(400), folds=2, embargo=timedelta(days=400))

    def test_a_sample_that_resolves_before_it_happens_is_refused(self):
        with pytest.raises(ValidationFailedError):
            lab.Sample("bad", START, START - timedelta(hours=1))

    def test_naive_timestamps_are_refused(self):
        with pytest.raises(ValidationFailedError):
            lab.Sample("bad", datetime(2024, 1, 1), datetime(2024, 1, 2))


# ================================================================= lineage
class TestLineage:
    def test_a_model_trained_on_no_features_has_no_lineage(self):
        with pytest.raises(ValidationFailedError):
            lineage(feature_set=())

    def test_a_knowledge_cutoff_before_the_last_training_bar_is_refused(self):
        """That combination means the model saw a bar before it was knowable."""
        with pytest.raises(ValidationFailedError) as exc:
            lineage(as_of=START + timedelta(days=1))

        assert "not yet known" in str(exc.value)

    def test_a_backwards_training_window_is_refused(self):
        with pytest.raises(ValidationFailedError):
            lineage(train_start=START + timedelta(days=90), train_end=START)

    def test_an_unnamed_code_version_is_refused(self):
        with pytest.raises(ValidationFailedError):
            lineage(code_version="  ")

    def test_the_same_training_produces_the_same_fingerprint(self):
        assert lineage().fingerprint == lineage().fingerprint

    def test_a_different_feature_set_is_a_different_model(self):
        assert lineage().fingerprint != lineage(feature_set=("atr_14",)).fingerprint


# ============================================================= promotion
class TestPromotionNeedsEvidence:
    def test_an_unevaluated_pair_cannot_be_compared(self):
        registry = reg.ModelRegistry()
        champ = registry.register("council", lineage())
        chall = registry.register("council", lineage())

        assert reg.compare(champ, chall).promote is False

    def test_a_small_sample_cannot_promote_however_large_the_margin(self):
        """The smaller sample is the one more likely to show an edge by accident."""
        registry = reg.ModelRegistry()
        champ = registry.register("council", lineage())
        chall = registry.register("council", lineage())
        champ.evaluation = evaluation(20, 6, -2.0)
        chall.evaluation = evaluation(20, 18, 14.0)

        decision = reg.compare(champ, chall)

        assert decision.promote is False
        assert "below the" in decision.reason

    def test_non_overlapping_samples_cannot_promote(self):
        registry = reg.ModelRegistry()
        champ = registry.register("council", lineage())
        chall = registry.register("council", lineage())
        champ.evaluation = evaluation(200, 100, 10.0)
        chall.evaluation = evaluation(200, 150, 60.0, offset=1000)

        decision = reg.compare(champ, chall)

        assert decision.promote is False
        assert "different markets" in decision.reason

    def test_a_thin_margin_is_similar_not_better(self):
        registry = reg.ModelRegistry()
        champ = registry.register("council", lineage())
        chall = registry.register("council", lineage())
        champ.evaluation = evaluation(200, 100, 5.0)
        chall.evaluation = evaluation(200, 104, 7.0)

        decision = reg.compare(champ, chall)

        assert decision.promote is False
        assert "similar, not better" in decision.reason

    def test_a_real_margin_on_a_shared_sample_promotes(self):
        registry = reg.ModelRegistry()
        champ = registry.register("council", lineage())
        chall = registry.register("council", lineage())
        champ.evaluation = evaluation(400, 180, 5.0)
        chall.evaluation = evaluation(400, 260, 60.0)

        decision = reg.compare(champ, chall)

        assert decision.promote is True
        assert decision.margin > 0

    def test_more_hits_than_decisions_is_refused(self):
        with pytest.raises(ValidationFailedError):
            reg.Evaluation(decision_ids=("a", "b"), hits=3, total_r=1.0)


class TestTheRegistry:
    def test_a_champion_is_promoted_out_of_shadow_only(self):
        """So it has been wrong somewhere it cost nothing first."""
        registry = reg.ModelRegistry()
        record = registry.register("council", lineage())
        passing = reg.PromotionDecision(promote=True, reason="beat it")

        with pytest.raises(ValidationFailedError) as exc:
            registry.promote(record.key, decision=passing)

        assert "out of shadow" in str(exc.value)

    def test_promotion_requires_a_passing_decision_not_a_flag(self):
        registry = reg.ModelRegistry()
        record = registry.register("council", lineage())
        registry.start_shadow(record.key)

        with pytest.raises(ValidationFailedError):
            registry.promote(
                record.key,
                decision=reg.PromotionDecision(promote=False, reason="too few trades"),
            )

    def test_promoting_retires_the_previous_champion(self):
        registry = reg.ModelRegistry()
        first = registry.register("council", lineage())
        second = registry.register("council", lineage())
        for record in (first, second):
            registry.start_shadow(record.key)
        passing = reg.PromotionDecision(promote=True, reason="beat it")

        registry.promote(first.key, decision=passing)
        registry.promote(second.key, decision=passing)

        assert registry.champion("council").key == second.key
        assert registry.get(first.key).stage is reg.ModelStage.RETIRED

    def test_only_one_champion_exists_at_a_time(self):
        registry = reg.ModelRegistry()
        keys = []
        for _ in range(3):
            record = registry.register("council", lineage())
            registry.start_shadow(record.key)
            keys.append(record.key)
        for key in keys:
            registry.promote(key, decision=reg.PromotionDecision(True, "beat it"))

        champions = [
            v for v in registry.as_dict()["versions"] if v["stage"] == "champion"
        ]
        assert len(champions) == 1

    def test_an_unknown_version_is_refused(self):
        with pytest.raises(ValidationFailedError):
            reg.ModelRegistry().start_shadow("nope:v1")


# ==================================================================== drift
class TestFeatureDrift:
    def test_a_stable_feature_scores_low(self):
        reference = [float(i % 100) for i in range(500)]
        recent = [float(i % 100) for i in range(500)]

        result = dft.population_stability(reference, recent)

        assert result.available is True
        assert result.verdict == "stable"

    def test_a_shifted_distribution_is_detected(self):
        reference = [float(i % 100) for i in range(500)]
        recent = [float(i % 100) + 60 for i in range(500)]

        result = dft.population_stability(reference, recent)

        assert result.verdict == "broken"
        assert result.score > dft.PSI_BROKEN

    def test_a_small_sample_reports_insufficient_not_stable(self):
        result = dft.population_stability([1.0] * 10, [1.0] * 10)

        assert result.available is False
        assert result.score is None
        assert "below the" in result.reason

    def test_a_constant_reference_has_no_distribution_to_move_away_from(self):
        result = dft.population_stability([5.0] * 200, [9.0] * 200)

        assert result.available is False
        assert "too concentrated" in result.reason

    def test_the_bins_come_from_the_reference_not_the_pool(self):
        """Pooling would let the recent window move the edges it is measured against."""
        reference = [float(i % 50) for i in range(400)]
        recent = [float(i % 50) * 4 for i in range(400)]

        result = dft.population_stability(reference, recent)

        assert result.verdict in ("shifted", "broken")

    def test_the_thresholds_are_published_as_policy(self):
        payload = dft.population_stability(
            [float(i % 100) for i in range(500)],
            [float(i % 100) for i in range(500)],
        ).as_dict()

        assert payload["thresholds"] == {"shifted": dft.PSI_SHIFTED, "broken": dft.PSI_BROKEN}


class TestConceptDrift:
    def test_degradation_is_flagged(self):
        reference = [1.0, -1.0] * 100
        recent = [-1.0] * 200

        result = dft.concept_drift(reference, recent)

        assert result.verdict == "broken"
        assert result.score < 0

    def test_improvement_is_a_change_not_a_fault(self):
        """Otherwise the alarm fires on a good month."""
        reference = [-1.0, -0.5] * 100
        recent = [2.0, 1.5] * 100

        result = dft.concept_drift(reference, recent)

        assert result.score > 0
        assert result.verdict == "stable"

    def test_it_is_measured_on_r_not_on_hit_rate(self):
        """A model can hold its hit rate while its winners shrink."""
        reference = [3.0] * 100 + [-1.0] * 100
        recent = [0.2] * 100 + [-1.0] * 100

        result = dft.concept_drift(reference, recent)

        assert result.verdict in ("shifted", "broken")

    def test_too_few_matured_outcomes_reports_insufficient(self):
        result = dft.concept_drift([1.0] * 10, [1.0] * 10)

        assert result.available is False
        assert "late warning" in result.reason

    def test_two_constant_windows_have_no_scale_to_measure_on(self):
        result = dft.concept_drift([1.0] * 200, [1.0] * 200)

        assert result.available is False


# ================================================================ benchmark
class TestBenchmark:
    def test_a_strategy_beating_every_baseline_is_reported(self):
        result = dft.benchmark([1.0] * 100, {"always_long": [0.2] * 100})

        assert result.beats_every_baseline is True
        assert result.beaten == ["always_long"]

    def test_losing_to_a_baseline_is_reported(self):
        result = dft.benchmark([0.1] * 100, {"always_long": [0.5] * 100})

        assert result.beats_every_baseline is False
        assert result.lost_to == ["always_long"]

    def test_a_baseline_over_a_different_window_is_refused(self):
        """The comparison would report the window as an edge."""
        result = dft.benchmark([1.0] * 100, {"always_long": [1.0] * 40})

        assert result.available is False
        assert "different number of decisions" in result.reason

    def test_a_return_with_nothing_to_beat_is_not_evidence_of_skill(self):
        result = dft.benchmark([1.0] * 100, {})

        assert result.available is False
        assert "nothing to beat" in result.reason

    def test_an_exact_tie_does_not_count_as_beating(self):
        result = dft.benchmark([1.0] * 100, {"always_long": [1.0] * 100})

        assert result.lost_to == ["always_long"]
