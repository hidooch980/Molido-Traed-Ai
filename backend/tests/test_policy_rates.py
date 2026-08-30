"""Central bank policy rates, and the difference between two of them.

The property that matters most here is the one a plausible number hides: a
missing rate must never become a rate of zero. Zero is a real policy rate - the
Swiss National Bank's is exactly that - so a differential computed against a
currency whose rate failed to parse would be wrong by the entire size of the
missing side while looking like an ordinary answer. Half these tests exist to
keep those two states apart.
"""

from __future__ import annotations

from datetime import date

import pytest

from app.core.errors import InsufficientDataError, LookaheadViolationError, ProviderError
from app.services import policy_rates

HEADER = (
    "FREQ,REF_AREA,UNIT_MEASURE,UNIT_MULT,TIME_FORMAT,COMPILATION,DECIMALS,"
    "SOURCE_REF,SUPP_INFO_BREAKS,TITLE,TIME_PERIOD,OBS_VALUE,OBS_STATUS,OBS_CONF"
)


def row(area: str, period: str, value: str) -> str:
    return f"D,{area},A,0,P1D,,2,,,Policy rate,{period},{value},A,F"


def feed(*rows: str) -> str:
    return "\n".join([HEADER, *rows]) + "\n"


LIVE = feed(
    row("US", "2026-08-18", "3.625"),
    row("XM", "2026-08-18", "2.25"),
    row("GB", "2026-08-17", "3.75"),
    row("JP", "2026-08-18", "1"),
    row("CH", "2026-08-18", "0"),
    row("AU", "2026-08-06", "4.35"),
)


class FakeOpener:
    """Stands in for `urllib.request.urlopen`."""

    def __init__(self, body: str):
        self.body = body
        self.calls = 0

    def __call__(self, request, timeout=None):  # noqa: ANN001 - urllib's shape
        self.calls += 1
        return self

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False

    def read(self) -> bytes:
        return self.body.encode("utf-8")


class TestParsing:
    def test_reads_a_rate_for_every_area_it_knows(self):
        rates = policy_rates.parse(LIVE)
        assert set(rates) == {"USD", "EUR", "GBP", "JPY", "CHF", "AUD"}

    def test_maps_the_euro_area_to_the_euro(self):
        """`XM` is not a country and no ISO table maps it to EUR.

        Deriving a currency from an area code would drop the euro entirely,
        which is the one currency this platform trades most.
        """
        rates = policy_rates.parse(LIVE)
        assert rates["EUR"].rate == 2.25
        assert rates["EUR"].bank == "European Central Bank"

    def test_carries_the_observation_date(self):
        rates = policy_rates.parse(LIVE)
        assert rates["AUD"].observed == date(2026, 8, 6)

    def test_a_zero_rate_is_a_rate(self):
        """The Swiss National Bank is genuinely at zero.

        If zero were treated as absent, every CHF pair would refuse; if absent
        were treated as zero, every CHF pair would answer wrongly. This is the
        test that says which.
        """
        rates = policy_rates.parse(LIVE)
        assert "CHF" in rates
        assert rates["CHF"].rate == 0.0

    def test_an_area_it_cannot_attribute_is_dropped(self):
        """Not kept under its own code, which would inflate the count.

        A rate nobody can tie to a currency can never enter a differential, so
        carrying it would only make coverage look better than it is.
        """
        rates = policy_rates.parse(feed(row("ZZ", "2026-08-18", "9.99")))
        assert rates == {}

    def test_a_row_with_no_observation_is_not_a_bank_at_zero(self):
        rates = policy_rates.parse(feed(row("US", "2026-08-18", "")))
        assert "USD" not in rates

    def test_an_unreadable_number_is_skipped_rather_than_fatal(self):
        """One malformed row must not cost every other bank's rate."""
        rates = policy_rates.parse(
            feed(row("US", "2026-08-18", "n/a"), row("JP", "2026-08-18", "1"))
        )
        assert "USD" not in rates
        assert rates["JPY"].rate == 1.0


class TestDifferential:
    @pytest.fixture
    def rates(self):
        return policy_rates.parse(LIVE)

    def test_is_the_base_minus_the_quote(self, rates):
        assert policy_rates.differential("AUD", "JPY", rates) == pytest.approx(3.35)

    def test_reverses_with_the_pair(self, rates):
        assert policy_rates.differential("JPY", "AUD", rates) == pytest.approx(-3.35)

    def test_a_negative_carry_stays_negative(self, rates):
        """EUR/USD pays less than nothing, and saying so is the point."""
        assert policy_rates.differential("EUR", "USD", rates) < 0

    def test_a_missing_currency_is_refused_not_defaulted(self, rates):
        """The failure this whole module is shaped around.

        Reading a missing rate as zero would answer +4.35 for AUD/XXX - a
        number with no meaning, in a form nothing downstream could question.
        """
        with pytest.raises(InsufficientDataError) as refused:
            policy_rates.differential("AUD", "XXX", rates)
        assert "XXX" in refused.value.context["missing"]

    def test_a_zero_rate_still_produces_a_differential(self, rates):
        """Distinct from the case above, and easy to conflate."""
        assert policy_rates.differential("GBP", "CHF", rates) == pytest.approx(3.75)


class TestFetching:
    def setup_method(self):
        policy_rates._cached = None

    def teardown_method(self):
        policy_rates._cached = None

    def test_an_injected_opener_never_populates_the_cache(self):
        """Otherwise one test's fixture becomes the next test's live feed."""
        opener = FakeOpener(LIVE)
        policy_rates.current(opener=opener)
        assert policy_rates._cached is None

    def test_a_refused_feed_is_reported_rather_than_returned_empty(self):
        def broken(request, timeout=None):  # noqa: ANN001
            raise OSError("connection reset")

        with pytest.raises(ProviderError):
            policy_rates.current(opener=broken)

    def test_a_failed_fetch_does_not_poison_the_cache(self):
        def broken(request, timeout=None):  # noqa: ANN001
            raise OSError("connection reset")

        with pytest.raises(ProviderError):
            policy_rates.current(opener=broken)
        assert policy_rates._cached is None


class TestAsOf:
    def test_refuses_to_answer_for_a_date_before_the_reading(self):
        """The feed carries today's rates and only today's.

        Serving them against a historical timestamp is a decision that knows
        the outcome of a meeting which had not happened yet - the exact shape
        of lookahead this codebase refuses everywhere else.
        """
        opener = FakeOpener(LIVE)
        with pytest.raises(LookaheadViolationError) as refused:
            policy_rates.as_of(date(2020, 1, 1), opener=opener)
        assert "USD" in refused.value.context["currencies"]

    def test_answers_when_nothing_is_ahead_of_the_asked_date(self):
        opener = FakeOpener(LIVE)
        rates = policy_rates.as_of(date(2030, 1, 1), opener=opener)
        assert rates["USD"].rate == 3.625


class TestTheParsedReadingIsCached:
    """Parsing was free when this was read once to draw a page.

    It stopped being free when the decision chain began asking for a
    differential per instrument: forty-three instruments meant parsing
    forty-nine central banks forty-three times to answer a question whose
    input had not changed.
    """

    def test_the_same_body_is_only_parsed_once(self, monkeypatch):
        from app.services import policy_rates

        policy_rates._parsed = None
        parses = {"count": 0}
        real_parse = policy_rates.parse

        def counting_parse(body):
            parses["count"] += 1
            return real_parse(body)

        monkeypatch.setattr(policy_rates, "parse", counting_parse)
        monkeypatch.setattr(policy_rates, "fetch", lambda **_: LIVE)

        policy_rates.current()
        policy_rates.current()
        policy_rates.current()

        assert parses["count"] == 1

    def test_a_replaced_body_is_parsed_again(self, monkeypatch):
        """The cache is keyed on the document, not on a clock.

        A separate expiry would eventually serve a parse of a body that had
        already been replaced - reporting a rate the feed no longer carries.
        """
        from app.services import policy_rates

        policy_rates._parsed = None
        bodies = [LIVE, LIVE.replace("3.625", "4.125")]
        monkeypatch.setattr(policy_rates, "fetch", lambda **_: bodies[0])
        first = policy_rates.current()

        bodies.pop(0)
        second = policy_rates.current()

        assert first["USD"].rate != second["USD"].rate

    def test_a_caller_cannot_edit_the_reading_for_everybody_else(self, monkeypatch):
        from app.services import policy_rates

        policy_rates._parsed = None
        monkeypatch.setattr(policy_rates, "fetch", lambda **_: LIVE)

        mine = policy_rates.current()
        mine.pop("USD", None)

        assert "USD" in policy_rates.current()
