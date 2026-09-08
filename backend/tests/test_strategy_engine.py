"""The four declared strategies, which nothing imported directly.

`app.brain.strategy` sat at 68% coverage earned entirely by other modules
running through it. That is enough to prove it does not crash and nothing
more - and the two properties its docstring leads with are exactly the kind
that indirect coverage never checks:

**Regime-awareness is a refusal, not a discount.** A mean-reversion strategy
in a trend must return nothing, not a weaker signal. Every strategy below is
asked in every wrong regime, and the answer has to be a refusal that names
the regime it saw.

**A strategy fires or it does not.** There is no partial match. So the tests
sit on the boundaries - 40, 60, 0.85, 0.15, 65, 35 - because a threshold that
is not pinned is a threshold that erodes.

The third thing worth testing is that missing evidence is not absent
evidence: a feature block that is unavailable must not read as a feature
whose value happens to be zero.
"""

from __future__ import annotations

import pytest

from app.brain import strategy as engine
from app.core.enums import Decision, Regime

EVERY_REGIME = [r.value for r in Regime]


def world(
    regime: str,
    *,
    features: dict | None = None,
    available: bool = True,
    memory: dict | None = None,
) -> dict:
    state: dict = {
        "regime": {"regime": regime},
        "features": {"available": available, "values": features or {}},
    }
    if memory is not None:
        state["memory"] = memory
    return state


def short_horizon(trend: str | None, *, available: bool = True) -> dict:
    return {"horizons": {"short": {"available": available, "trend": trend}}}


class TestTheRegistry:
    def test_all_four_strategies_are_registered(self):
        assert engine.names() == [
            "breakout_continuation",
            "range_fade",
            "trend_pullback",
            "volatility_stand_aside",
        ]

    def test_names_are_sorted(self):
        assert engine.names() == sorted(engine.names())

    def test_evaluate_runs_every_registered_strategy(self):
        assert len(engine.evaluate(world(Regime.RANGE.value))) == len(engine.names())

    def test_evaluate_returns_them_in_registry_order(self):
        setups = engine.evaluate(world(Regime.RANGE.value))

        assert [s.strategy for s in setups] == engine.names()

    def test_the_decorator_returns_the_function_unchanged(self):
        def probe(state):
            return engine.Setup("probe", "test", False)

        assert engine.strategy("probe_temp")(probe) is probe
        engine._REGISTRY.pop("probe_temp", None)

    def test_fired_is_a_subset_of_evaluate(self):
        state = world(Regime.UNCERTAIN.value)

        assert set(s.strategy for s in engine.fired(state)) <= set(
            s.strategy for s in engine.evaluate(state)
        )

    def test_fired_returns_only_setups_that_fired(self):
        state = world(Regime.HIGH_VOLATILITY.value)

        assert all(s.fired for s in engine.fired(state))

    def test_every_setup_declares_the_declared_origin(self):
        # Research-proposed strategies will carry a different origin and be
        # tracked separately; today every one of these is declared.
        assert all(s.origin == "declared" for s in engine.evaluate(world("range")))


class TestSetupSerialises:
    def test_it_reports_the_direction_as_a_value_not_an_enum(self):
        body = engine.Setup("s", "f", True, direction=Decision.BUY).as_dict()

        assert body["direction"] == "buy"

    def test_a_setup_that_did_not_fire_waits_by_default(self):
        assert engine.Setup("s", "f", False).direction is Decision.WAIT

    def test_every_declared_field_is_serialised(self):
        body = engine.Setup("s", "f", True).as_dict()

        assert set(body) == {
            "strategy",
            "family",
            "fired",
            "direction",
            "reason",
            "conditions_met",
            "conditions_failed",
            "suitable_regimes",
            "origin",
            "version",
        }

    def test_condition_lists_are_not_shared_between_setups(self):
        first = engine.Setup("a", "f", False)
        second = engine.Setup("b", "f", False)

        first.conditions_met.append("x")

        assert second.conditions_met == []


class TestRegimeIsARefusalNotADiscount:
    @pytest.mark.parametrize(
        "name,suitable",
        [
            ("trend_pullback", {"trend_up", "trend_down"}),
            ("range_fade", {"range"}),
            ("breakout_continuation", {"breakout"}),
            ("volatility_stand_aside", {"high_volatility", "uncertain"}),
        ],
    )
    def test_it_refuses_in_every_regime_it_does_not_declare(self, name, suitable):
        for regime in EVERY_REGIME:
            if regime in suitable:
                continue
            setup = engine._REGISTRY[name](world(regime, features={"rsi_14": 50}))
            assert setup.fired is False, f"{name} fired in {regime}"

    @pytest.mark.parametrize(
        "name", ["trend_pullback", "range_fade", "breakout_continuation"]
    )
    def test_a_refusal_names_the_regime_it_saw(self, name):
        setup = engine._REGISTRY[name](world(Regime.REVERSAL.value))

        assert "reversal" in setup.reason

    @pytest.mark.parametrize(
        "name", ["trend_pullback", "range_fade", "breakout_continuation"]
    )
    def test_a_refusal_lists_the_regimes_it_would_accept(self, name):
        setup = engine._REGISTRY[name](world(Regime.REVERSAL.value))

        assert setup.suitable_regimes

    @pytest.mark.parametrize(
        "name", ["trend_pullback", "range_fade", "breakout_continuation"]
    )
    def test_a_wrong_regime_waits_rather_than_leaning(self, name):
        # The discount this module refuses to apply: no weaker signal, no
        # direction, nothing downstream can weight back up.
        setup = engine._REGISTRY[name](world(Regime.REVERSAL.value))

        assert setup.direction is Decision.WAIT

    @pytest.mark.parametrize(
        "name", ["trend_pullback", "range_fade", "breakout_continuation"]
    )
    def test_a_wrong_regime_claims_no_conditions_met(self, name):
        setup = engine._REGISTRY[name](world(Regime.REVERSAL.value))

        assert setup.conditions_met == []

    def test_a_missing_regime_block_reads_as_uncertain(self):
        assert engine._regime({}) == Regime.UNCERTAIN.value

    def test_a_null_regime_block_reads_as_uncertain(self):
        assert engine._regime({"regime": None}) == Regime.UNCERTAIN.value

    def test_an_empty_regime_block_reads_as_uncertain(self):
        assert engine._regime({"regime": {}}) == Regime.UNCERTAIN.value

    def test_uncertain_is_where_stand_aside_fires(self):
        # Because the fallback is uncertain, a state with no regime at all
        # lands on the no-trade strategy rather than on a trading one.
        assert engine.volatility_stand_aside({}).fired is True


class TestFeaturesUnavailableIsNotFeaturesZero:
    def test_an_unavailable_block_yields_no_features(self):
        assert engine._features({"features": {"available": False, "values": {"rsi_14": 50}}}) == {}

    def test_a_missing_block_yields_no_features(self):
        assert engine._features({}) == {}

    def test_an_available_block_yields_its_values(self):
        assert engine._features(
            {"features": {"available": True, "values": {"rsi_14": 50}}}
        ) == {"rsi_14": 50}

    @pytest.mark.parametrize("name", ["trend_pullback", "range_fade"])
    def test_a_strategy_refuses_when_the_block_is_unavailable(self, name):
        regime = "trend_up" if name == "trend_pullback" else "range"
        setup = engine._REGISTRY[name](
            world(regime, features={"rsi_14": 50, "close_over_sma_20": 1.1,
                                    "position_in_range_20": 0.9}, available=False)
        )

        assert setup.fired is False
        assert "unavailable" in setup.reason


class TestTrendPullback:
    def test_it_fires_on_a_dip_inside_an_uptrend(self):
        setup = engine.trend_pullback(
            world("trend_up", features={"rsi_14": 50, "close_over_sma_20": 1.02})
        )

        assert setup.fired is True
        assert setup.direction is Decision.BUY

    def test_it_mirrors_for_a_downtrend(self):
        setup = engine.trend_pullback(
            world("trend_down", features={"rsi_14": 50, "close_over_sma_20": 0.98})
        )

        assert setup.fired is True
        assert setup.direction is Decision.SELL

    def test_it_belongs_to_the_trend_following_family(self):
        setup = engine.trend_pullback(world("trend_up", features={}))

        assert setup.family == "trend_following"

    @pytest.mark.parametrize("rsi", [40, 50, 60])
    def test_the_rsi_band_is_inclusive_at_both_ends(self, rsi):
        setup = engine.trend_pullback(
            world("trend_up", features={"rsi_14": rsi, "close_over_sma_20": 1.02})
        )

        assert setup.fired is True

    @pytest.mark.parametrize("rsi", [39.9, 60.1, 0, 100])
    def test_rsi_outside_the_band_does_not_fire(self, rsi):
        setup = engine.trend_pullback(
            world("trend_up", features={"rsi_14": rsi, "close_over_sma_20": 1.02})
        )

        assert setup.fired is False

    def test_price_exactly_at_the_average_is_not_above_it(self):
        setup = engine.trend_pullback(
            world("trend_up", features={"rsi_14": 50, "close_over_sma_20": 1.0})
        )

        assert setup.fired is False

    def test_price_exactly_at_the_average_is_not_below_it(self):
        setup = engine.trend_pullback(
            world("trend_down", features={"rsi_14": 50, "close_over_sma_20": 1.0})
        )

        assert setup.fired is False

    def test_price_below_the_average_in_an_uptrend_does_not_fire(self):
        setup = engine.trend_pullback(
            world("trend_up", features={"rsi_14": 50, "close_over_sma_20": 0.95})
        )

        assert setup.fired is False

    def test_a_failed_condition_is_recorded_by_name(self):
        setup = engine.trend_pullback(
            world("trend_up", features={"rsi_14": 90, "close_over_sma_20": 1.02})
        )

        assert "RSI pulled back into 40-60" in setup.conditions_failed

    def test_a_met_condition_is_recorded_even_when_the_setup_fails(self):
        setup = engine.trend_pullback(
            world("trend_up", features={"rsi_14": 90, "close_over_sma_20": 1.02})
        )

        assert "price above its 20-bar average" in setup.conditions_met

    def test_the_downtrend_wording_says_recovered(self):
        setup = engine.trend_pullback(
            world("trend_down", features={"rsi_14": 90, "close_over_sma_20": 0.98})
        )

        assert "RSI recovered into 40-60" in setup.conditions_failed

    def test_a_missing_rsi_refuses(self):
        setup = engine.trend_pullback(
            world("trend_up", features={"close_over_sma_20": 1.02})
        )

        assert setup.fired is False
        assert "unavailable" in setup.reason

    def test_a_missing_trend_position_refuses(self):
        setup = engine.trend_pullback(world("trend_up", features={"rsi_14": 50}))

        assert setup.fired is False
        assert "unavailable" in setup.reason

    def test_missing_evidence_claims_no_failed_conditions(self):
        # It could not check, which is not the same as checking and failing.
        setup = engine.trend_pullback(world("trend_up", features={}))

        assert setup.conditions_failed == []

    def test_a_setup_that_does_not_fire_waits(self):
        setup = engine.trend_pullback(
            world("trend_up", features={"rsi_14": 90, "close_over_sma_20": 1.02})
        )

        assert setup.direction is Decision.WAIT


class TestRangeFade:
    def test_it_fades_the_top_of_a_range(self):
        setup = engine.range_fade(
            world("range", features={"position_in_range_20": 0.9, "rsi_14": 70})
        )

        assert setup.fired is True
        assert setup.direction is Decision.SELL

    def test_it_fades_the_bottom_of_a_range(self):
        setup = engine.range_fade(
            world("range", features={"position_in_range_20": 0.1, "rsi_14": 30})
        )

        assert setup.fired is True
        assert setup.direction is Decision.BUY

    def test_it_belongs_to_the_mean_reversion_family(self):
        setup = engine.range_fade(world("range", features={}))

        assert setup.family == "mean_reversion"

    def test_the_top_boundary_is_inclusive(self):
        setup = engine.range_fade(
            world("range", features={"position_in_range_20": 0.85, "rsi_14": 70})
        )

        assert setup.fired is True

    def test_the_bottom_boundary_is_inclusive(self):
        setup = engine.range_fade(
            world("range", features={"position_in_range_20": 0.15, "rsi_14": 30})
        )

        assert setup.fired is True

    @pytest.mark.parametrize("position", [0.16, 0.5, 0.84])
    def test_the_middle_of_a_range_is_not_an_extreme(self, position):
        setup = engine.range_fade(
            world("range", features={"position_in_range_20": position, "rsi_14": 70})
        )

        assert setup.fired is False
        assert "price is not at a range extreme" in setup.conditions_failed

    def test_the_top_needs_rsi_confirmation(self):
        setup = engine.range_fade(
            world("range", features={"position_in_range_20": 0.9, "rsi_14": 64})
        )

        assert setup.fired is False

    def test_the_top_rsi_boundary_is_inclusive(self):
        setup = engine.range_fade(
            world("range", features={"position_in_range_20": 0.9, "rsi_14": 65})
        )

        assert setup.fired is True

    def test_the_bottom_needs_rsi_confirmation(self):
        setup = engine.range_fade(
            world("range", features={"position_in_range_20": 0.1, "rsi_14": 36})
        )

        assert setup.fired is False

    def test_the_bottom_rsi_boundary_is_inclusive(self):
        setup = engine.range_fade(
            world("range", features={"position_in_range_20": 0.1, "rsi_14": 35})
        )

        assert setup.fired is True

    def test_the_extreme_is_reported_as_a_percentage(self):
        setup = engine.range_fade(
            world("range", features={"position_in_range_20": 0.9, "rsi_14": 70})
        )

        assert "90%" in setup.conditions_met[0]

    def test_an_unconfirmed_extreme_still_records_the_extreme(self):
        setup = engine.range_fade(
            world("range", features={"position_in_range_20": 0.9, "rsi_14": 50})
        )

        assert any("top of its range" in c for c in setup.conditions_met)
        assert "RSI confirms the extreme" in setup.conditions_failed

    def test_a_missing_position_refuses(self):
        setup = engine.range_fade(world("range", features={"rsi_14": 70}))

        assert setup.fired is False
        assert "unavailable" in setup.reason

    def test_a_missing_rsi_refuses(self):
        setup = engine.range_fade(
            world("range", features={"position_in_range_20": 0.9})
        )

        assert setup.fired is False

    def test_a_position_of_zero_is_still_a_position(self):
        # 0.0 is falsy and is a real reading: the bottom of the range.
        setup = engine.range_fade(
            world("range", features={"position_in_range_20": 0.0, "rsi_14": 30})
        )

        assert setup.fired is True
        assert setup.direction is Decision.BUY


class TestBreakoutContinuation:
    def test_it_joins_an_upward_breakout(self):
        setup = engine.breakout_continuation(
            world("breakout", features={"position_in_range_20": 0.95},
                  memory=short_horizon("up"))
        )

        assert setup.fired is True
        assert setup.direction is Decision.BUY

    def test_it_joins_a_downward_breakout(self):
        setup = engine.breakout_continuation(
            world("breakout", features={"position_in_range_20": 0.05},
                  memory=short_horizon("down"))
        )

        assert setup.fired is True
        assert setup.direction is Decision.SELL

    def test_it_belongs_to_the_breakout_family(self):
        setup = engine.breakout_continuation(world("breakout", features={}))

        assert setup.family == "breakout"

    def test_the_midpoint_leans_long(self):
        setup = engine.breakout_continuation(
            world("breakout", features={"position_in_range_20": 0.5},
                  memory=short_horizon("up"))
        )

        assert setup.direction is Decision.BUY

    def test_just_below_the_midpoint_leans_short(self):
        setup = engine.breakout_continuation(
            world("breakout", features={"position_in_range_20": 0.49},
                  memory=short_horizon("up"))
        )

        assert setup.direction is Decision.SELL

    def test_no_memory_block_means_no_direction_to_join(self):
        setup = engine.breakout_continuation(
            world("breakout", features={"position_in_range_20": 0.95})
        )

        assert setup.fired is False
        assert "no short-horizon direction to join" in setup.conditions_failed

    def test_a_null_memory_block_does_not_raise(self):
        state = world("breakout", features={"position_in_range_20": 0.95})
        state["memory"] = None

        assert engine.breakout_continuation(state).fired is False

    def test_an_unavailable_short_horizon_does_not_fire(self):
        setup = engine.breakout_continuation(
            world("breakout", features={"position_in_range_20": 0.95},
                  memory=short_horizon("up", available=False))
        )

        assert setup.fired is False

    def test_a_flat_short_horizon_does_not_fire(self):
        setup = engine.breakout_continuation(
            world("breakout", features={"position_in_range_20": 0.95},
                  memory=short_horizon("flat"))
        )

        assert setup.fired is False

    def test_a_null_trend_does_not_fire(self):
        setup = engine.breakout_continuation(
            world("breakout", features={"position_in_range_20": 0.95},
                  memory=short_horizon(None))
        )

        assert setup.fired is False

    def test_the_agreeing_horizon_is_recorded(self):
        setup = engine.breakout_continuation(
            world("breakout", features={"position_in_range_20": 0.95},
                  memory=short_horizon("up"))
        )

        assert "short horizon agrees (up)" in setup.conditions_met

    def test_a_missing_position_refuses(self):
        setup = engine.breakout_continuation(
            world("breakout", features={}, memory=short_horizon("up"))
        )

        assert setup.fired is False
        assert "unavailable" in setup.reason

    def test_volatility_is_not_double_counted(self):
        # The regime engine only calls a breakout when volatility is
        # expanding, so this strategy carries that evidence rather than
        # re-checking it and counting the same fact twice.
        setup = engine.breakout_continuation(
            world("breakout", features={"position_in_range_20": 0.95},
                  memory=short_horizon("up"))
        )

        assert len([c for c in setup.conditions_met if "volatil" in c.lower()]) == 0


class TestVolatilityStandAside:
    @pytest.mark.parametrize("regime", ["high_volatility", "uncertain"])
    def test_it_fires_where_not_trading_is_the_setup(self, regime):
        assert engine.volatility_stand_aside(world(regime)).fired is True

    @pytest.mark.parametrize("regime", ["high_volatility", "uncertain"])
    def test_firing_still_means_wait(self, regime):
        # The one strategy whose fired setup is a position of zero. Anything
        # downstream reading `fired` as "take a trade" breaks here.
        assert engine.volatility_stand_aside(world(regime)).direction is Decision.WAIT

    def test_it_belongs_to_the_no_trade_family(self):
        assert engine.volatility_stand_aside(world("uncertain")).family == "no_trade"

    def test_it_records_the_regime_as_the_condition_met(self):
        setup = engine.volatility_stand_aside(world("high_volatility"))

        assert setup.conditions_met == ["regime high_volatility"]

    def test_it_says_the_setup_is_to_take_no_position(self):
        setup = engine.volatility_stand_aside(world("uncertain"))

        assert "take no position" in setup.reason

    def test_it_needs_no_features_at_all(self):
        # The reason for inaction is recorded in the same format as the reason
        # for action, and it must not depend on a feature block that may be
        # exactly what is missing.
        assert engine.volatility_stand_aside({"regime": {"regime": "uncertain"}}).fired

    def test_it_never_reports_a_failed_condition(self):
        setup = engine.volatility_stand_aside(world("uncertain"))

        assert setup.conditions_failed == []


class TestOnlyOneFamilyFiresAtATime:
    @pytest.mark.parametrize("regime", EVERY_REGIME)
    def test_at_most_one_strategy_fires_in_any_regime(self, regime):
        # Each strategy declares disjoint suitable regimes, so a world state
        # can never satisfy two at once. If a fifth strategy overlaps an
        # existing one, this is where it shows up.
        state = world(
            regime,
            features={
                "rsi_14": 50,
                "close_over_sma_20": 1.02,
                "position_in_range_20": 0.9,
            },
            memory=short_horizon("up"),
        )

        assert len(engine.fired(state)) <= 1

    @pytest.mark.parametrize("regime", ["reversal"])
    def test_a_regime_no_strategy_claims_fires_nothing(self, regime):
        state = world(regime, features={"rsi_14": 50, "close_over_sma_20": 1.02})

        assert engine.fired(state) == []

    def test_three_regimes_are_declared_by_nobody(self):
        # Which regimes no strategy claims is a design fact, not an accident.
        # Recorded from the declarations themselves so that adding a strategy
        # for one of them is a deliberate edit rather than a silent change.
        declared = set()
        for name in engine.names():
            setup = engine._REGISTRY[name](world(Regime.REVERSAL.value))
            declared |= set(setup.suitable_regimes)

        assert set(EVERY_REGIME) - declared == {
            "reversal",
            "low_volatility",
            "news_event",
        }

    @pytest.mark.parametrize("regime", ["reversal", "low_volatility", "news_event"])
    def test_an_unclaimed_regime_fires_nothing_whatever_the_features(self, regime):
        state = world(
            regime,
            features={
                "rsi_14": 50,
                "close_over_sma_20": 1.02,
                "position_in_range_20": 0.9,
            },
            memory=short_horizon("up"),
        )

        assert engine.fired(state) == []
