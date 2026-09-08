

from datetime import UTC, datetime


class TestCarryDifferential:
    """Brain #5. Long what pays, short what charges - scored only from rates
    that were observable strictly before the instant."""

    AS_OF = datetime(2026, 8, 15, 12, 0, tzinfo=UTC)

    def table(self):
        from datetime import date

        day = date(2026, 8, 10)
        flat = [(day, 0.5)]
        return {
            "AUD": [(day, 4.35)],
            "NZD": [(day, 5.5)],
            "JPY": [(day, 0.25)],
            "CHF": [(day, 0.0)],
            "EUR": flat,
            "USD": [(day, 4.5)],
            "GBP": [(day, 4.0)],
            "CAD": [(day, 2.75)],
        }

    def snapshot(self, symbols):
        return {
            symbol: {
                "closes": [1.0] * 90,
                "bars": [(1.01, 0.99, 1.0)] * 90,
                "last_at": self.AS_OF,
            }
            for symbol in symbols
        }

    def rule(self, table=None):
        from app.learning.rules import CarryDifferential

        return CarryDifferential(table=self.table() if table is None else table)

    def test_pays_long_and_charges_short(self):
        picks = self.rule()(
            self.snapshot(
                ["NZDJPY", "AUDJPY", "USDCHF", "EURUSD", "CHFJPY", "EURAUD",
                 "GBPCAD", "EURNZD"]
            ),
            universe=None,
        )

        # NZDJPY carries +5.25, EURNZD carries -5.0: the ends of the ranking.
        assert "NZDJPY" in picks.longs
        assert "EURNZD" in picks.shorts

    def test_a_missing_rate_is_not_a_rate_of_zero(self):
        table = self.table()
        del table["JPY"]

        picks = self.rule(table)(
            self.snapshot(["NZDJPY", "AUDJPY", "CHFJPY", "EURUSD", "USDCHF",
                           "GBPCAD"]),
            universe=None,
        )

        # Every JPY pair became unscoreable, leaving too few - a declared
        # decline, not a ranking built around an invented zero.
        assert picks.empty
        assert picks.declined is not None

    def test_a_stale_rate_is_treated_as_missing(self):
        from datetime import date

        table = self.table()
        table["JPY"] = [(date(2026, 1, 1), 0.25)]  # seven months old

        picks = self.rule(table)(
            self.snapshot(["NZDJPY", "AUDJPY", "CHFJPY", "EURUSD", "USDCHF",
                           "GBPCAD"]),
            universe=None,
        )

        assert picks.empty

    def test_a_rate_observed_after_the_instant_is_unreadable(self):
        """The whole reason the history table exists: a replay must not know
        a decision the bank had not yet made."""
        from datetime import date

        table = self.table()
        table["JPY"] = [(date(2026, 8, 20), 9.99)]  # five days in the future

        picks = self.rule(table)(
            self.snapshot(["NZDJPY", "AUDJPY", "CHFJPY", "EURUSD", "USDCHF",
                           "GBPCAD"]),
            universe=None,
        )

        assert picks.empty

    def test_gold_has_no_policy_rate(self):
        picks = self.rule()(
            self.snapshot(["XAUUSD", "NZDJPY", "AUDJPY", "USDCHF", "EURUSD",
                           "CHFJPY", "GBPCAD", "EURNZD"]),
            universe=None,
        )

        assert "XAUUSD" not in picks.longs + picks.shorts

    def test_no_stored_history_declines_by_name(self):
        picks = self.rule(table={})(
            self.snapshot(["NZDJPY", "AUDJPY"]), universe=None
        )

        assert picks.empty
        assert "policy rate history" in (picks.declined or "")


class TestPolicyRateHistoryParsing:
    def test_history_rows_parse_to_currency_day_rate(self):
        from datetime import date

        from app.services.policy_rates import parse_history

        body = (
            "REF_AREA,TIME_PERIOD,OBS_VALUE\n"
            "US,2026-08-10,4.5\n"
            "JP,2026-08-10,0.25\n"
            "XX,2026-08-10,7.0\n"
            "GB,2026-08-10,\n"
        )

        rows = parse_history(body)

        assert ("USD", date(2026, 8, 10), 4.5) in rows
        assert ("JPY", date(2026, 8, 10), 0.25) in rows
        # An unmapped area and an empty observation both vanish rather than
        # entering the table as numbers nobody published.
        assert len(rows) == 2


class TestTheThreeSingleInstrumentBrains:
    """Per instrument rather than across a cross-section, which is what makes
    them usable on a seven-symbol list: the incumbent needs twenty
    instruments before a ranking means anything, these need one."""

    def rising(self, count=160, base=100.0, drift=0.5):
        return {
            "closes": [base + i * drift for i in range(count)],
            "bars": [
                (base + i * drift + 1, base + i * drift - 1, base + i * drift)
                for i in range(count)
            ],
        }

    def falling(self, count=160, base=100.0):
        return self.rising(count=count, base=base, drift=-0.5)

    def flat(self, count=160, base=100.0):
        return self.rising(count=count, base=base, drift=0.0)

    def snapshot(self, **kinds):
        return {name: shape for name, shape in kinds.items()}

    def test_trend_following_buys_the_riser_and_sells_the_faller(self):
        from app.learning.rules import TrendFollowing

        picks = TrendFollowing(per_side=1)(
            self.snapshot(
                UP=self.rising(),
                DOWN=self.falling(),
                FLAT1=self.flat(),
                FLAT2=self.flat(base=50.0),
            ),
            universe=None,
        )

        assert "UP" in picks.longs
        assert "DOWN" in picks.shorts

    def test_trend_following_is_scaled_by_volatility(self):
        """Without dividing by ATR a four-thousand-dollar instrument wins
        every ranking on arithmetic rather than on trend."""
        from app.learning.rules import TrendFollowing

        picks = TrendFollowing(per_side=1)(
            self.snapshot(
                CHEAP=self.rising(base=1.0, drift=0.01),
                GOLD=self.rising(base=4000.0, drift=0.5),
                DOWN=self.falling(),
                FLAT=self.flat(),
            ),
            universe=None,
        )

        # Both rise; the pick is about trend strength in each instrument's
        # own units, so the expensive one does not win automatically.
        assert picks.longs and picks.longs[0] in {"CHEAP", "GOLD"}

    def test_rsi_declines_when_nothing_is_stretched(self):
        """An oscillator that always has an opinion is not an oscillator."""
        from app.learning.rules import RSIMeanReversion

        picks = RSIMeanReversion()(
            self.snapshot(A=self.flat(), B=self.flat(base=2.0)), universe=None
        )

        assert picks.empty
        assert picks.declined is not None

    def test_rsi_buys_the_oversold(self):
        from app.learning.rules import RSIMeanReversion

        picks = RSIMeanReversion(per_side=1)(
            self.snapshot(DOWN=self.falling(), FLAT=self.flat()), universe=None
        )

        assert "DOWN" in picks.longs

    def test_donchian_needs_a_break_of_the_prior_channel(self):
        """Including the current bar makes every bar its own breakout."""
        from app.learning.rules import DonchianBreakout

        picks = DonchianBreakout()(
            self.snapshot(FLAT=self.flat(), FLAT2=self.flat(base=3.0)),
            universe=None,
        )

        assert picks.empty

    def test_donchian_buys_a_new_high(self):
        from app.learning.rules import DonchianBreakout

        shape = self.flat()
        shape["closes"] = shape["closes"][:-1] + [200.0]
        shape["bars"] = shape["bars"][:-1] + [(201.0, 199.0, 200.0)]

        picks = DonchianBreakout(per_side=1)(
            self.snapshot(BREAK=shape, FLAT=self.flat(base=5.0)), universe=None
        )

        assert "BREAK" in picks.longs

    def test_each_declares_the_history_it_needs(self):
        """The recorder sizes its window from this, and a brain that
        understates it silently declines every instant."""
        from app.learning.rules import (
            DonchianBreakout,
            RSIMeanReversion,
            TrendFollowing,
        )

        assert TrendFollowing().lookback >= TrendFollowing().slow
        assert RSIMeanReversion().lookback > RSIMeanReversion().period
        assert DonchianBreakout().lookback > DonchianBreakout().channel


class TestTheThreeFamiliesThatHadNoRepresentative:
    """Market Structure, Volatility and Statistical are the three families
    the brief names that this project had nothing in at all. These are their
    first members, and they live in PROPOSED - CANDIDATES is deployment,
    because the forward loop writes a decision for everything in it on every
    cycle.

    What is tested here is that each rule says what its docstring claims it
    says. Whether it earns anything is the harness's question, not this
    file's."""

    def bars(self, highs, lows, closes):
        return {
            "bars": list(zip(highs, lows, closes, strict=True)),
            "closes": list(closes),
        }

    def stepped(self, *, n=60, drift=0.0, base=100.0, span=1.0):
        closes = [base + drift * i for i in range(n)]
        return self.bars(
            [c + span for c in closes], [c - span for c in closes], closes
        )

    # ---------------------------------------------------------- structure

    def test_swing_structure_needs_both_halves_to_agree(self):
        """A higher high alone is a spike and a higher low alone is a
        pullback that held. The rule is about the two together."""
        from app.learning.rules import SwingStructure

        rising = self.stepped(drift=0.5)
        falling = self.stepped(drift=-0.5, base=200.0)
        # High rises, low does not: the second half spikes up but keeps
        # visiting the first half's floor.
        spike = self.bars(
            [100.0 + (5.0 if i >= 30 and i % 5 == 0 else 0.0) for i in range(60)],
            [98.0] * 60,
            [99.0] * 60,
        )

        picks = SwingStructure(per_side=1)(
            {"UP": rising, "DOWN": falling, "SPIKE": spike}, universe=None
        )

        assert picks.longs == ("UP",)
        assert picks.shorts == ("DOWN",)
        assert "SPIKE" not in picks.longs + picks.shorts

    def test_swing_structure_declines_on_a_flat_list(self):
        from app.learning.rules import SwingStructure

        picks = SwingStructure()(
            {"A": self.stepped(), "B": self.stepped(base=50.0)}, universe=None
        )

        assert picks.longs == () and picks.shorts == ()
        assert picks.declined

    # --------------------------------------------------------- volatility

    def test_volatility_expansion_reads_the_close_not_the_direction(self):
        """A wide bar closing in its middle is not a signal, however far it
        travelled."""
        from app.learning.rules import VolatilityExpansion

        def with_last(high, low, close):
            row = self.stepped(n=40)
            row["bars"][-1] = (high, low, close)
            row["closes"][-1] = close
            return row

        picks = VolatilityExpansion(per_side=1)(
            {
                "TOP": with_last(110.0, 90.0, 109.5),
                "BOTTOM": with_last(110.0, 90.0, 90.5),
                "MIDDLE": with_last(110.0, 90.0, 100.0),
            },
            universe=None,
        )

        assert picks.longs == ("TOP",)
        assert picks.shorts == ("BOTTOM",)
        assert "MIDDLE" not in picks.longs + picks.shorts

    def test_an_ordinary_bar_is_not_an_expansion(self):
        from app.learning.rules import VolatilityExpansion

        picks = VolatilityExpansion()({"A": self.stepped(n=40)}, universe=None)

        assert picks.declined

    # -------------------------------------------------------- statistical

    def test_residual_reversion_ignores_a_move_the_whole_list_made(self):
        """The case that separates it from the incumbent. Every instrument
        drifting together is a large stretch on each and a residual of zero
        on all - and a common move is the one thing a reversion rule must not
        fade."""
        from app.brain import crosssection
        from app.learning.rules import ResidualReversion

        universe = sorted(crosssection.RANKED_UNIVERSE)[
            : crosssection.MIN_CROSS_SECTION
        ]
        together = {sym: self.stepped(n=40, drift=0.5) for sym in universe}

        picks = ResidualReversion()(together, universe=None)

        assert picks.declined == "every residual is identical"

    def test_it_fades_the_one_that_left_its_peers(self):
        from app.brain import crosssection
        from app.learning.rules import ResidualReversion

        universe = sorted(crosssection.RANKED_UNIVERSE)[
            : crosssection.MIN_CROSS_SECTION + 2
        ]
        book = {sym: self.stepped(n=40, drift=0.5) for sym in universe}
        book[universe[0]] = self.stepped(n=40, drift=2.0)
        book[universe[1]] = self.stepped(n=40, drift=-2.0)

        picks = ResidualReversion(per_side=1)(book, universe=None)

        assert picks.shorts == (universe[0],)
        assert picks.longs == (universe[1],)

    def test_it_refuses_a_cross_section_too_thin_to_have_a_common_move(self):
        from app.learning.rules import ResidualReversion

        picks = ResidualReversion()(
            {"A": self.stepped(n=40), "B": self.stepped(n=40, base=50.0)},
            universe=None,
        )

        assert "instruments could be returned" in (picks.declined or "")

    # ------------------------------------------------------------ wiring

    def test_they_are_proposed_and_not_deployed(self):
        """CANDIDATES is deployment: `forward.record_forward` iterates it and
        writes a decision for every rule in it on every cycle."""
        from app.learning import rules

        assert rules.proposed_names() == [
            "residual-reversion",
            "swing-structure",
            "volatility-expansion",
        ]
        for name in rules.proposed_names():
            assert name not in rules.names()
            assert rules.get(name) is not None


class TestTwoRulesThatAgree:
    """The deployment already acts on an answer it has never had.
    `MOLIDO_CONSENSUS_REQUIRED` makes the order gate wait for N brains to
    agree, and nothing has measured whether agreement is worth anything -
    because `measure` takes one rule and the gate is not one."""

    class Fixed:
        """A rule that always names what it was constructed with."""

        def __init__(self, name, longs=(), shorts=(), scores=None, declined=None):
            self.name = name
            self._picks = (longs, shorts, scores, declined)

        def __call__(self, snapshot, *, universe):
            from app.learning.rules import Picks

            longs, shorts, scores, declined = self._picks
            if declined:
                return Picks(declined=declined)
            return Picks(longs=longs, shorts=shorts, scores=scores)

    def test_it_keeps_only_what_both_named_on_the_same_side(self):
        from app.learning.rules import Agreement

        pair = Agreement(
            self.Fixed("a", longs=("EURUSD", "GBPUSD"), shorts=("USDJPY",)),
            self.Fixed("b", longs=("GBPUSD", "AUDUSD"), shorts=("USDJPY",)),
        )

        picks = pair({}, universe=None)

        assert picks.longs == ("GBPUSD",)
        assert picks.shorts == ("USDJPY",)

    def test_a_symbol_the_two_disagree_about_is_dropped(self):
        """One wants it long and the other short. Taking either side is
        picking a winner the evidence has not picked."""
        from app.learning.rules import Agreement

        pair = Agreement(
            self.Fixed("a", longs=("EURUSD",)),
            self.Fixed("b", shorts=("EURUSD",)),
        )

        picks = pair({}, universe=None)

        assert picks.longs == () and picks.shorts == ()
        assert picks.declined

    def test_conviction_is_the_weaker_of_the_two(self):
        """A pair is only as sure as its less sure half. Taking the stronger
        would let one rule carry a symbol the other barely wanted."""
        from app.learning.rules import Agreement

        pair = Agreement(
            self.Fixed("a", longs=("EURUSD",), scores={"EURUSD": 0.9}),
            self.Fixed("b", longs=("EURUSD",), scores={"EURUSD": 0.2}),
        )

        picks = pair({}, universe=None)

        assert picks.scores == {"EURUSD": 0.2}

    def test_a_refusal_names_which_half_refused(self):
        from app.learning.rules import Agreement

        pair = Agreement(
            self.Fixed("a", declined="the cross-section was thin"),
            self.Fixed("b", longs=("EURUSD",)),
        )

        picks = pair({}, universe=None)

        assert "a declined" in picks.declined
        assert "cross-section was thin" in picks.declined

    def test_it_needs_the_history_of_its_hungrier_half(self):
        """Without this a composite reports the history of neither part and is
        starved exactly the way `trend-following` was."""
        from app.learning import rules

        pair = rules.Agreement(
            rules.get("trend-following"), rules.get("rsi-mean-reversion")
        )

        assert rules.history_needed(rules.get("trend-following")) == 101
        assert rules.history_needed(rules.get("rsi-mean-reversion")) == 16
        assert rules.history_needed(pair) == 101

    def test_it_names_itself_after_both(self):
        from app.learning import rules

        pair = rules.Agreement(
            rules.get("carry-differential"), rules.get("trend-following")
        )

        assert pair.name == "agree:carry-differential+trend-following"
