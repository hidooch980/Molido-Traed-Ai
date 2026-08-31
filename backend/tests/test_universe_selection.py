"""Choosing instruments by evidence without choosing the answer too.

The universe was declared by hand and turned out to be the largest term
anybody had measured: the twenty-seven instruments the declaration added over
what the historical result was actually measured on move the number by 0.086 R,
four times the entire claimed edge.

The obvious fix is the dangerous one. Score every instrument, keep the winners,
and with forty-nine instruments and a coin roughly half look positive - so the
selection reproduces the coin's history exactly and calls it a universe.

Every test here is about the guard rather than the arithmetic: that selection
never sees the years it is judged on, that one good quarter cannot buy a place,
and that a filter which keeps everything says so.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from app.learning.measure import Bar, measure
from app.learning.universe_selection import (
    STABILITY_BLOCKS,
    STABILITY_REQUIRED,
    SUSPICIOUS_KEEP_RATE,
    TRAIN_FRACTION,
    InstrumentScore,
    SelectionResult,
    _cut,
    _span,
    score_instrument,
    select,
)

START = datetime(2024, 1, 1, tzinfo=UTC)


def bars(count: int, *, base: float = 100.0, drift: float = 0.1) -> list[Bar]:
    return [
        Bar(
            at=START + timedelta(days=index),
            open=base + index * drift,
            high=base + index * drift + 1.0,
            low=base + index * drift - 1.0,
            close=base + index * drift + 0.5,
        )
        for index in range(count)
    ]


def series(symbols: list[str], count: int = 200) -> dict[str, list[Bar]]:
    return {
        symbol: bars(count, base=100.0 + index, drift=0.1 + index * 0.01)
        for index, symbol in enumerate(symbols)
    }


class TestSelectionNeverSeesWhatJudgesIt:
    """The whole method. The out-of-sample measurement is only a result
    because selection could not read it."""

    def test_the_split_falls_inside_the_series(self):
        data = series([f"SYM{i:02d}" for i in range(25)])

        result = select(
            data, bar_interval=timedelta(days=1), considered=frozenset(data)
        )

        span = _span(data)
        assert span is not None
        assert span[0] < result.split_at < span[1]

    def test_the_training_window_is_the_stated_fraction(self):
        data = series([f"SYM{i:02d}" for i in range(25)])
        span = _span(data)
        assert span is not None

        result = select(
            data, bar_interval=timedelta(days=1), considered=frozenset(data)
        )

        elapsed = (result.split_at - span[0]) / (span[1] - span[0])
        assert abs(elapsed - TRAIN_FRACTION) < 0.01

    def test_a_series_too_short_to_split_selects_nothing(self):
        """A universe chosen on everything is a universe nothing can judge."""
        data = {"EURUSD": bars(1)}

        result = select(
            data, bar_interval=timedelta(days=1), considered=frozenset(data)
        )

        assert result.selected == frozenset()
        assert any("nothing can judge" in note for note in result.warnings)

    def test_an_empty_series_selects_nothing_rather_than_raising(self):
        result = select(
            {}, bar_interval=timedelta(days=1), considered=frozenset({"EURUSD"})
        )

        assert result.selected == frozenset()
        assert result.out_of_sample is None


class TestTheGapIsReported:
    """The number selection cannot argue with."""

    def test_the_gap_is_none_without_both_measurements(self):
        result = SelectionResult(
            selected=frozenset(),
            considered=frozenset({"EURUSD"}),
            scores=[],
            in_sample=None,
            out_of_sample=None,
            split_at=None,
        )

        assert result.overfit_gap_r is None

    def test_the_payload_says_which_number_is_the_result(self):
        result = SelectionResult(
            selected=frozenset(),
            considered=frozenset(),
            scores=[],
            in_sample=None,
            out_of_sample=None,
            split_at=None,
        )

        assert "out-of-sample measurement is the result" in result.as_dict()["note"]


class TestStabilityIsRequiredNotJustProfit:
    """An instrument that carried the whole edge in one quarter and lost in
    the others is a story about that quarter."""

    def score(self, **over) -> InstrumentScore:
        base = dict(
            symbol="EURUSD",
            edge_r=0.05,
            instants=400,
            blocks_positive=STABILITY_REQUIRED,
            blocks_measured=STABILITY_BLOCKS,
        )
        base.update(over)
        return InstrumentScore(**base)

    def test_positive_and_stable_is_selected(self):
        assert self.score().selected is True

    def test_profitable_but_unstable_is_not(self):
        """One windfall quarter cannot buy a place."""
        assert self.score(blocks_positive=1).selected is False

    def test_stable_but_unprofitable_is_not(self):
        assert self.score(edge_r=-0.01).selected is False

    def test_a_flat_instrument_is_not_selected(self):
        """Zero is not positive, and the rule has to earn its place."""
        assert self.score(edge_r=0.0).selected is False

    def test_too_little_history_cannot_answer_and_is_not_selected(self):
        assert self.score(blocks_measured=2, blocks_positive=2).stable is False

    def test_perfection_is_not_demanded(self):
        """Requiring every block selects for luck as surely as requiring
        none, because no real instrument is positive every quarter."""
        assert STABILITY_REQUIRED < STABILITY_BLOCKS

    def test_a_majority_is_demanded(self):
        assert STABILITY_REQUIRED > STABILITY_BLOCKS / 2


class TestAFilterThatKeepsEverythingSaysSo:
    def test_the_keep_rate_is_reported(self):
        result = SelectionResult(
            selected=frozenset({"A", "B"}),
            considered=frozenset({"A", "B", "C", "D"}),
            scores=[],
            in_sample=None,
            out_of_sample=None,
            split_at=None,
        )

        assert result.keep_rate == 0.5

    def test_keeping_nothing_from_nothing_is_zero_not_a_crash(self):
        result = SelectionResult(
            selected=frozenset(),
            considered=frozenset(),
            scores=[],
            in_sample=None,
            out_of_sample=None,
            split_at=None,
        )

        assert result.keep_rate == 0.0

    def test_the_suspicious_threshold_is_below_everything(self):
        """A filter keeping all of what it was given is not selecting."""
        assert SUSPICIOUS_KEEP_RATE < 1.0


class TestCuttingTheSeries:
    def test_before_keeps_only_earlier_bars(self):
        data = {"EURUSD": bars(10)}
        cut = _cut(data, before=START + timedelta(days=4))

        assert len(cut["EURUSD"]) == 4

    def test_after_is_inclusive_of_the_boundary(self):
        """The two halves must partition the series rather than overlap or
        drop the bar on the line."""
        data = {"EURUSD": bars(10)}
        split = START + timedelta(days=4)

        early = _cut(data, before=split)
        late = _cut(data, after=split)

        assert len(early["EURUSD"]) + len(late["EURUSD"]) == 10

    def test_an_instrument_with_nothing_left_is_dropped(self):
        """Rather than kept as an empty list, which every downstream reader
        would then have to remember to check."""
        data = {"EURUSD": bars(10)}

        assert _cut(data, before=START) == {}

    def test_the_span_of_nothing_is_none(self):
        assert _span({}) is None


class TestAnInstrumentIsScoredInsideTheCrossSection:
    """Scoring one instrument by narrowing the *ranking* to it leaves a
    cross-section of one, which `rank` refuses as too thin. Every instant is
    then skipped, `instants` comes back 0 and `edge_r` 0.0 - and `selected`,
    which asks for `edge_r > 0`, reads that as "not good enough" rather than
    "never measured". Nothing was ever selected and nothing said so.

    So the ranking stays wide and the count goes narrow.
    """

    SYMBOLS = [f"S{index:02d}" for index in range(25)]
    INTERVAL = timedelta(days=1)

    #: Long enough that each of the four sub-periods clears `min_history` on
    #: its own. A block is cut before it is measured, so the 80 bars of
    #: history every instant needs have to fit *inside* the block - 200 bars
    #: split four ways gives 50, and the sub-period count comes back 0.
    BARS = 600

    def data(self) -> dict[str, list[Bar]]:
        return series(self.SYMBOLS, count=self.BARS)

    def test_the_instrument_is_actually_measured(self):
        score = score_instrument(
            self.data(),
            "S00",
            bar_interval=self.INTERVAL,
            universe=frozenset(self.SYMBOLS),
        )

        assert score.instants > 0

    def test_narrowing_the_ranking_instead_measures_nothing(self):
        """The defect, stated as the arithmetic it produced. A cross-section
        of one is below the minimum, so no instant is ever ranked."""
        alone = measure(
            self.data(),
            bar_interval=self.INTERVAL,
            universe=frozenset({"S00"}),
        )

        assert alone.instants == 0
        assert alone.edge_r == 0.0

    def test_only_the_named_instrument_is_counted(self):
        """Wide ranking, narrow count. Counting the whole basket would give
        every instrument the same number, which ranks nothing."""
        data = self.data()
        universe = frozenset(self.SYMBOLS)

        basket = measure(data, bar_interval=self.INTERVAL, universe=universe)
        mine = measure(
            data,
            bar_interval=self.INTERVAL,
            universe=universe,
            only=frozenset({"S00"}),
        )

        assert 0 < mine.trades < basket.trades

    def test_the_sub_periods_are_measured_the_same_way(self):
        """A block scored against a cross-section of one is the same zero,
        and `stable` would then refuse every instrument for having too little
        history rather than for being inconsistent."""
        score = score_instrument(
            self.data(),
            "S00",
            bar_interval=self.INTERVAL,
            universe=frozenset(self.SYMBOLS),
        )

        assert score.blocks_measured > 0


class TestTheCommand:
    """`python -m app.learning.universe_selection` - runnable by anybody,
    like `measure`, and for the same reason: a selection nobody can re-run
    is a selection nobody can check."""

    def run(self, argv, session, monkeypatch, series):
        from contextlib import contextmanager

        from app.learning import measure as measure_module
        from app.learning import universe_selection

        @contextmanager
        def fixed_session():
            yield session

        monkeypatch.setattr(
            "app.db.session.session_scope", fixed_session, raising=False
        )
        monkeypatch.setattr(
            measure_module, "load_series", lambda *a, **k: series
        )
        return universe_selection.main(argv)

    def test_the_provider_is_required(self):
        import pytest

        from app.learning import universe_selection

        with pytest.raises(SystemExit):
            universe_selection.main(["--timeframe", "H1"])

    def test_an_empty_source_is_named_not_a_selection_of_zero(
        self, session, monkeypatch, capsys
    ):
        code = self.run(
            ["--provider", "not-a-provider"], session, monkeypatch, {}
        )

        assert code == 1
        assert "not a selection of zero" in capsys.readouterr().out

    def test_symbols_outside_the_ranking_universe_are_not_silently_considered(
        self, session, monkeypatch, capsys
    ):
        stored = {"NOTAPAIR": bars(10)}

        code = self.run(
            ["--provider", "csv"], session, monkeypatch, stored
        )

        assert code == 1
        assert "do not overlap" in capsys.readouterr().out

    def test_a_selection_of_nothing_is_reported_as_a_result(
        self, session, monkeypatch, capsys
    ):
        """Too few instruments to ever rank selects nothing - and that is a
        result about the rule, printed, exit code zero."""
        stored = series([f"SYM{i:02d}" for i in range(5)], count=60)

        code = self.run(
            ["--provider", "csv", "--considered", "all"],
            session,
            monkeypatch,
            stored,
        )

        out = capsys.readouterr().out
        assert code == 0
        assert "Nothing was selected" in out
        assert "considering 5 instruments" in out
