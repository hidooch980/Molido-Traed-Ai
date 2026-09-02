"""Observations land in a table, and the window counts what is really there."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from app.ops import slo

NOW = datetime(2026, 9, 2, 20, 0, tzinfo=UTC)


class TestWindow:
    def test_an_empty_table_is_an_empty_window(self, session):
        window = slo.window(session, now=NOW)

        assert window.observations == 0
        assert window.populated is False
        assert window.latency_p95_ms is None

    def test_observations_inside_the_window_count_and_older_ones_do_not(self, session):
        for i in range(120):
            slo.record(session, slo.METRIC_LATENCY, 20.0 + i, at=NOW - timedelta(minutes=i))
        slo.record(session, slo.METRIC_LATENCY, 5000.0, at=NOW - timedelta(days=2))
        session.commit()

        window = slo.window(session, now=NOW)

        assert window.observations == 120
        assert window.populated is True
        assert window.latency_p95_ms is not None and window.latency_p95_ms < 5000.0

    def test_availability_is_the_share_of_non_5xx(self, session):
        for status in (200, 200, 200, 503):
            slo.record(session, slo.METRIC_AVAILABILITY, 0.0 if status >= 500 else 1.0, at=NOW)
        session.commit()

        window = slo.window(session, now=NOW)

        assert window.availability == 0.75
        assert window.error_rate == 0.25


class TestRequestBuffer:
    def test_health_probes_are_not_observations(self):
        assert slo.observe_request("/health/ready", 200, 1.0) is False

    def test_requests_are_buffered_then_flushed_as_two_metrics(self, session):
        slo.REQUESTS.drain()
        for _ in range(3):
            slo.observe_request("/api/v1/decisions/readiness", 200, 12.0)
        slo.observe_request("/api/v1/x", 500, 30.0)

        written = slo.flush_requests(session)
        window = slo.window(session)

        assert written == 4
        assert window.by_metric[slo.METRIC_LATENCY] == 4
        assert window.by_metric[slo.METRIC_AVAILABILITY] == 4
        assert window.availability == 0.75
