"""One request for the whole universe's market state.

This route exists because its absence shaped a page. Asking for one
instrument's session at a time made each row of the markets table an HTTP
round trip, so the table capped itself at twenty-five rows - and since the
instrument list is sorted alphabetically, that cap hid everything from NZDCHF
onward. Gold was missing from a page called markets, the header honestly read
"25 / 43", and nothing anywhere was broken.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.core.enums import AssetClass
from app.models.instruments import Instrument


@pytest.fixture()
def client(session):
    from app.db.session import get_db
    from app.main import app

    app.dependency_overrides[get_db] = lambda: session
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


@pytest.fixture()
def universe(session):
    """Enough instruments, and deliberately ones that sort late.

    XAUUSD and XRPUSD are the two that a twenty-five row alphabetical cap
    would have removed, which is the whole point of naming them here.
    """
    rows = [
        Instrument(
            symbol=symbol,
            name=symbol,
            asset_class=asset_class,
            base_currency=symbol[:3],
            quote_currency=symbol[3:] or "USD",
        )
        for symbol, asset_class in [
            ("AUDUSD", AssetClass.FOREX),
            ("EURUSD", AssetClass.FOREX),
            ("XAUUSD", AssetClass.COMMODITY),
            ("XRPUSD", AssetClass.CRYPTO),
        ]
    ]
    session.add_all(rows)
    session.flush()
    return rows


class TestBatchSessionStatus:
    def test_answers_for_every_active_instrument(self, client, universe):
        body = client.get("/api/v1/sessions/status").json()
        assert {row["symbol"] for row in body} == {
            "AUDUSD",
            "EURUSD",
            "XAUUSD",
            "XRPUSD",
        }

    def test_includes_the_symbols_an_alphabetical_cap_would_drop(
        self, client, universe
    ):
        """Named rather than implied, because this is the reported bug.

        A list route that quietly returns a prefix is indistinguishable from
        one that returns everything, right up until somebody looks for a
        symbol late in the alphabet.
        """
        body = client.get("/api/v1/sessions/status").json()
        assert "XAUUSD" in {row["symbol"] for row in body}

    def test_every_row_is_evaluated_at_the_same_instant(self, client, universe):
        """Not `now` per instrument.

        Rows a few milliseconds apart could otherwise straddle an open or a
        close, and the table would show two markets disagreeing about what
        time it is.
        """
        body = client.get("/api/v1/sessions/status").json()
        assert len({row["at"] for row in body}) == 1

    def test_an_explicit_instant_is_honoured(self, client, universe):
        body = client.get(
            "/api/v1/sessions/status?at=2026-08-26T12:00:00Z"
        ).json()
        assert all(row["at"].startswith("2026-08-26T12:00:00") for row in body)

    def test_an_inactive_instrument_is_left_out(self, client, universe, session):
        universe[0].is_active = False
        session.flush()
        body = client.get("/api/v1/sessions/status").json()
        assert "AUDUSD" not in {row["symbol"] for row in body}

    def test_the_route_is_not_shadowed_by_the_single_instrument_one(
        self, client, universe
    ):
        """`/{instrument_id}` parses its segment as a UUID.

        Declared in the wrong order, "status" would be refused as a malformed
        identifier rather than reaching the handler above it - a 422 that
        looks like a client mistake.
        """
        assert client.get("/api/v1/sessions/status").status_code == 200

    def test_carries_the_fields_the_table_renders(self, client, universe):
        body = client.get("/api/v1/sessions/status").json()
        row = body[0]
        for field in ("instrument_id", "symbol", "is_open", "market_code", "at"):
            assert field in row
