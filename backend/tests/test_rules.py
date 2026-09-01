

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
