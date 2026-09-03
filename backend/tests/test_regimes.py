"""The regime filter has to be able to say no.

A filter that cannot fail its own test is not a test. So the sample below
where the regime carries nothing must come back NOT_CONFIRMED, and the one
where it carries everything must come back CONFIRMED only because the
held-out half agreed - never because the training half did.
"""

from __future__ import annotations

import random
from datetime import UTC, datetime, timedelta

import pytest

from app.learning import regimes as rg
from app.learning.measure import Bar

START = datetime(2010, 1, 1, tzinfo=UTC)


def rows_with(values):
    return [(START + timedelta(days=i), float(v), 0.0) for i, v in enumerate(values)]


def readings_for(rows, dispersions):
    return {
        row[0]: rg.Feature(at=row[0], dispersion=float(d), breadth=20)
        for row, d in zip(rows, dispersions, strict=True)
    }


class TestTheProtocol:
    def test_the_threshold_comes_from_the_training_period_alone(self):
        """If the test period's dispersion were included, the split would have
        been chosen with knowledge of the data it is judged on."""
        rows = rows_with([0.1] * 1000)
        # Training dispersions 0..599 (median 300), test all far higher.
        dispersions = list(range(600)) + [10_000] * 400

        result = rg.test_dispersion_regime(rows, readings_for(rows, dispersions))

        assert result.threshold == 300
        assert result.test_low.instants == 0
        assert result.test_high.instants == 400

    def test_instants_with_no_reading_are_counted_not_quietly_dropped(self):
        rows = rows_with([0.1] * 1000)
        readings = readings_for(rows, [1.0] * 1000)
        for row in rows[:120]:
            del readings[row[0]]

        result = rg.test_dispersion_regime(rows, readings)

        assert result.unknown_instants == 120

    def test_too_few_instants_is_untestable_rather_than_a_verdict(self):
        rows = rows_with([0.5] * 100)

        result = rg.test_dispersion_regime(rows, readings_for(rows, [1.0] * 100))

        assert result.verdict == "UNTESTABLE"
        assert "fewer than" in result.notes[0]


class TestItCanSayNo:
    def test_a_regime_that_carries_nothing_is_not_confirmed(self):
        rng = random.Random(4)
        n = 2000
        rows = rows_with([rng.gauss(0.1, 1.0) for _ in range(n)])
        dispersions = [rng.random() for _ in range(n)]

        result = rg.test_dispersion_regime(rows, readings_for(rows, dispersions))

        assert result.verdict == "NOT_CONFIRMED_OUT_OF_SAMPLE"

    def test_a_regime_that_works_only_in_training_is_not_confirmed(self):
        """The failure this exists to catch."""
        rng = random.Random(4)
        n = 2000
        cut = int(n * rg.TRAIN_FRACTION)
        dispersions = [rng.random() for _ in range(n)]
        values = []
        for i, d in enumerate(dispersions):
            if i < cut:
                values.append(rng.gauss(0.8 if d >= 0.5 else -0.8, 0.5))
            else:
                values.append(rng.gauss(0.0, 0.5))
        rows = rows_with(values)

        result = rg.test_dispersion_regime(rows, readings_for(rows, dispersions))

        assert result.train_separation > 1.0
        assert result.verdict == "NOT_CONFIRMED_OUT_OF_SAMPLE"

    def test_a_separation_made_only_of_a_negative_low_half_is_not_a_filter(self):
        """High half no better than nothing, low half badly negative. The
        separation is real and the conclusion is "do not trade", not "trade
        the high half"."""
        rng = random.Random(4)
        n = 2000
        dispersions = [rng.random() for _ in range(n)]
        values = [rng.gauss(0.0 if d >= 0.5 else -0.9, 0.5) for d in dispersions]
        rows = rows_with(values)

        result = rg.test_dispersion_regime(rows, readings_for(rows, dispersions))

        assert result.test_separation > 0
        assert result.verdict == "NOT_CONFIRMED_OUT_OF_SAMPLE"

    def test_a_real_conditional_edge_is_confirmed(self):
        rng = random.Random(4)
        n = 2000
        dispersions = [rng.random() for _ in range(n)]
        values = [rng.gauss(0.6 if d >= 0.5 else 0.0, 0.5) for d in dispersions]
        rows = rows_with(values)

        result = rg.test_dispersion_regime(rows, readings_for(rows, dispersions))

        assert result.verdict == "CONFIRMED_OUT_OF_SAMPLE"
        assert result.test_high.edge_r > result.test_low.edge_r


class TestTheFeatureIsTheRulesOwnInput:
    def series(self, symbols: int, *, spread: float, bars: int = 80):
        """`spread` scales how differently the instruments move."""
        out = {}
        for s in range(symbols):
            price = 1.0 + s * spread * 0.01
            rows_ = []
            for i in range(bars):
                drift = (s - symbols / 2) * spread * 0.0005 * i
                close = price + drift + (i % 3) * 0.0001
                rows_.append(
                    Bar(
                        at=START + timedelta(days=i),
                        open=close,
                        high=close + 0.002,
                        low=close - 0.002,
                        close=close,
                    )
                )
            out[f"SYM{s:02d}"] = rows_
        return out

    def test_a_universe_that_moves_together_reads_lower_than_one_that_does_not(self):
        together = self.series(20, spread=0.0)
        apart = self.series(20, spread=1.0)
        at = START + timedelta(days=79)
        universe = frozenset(together)

        low = rg.features(together, [at], universe=universe)
        high = rg.features(apart, [at], universe=universe)

        assert low[at].dispersion < high[at].dispersion

    def test_a_thin_cross_section_gets_no_reading_rather_than_a_made_up_one(self):
        thin = self.series(4, spread=1.0)
        at = START + timedelta(days=79)

        assert rg.features(thin, [at], universe=frozenset(thin)) == {}

    def test_the_reading_uses_only_bars_up_to_the_instant(self):
        """Point in time, like the measurement. A reading that saw the future
        would decide the regime with the answer in hand."""
        full = self.series(20, spread=1.0, bars=200)
        early = START + timedelta(days=79)
        universe = frozenset(full)

        whole = rg.features(full, [early], universe=universe)[early]
        cut = {s: b[:80] for s, b in full.items()}
        truncated = rg.features(cut, [early], universe=universe)[early]

        assert whole.dispersion == pytest.approx(truncated.dispersion)
