"""The contract between the API and the pages that read it.

Every other test here checks one side. These check the seam, because that is
where the two halves drift apart silently: the backend renames a field, its own
tests still pass, and the page renders `undefined` in production.

The frontend's TypeScript interfaces are the specification, so they are parsed
out of `api.ts` and compared against what the running API actually returns. A
type that says `blockers: string[]` and an endpoint that returns
`blocking_reasons` both pass their own suites and fail together only here.
"""

from __future__ import annotations

import json
import pathlib
import re

import pytest
from fastapi.testclient import TestClient

API_TS = (
    pathlib.Path(__file__).resolve().parents[2] / "frontend" / "src" / "lib" / "api.ts"
)


@pytest.fixture()
def client(session):
    from app.db.session import get_db
    from app.main import app

    app.dependency_overrides[get_db] = lambda: session
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


def declared_fields(interface: str) -> set[str]:
    """Top-level field names the frontend declares for one interface.

    Nested objects are skipped rather than parsed: a brace-counting parser for
    TypeScript would be its own source of false failures, and the top level is
    where renames actually bite.
    """
    source = API_TS.read_text(encoding="utf-8")
    match = re.search(
        rf"export interface {interface} \{{(.*?)^\}}", source, re.S | re.M
    )
    if match is None:
        raise AssertionError(f"the frontend declares no {interface} interface")

    body = match.group(1)
    fields: set[str] = set()
    depth = 0
    for line in body.splitlines():
        stripped = line.strip()
        if depth == 0 and (found := re.match(r"(\w+)\??:", stripped)):
            fields.add(found.group(1))
        depth += stripped.count("{") - stripped.count("}")
    return fields


class TestTheFrontendTypesMatchTheApi:
    def test_the_contract_file_is_where_the_test_thinks_it_is(self):
        """Guards the guard: a moved file would make every check below vacuous."""
        assert API_TS.exists(), API_TS

    @pytest.mark.parametrize(
        ("interface", "path"),
        [
            ("Posture", "/api/v1/decisions/posture"),
            ("Readiness", "/api/v1/decisions/readiness"),
            ("Health", "/health/ready"),
        ],
    )
    def test_every_declared_field_is_actually_returned(self, client, interface, path):
        response = client.get(path)
        assert response.status_code == 200, response.text

        payload = response.json()
        missing = declared_fields(interface) - set(payload)

        assert not missing, (
            f"the page reads {sorted(missing)} from {path}, and the API does not "
            f"send them — they would render as undefined"
        )

    def test_the_readiness_checks_carry_the_fields_the_table_renders(self, client):
        checks = client.get("/api/v1/decisions/readiness").json()["checks"]

        assert checks, "an empty checks array renders an empty table, not a passing one"
        for field in declared_fields("ReadinessCheck"):
            assert field in checks[0], field

    def test_the_grade_values_the_page_maps_are_the_grades_the_api_sends(self, client):
        """The page maps three grades to badge colours. A fourth would render
        with no colour and read as a passing check."""
        page = (
            pathlib.Path(__file__).resolve().parents[2]
            / "frontend" / "src" / "app" / "posture" / "page.tsx"
        ).read_text(encoding="utf-8")
        mapped = set(re.findall(r"(\w+): \"(?:critical|warning|info)\"", page))

        sent = {c["grade"] for c in client.get("/api/v1/decisions/readiness").json()["checks"]}

        assert sent <= mapped, f"unmapped grades: {sorted(sent - mapped)}"

    def test_the_posture_payload_is_json_serialisable_end_to_end(self, client):
        """Server components receive this as JSON; a stray object would 500."""
        json.dumps(client.get("/api/v1/decisions/posture").json())


class TestThePageCannotOverclaim:
    def test_a_default_deployment_reports_that_it_cannot_trade(self, client):
        assert client.get("/api/v1/decisions/posture").json()["can_trade"] is False

    def test_the_blockers_list_is_never_empty_while_it_cannot_trade(self, client):
        """An empty list beside `can_trade: false` gives the page nothing to
        show, which reads as a system with no explanation for its own state."""
        payload = client.get("/api/v1/decisions/posture").json()

        assert payload["can_trade"] is False
        assert payload["blockers"]

    def test_readiness_never_reports_ready_without_checks(self, client):
        payload = client.get("/api/v1/decisions/readiness").json()

        assert payload["total"] > 0
        assert payload["passed"] <= payload["total"]
