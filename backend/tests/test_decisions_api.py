"""Decision, posture and readiness endpoint tests (phases 38-40).

These are the three screens an operator actually opens, so the tests are about
what the screens must never say: that the system can trade when it cannot, that
a decision is an order, or that a figure was measured when nobody measured it.
"""

from __future__ import annotations

from datetime import timedelta

import pytest
from fastapi.testclient import TestClient

from app.core.enums import Timeframe
from tests.conftest import BASE_TIME, insert_bar


@pytest.fixture()
def client(session):
    from app.db.session import get_db
    from app.main import app

    app.dependency_overrides[get_db] = lambda: session
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


def seed(session, instrument, provider, count=400):
    for hour in range(count):
        close = 1.10 + hour * 0.0002
        insert_bar(
            session, instrument.id, provider.id,
            event_time=BASE_TIME + timedelta(hours=hour),
            ingested_at=BASE_TIME + timedelta(hours=hour),
            close=round(close, 8), open_=round(close - 0.0002, 8),
        )
    session.commit()


class TestPosture:
    def test_the_default_deployment_cannot_trade(self, client):
        payload = client.get("/api/v1/decisions/posture").json()

        assert payload["can_trade"] is False
        assert len(payload["blockers"]) >= 3

    def test_every_blocker_is_named(self, client):
        blockers = client.get("/api/v1/decisions/posture").json()["blockers"]

        joined = " ".join(blockers)
        assert "disabled" in joined
        assert "dry run" in joined
        assert "authentication" in joined

    def test_it_reports_the_live_router_table(self, client):
        """A posture view built from a stored summary reassures during the
        incident it should be flagging."""
        payload = client.get("/api/v1/decisions/posture").json()

        # Mutating routes exist now and more will. Pinning the exact list
        # turns every new feature into a failing test that teaches nothing;
        # what must stay true is that none of them is ungated, which is the
        # condition the gate refuses to boot on.
        assert payload["routes"]["ungated"] == []
        assert payload["routes"]["mutating"], "the walk found no mutating routes at all"
        assert payload["routes"]["ungated"] == []

    def test_it_changes_nothing(self, client):
        assert "changes nothing" in client.get("/api/v1/decisions/posture").json()["note"]


class TestReadiness:
    def test_readiness_is_not_health(self, client):
        """A process can be entirely healthy and entirely unready."""
        health = client.get("/health/live")
        readiness = client.get("/api/v1/decisions/readiness")

        assert health.status_code == 200
        assert readiness.json()["safe_to_trade"] is False

    def test_what_the_process_cannot_see_is_graded_as_unknown(self, client):
        """Guessing the host's disk or restore history is the one thing the
        readiness module refuses to do."""
        checks = {c["name"]: c for c in client.get("/api/v1/decisions/readiness").json()["checks"]}

        assert "could not be determined" in checks["disk_headroom"]["detail"]
        assert "could not be determined" in checks["restore_drill_recent"]["detail"]

    def test_what_it_can_see_is_graded_properly(self, client):
        checks = {c["name"]: c for c in client.get("/api/v1/decisions/readiness").json()["checks"]}

        assert checks["no_ungated_mutating_routes"]["passed"] is True
        assert checks["kill_switch_defaults_engaged"]["passed"] is True

    def test_it_never_grades_the_strategy(self, client):
        payload = client.get("/api/v1/decisions/readiness").json()

        assert "not whether the strategy" in payload["note"]


class TestDecisionPreview:
    def test_a_decision_returns_its_trace(self, client, session, instrument, provider):
        seed(session, instrument, provider)

        response = client.get(
            f"/api/v1/decisions/{instrument.id}",
            params={"timeframe": Timeframe.H1.value,
                    "as_of": (BASE_TIME + timedelta(hours=399)).isoformat()},
        )

        assert response.status_code == 200
        payload = response.json()
        assert payload["symbol"] == instrument.symbol
        assert isinstance(payload["stages"], list)

    def test_the_chain_stops_and_the_trace_says_where(
        self, client, session, instrument, provider
    ):
        seed(session, instrument, provider)

        payload = client.get(
            f"/api/v1/decisions/{instrument.id}",
            params={"as_of": (BASE_TIME + timedelta(hours=399)).isoformat()},
        ).json()

        assert payload["reached_intent"] is False
        assert payload["stopped_at"] is not None

    def test_a_decision_is_never_an_order(self, client, session, instrument, provider):
        seed(session, instrument, provider)

        payload = client.get(
            f"/api/v1/decisions/{instrument.id}",
            params={"as_of": (BASE_TIME + timedelta(hours=399)).isoformat()},
        ).json()

        assert payload["authorises_execution"] is False

    def test_the_policy_constants_are_visible_to_the_reader(
        self, client, session, instrument, provider
    ):
        """So nobody reads the levels as derived facts."""
        seed(session, instrument, provider)

        payload = client.get(
            f"/api/v1/decisions/{instrument.id}",
            params={"as_of": (BASE_TIME + timedelta(hours=399)).isoformat()},
        ).json()

        assert payload["policy"]["stop_atr_multiple"] > 0

    def test_an_unknown_instrument_is_a_clean_error(self, client):
        response = client.get("/api/v1/decisions/00000000-0000-0000-0000-000000000000")

        assert response.status_code in (404, 409, 422)

    def test_a_non_positive_equity_is_refused(self, client, instrument):
        response = client.get(
            f"/api/v1/decisions/{instrument.id}", params={"equity": 0}
        )

        assert response.status_code == 422

    def test_the_preview_invents_no_trade_history(
        self, client, session, instrument, provider
    ):
        """A plausible history would let stress project survival for an account
        that has never traded."""
        seed(session, instrument, provider)

        payload = client.get(
            f"/api/v1/decisions/{instrument.id}",
            params={"as_of": (BASE_TIME + timedelta(hours=399)).isoformat()},
        ).json()
        stress = [s for s in payload["stages"] if s["stage"] == "stress"]

        assert stress == [] or stress[0]["passed"] is False


class TestTheSecondBrainReadsTheSameTrace:
    """The analysis endpoint returns the chain's decision and one opinion about
    it, side by side and never merged. A response that blended them would let a
    sentence the model wrote be read as a step the chain took."""

    @pytest.fixture()
    def signed_in(self, session):
        """A caller holding SIMULATE, which the analysis endpoint requires."""
        import uuid as uuid_module

        from app.api.deps import ROLE_PERMISSIONS, Principal, resolve_principal
        from app.core.enums import UserRole
        from app.db.session import get_db
        from app.main import app

        app.dependency_overrides[get_db] = lambda: session
        app.dependency_overrides[resolve_principal] = lambda: Principal(
            tenant_id=uuid_module.uuid4(),
            user_id=uuid_module.uuid4(),
            role=UserRole.ANALYST,
            permissions=frozenset(ROLE_PERMISSIONS[UserRole.ANALYST]),
            authenticated=True,
        )
        with TestClient(app) as test_client:
            yield test_client
        app.dependency_overrides.clear()

    def test_reading_alone_is_not_enough_to_reach_it(self, client, session, instrument, provider):
        """It costs money to answer. A page polling it on READ would bill the
        account holder for a refresh they did not know they made."""
        seed(session, instrument, provider)

        response = client.get(f"/api/v1/decisions/{instrument.id}/analysis")

        assert response.status_code in (401, 403)

    def test_the_trace_and_the_analysis_stay_apart(self, signed_in, session, instrument, provider):
        seed(session, instrument, provider)

        payload = signed_in.get(f"/api/v1/decisions/{instrument.id}/analysis").json()

        assert "trace" in payload
        assert "analysis" in payload
        assert payload["trace"]["symbol"] == instrument.symbol

    def test_it_is_the_same_trace_the_plain_endpoint_returns(
        self, signed_in, session, instrument, provider
    ):
        """Two constructions that drifted would mean the analysis explains a
        decision the operator never saw."""
        seed(session, instrument, provider)

        plain = signed_in.get(f"/api/v1/decisions/{instrument.id}").json()
        analysed = signed_in.get(f"/api/v1/decisions/{instrument.id}/analysis").json()

        assert analysed["trace"]["stopped_at"] == plain["stopped_at"]
        assert analysed["trace"]["reached_intent"] == plain["reached_intent"]
        assert analysed["trace"]["symbol"] == plain["symbol"]

    def test_with_no_key_it_says_so_rather_than_failing(
        self, signed_in, session, instrument, provider
    ):
        """The deployment's actual state. A missing commentary layer must not
        turn a working decision endpoint into a 500."""
        seed(session, instrument, provider)

        response = signed_in.get(f"/api/v1/decisions/{instrument.id}/analysis")

        assert response.status_code == 200
        assert response.json()["analysis"]["available"] is False
        assert response.json()["analysis"]["unavailable_because"]

    def test_the_answer_says_it_reaches_nothing(self, signed_in, session, instrument, provider):
        seed(session, instrument, provider)

        payload = signed_in.get(f"/api/v1/decisions/{instrument.id}/analysis").json()

        assert "connected to nothing" in payload["note"]

    def test_what_it_said_is_recorded_even_when_it_said_nothing(
        self, signed_in, session, instrument, provider
    ):
        """Only keeping the answers somebody liked would make "was the analyst
        right" unanswerable."""
        from sqlalchemy import select

        from app.core.enums import AuditEventType
        from app.models.audit import AuditEvent

        seed(session, instrument, provider)
        signed_in.get(f"/api/v1/decisions/{instrument.id}/analysis")

        rows = list(
            session.scalars(
                select(AuditEvent).where(
                    AuditEvent.event_type == str(AuditEventType.ANALYST_SPOKE)
                )
            )
        )

        assert len(rows) == 1
        assert rows[0].payload["available"] is False
        assert rows[0].payload["stopped_at"], "the gate that ended it is the scoring question"


class TestTheDifferentialReachesTheChain:
    """The route fetches the carry input; the chain must not.

    The pipeline takes `rate_differential` as an argument because a chain that
    reads "now" from inside itself can never be replayed over history. That
    puts the fetching on this route - and fetching is exactly the step that can
    quietly fail to happen, because the chain runs perfectly well without it
    and simply leaves the swap in the unmeasured list, which is where it had
    silently sat for every decision this deployment has ever made.
    """

    def test_the_route_asks_for_the_differential(
        self, client, session, instrument, provider, monkeypatch
    ):
        seed(session, instrument, provider)

        from app.services import policy_rates

        asked: list[tuple[str, str]] = []

        def fake_differential(base, quote, rates=None):
            asked.append((base, quote))
            return -1.375

        monkeypatch.setattr(policy_rates, "differential", fake_differential)

        client.get(
            f"/api/v1/decisions/{instrument.id}",
            params={
                "timeframe": Timeframe.H1.value,
                "as_of": (BASE_TIME + timedelta(hours=399)).isoformat(),
            },
        )

        # The fixture instrument is EUR/USD, and both of its legs have a
        # policy rate. Asserting the pair rather than a bare call count,
        # because handing the legs over in the wrong order silently inverts
        # the carry.
        assert asked == [("EUR", "USD")]

    def test_an_unreadable_feed_does_not_break_the_decision(
        self, client, session, instrument, provider, monkeypatch
    ):
        """The differential is a term of a sum, not a gate.

        The chain's rule that "could not check" equals "failed" governs its
        gates. A rate feed on another continent being unreachable has to
        degrade the answer - swap returns to unmeasured, and the cost model
        says so by name - rather than turn a decision into a 500.
        """
        seed(session, instrument, provider)

        from app.core.errors import ProviderError
        from app.services import policy_rates

        def down(base, quote, rates=None):
            raise ProviderError("the policy rate feed answered 503")

        monkeypatch.setattr(policy_rates, "differential", down)

        response = client.get(
            f"/api/v1/decisions/{instrument.id}",
            params={
                "timeframe": Timeframe.H1.value,
                "as_of": (BASE_TIME + timedelta(hours=399)).isoformat(),
            },
        )

        assert response.status_code == 200
