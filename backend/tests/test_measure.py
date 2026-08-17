"""Reproducing the number the whole project turns on.

+0.0212 R at t = 3.69 came from a script that no longer exists. That is the
gap this module closes: a result nobody can re-run is a result nobody can
check, including whoever produced it.

So these tests are not about the rule being right. They are about the harness
being the same harness - same geometry, same resolution, same clustering as
the live loop - because a historical measurement scored under its own copy of
those is not a comparison with the forward series, it is a second unrelated
measurement wearing the same name.
"""

from __future__ import annotations

import pathlib
from datetime import UTC, datetime, timedelta

import pytest

from app.brain import crosssection
from app.learning import measure
from app.learning.measure import Bar

START = datetime(2020, 1, 1, tzinfo=UTC)
UNIVERSE = sorted(crosssection.RANKED_UNIVERSE)


def walk(prices: list[float], *, spread: float = 0.5) -> list[Bar]:
    """Bars from a list of closes, one hour apart."""
    return [
        Bar(
            at=START + timedelta(hours=i),
            open=p,
            high=p + spread,
            low=p - spread,
            close=p,
        )
        for i, p in enumerate(prices)
    ]


def flat_market(n: int = 30, bars: int = 300) -> dict[str, list[Bar]]:
    """Thirty instruments that go nowhere. No edge exists to be found."""
    return {UNIVERSE[i]: walk([100.0] * bars) for i in range(n)}


class TestItSharesTheLiveGeometry:
    """Copying any constant here to keep the module self-contained would break
    the only property that makes the historical and forward numbers
    comparable."""

    def test_the_stop_and_target_come_from_the_live_recorder(self):
        from app.workers import forward

        assert measure.STOP_MULTIPLE is forward.STOP_MULTIPLE
        assert measure.TARGET_MULTIPLE is forward.TARGET_MULTIPLE

    def test_the_horizon_comes_from_the_live_resolver(self):
        from app.workers import resolve

        assert measure.HORIZON is resolve.HORIZON

    def test_the_geometry_travels_with_the_result(self):
        """So a number read back later can be identified rather than assumed
        to have used whatever the constants say today."""
        described = measure.measure(
            flat_market(), bar_interval=timedelta(hours=1)
        ).as_dict()

        assert described["geometry"]["stop_multiple"] == measure.STOP_MULTIPLE
        assert described["geometry"]["horizon_bars"] == measure.HORIZON

    def test_it_resolves_with_the_live_resolver_itself(self):
        """Not a copy of it. Two resolvers that agree today and are edited
        separately do not stay agreeing."""
        from app.workers import resolve

        assert measure._outcome is resolve._outcome


class TestClusteringIsTheWholeResult:
    """Counting trades instead of instants inflated the original daily figure
    from -0.12 to 3.95 - a factor of thirty-two, in the direction that
    manufactures a discovery."""

    def test_both_figures_are_published(self):
        result = measure.measure(trending_market(), bar_interval=timedelta(hours=1))
        described = result.as_dict()

        assert "t" in described
        assert "unclustered_t" in described
        assert "clustering_inflation" in described

    def test_an_instant_contributes_one_observation_not_eight(self):
        """The rule opens both tails at every instant, so trades outnumber
        instants several times over. If they were equal, nothing is being
        clustered."""
        result = measure.measure(trending_market(), bar_interval=timedelta(hours=1))

        assert result.instants > 0
        assert result.trades > result.instants

    def test_the_reason_is_carried_with_the_numbers(self):
        described = measure.measure(
            flat_market(), bar_interval=timedelta(hours=1)
        ).as_dict()

        assert "one instant is one observation" in described["note"]


def trending_market(n: int = 30, bars: int = 300) -> dict[str, list[Bar]]:
    """Instruments drifting at different rates, so the ranking has work to do
    and trades actually resolve."""
    built = {}
    for i in range(n):
        drift = (i - n / 2) * 0.02
        closes = [100.0 + drift * step + (step % 7) * 0.3 for step in range(bars)]
        built[UNIVERSE[i]] = walk(closes)
    return built


class TestPointInTimeIntegrity:
    def test_a_short_series_produces_nothing_rather_than_a_guess(self):
        """Fewer bars than the lookback means no instrument can be ranked."""
        short = {UNIVERSE[i]: walk([100.0] * 40) for i in range(30)}

        assert measure.measure(short, bar_interval=timedelta(hours=1)).instants == 0

    def test_a_thin_cross_section_produces_nothing(self):
        """Eight instruments always have a most-extended member."""
        thin = {UNIVERSE[i]: walk([100.0 + i] * 300) for i in range(8)}

        assert measure.measure(thin, bar_interval=timedelta(hours=1)).instants == 0

    def test_the_window_is_reported(self):
        result = measure.measure(trending_market(), bar_interval=timedelta(hours=1))

        assert result.window is not None
        assert result.window[0] == START


class TestBothArmsOrNeither:
    def test_an_undecided_pair_is_dropped_whole(self):
        """Keeping one side of a pair whose partner never resolved is a bias,
        and it favours the arm whose geometry the ranking chose - the rule."""
        result = measure.measure(flat_market(), bar_interval=timedelta(hours=1))

        # A flat market never reaches a stop or a target, so every pair is
        # undecided and none is scored.
        assert result.trades == 0
        assert result.dropped_undecided > 0

    def test_a_market_that_resolves_scores_both_arms(self):
        result = measure.measure(trending_market(), bar_interval=timedelta(hours=1))

        assert result.trades > 0
        # Both arms saw the same instants, so neither can be empty while the
        # other is populated.
        assert result.rule_r != 0.0 or result.control_r != 0.0


class TestTheArithmetic:
    def test_no_edge_is_reported_as_no_edge(self):
        """An empty measurement is not a measurement of zero, but a market
        with nothing in it must not produce a significant result either."""
        result = measure.measure(flat_market(), bar_interval=timedelta(hours=1))

        assert result.significant is False
        assert result.t_statistic == 0.0

    def test_the_cost_is_charged_to_the_edge_not_to_one_arm(self):
        """Charging the rule and not the control invents an edge worth exactly
        the cost."""
        result = measure.measure(trending_market(), bar_interval=timedelta(hours=1))

        assert result.net_r == pytest.approx(result.edge_r - measure.COST_R)

    def test_significance_needs_1_96(self):
        from dataclasses import replace

        result = measure.measure(trending_market(), bar_interval=timedelta(hours=1))

        assert replace(result, t_statistic=1.95).significant is False
        assert replace(result, t_statistic=1.97).significant is True
        # Both directions: a strongly negative result is a finding too.
        assert replace(result, t_statistic=-3.0).significant is True

    def test_a_paired_t_of_one_sample_is_zero_not_infinite(self):
        assert measure._paired_t([0.5]) == (0.0, 0.0)

    def test_a_zero_spread_is_zero_not_a_division(self):
        """Identical differences have no spread, and dividing by it would
        report infinite significance on a sample that shows nothing."""
        assert measure._paired_t([0.5, 0.5, 0.5]) == (0.0, 0.0)


class TestTheUniverseIsRespected:
    def test_an_instrument_outside_it_is_not_traded(self):
        market = trending_market()
        market["NOTINUNIVERSE"] = walk([100.0 + i * 0.5 for i in range(300)])

        with_extra = measure.measure(market, bar_interval=timedelta(hours=1))
        without = measure.measure(
            trending_market(), bar_interval=timedelta(hours=1)
        )

        assert with_extra.trades == without.trades

    def test_passing_none_ranks_everything(self):
        """A caller running an explicit experiment across a different universe
        may say so; the default is the measured one.

        Checked on the dropped count rather than on instants: these symbols
        oscillate inside their own stop distance, so the rule ranks them and
        nothing ever resolves. That is the honest signal that the ranking ran
        - `instants` counts only instants that produced a scored pair.
        """
        market = {
            f"MADEUP{i}": walk(
                [100.0 + i * 0.4 + (step % 7) * 0.3 for step in range(300)]
            )
            for i in range(30)
        }

        ranked_all = measure.measure(
            market, bar_interval=timedelta(hours=1), universe=None
        )
        ranked_none = measure.measure(market, bar_interval=timedelta(hours=1))

        assert ranked_all.dropped_undecided > 0
        assert ranked_none.dropped_undecided == 0
        assert ranked_none.instants == 0


class TestLoadingAStoredSeries:
    """One provider, never a merge. The broker and the public feed differ by
    33-39% of a stop distance on every major pair, so a series assembled from
    whichever source happened to hold each bar measures the assembly."""

    def stored(self, session, provider, symbol, prices, timeframe=None):
        from app.core.enums import AssetClass, Timeframe
        from app.models.instruments import Instrument
        from app.models.market_data import Bar as StoredBar

        timeframe = timeframe or Timeframe.H1
        row = session.scalar(
            __import__("sqlalchemy").select(Instrument).where(
                Instrument.symbol == symbol
            )
        )
        if row is None:
            row = Instrument(symbol=symbol, name=symbol, asset_class=AssetClass.FOREX)
            session.add(row)
            session.flush()
        for i, price in enumerate(prices):
            session.add(
                StoredBar(
                    instrument_id=row.id,
                    timeframe=timeframe.value,
                    provider_id=provider.id,
                    event_time=START + timedelta(hours=i),
                    revision=1,
                    ingested_at=START,
                    open=price,
                    high=price + 0.5,
                    low=price - 0.5,
                    close=price,
                    volume=1.0,
                    quality_score=1.0,
                )
            )
        session.flush()
        return row

    def test_it_reads_one_provider_only(self, session, provider):
        from app.core.enums import Timeframe
        from app.models.instruments import Provider

        other = Provider(code="somewhere-else", name="Other", capabilities={})
        session.add(other)
        session.flush()

        self.stored(session, provider, "EURUSD", [1.10, 1.11, 1.12])
        self.stored(session, other, "GBPUSD", [1.27, 1.28, 1.29])

        loaded = measure.load_series(
            session, provider_code=provider.code, timeframe=Timeframe.H1
        )

        assert set(loaded) == {"EURUSD"}

    def test_an_unknown_provider_returns_nothing_rather_than_everything(
        self, session, provider
    ):
        """The failure mode worth naming: a typo in the provider code that
        silently measured the whole database would look like a successful run
        across a series nobody chose."""
        from app.core.enums import Timeframe

        self.stored(session, provider, "EURUSD", [1.10, 1.11])

        assert measure.load_series(
            session, provider_code="not-a-provider", timeframe=Timeframe.H1
        ) == {}

    def test_the_bars_come_back_ascending(self, session, provider):
        from app.core.enums import Timeframe

        self.stored(session, provider, "EURUSD", [1.10, 1.11, 1.12, 1.13])

        bars = measure.load_series(
            session, provider_code=provider.code, timeframe=Timeframe.H1
        )["EURUSD"]

        assert [b.at for b in bars] == sorted(b.at for b in bars)
        assert [b.close for b in bars] == [1.10, 1.11, 1.12, 1.13]

    def test_the_window_is_honoured(self, session, provider):
        from app.core.enums import Timeframe

        self.stored(session, provider, "EURUSD", [1.10, 1.11, 1.12, 1.13])

        bars = measure.load_series(
            session,
            provider_code=provider.code,
            timeframe=Timeframe.H1,
            start=START + timedelta(hours=1),
            end=START + timedelta(hours=3),
        )["EURUSD"]

        assert len(bars) == 2

    def test_a_different_timeframe_is_not_mixed_in(self, session, provider):
        from app.core.enums import Timeframe

        self.stored(session, provider, "EURUSD", [1.10, 1.11])
        self.stored(session, provider, "EURUSD", [9.0, 9.1], timeframe=Timeframe.D1)

        bars = measure.load_series(
            session, provider_code=provider.code, timeframe=Timeframe.H1
        )["EURUSD"]

        assert [b.close for b in bars] == [1.10, 1.11]


class TestTheCommand:
    """The original result came from a script nobody can find, so the way to
    get this number has to be something anybody can type and re-type."""

    def test_the_provider_is_required_and_has_no_default(self):
        """A measurement whose source was implicit is one whose source will be
        misremembered, and the three sources here disagree by more than the
        effect being looked for."""
        with pytest.raises(SystemExit):
            measure.main(["--timeframe", "H1"])

    def test_an_empty_source_is_named_not_reported_as_zero(
        self, session, monkeypatch, capsys
    ):
        """"No bars for that provider" and "the rule found nothing" are
        different facts, and a table of zeros for the first reads as the
        second."""
        from contextlib import contextmanager

        @contextmanager
        def fixed_session():
            yield session

        monkeypatch.setattr(
            "app.db.session.session_scope", fixed_session, raising=False
        )

        code = measure.main(["--provider", "not-a-provider"])

        assert code == 1
        assert "not a result of zero" in capsys.readouterr().out

    def test_a_negative_result_is_stated_as_plainly_as_a_positive_one(self):
        """A negative reported quietly and a positive reported loudly is how a
        registry fills up with edges that are not there."""
        source = pathlib.Path(measure.__file__).read_text(encoding="utf-8")

        assert "lost to" in source
        assert "beat" in source
        assert "whichever" in source


class TestResearchYieldsToTheServingPath:
    """Running a measurement over 604,000 bars on the production box took the
    one core the serving stack had left, and sshd and caddy stopped being
    scheduled long enough that the machine looked dead from outside for half an
    hour. Nothing ran out of memory: the kernel logged zero OOM kills and the
    box has no swap. Nothing else simply got a timeslice."""

    def test_the_command_drops_priority_before_doing_anything(self):
        calls: list[int] = []
        import os

        if not hasattr(os, "nice"):
            pytest.skip("no nice() on this platform")

        original = os.nice
        try:
            os.nice = lambda value: calls.append(value)  # type: ignore[assignment]
            measure._yield_to_the_serving_path()
        finally:
            os.nice = original  # type: ignore[assignment]

        assert calls == [19]

    def test_a_platform_without_nice_is_not_an_error(self, monkeypatch):
        """It is a courtesy to co-tenants, not a correctness requirement, and
        a research command that refuses to start on Windows helps nobody."""
        import os

        monkeypatch.delattr(os, "nice", raising=False)

        measure._yield_to_the_serving_path()

    def test_a_container_that_forbids_it_is_not_an_error(self, monkeypatch):
        import os

        if not hasattr(os, "nice"):
            pytest.skip("no nice() on this platform")

        def refuse(_value):
            raise PermissionError("not permitted")

        monkeypatch.setattr(os, "nice", refuse)

        measure._yield_to_the_serving_path()


class TestTheCostIsMeasuredNotAssumed:
    """A constant cost is the wrong shape. R is defined by the stop distance,
    so what the spread costs in R falls out of that distance - which is why a
    shorter timeframe is dearer without anybody re-estimating anything."""

    SPREAD = 0.00014  # live EURUSD, measured off the terminal

    def test_a_tighter_stop_costs_more_in_r(self):
        wide = measure.cost_in_r(self.SPREAD, 0.00225)   # H1 geometry
        tight = measure.cost_in_r(self.SPREAD, 0.00027)  # M1 geometry

        assert tight > wide
        assert round(wide, 4) == 0.0622
        assert round(tight, 4) == 0.5185

    def test_the_ratio_tracks_the_stop_and_nothing_else(self):
        """Halve the stop, double the cost. Nothing else may move it."""
        assert measure.cost_in_r(self.SPREAD, 0.001) == pytest.approx(
            2 * measure.cost_in_r(self.SPREAD, 0.002)
        )

    def test_a_zero_stop_raises_rather_than_defaulting(self):
        """R is undefined without a stop, and a cost against an undefined R is
        a number with no meaning that would go on to be subtracted from an edge."""
        with pytest.raises(ValueError, match="positive stop distance"):
            measure.cost_in_r(self.SPREAD, 0.0)

    def test_a_negative_spread_raises(self):
        with pytest.raises(ValueError, match="cannot be negative"):
            measure.cost_in_r(-0.0001, 0.002)

    def test_a_zero_spread_is_free_rather_than_an_error(self):
        """Zero is a real spread on some instruments, unlike a zero stop."""
        assert measure.cost_in_r(0.0, 0.002) == 0.0

    def test_the_old_constant_understated_the_real_h1_cost(self):
        """The registry charged 0.01 R. On this deployment's own spread and
        stop geometry the H1 cost is six times that, and it is subtracted from
        an edge of 0.0212 R - so the gap decides the answer, not the rounding."""
        real = measure.cost_in_r(self.SPREAD, 0.00225)

        assert real > measure.COST_R * 5
