"""Realised profit, and the two ways a P&L quietly lies.

The platform could show floating profit and nothing else. A closed trade leaves
the positions file entirely, so an account could be up four hundred dollars on
the day and every page would show only what was still open.

These tests are about the two figures that go wrong silently: a total that
counts profit but not swap and commission, and a zero that means "not
published" rather than "nothing closed".
"""

from __future__ import annotations

import json
from datetime import UTC, datetime

from app.services import realised

CLOSED = {
    "published_at": "2026.08.17 15:00:00",
    "window_days": 30,
    "deals": [
        {
            "ticket": 1,
            "symbol": "EURUSD",
            "side": "sell",
            "volume": 0.01,
            "price": 1.16,
            "profit": 12.0,
            "swap": -1.5,
            "commission": -0.5,
            "net": 10.0,
            "closed_at": "2026.08.17 14:00:00",
        },
        {
            "ticket": 2,
            "symbol": "USDCAD",
            "side": "sell",
            "volume": 0.24,
            "price": 1.386,
            "profit": -6.0,
            "swap": 0.0,
            "commission": -1.0,
            "net": -7.0,
            "closed_at": "2026.08.17 13:00:00",
        },
    ],
}


def publish(directory, body=None):
    (directory / realised.DEALS_FILE).write_text(
        json.dumps(body if body is not None else CLOSED), encoding="utf-8"
    )


class TestAbsentIsNotZero:
    """An account with no closed trades and an expert that is not publishing
    them look identical in a zero, and only one of them is about trading."""

    def test_a_missing_file_says_why(self, tmp_path):
        found = realised.read(directory=tmp_path)

        assert found["available"] is False
        assert found["net"] is None
        assert "not publishing closed deals yet" in found["reason"]

    def test_an_unreadable_file_says_so_rather_than_reporting_nothing(
        self, tmp_path
    ):
        (tmp_path / realised.DEALS_FILE).write_text("{ half", encoding="utf-8")

        found = realised.read(directory=tmp_path)

        assert found["available"] is False
        assert "could not be read" in found["reason"]

    def test_a_published_but_empty_history_is_available_and_zero(self, tmp_path):
        """This one *is* a real zero: the terminal answered and had nothing."""
        publish(tmp_path, {"deals": []})

        found = realised.read(directory=tmp_path)

        assert found["available"] is True
        assert found["net"] == 0.0
        assert found["trades"] == 0


class TestTheTotalIsNetOfEverything:
    """The terminal stores profit, swap and commission separately, and a page
    showing only the first shows a figure the account never saw."""

    def test_the_net_counts_swap_and_commission(self, tmp_path):
        publish(tmp_path)

        found = realised.read(directory=tmp_path)

        assert found["net"] == 3.0          # 10.0 + (-7.0)
        assert found["gross"] == 6.0        # 12.0 + (-6.0)
        assert found["swap"] == -1.5
        assert found["commission"] == -1.5

    def test_gross_and_net_differ_so_the_gap_is_visible(self, tmp_path):
        publish(tmp_path)

        found = realised.read(directory=tmp_path)

        assert found["gross"] != found["net"]
        assert "never saw" in found["note"]


class TestPerInstrument:
    def test_it_groups_and_sorts_worst_first(self, tmp_path):
        publish(tmp_path)

        rows = realised.read(directory=tmp_path)["by_symbol"]

        assert [r["symbol"] for r in rows] == ["USDCAD", "EURUSD"]
        assert rows[0]["net"] == -7.0

    def test_a_hit_rate_needs_a_sample(self, tmp_path):
        """A hit rate from two trades is a coin flip wearing a percentage."""
        publish(tmp_path)

        rows = realised.read(directory=tmp_path)["by_symbol"]

        assert all(r["hit_rate"] is None for r in rows)

    def test_a_hit_rate_appears_once_there_is_something_to_divide(self, tmp_path):
        deals = [
            {**CLOSED["deals"][0], "ticket": i, "net": 1.0 if i % 2 else -1.0}
            for i in range(6)
        ]
        publish(tmp_path, {"deals": deals})

        rows = realised.read(directory=tmp_path)["by_symbol"]

        assert rows[0]["trades"] == 6
        assert rows[0]["hit_rate"] == 0.5


class TestTheBrokerClock:
    """The terminal stamps deals on its own clock, measured at +3 here. Reading
    them as UTC would put every close three hours in the future - the same bug
    that shifted the whole broker bar series."""

    def test_the_offset_is_applied(self, tmp_path):
        publish(tmp_path)

        found = realised.read(directory=tmp_path, offset_hours=3)

        assert found["deals"][0]["closed_at"].startswith("2026-08-17T11:00")

    def test_no_offset_leaves_the_stamp_as_published(self, tmp_path):
        publish(tmp_path)

        found = realised.read(directory=tmp_path)

        assert found["deals"][0]["closed_at"].startswith("2026-08-17T14:00")

    def test_deals_come_back_newest_first(self, tmp_path):
        publish(tmp_path)

        deals = realised.read(directory=tmp_path)["deals"]

        assert deals[0]["ticket"] == 1
        assert deals[1]["ticket"] == 2

    def test_a_window_filters_by_close_time(self, tmp_path):
        publish(tmp_path)

        found = realised.read(
            directory=tmp_path,
            since=datetime(2026, 8, 17, 13, 30, tzinfo=UTC),
        )

        assert found["trades"] == 1
        assert found["deals"][0]["ticket"] == 1

    def test_an_unparseable_stamp_does_not_lose_the_deal(self, tmp_path):
        """A deal with a broken timestamp is still money that moved."""
        publish(tmp_path, {"deals": [{**CLOSED["deals"][0], "closed_at": "nonsense"}]})

        found = realised.read(directory=tmp_path)

        assert found["trades"] == 1
        assert found["deals"][0]["closed_at"] is None
        assert found["net"] == 10.0
