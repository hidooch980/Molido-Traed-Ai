"""The two routes that read something other than a price.

The service layers underneath are tested separately and thoroughly. What is
tested here is the part a page depends on: that an upstream feed on another
continent going down produces a panel saying so, rather than an empty table, a
five hundred, or - worst - a plausible set of numbers from the last time it
worked.
"""

from __future__ import annotations

from datetime import date

import pytest
from fastapi.testclient import TestClient

from app.core.errors import ProviderError
from app.services import policy_rates, positioning


@pytest.fixture()
def client(session):
    from app.db.session import get_db
    from app.main import app

    app.dependency_overrides[get_db] = lambda: session
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


def rate(currency: str, value: float) -> policy_rates.PolicyRate:
    return policy_rates.PolicyRate(
        currency=currency,
        area=currency[:2],
        bank=f"{currency} central bank",
        rate=value,
        observed=date(2026, 8, 18),
    )


class TestPolicyRatesRoute:
    def test_reports_the_rates_and_the_headline_differentials(
        self, client, monkeypatch
    ):
        monkeypatch.setattr(
            policy_rates,
            "current",
            lambda **_: {
                "USD": rate("USD", 3.625),
                "EUR": rate("EUR", 2.25),
                "JPY": rate("JPY", 1.0),
                "AUD": rate("AUD", 4.35),
            },
        )
        body = client.get("/api/v1/fundamentals/policy-rates").json()

        assert body["available"] is True
        pairs = {d["pair"]: d["differential"] for d in body["differentials"]}
        assert pairs["EURUSD"] == pytest.approx(-1.375)
        assert pairs["AUDJPY"] == pytest.approx(3.35)

    def test_sorts_the_table_by_rate(self, client, monkeypatch):
        monkeypatch.setattr(
            policy_rates,
            "current",
            lambda **_: {"JPY": rate("JPY", 1.0), "AUD": rate("AUD", 4.35)},
        )
        body = client.get("/api/v1/fundamentals/policy-rates").json()
        assert [r["currency"] for r in body["rates"]] == ["AUD", "JPY"]

    def test_one_missing_currency_costs_one_row_not_the_table(
        self, client, monkeypatch
    ):
        """A pair whose leg vanished should be a gap, not an empty panel.

        Every headline pair but EUR/USD needs a currency that is absent here,
        so a route that gave up on the first refusal would return nothing at
        all - and nothing at all is indistinguishable from the feed being down.
        """
        monkeypatch.setattr(
            policy_rates,
            "current",
            lambda **_: {"USD": rate("USD", 3.625), "EUR": rate("EUR", 2.25)},
        )
        body = client.get("/api/v1/fundamentals/policy-rates").json()

        assert body["available"] is True
        assert [d["pair"] for d in body["differentials"]] == ["EURUSD"]

    def test_an_unreachable_feed_says_so_rather_than_returning_an_empty_table(
        self, client, monkeypatch
    ):
        """The distinction the whole route is shaped around.

        A stale or absent rate differential looks exactly like a live one on a
        screen, so "we could not read it" has to be a different answer from
        "there is nothing".
        """

        def down(**_):
            raise ProviderError("the policy rate feed answered 503", status=503)

        monkeypatch.setattr(policy_rates, "current", down)
        response = client.get("/api/v1/fundamentals/policy-rates")

        assert response.status_code == 200
        body = response.json()
        assert body["available"] is False
        assert body["rates"] == []
        assert "503" in body["reason"]


class TestPositioningRoute:
    def test_an_unmapped_market_is_refused_and_lists_what_it_knows(self, client):
        body = client.get("/api/v1/fundamentals/positioning?key=DOGECOIN").json()
        assert body["available"] is False
        assert "EUR" in body["known"]

    def test_an_unreachable_feed_reports_rather_than_raises(self, client, monkeypatch):
        def down(*_a, **_k):
            raise ProviderError("the positioning feed could not be read")

        monkeypatch.setattr(positioning, "as_of", down)
        response = client.get("/api/v1/fundamentals/positioning?key=EUR")

        assert response.status_code == 200
        assert response.json()["available"] is False
