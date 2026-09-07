"""The weekly scorecard: every brain's week, beside its own control."""

from datetime import UTC, datetime, timedelta

from app.learning.weekly import THIN_SAMPLE, build_report, verdicts
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


class TestTheJournalCanFinallyReachAVerdict:
    """`build_report` is a progress page and never refuses. This is the other
    question - does the forward record yet support saying a brain has an edge
    - and nothing used to ask it: `scorecard.score` issues that verdict and
    its only caller took hand-typed win and loss counts, so the journal the
    whole point-in-time apparatus exists to fill had no path to a verdict."""

    def a_move(self, session, *, n, hours_ago, r, strategy="cross-sectional-stretch"):
        """n decisions taken at one instant - one market move, several
        angles."""
        rows = []
        for i in range(n):
            row = entry(
                session,
                strategy=strategy,
                r=r,
                days_ago=hours_ago / 24,
                symbol=f"SYM{i:02d}JPY",
            )
            row.opened_at = NOW - timedelta(hours=hours_ago)
            rows.append(row)
        session.flush()
        return rows

    def test_sixty_decisions_at_six_instants_refuses(self, session):
        """The shape of 2026-09-07: 26 of 29 resolved rule-arm decisions were
        JPY crosses opened within a few hours, all one side of one yen move,
        all stopped out together. Read as 26 trials that is a devastating
        result about the rule. Read honestly it is one trade that lost."""
        for hour in range(6):
            self.a_move(session, n=10, hours_ago=hour + 1, r=-1.0)

        card = next(
            c for c in verdicts(session)["cards"]
            if c["strategy"] == "cross-sectional-stretch"
        )

        assert card["trials"] == 60
        assert card["effective_trials"] == 6
        assert card["verdict"] == "insufficient"
        assert card["trials_per_instant"] == 10.0

    def test_a_retracted_decision_is_out_of_the_verdict_too(self, session):
        """A decision withdrawn from the record is withdrawn from the count.
        Leaving it in would let a batch disowned for being taken on stale
        prices still count against the brain that did not really take it."""
        kept = self.a_move(session, n=2, hours_ago=1, r=-1.0)
        gone = self.a_move(session, n=3, hours_ago=2, r=-1.0)
        for row in gone:
            row.after = {"retracted": {"r_multiple": -1.0}, "reason": "stale prices"}
        session.flush()

        payload = verdicts(session)
        card = next(
            c for c in payload["cards"]
            if c["strategy"] == "cross-sectional-stretch"
        )

        assert payload["retracted_excluded"] == 3
        assert card["trials"] == len(kept)

    def test_the_control_arm_is_not_scored_as_the_rule(self, session):
        """The control is a coin flip on the same instrument at the same
        instant. It belongs in the comparison `measure` makes, not in a hit
        rate about the rule."""
        self.a_move(session, n=2, hours_ago=1, r=-1.0)
        entry(session, arm=ARM_CONTROL, r=1.0, symbol="EURJPY")

        card = next(
            c for c in verdicts(session)["cards"]
            if c["strategy"] == "cross-sectional-stretch"
        )

        assert card["trials"] == 2
