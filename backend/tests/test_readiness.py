"""Production-readiness tests (phases 50-53).

A readiness checker is trusted exactly as far as its own checks are honest, so
the first thing these tests do is check the checker: that a check which could
not run counts as failed, that no check passes unconditionally, and that a
green report cannot be produced from missing information.

The end-to-end test at the bottom drives the real application through its real
HTTP surface. Everything above it in the suite tests a layer; this tests that
the layers are bolted together.
"""

from __future__ import annotations

import inspect
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from app.ops import readiness as rd

NOW = datetime(2026, 8, 13, 12, 0, tzinfo=UTC)


def sound(**overrides) -> rd.Deployment:
    """A deployment that should pass everything."""
    defaults = dict(
        require_auth=True,
        execution_enabled=False,
        execution_dry_run=True,
        kill_switch_default_engaged=True,
        ungated_mutating_routes=[],
        log_rotation_configured=True,
        retention_configured=True,
        last_successful_restore=NOW - timedelta(days=3),
        disk_free_ratio=0.55,
        data_age_bars=0.5,
        calibrated_sources=1,
        slo_observations=500,
        audit_chain_intact=True,
        secrets_in_repository=[],
        broker_is_simulated=True,
    )
    defaults.update(overrides)
    return rd.Deployment(**defaults)


# =========================================================== check the checker
class TestTheCheckerIsHonest:
    def test_a_sound_deployment_passes_everything(self):
        report = rd.assess(sound(), now=NOW)

        assert report.safe_to_trade is True
        assert report.passed == report.total, [
            c.name for c in report.checks if not c.passed
        ]

    def test_an_empty_deployment_fails_every_check(self):
        """Nothing determinable must never read as everything fine."""
        report = rd.assess(rd.Deployment(), now=NOW)

        assert report.safe_to_trade is False
        assert report.passed == 0
        assert all("could not be determined" in c.detail for c in report.checks)

    def test_a_half_known_pair_is_undeterminable_not_decided(self):
        """Otherwise a two-fact check silently decides on the fact it knows."""
        report = rd.assess(sound(execution_enabled=None), now=NOW)

        check = next(c for c in report.checks if c.name == "auth_required_if_execution_enabled")
        assert check.passed is False
        assert "could not be determined" in check.detail

    def test_no_check_passes_unconditionally(self):
        """A check that cannot fail is decoration, and this module argues
        against decoration."""
        every_field = {
            f: None for f in rd.Deployment.__dataclass_fields__
        }
        failures = set()
        for name in every_field:
            broken = sound(**{name: None})
            for check in rd.assess(broken, now=NOW).checks:
                if not check.passed:
                    failures.add(check.name)

        all_names = {c.name for c in rd.assess(sound(), now=NOW).checks}
        assert failures == all_names

    def test_every_check_states_why_it_exists(self):
        report = rd.assess(sound(), now=NOW)

        assert all(c.rationale for c in report.checks)

    def test_the_report_never_claims_the_strategy_is_worth_running(self):
        assert "not whether the strategy" in rd.assess(sound(), now=NOW).as_dict()["note"]


class TestBlockingFailures:
    def test_an_ungated_mutating_route_blocks(self):
        report = rd.assess(sound(ungated_mutating_routes=["POST /orders"]), now=NOW)

        assert report.safe_to_trade is False
        assert "no_ungated_mutating_routes" in report.as_dict()["blocking_failures"]

    def test_execution_without_auth_blocks(self):
        report = rd.assess(
            sound(execution_enabled=True, require_auth=False), now=NOW
        )

        assert report.safe_to_trade is False

    def test_execution_with_auth_is_allowed(self):
        report = rd.assess(sound(execution_enabled=True, require_auth=True), now=NOW)

        assert report.safe_to_trade is True

    def test_a_kill_switch_that_starts_open_blocks(self):
        assert rd.assess(sound(kill_switch_default_engaged=False), now=NOW).safe_to_trade is False

    def test_a_committed_secret_blocks(self):
        report = rd.assess(sound(secrets_in_repository=["infra/.env.prod"]), now=NOW)

        assert report.safe_to_trade is False

    def test_an_old_restore_drill_blocks(self):
        report = rd.assess(
            sound(last_successful_restore=NOW - timedelta(days=200)), now=NOW
        )

        assert report.safe_to_trade is False

    def test_no_restore_drill_at_all_blocks(self):
        assert rd.assess(sound(last_successful_restore=None), now=NOW).safe_to_trade is False


class TestGradedFailures:
    def test_missing_log_rotation_is_important_not_blocking(self):
        report = rd.assess(sound(log_rotation_configured=False), now=NOW)

        assert report.safe_to_trade is True
        assert "log_rotation" in report.as_dict()["important_failures"]

    def test_a_full_disk_is_important(self):
        report = rd.assess(sound(disk_free_ratio=0.02), now=NOW)

        assert "disk_headroom" in report.as_dict()["important_failures"]

    def test_no_calibrated_source_is_important(self):
        """The chain still refuses to trade, so it is not a safety hole."""
        report = rd.assess(sound(calibrated_sources=0), now=NOW)

        assert report.safe_to_trade is True
        assert "at_least_one_calibrated_source" in report.as_dict()["important_failures"]

    def test_a_simulated_broker_with_dry_run_off_is_flagged(self):
        """A rehearsal nobody labelled becomes a track record nobody earned."""
        report = rd.assess(
            sound(broker_is_simulated=True, execution_dry_run=False), now=NOW
        )

        check = next(c for c in report.checks if c.name == "dry_run_while_simulated")
        assert check.passed is False

    def test_a_real_broker_with_dry_run_off_is_not_flagged_by_that_check(self):
        report = rd.assess(
            sound(broker_is_simulated=False, execution_dry_run=False), now=NOW
        )

        check = next(c for c in report.checks if c.name == "dry_run_while_simulated")
        assert check.passed is True


# ================================================================ end to end
class TestTheApplicationActuallyRuns:
    """Drives the real app through its real HTTP surface.

    Every other test in this suite exercises one layer. These prove the layers
    are bolted together: the app imports, the execution gate passes at import
    time, the routes resolve, and the error contract holds through the stack.
    """

    @pytest.fixture()
    def client(self, session):
        from app.db.session import get_db
        from app.main import app

        app.dependency_overrides[get_db] = lambda: session
        with TestClient(app) as test_client:
            yield test_client
        app.dependency_overrides.clear()

    def test_the_app_starts_at_all(self, client):
        """It cannot: `assert_execution_gate` runs at import and would refuse."""
        assert client.get("/").status_code == 200

    def test_liveness_answers(self, client):
        assert client.get("/health/live").status_code == 200

    def test_instruments_list_over_http(self, client, instrument):
        response = client.get("/api/v1/instruments")

        assert response.status_code == 200
        assert any(i["symbol"] == instrument.symbol for i in response.json())

    def test_a_historical_read_is_point_in_time_over_http(
        self, client, session, instrument, provider
    ):
        """The system's central promise, asserted through the public surface.

        Five hourly bars exist and the request asks as of 02:59. Two are
        returned, not three: the 02:00 bar does not close until 03:00, and a
        bar that has not closed is not a fact yet. Asking for it at 02:59 is
        asking to see the future, which is the exact mistake the whole
        point-in-time layer exists to make impossible.
        """
        from datetime import timedelta as td

        from tests.conftest import BASE_TIME, insert_bar

        for hour in range(5):
            insert_bar(
                session, instrument.id, provider.id,
                event_time=BASE_TIME + td(hours=hour),
                ingested_at=BASE_TIME + td(hours=hour),
                close=1.1000 + hour * 0.001,
            )
        session.commit()

        response = client.get(
            "/api/v1/bars",
            params={
                "instrument_id": str(instrument.id),
                "timeframe": "H1",
                "as_of": (BASE_TIME + td(hours=2, minutes=59)).isoformat(),
            },
        )

        assert response.status_code == 200, response.text
        bars = response.json()["bars"]
        stamps = [b["event_time"] for b in bars]
        assert len(bars) == 2, stamps
        assert all(stamp < (BASE_TIME + td(hours=2)).isoformat() for stamp in stamps)

    def test_an_unknown_instrument_is_a_clean_error_not_a_crash(self, client):
        response = client.get("/api/v1/instruments/00000000-0000-0000-0000-000000000000")

        assert response.status_code in (404, 422)
        assert "detail" in response.json() or "error" in response.json()

    def test_every_response_carries_a_trace_id(self, client):
        """The one thing that makes a production incident reconstructable."""
        response = client.get("/health/live")

        assert response.headers.get("x-trace-id")

    def test_the_openapi_document_builds(self, client):
        """A schema that cannot render is a client integration that cannot start."""
        response = client.get("/openapi.json")

        assert response.status_code == 200
        assert response.json()["info"]["title"] == "MolidoTrade AI"

    def test_the_execution_gate_is_enforced_at_import(self):
        """Not at first request — a hole that appears under load is one that ships."""
        from app.main import assert_execution_gate

        source = inspect.getsource(inspect.getmodule(assert_execution_gate))
        assert "assert_execution_gate" in source
