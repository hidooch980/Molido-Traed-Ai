"""The scan finds what looks like a credential, ignores what looks like a
template, and never writes a value down."""

from __future__ import annotations

import json
import pathlib

from app.ops import secrets_scan as scan


def repo(tmp_path: pathlib.Path, files: dict[str, str]) -> pathlib.Path:
    for name, body in files.items():
        target = tmp_path / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(body, encoding="utf-8")
    return tmp_path


class TestValues:
    def test_a_private_key_block_is_a_secret(self, tmp_path):
        root = repo(tmp_path, {"deploy/id.pem": "-----BEGIN RSA PRIVATE KEY-----\nabc\n"})
        result = scan.scan_paths(root, ["deploy/id.pem"])
        assert [f.category for f in result.secrets] == ["private-key"]
        assert not result.passed

    def test_a_telegram_token_is_a_secret(self, tmp_path):
        root = repo(tmp_path, {"notes.txt": "bot: 1234567890:AAF-abcdefghijklmnopqrstuvwxyz0123456\n"})
        assert [f.category for f in scan.scan_paths(root, ["notes.txt"]).secrets] == ["telegram-bot-token"]

    def test_a_random_looking_password_assignment_is_a_secret(self, tmp_path):
        root = repo(tmp_path, {"settings.ini": "password = q7Vh2LmZp9Xs4TbR8wYc\n"})
        assert [f.category for f in scan.scan_paths(root, ["settings.ini"]).secrets] == ["credential-assignment"]

    def test_a_placeholder_is_not(self, tmp_path):
        root = repo(tmp_path, {".env.example": "API_KEY=<your-api-key-here>\nPASSWORD=changeme-please-now\n"})
        result = scan.scan_paths(root, [".env.example"])
        assert result.passed and result.findings == []

    def test_a_test_fixture_password_is_not(self, tmp_path):
        root = repo(tmp_path, {"tests/test_login.py": 'password = "correct-horse-battery-staple-1"\n'})
        assert scan.scan_paths(root, ["tests/test_login.py"]).passed

    def test_but_a_real_key_in_a_test_is(self, tmp_path):
        root = repo(tmp_path, {"tests/fixture.pem": "-----BEGIN EC PRIVATE KEY-----\n"})
        assert not scan.scan_paths(root, ["tests/fixture.pem"]).passed


class TestNames:
    def test_a_tracked_env_file_with_a_public_url_is_shape_not_secret(self, tmp_path):
        root = repo(tmp_path, {"frontend/.env.local": "NEXT_PUBLIC_API_URL=https://trade.example/api\n"})
        result = scan.scan_paths(root, ["frontend/.env.local"])
        assert result.passed
        assert [f.severity for f in result.findings] == ["shape"]
        assert "env-file" in result.findings[0].category

    def test_a_template_name_is_not_even_shape(self, tmp_path):
        root = repo(tmp_path, {".env.example": "X=1\n"})
        assert scan.scan_paths(root, [".env.example"]).findings == []


class TestTheNoteIsSafe:
    def test_values_never_appear_in_the_output(self, tmp_path):
        secret = "q7Vh2LmZp9Xs4TbR8wYc"
        root = repo(tmp_path, {"a.cfg": f"api_key = {secret}\n"})
        body = json.dumps(scan.scan_paths(root, ["a.cfg"]).as_dict())
        assert secret not in body
        assert "a.cfg" in body

    def test_an_unreadably_large_file_makes_the_scan_incomplete(self, tmp_path):
        big = tmp_path / "dump.sql"
        big.write_bytes(b"x" * (scan.MAX_FILE_BYTES + 1))
        result = scan.scan_paths(tmp_path, ["dump.sql"])
        assert result.complete is False
        assert not result.passed


class TestThisRepository:
    def test_the_checkout_holds_no_secret_shaped_value(self):
        """The live check, on the real tree. A failure here is a finding,
        not a flaky test: go and look at the path it names."""
        root = pathlib.Path(__file__).resolve().parents[2]
        result = scan.scan(root)
        assert result.scanned_files > 100
        assert result.secrets == [], [(f.path, f.category, f.line) for f in result.secrets]
