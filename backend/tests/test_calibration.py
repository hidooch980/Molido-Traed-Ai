"""A source is calibrated on its forward record against its control, or not."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from app.models.journal import ARM_CONTROL, ARM_RULE, JournalEntry
from app.ops import calibration

NOW = datetime(2026, 9, 2, 20, 0, tzinfo=UTC)


def journal(session, strategy: str, *, resolved: int, rule_wins: int, control_wins: int):
    for arm, wins in ((ARM_RULE, rule_wins), (ARM_CONTROL, control_wins)):
        for i in range(resolved):
            won = i < wins
            session.add(
                JournalEntry(
                    symbol=f"S{i % 7}",
                    decision="long",
                    account_key="k",
                    opened_at=NOW - timedelta(hours=resolved - i),
                    closed_at=NOW - timedelta(hours=resolved - i) + timedelta(hours=2),
                    r_multiple=1.0 if won else -1.0,
                    outcome="win" if won else "loss",
                    arm=arm,
                    price_source="test",
                    timeframe="H1",
                    strategy=strategy,
                    before={},
                    during={},
                    after={},
                )
            )
    session.commit()


class TestPolicy:
    def test_a_large_forward_edge_over_control_is_calibrated(self, session):
        journal(session, "stretch", resolved=600, rule_wins=330, control_wins=290)
        report = calibration.measure(session, now=NOW)

        [source] = report.sources
        assert source.sample_sufficient
        assert source.z is not None and source.z >= calibration.REQUIRED_Z
        assert source.calibrated is True
        assert report.as_dict()["calibrated_sources"] == 1

    def test_a_small_sample_is_a_sample_not_a_calibration(self, session):
        journal(session, "rsi", resolved=34, rule_wins=17, control_wins=22)
        [source] = calibration.measure(session, now=NOW).sources

        assert source.sample_sufficient is False
        assert source.shortfall == calibration.MIN_RESOLVED - 34
        assert source.calibrated is False

    def test_beating_the_control_inside_the_noise_is_not_calibrated(self, session):
        journal(session, "flat", resolved=600, rule_wins=302, control_wins=298)
        [source] = calibration.measure(session, now=NOW).sources

        assert source.sample_sufficient
        assert source.calibrated is False

    def test_no_journal_means_no_calibrated_source(self, session):
        assert calibration.measure(session, now=NOW).calibrated == []

    def test_the_period_is_reported(self, session):
        journal(session, "stretch", resolved=210, rule_wins=130, control_wins=100)
        payload = calibration.measure(session, now=NOW).as_dict()["sources"][0]

        assert payload["period_start"] is not None and payload["period_end"] is not None
        assert payload["oos"].startswith("forward journal")
