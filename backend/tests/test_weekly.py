"""The weekly scorecard: every brain's week, beside its own control."""

from datetime import UTC, datetime, timedelta

from app.learning.weekly import THIN_SAMPLE, build_report
from app.models.journal import ARM_CONTROL, ARM_RULE, JournalEntry

NOW = datetime.now(UTC)


def entry(session, *, strategy="cross-sectional-stretch", arm=ARM_RULE,
          r=None, orders=None, days_ago=1, symbol="EURUSD"):
    row = JournalEntry(
        symbol=symbol,
        decision="long",
        opened_at=NOW - timedelta(days=days_ago),
        arm=arm,
        strategy=strategy,
        r_multiple=r,
        during={"orders": orders} if orders else {},
    )
    session.add(row)
    session.flush()
    return row


class TestTheWeeklyScorecard:
    def test_each_brain_is_read_beside_its_own_control(self, session):
        entry(session, r=0.5)
        entry(session, r=-1.0, symbol="GBPUSD")
        entry(session, arm=ARM_CONTROL, r=-0.5)
        entry(session, strategy="carry-differential", r=1.0, symbol="AUDJPY")

        report = build_report(session)
        by_name = {b["strategy"]: b for b in report["brains"]}

        incumbent = by_name["cross-sectional-stretch"]
        assert incumbent["resolved"] == 2
        assert incumbent["total_r"] == -0.5
        assert incumbent["control_mean_r"] == -0.5
        # -0.25 mean against a -0.5 control: a losing week that still beat
        # its coin flip - exactly the distinction raw R hides.
        assert incumbent["edge_r"] == 0.25
        assert by_name["carry-differential"]["control_mean_r"] is None

    def test_a_thin_sample_is_labelled_not_smoothed(self, session):
        entry(session, r=2.0)

        report = build_report(session)

        assert report["brains"][0]["thin_sample"] is True
        assert THIN_SAMPLE > 1

    def test_orders_are_counted_per_account(self, session):
        entry(session, r=1.0, orders={"111": {"state": "filled"}})
        entry(session, symbol="GBPUSD",
              orders={"111": {"state": "rejected"}, "222": {"state": "filled"}})

        report = build_report(session)

        assert report["accounts"]["111"] == {
            "sent": 2, "filled": 1, "rejected": 1, "resolved_r": 1.0,
        }
        assert report["accounts"]["222"]["filled"] == 1

    def test_old_rows_are_outside_the_window(self, session):
        entry(session, r=5.0, days_ago=30)

        report = build_report(session)

        assert report["brains"] == []
