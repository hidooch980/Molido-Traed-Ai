"""The session table under the dashboard clocks, on Iran's clock."""

from __future__ import annotations

from datetime import UTC, datetime

from app.services.sessions import session_table


class TestTheSessionTable:
    def test_all_four_sessions_are_present(self):
        rows = session_table(datetime(2026, 9, 2, 12, 0, tzinfo=UTC))

        assert [r["session"] for r in rows] == [
            "sydney", "tokyo", "london", "new_york",
        ]

    def test_iran_times_follow_the_source_timezone_dst(self):
        """Tokyo has no DST: 09:00 JST is always 03:30 in Iran (Tokyo runs
        five and a half hours ahead of Tehran). London does have DST: 08:00
        there is 10:30 Iran in summer (BST) and 11:30 in winter."""
        summer = session_table(datetime(2026, 7, 15, 12, 0, tzinfo=UTC))
        winter = session_table(datetime(2026, 1, 15, 12, 0, tzinfo=UTC))

        tokyo = {r["session"]: r for r in summer}["tokyo"]
        assert tokyo["opens_iran"] == "03:30"

        london_summer = {r["session"]: r for r in summer}["london"]
        london_winter = {r["session"]: r for r in winter}["london"]
        assert london_summer["opens_iran"] == "10:30"
        assert london_winter["opens_iran"] == "11:30"

    def test_open_state_matches_the_active_sessions(self):
        # Wednesday 13:00 UTC: London and New York both inside their windows.
        rows = {r["session"]: r for r in session_table(datetime(2026, 9, 2, 13, 0, tzinfo=UTC))}

        assert rows["london"]["is_open"] is True
        assert rows["new_york"]["is_open"] is True
        assert rows["sydney"]["is_open"] is False

    def test_the_weekend_shows_every_session_shut(self):
        rows = session_table(datetime(2026, 9, 5, 12, 0, tzinfo=UTC))  # Saturday

        assert all(r["is_open"] is False for r in rows)
