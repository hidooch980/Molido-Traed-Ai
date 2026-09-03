"""Nine thousand rows read to write nothing, ninety-three times a cycle.

The log said it plainly: `bars 412, written 0, skipped 9064`. Every cycle the
materialiser read every existing feature key across the whole requested range
to discover that all of them were already written. Postgres sat at 58% of a
core doing it and the collect cycle grew from ten minutes to forty-five,
which pushed the decision-to-order delay toward the ninety-minute staleness
limit - at which point orders start being refused for age rather than for
judgement.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from app.core.enums import Timeframe
from app.services import feature_store

START = datetime(2026, 9, 1, tzinfo=UTC)
END = datetime(2026, 9, 3, tzinfo=UTC)


class Spec:
    """The two fields the watermark cares about."""

    def __init__(self, name: str, version: int = 1):
        self.name = name
        self.version = version


class FakeSession:
    """Answers one grouped max() query with whatever the test supplies."""

    def __init__(self, rows):
        self.rows = rows
        self.queries = 0

    def execute(self, _statement):
        self.queries += 1
        return self

    def all(self):
        return self.rows


def through(rows, specs):
    return feature_store._materialised_through(
        FakeSession(rows), "instrument", Timeframe.H1, specs, START, END
    )


class TestTheWatermark:
    def test_it_is_the_earliest_point_every_spec_has_reached(self):
        """The minimum of each spec's own maximum, not the maximum of all of
        them - a spec that lags is the one that decides where work resumes."""
        rows = [
            ("atr", 1, datetime(2026, 9, 2, 10, tzinfo=UTC)),
            ("rsi", 1, datetime(2026, 9, 2, 8, tzinfo=UTC)),
        ]

        assert through(rows, [Spec("atr"), Spec("rsi")]) == datetime(2026, 9, 2, 8, tzinfo=UTC)

    def test_a_newly_added_indicator_forces_the_full_pass(self):
        """This is the case a plain max() gets silently wrong: the new spec
        has no history, and skipping to the others' watermark would leave it
        permanently empty."""
        rows = [("atr", 1, datetime(2026, 9, 2, 10, tzinfo=UTC))]

        assert through(rows, [Spec("atr"), Spec("brand-new")]) is None

    def test_a_version_bump_forces_the_full_pass(self):
        """A feature is a pure function of the bars *and the version*. Rows
        written under version 1 say nothing about version 2."""
        rows = [("atr", 1, datetime(2026, 9, 2, 10, tzinfo=UTC))]

        assert through(rows, [Spec("atr", version=2)]) is None

    def test_nothing_materialised_at_all_is_the_full_pass(self):
        assert through([], [Spec("atr")]) is None

    def test_one_spec_asked_for_and_one_present_is_the_simple_case(self):
        rows = [("atr", 1, datetime(2026, 9, 2, 10, tzinfo=UTC))]

        assert through(rows, [Spec("atr")]) == datetime(2026, 9, 2, 10, tzinfo=UTC)


class TestTheCallSite:
    def test_it_resumes_one_bar_after_the_watermark(self):
        """Not at the watermark, which is already written, and not two bars
        after, which would leave a hole nothing ever fills."""
        import inspect

        source = inspect.getsource(feature_store.materialize)

        assert "resumed = through + timeframe.delta" in source

    def test_it_never_moves_the_start_past_the_end(self):
        import inspect

        source = inspect.getsource(feature_store.materialize)

        assert "if start < resumed < end:" in source

    def test_recompute_still_does_the_whole_range(self):
        """`recompute` exists to rebuild history after a formula changes. A
        watermark that applied to it would make it silently a no-op."""
        import inspect

        source = inspect.getsource(feature_store.materialize)
        guard = source.index("if not recompute:")
        watermark = source.index("_materialised_through(")

        assert guard < watermark
