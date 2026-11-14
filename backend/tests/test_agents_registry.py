"""Stage-1 agent registry: complete, honest, and unable to reach execution."""

from __future__ import annotations

import ast
import pathlib
import uuid
from datetime import UTC, datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.agents import registry
from app.agents.messages import AgentMessage, Market, Recommendation
from app.agents.model import (
    AgentGroup,
    AgentRole,
    ImplementationStatus,
    PermissionLevel,
)

BACKEND = pathlib.Path(__file__).resolve().parents[1]
REPO = BACKEND.parent
AGENTS_PKG = BACKEND / "app" / "agents"

#: Packages on the decision, risk and execution path. None may depend on the
#: registry, and the registry may depend on none of them.
TRADING_PATH = ("app.execution", "app.workers", "app.pipeline", "app.brain")


def _imports(path: pathlib.Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    found: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            found.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            found.add(node.module)
    return found


class TestTheRegistryCannotReachExecution:
    def test_the_agents_package_imports_nothing_on_the_trading_path(self):
        offenders = {
            path.name: sorted(m for m in _imports(path) if m.startswith(TRADING_PATH))
            for path in sorted(AGENTS_PKG.glob("*.py"))
        }
        assert {k: v for k, v in offenders.items() if v} == {}

    def test_the_agents_package_imports_only_core_and_itself_from_app(self):
        allowed = ("app.agents", "app.core.enums")
        for path in sorted(AGENTS_PKG.glob("*.py")):
            internal = {m for m in _imports(path) if m == "app" or m.startswith("app.")}
            assert all(m.startswith(allowed) for m in internal), (path.name, internal)

    def test_nothing_on_the_trading_path_imports_the_registry(self):
        offenders = []
        for package in ("execution", "workers", "pipeline", "brain"):
            for path in sorted((BACKEND / "app" / package).rglob("*.py")):
                if any(m.startswith("app.agents") for m in _imports(path)):
                    offenders.append(path.relative_to(BACKEND).as_posix())
        assert offenders == []

    def test_risk_and_safety_modules_do_not_import_the_api_router_either(self):
        for path in sorted((BACKEND / "app").rglob("*.py")):
            relative = path.relative_to(BACKEND).as_posix()
            if relative.startswith("app/api/"):
                continue
            assert "app.api.v1.agents" not in _imports(path), relative


class TestCompleteness:
    def test_exactly_the_51_requested_ids_in_order(self):
        assert registry.ids() == registry.EXPECTED_IDS
        assert len(registry.all_roles()) == 51

    def test_group_sizes(self):
        sizes = {g: len(registry.by_group(g)) for g in AgentGroup}
        assert sizes == {
            AgentGroup.SCALPING: 10,
            AgentGroup.SMART_MONEY: 10,
            AgentGroup.TECHNICAL: 6,
            AgentGroup.PREDICTION: 4,
            AgentGroup.RISK: 5,
            AgentGroup.EXECUTION: 5,
            AgentGroup.CENTRAL: 1,
            AgentGroup.ROCKET: 10,
        }

    def test_every_role_is_fully_described(self):
        for role in registry.all_roles():
            assert role.name_fa and role.name_en, role.id
            assert role.responsibilities, role.id
            assert role.triggers, role.id
            assert len(role.all_restrictions) > len(role.restrictions), role.id

    def test_status_counts_add_up(self):
        assert sum(registry.status_counts().values()) == 51


class TestHonesty:
    def test_every_mapped_module_exists(self):
        missing = [
            (role.id, module)
            for role in registry.all_roles()
            for module in role.modules
            if not (REPO / module).is_file()
        ]
        assert missing == []

    def test_not_implemented_roles_claim_no_code(self):
        for role in registry.all_roles():
            if role.status is ImplementationStatus.NOT_IMPLEMENTED:
                assert role.modules == (), role.id
            else:
                assert role.modules, role.id

    def test_groups_the_audit_found_missing_are_not_upgraded(self):
        """SMC/ICT order blocks, FVG, BOS/CHoCH and most Rocket roles do not
        exist in code. Changing that status needs code, not an edit here."""
        for agent_id in ("SM01", "SM02", "SM03", "SM04", "SM05", "SM07",
                         "RT01", "RT02", "RT05", "RT07", "RT08", "RT09", "RT10",
                         "SC01", "SC02", "SC04"):
            role = registry.get(agent_id)
            assert role is not None
            assert role.status is ImplementationStatus.NOT_IMPLEMENTED, agent_id

    def test_no_role_claims_a_language_model_it_does_not_have(self):
        for role in registry.all_roles():
            text = " ".join((role.notes, *role.responsibilities)).lower()
            if "grok" in text:
                assert "مرحله" in role.notes or "stage" in text, role.id


class TestPermissions:
    def test_no_role_holds_l5(self):
        assert max(int(level) for level in PermissionLevel) == 4
        for role in registry.all_roles():
            assert 1 <= int(role.permission_level) <= 4, role.id

    def test_no_role_overrides_risk_or_submits_orders(self):
        for role in registry.all_roles():
            assert role.may_override_risk is False, role.id
            assert role.can_submit_orders is False, role.id
            assert any("Risk Brain" in r for r in role.all_restrictions), role.id

    def test_a_role_that_tries_to_override_risk_cannot_be_built(self):
        base = registry.get("EX01")
        assert base is not None
        kwargs = {**base.__dict__}
        for flag in ("may_override_risk", "can_submit_orders"):
            with pytest.raises(ValueError):
                AgentRole(**{**kwargs, flag: True})

    def test_a_not_implemented_role_cannot_claim_modules(self):
        base = registry.get("RT01")
        assert base is not None
        with pytest.raises(ValueError):
            AgentRole(**{**base.__dict__, "modules": ("backend/app/brain/risk.py",)})

    def test_only_risk_and_execution_roles_hold_control(self):
        for role in registry.all_roles():
            if role.permission_level is PermissionLevel.CONTROL:
                assert role.group in (AgentGroup.RISK, AgentGroup.EXECUTION), role.id


def _message(**overrides):
    fields = {
        "agent_id": "TA04",
        "timestamp": datetime(2026, 11, 14, 12, 0, tzinfo=UTC),
        "market": Market.FOREX,
        "symbol": "EURUSD",
        "timeframe": "H1",
        "analysis": "trend up on H1",
        "evidence": ["close above 50-bar mean"],
        "confidence": 0.6,
        "risk_assessment": "normal spread, no news window",
        "recommendation": Recommendation.BUY,
        "data_source": "mt5:term-b",
        "model_version": "rules-v1",
    }
    fields.update(overrides)
    return AgentMessage(**fields)


class TestMessageSchema:
    def test_a_valid_message_has_a_unique_id(self):
        first, second = _message(), _message()
        assert isinstance(first.message_id, uuid.UUID)
        assert first.message_id != second.message_id

    def test_the_same_reading_has_the_same_dedup_key(self):
        assert _message().dedup_key == _message().dedup_key
        assert _message().dedup_key != _message(symbol="GBPUSD").dedup_key

    def test_timestamps_are_normalised_to_utc(self):
        tehran = timezone(timedelta(hours=3, minutes=30))
        msg = _message(timestamp=datetime(2026, 11, 14, 15, 30, tzinfo=tehran))
        assert msg.timestamp == datetime(2026, 11, 14, 12, 0, tzinfo=UTC)
        assert msg.dedup_key == _message().dedup_key

    def test_a_naive_timestamp_is_refused(self):
        with pytest.raises(ValidationError):
            _message(timestamp=datetime(2026, 11, 14, 12, 0))

    def test_unknown_agent_is_refused(self):
        with pytest.raises(ValidationError):
            _message(agent_id="XX99")

    def test_direction_without_evidence_is_refused(self):
        with pytest.raises(ValidationError):
            _message(evidence=[])
        assert _message(evidence=[], recommendation=Recommendation.WAIT)

    def test_confidence_is_bounded(self):
        for bad in (-0.1, 1.1):
            with pytest.raises(ValidationError):
                _message(confidence=bad)

    def test_only_control_roles_may_block(self):
        with pytest.raises(ValidationError):
            _message(recommendation=Recommendation.BLOCK)
        assert _message(agent_id="RK01", recommendation=Recommendation.BLOCK)

    def test_unknown_timeframe_and_extra_fields_are_refused(self):
        with pytest.raises(ValidationError):
            _message(timeframe="M7")
        with pytest.raises(ValidationError):
            _message(api_key="x")


@pytest.fixture()
def client(session):
    from app.db.session import get_db
    from app.main import app

    app.dependency_overrides[get_db] = lambda: session
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


class TestEndpoint:
    def test_registry_endpoint_lists_all_51(self, client):
        response = client.get("/api/v1/agents/registry")
        assert response.status_code == 200
        body = response.json()
        assert body["total"] == 51
        assert body["mode"] == "paper_only"
        assert [a["id"] for a in body["agents"]] == list(registry.EXPECTED_IDS)
        assert all(a["can_submit_orders"] is False for a in body["agents"])
        assert all(a["permission_level"] in {"L1", "L2", "L3", "L4"} for a in body["agents"])

    def test_registry_endpoint_is_read_only(self, client):
        assert client.post("/api/v1/agents/registry").status_code == 405
