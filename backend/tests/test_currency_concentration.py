"""Seven small copies of one trade are still one trade.

term-g held ten positions on 2026-09-03. Seven were long against the yen -
AUDJPY, EURJPY, CHFJPY, GBPJPY, USDJPY, NZDJPY, CADJPY - and every one of
them was losing, together, because they are one bet wearing seven names.

The portfolio brain has a currency cap of 3.0 R and it never fired. Each
position risked 0.04 R, because the deployment is unsure of itself and sizes
every trade at a twenty-fifth of the configured risk, so the yen exposure
totalled 0.28 R against a limit of 3.0.

The guard against concentration scaled down with the very uncertainty that
should have made it stricter. A count does not scale.
"""

from __future__ import annotations

from app.brain import portfolio


def leg(symbol: str, direction: str, risk_r: float = 0.04):
    base, quote = symbol[:3], symbol[3:]
    return portfolio.Position(
        symbol=symbol,
        direction=direction,
        risk_r=risk_r,
        base_currency=base,
        quote_currency=quote,
    )


# The book as it actually stood, in the order it was opened.
YEN_BOOK = [
    leg("AUDJPY", "buy"),
    leg("EURJPY", "buy"),
    leg("CHFJPY", "buy"),
]


class TestTheRealBook:
    def test_the_r_cap_alone_would_have_allowed_all_seven(self):
        """Not a hypothetical: this is why it happened. Every one of those
        positions passed the check that exists to stop exactly this."""
        seven = [
            leg(s, "buy")
            for s in ("AUDJPY", "EURJPY", "CHFJPY", "GBPJPY", "USDJPY", "NZDJPY", "CADJPY")
        ]
        exposure = portfolio.currency_exposure(seven)

        assert abs(exposure["JPY"]) == 0.28
        assert abs(exposure["JPY"]) < portfolio.MAX_CURRENCY_RISK_R

    def test_a_fourth_yen_short_is_refused_however_small_it_is(self):
        verdict = portfolio.evaluate(
            symbol="GBPJPY",
            direction="buy",
            proposed_risk_r=0.04,
            positions=YEN_BOOK,
            base_currency="GBP",
            quote_currency="JPY",
        )

        assert not verdict.allowed
        assert any("currency-count:JPY" in b for b in verdict.breaches)

    def test_the_same_refusal_at_any_size(self):
        """The point of the count is that size cannot buy past it."""
        for size in (0.001, 0.04, 1.0):
            verdict = portfolio.evaluate(
                symbol="GBPJPY",
                direction="buy",
                proposed_risk_r=size,
                positions=YEN_BOOK,
                base_currency="GBP",
                quote_currency="JPY",
            )

            assert not verdict.allowed, f"allowed at {size} R"


class TestItDoesNotStopHonestDiversification:
    def test_three_on_one_currency_is_still_allowed(self):
        """The limit is three, and two open positions must not block the
        third - an off-by-one here would quietly halve the book."""
        verdict = portfolio.evaluate(
            symbol="CHFJPY",
            direction="buy",
            proposed_risk_r=0.04,
            positions=YEN_BOOK[:2],
            base_currency="CHF",
            quote_currency="JPY",
        )

        assert verdict.allowed

    def test_the_other_side_of_the_same_currency_is_not_the_same_bet(self):
        """Short EUR against three long-EUR positions reduces the account's
        exposure. Refusing it would be the guard working backwards."""
        book = [leg("EURUSD", "buy"), leg("EURJPY", "buy"), leg("EURGBP", "buy")]

        verdict = portfolio.evaluate(
            symbol="EURCHF",
            direction="sell",
            proposed_risk_r=0.04,
            positions=book,
            base_currency="EUR",
            quote_currency="CHF",
        )

        assert verdict.allowed

    def test_a_different_currency_is_unaffected(self):
        verdict = portfolio.evaluate(
            symbol="EURGBP",
            direction="buy",
            proposed_risk_r=0.04,
            positions=YEN_BOOK,
            base_currency="EUR",
            quote_currency="GBP",
        )

        assert verdict.allowed

    def test_an_empty_book_allows_the_first_trade(self):
        verdict = portfolio.evaluate(
            symbol="USDJPY",
            direction="buy",
            proposed_risk_r=0.04,
            positions=[],
            base_currency="USD",
            quote_currency="JPY",
        )

        assert verdict.allowed


class TestItNamesItself:
    def test_the_breach_says_which_currency(self):
        """"portfolio: blocked" would send somebody to read the code. The
        reason a trade was refused is the only part of it anybody sees."""
        verdict = portfolio.evaluate(
            symbol="USDJPY",
            direction="buy",
            proposed_risk_r=0.04,
            positions=YEN_BOOK,
            base_currency="USD",
            quote_currency="JPY",
        )

        assert "JPY" in " ".join(verdict.breaches)


class TestItReportsTheWorstBreachNotTheFirst:
    def test_the_deeper_pile_is_the_one_named(self):
        """The live book was three deep on USD and seven deep on JPY, both at
        zero headroom, and it reported USD. True, and not the sentence
        somebody needs to read."""
        book = [
            leg("XAGUSD", "sell"),   # long USD
            leg("AUDUSD", "sell"),   # long USD
            leg("AUDJPY", "buy"),    # short JPY
            leg("EURJPY", "buy"),
            leg("CHFJPY", "buy"),
            leg("GBPJPY", "buy"),
            leg("NZDJPY", "buy"),
            leg("CADJPY", "buy"),
        ]

        verdict = portfolio.evaluate(
            symbol="USDJPY",
            direction="buy",  # long USD and short JPY at once
            proposed_risk_r=0.04,
            positions=book,
            base_currency="USD",
            quote_currency="JPY",
        )

        assert not verdict.allowed
        assert "currency-count:JPY" in " ".join(verdict.breaches)

    def test_a_currency_inside_the_limit_never_caps_a_trade(self):
        """A count headroom compared against headrooms measured in R would
        make "one position of room" cap a trade at 1.0 R, which is a limit
        nobody chose and a unit nobody meant."""
        book = [leg("EURUSD", "buy", risk_r=0.5)]

        verdict = portfolio.evaluate(
            symbol="EURJPY",
            direction="buy",
            proposed_risk_r=1.5,
            positions=book,
            base_currency="EUR",
            quote_currency="JPY",
        )

        assert verdict.allowed
        assert verdict.max_additional_risk_r == 1.5
