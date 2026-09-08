"""The host-side kill switch command, which nothing else covered.

`killswitch_store` was tested thoroughly and the command that drives it was
not tested at all - it sat at 0% while being the only path a human has to
halt or release trading, and the only writer of the file every gate reads.

The module's own docstring makes three promises a test can hold it to: the
switch moves even when the database is down, a release names somebody, and
nothing here is reachable without a human at the host. Each of those is a
class below. The remaining class is the plain reporting an operator reads at
three in the morning, when the output of `status` is the whole story.
"""

from __future__ import annotations

import json

import pytest

from app.execution import killswitch as cli
from app.execution import killswitch_store as store
from app.execution.safety import KillSwitch


@pytest.fixture()
def state_file(tmp_path, monkeypatch):
    """Point the command at a scratch file.

    Both the command and the store read `DEFAULT_STATE_PATH` at call time, so
    patching the attribute is enough and no test touches /var/lib/molido.
    """
    where = tmp_path / "kill-switch.json"
    monkeypatch.setattr(store, "DEFAULT_STATE_PATH", where)
    return where


@pytest.fixture()
def silent_audit(monkeypatch):
    """Record audit calls without a database, and report them as audited."""
    seen: list[tuple[str, str, str]] = []

    def fake(action: str, by: str, reason: str) -> str:
        seen.append((action, by, reason))
        return "audited"

    monkeypatch.setattr(cli, "_audit", fake)
    return seen


def run(argv, capsys) -> tuple[int, dict]:
    """Run the command and parse what it printed on stdout."""
    code = cli.main(argv)
    out = capsys.readouterr().out
    return code, (json.loads(out) if out.strip() else {})


class TestStatusReportsWithoutChangingAnything:
    def test_status_on_a_missing_file_reports_engaged(self, state_file, capsys):
        code, body = run(["status"], capsys)

        assert code == 0
        assert body["engaged"] is True

    def test_status_does_not_create_the_file(self, state_file, capsys):
        run(["status"], capsys)

        assert not state_file.exists()

    def test_status_names_the_path_it_read(self, state_file, capsys):
        _, body = run(["status"], capsys)

        assert body["path"] == str(state_file)

    def test_status_explains_why_it_is_engaged(self, state_file, capsys):
        _, body = run(["status"], capsys)

        assert "halted until somebody deliberately allows it" in body["reason"]

    def test_status_reports_a_release_that_was_written(
        self, state_file, capsys, silent_audit
    ):
        run(["release", "--by", "aziz", "--reason", "verified"], capsys)

        _, body = run(["status"], capsys)

        assert body["engaged"] is False
        assert body["engaged_by"] == "aziz"

    def test_status_reports_a_halt_that_was_written(
        self, state_file, capsys, silent_audit
    ):
        run(["engage", "--by", "aziz", "--reason", "rolling the expert"], capsys)

        _, body = run(["status"], capsys)

        assert body["engaged"] is True
        assert "rolling the expert" in body["reason"]

    def test_status_is_prose_an_operator_can_read(self, state_file, capsys):
        cli.main(["status"])
        out = capsys.readouterr().out

        # Indented, not one line: this is read by a person, at the host,
        # while something is already wrong.
        assert "\n" in out.strip()

    def test_status_output_is_valid_json(self, state_file, capsys):
        cli.main(["status"])

        json.loads(capsys.readouterr().out)

    def test_status_reports_an_unreadable_file_as_engaged(self, state_file, capsys):
        state_file.write_text("{not json", encoding="utf-8")

        _, body = run(["status"], capsys)

        assert body["engaged"] is True

    def test_status_reports_an_unrecognised_state_as_engaged(self, state_file, capsys):
        state_file.write_text(json.dumps({"state": "maybe"}), encoding="utf-8")

        _, body = run(["status"], capsys)

        assert body["engaged"] is True

    def test_status_reports_an_unattributed_release_as_engaged(
        self, state_file, capsys
    ):
        state_file.write_text(
            json.dumps({"state": "disengaged", "by": ""}), encoding="utf-8"
        )

        _, body = run(["status"], capsys)

        assert body["engaged"] is True


class TestEngageHalts:
    def test_engage_writes_an_engaged_file(self, state_file, capsys, silent_audit):
        run(["engage", "--by", "aziz", "--reason", "rolling the expert"], capsys)

        assert json.loads(state_file.read_text(encoding="utf-8"))["state"] == "engaged"

    def test_engage_returns_zero(self, state_file, capsys, silent_audit):
        code, _ = run(["engage", "--by", "aziz", "--reason", "why"], capsys)

        assert code == 0

    def test_engage_records_the_reason_verbatim(self, state_file, capsys, silent_audit):
        run(["engage", "--by", "aziz", "--reason", "expert is being rolled"], capsys)

        assert "expert is being rolled" in store.load(state_file).reason

    def test_engage_records_who(self, state_file, capsys, silent_audit):
        run(["engage", "--by", "aziz", "--reason", "why"], capsys)

        assert json.loads(state_file.read_text(encoding="utf-8"))["by"] == "aziz"

    def test_engage_stamps_a_time(self, state_file, capsys, silent_audit):
        run(["engage", "--by", "aziz", "--reason", "why"], capsys)

        assert json.loads(state_file.read_text(encoding="utf-8"))["at"]

    def test_engage_over_a_release_halts_again(self, state_file, capsys, silent_audit):
        run(["release", "--by", "aziz", "--reason", "verified"], capsys)

        run(["engage", "--by", "aziz", "--reason", "second thoughts"], capsys)

        assert store.load(state_file).engaged is True

    def test_engage_is_idempotent(self, state_file, capsys, silent_audit):
        run(["engage", "--by", "aziz", "--reason", "one"], capsys)
        run(["engage", "--by", "aziz", "--reason", "two"], capsys)

        switch = store.load(state_file)
        assert switch.engaged is True
        assert "two" in switch.reason

    def test_engage_prints_the_state_it_reread(self, state_file, capsys, silent_audit):
        _, body = run(["engage", "--by", "aziz", "--reason", "why"], capsys)

        # Reread from disk rather than echoed from memory: the operator is
        # being told what the next cycle will see, not what was intended.
        assert body["engaged"] is store.load(state_file).engaged

    def test_engage_prints_the_path(self, state_file, capsys, silent_audit):
        _, body = run(["engage", "--by", "aziz", "--reason", "why"], capsys)

        assert body["path"] == str(state_file)

    def test_engage_reports_the_audit_outcome(self, state_file, capsys, silent_audit):
        _, body = run(["engage", "--by", "aziz", "--reason", "why"], capsys)

        assert body["audit"] == "audited"

    def test_engage_passes_who_and_why_to_the_audit(
        self, state_file, capsys, silent_audit
    ):
        run(["engage", "--by", "aziz", "--reason", "rolling"], capsys)

        assert silent_audit == [("engage", "aziz", "rolling")]

    def test_engage_creates_the_parent_directory(
        self, tmp_path, monkeypatch, capsys, silent_audit
    ):
        deep = tmp_path / "var" / "lib" / "molido" / "kill-switch.json"
        monkeypatch.setattr(store, "DEFAULT_STATE_PATH", deep)

        run(["engage", "--by", "aziz", "--reason", "why"], capsys)

        assert deep.exists()

    def test_engage_leaves_no_temporary_file_behind(
        self, state_file, capsys, silent_audit
    ):
        run(["engage", "--by", "aziz", "--reason", "why"], capsys)

        assert not list(state_file.parent.glob("*.tmp"))

    def test_engage_repairs_a_corrupt_file(self, state_file, capsys, silent_audit):
        state_file.write_text("{truncated", encoding="utf-8")

        run(["engage", "--by", "aziz", "--reason", "why"], capsys)

        assert json.loads(state_file.read_text(encoding="utf-8"))["state"] == "engaged"


class TestReleaseNamesSomebody:
    def test_release_writes_a_disengaged_file(self, state_file, capsys, silent_audit):
        run(["release", "--by", "aziz", "--reason", "verified"], capsys)

        body = json.loads(state_file.read_text(encoding="utf-8"))
        assert body["state"] == "disengaged"

    def test_release_records_who(self, state_file, capsys, silent_audit):
        run(["release", "--by", "aziz", "--reason", "verified"], capsys)

        assert json.loads(state_file.read_text(encoding="utf-8"))["by"] == "aziz"

    def test_release_reads_back_as_released(self, state_file, capsys, silent_audit):
        run(["release", "--by", "aziz", "--reason", "verified"], capsys)

        assert store.load(state_file).engaged is False

    def test_release_records_both_who_and_why_in_the_reason(
        self, state_file, capsys, silent_audit
    ):
        run(["release", "--by", "aziz", "--reason", "expert verified"], capsys)

        stored = json.loads(state_file.read_text(encoding="utf-8"))["reason"]
        assert "aziz" in stored
        assert "expert verified" in stored

    def test_release_returns_zero(self, state_file, capsys, silent_audit):
        code, _ = run(["release", "--by", "aziz", "--reason", "verified"], capsys)

        assert code == 0

    def test_release_reports_the_audit_outcome(self, state_file, capsys, silent_audit):
        _, body = run(["release", "--by", "aziz", "--reason", "verified"], capsys)

        assert body["audit"] == "audited"

    def test_release_passes_who_and_why_to_the_audit(
        self, state_file, capsys, silent_audit
    ):
        run(["release", "--by", "aziz", "--reason", "verified"], capsys)

        assert silent_audit == [("release", "aziz", "verified")]

    def test_release_clears_the_engaged_at_stamp(
        self, state_file, capsys, silent_audit
    ):
        run(["engage", "--by", "aziz", "--reason", "rolling"], capsys)

        run(["release", "--by", "aziz", "--reason", "verified"], capsys)

        assert store.load(state_file).engaged_at is None

    def test_a_release_the_store_would_refuse_never_reaches_disk(self, state_file):
        # The store refuses to persist an unattributed release. Whitespace
        # gets past argparse's `required=True`, so the command rejects it
        # first - but if that check were ever removed, this is the wall.
        with pytest.raises(ValueError):
            store.save(KillSwitch(engaged=False, engaged_by="  "), state_file)

        assert not state_file.exists()


class TestAttributionIsNotOptional:
    @pytest.mark.parametrize("command", ["engage", "release"])
    def test_a_blank_by_is_refused(self, command, state_file):
        assert cli.main([command, "--by", "   ", "--reason", "why"]) == 2

    @pytest.mark.parametrize("command", ["engage", "release"])
    def test_a_blank_reason_is_refused(self, command, state_file):
        assert cli.main([command, "--by", "aziz", "--reason", "  "]) == 2

    @pytest.mark.parametrize("command", ["engage", "release"])
    def test_an_empty_by_is_refused(self, command, state_file):
        assert cli.main([command, "--by", "", "--reason", "why"]) == 2

    @pytest.mark.parametrize("command", ["engage", "release"])
    def test_an_empty_reason_is_refused(self, command, state_file):
        assert cli.main([command, "--by", "aziz", "--reason", ""]) == 2

    @pytest.mark.parametrize("command", ["engage", "release"])
    def test_a_tab_is_not_attribution(self, command, state_file):
        assert cli.main([command, "--by", "\t", "--reason", "why"]) == 2

    @pytest.mark.parametrize("command", ["engage", "release"])
    def test_a_newline_is_not_a_reason(self, command, state_file):
        assert cli.main([command, "--by", "aziz", "--reason", "\n"]) == 2

    @pytest.mark.parametrize("command", ["engage", "release"])
    def test_a_refusal_writes_nothing(self, command, state_file):
        cli.main([command, "--by", " ", "--reason", " "])

        assert not state_file.exists()

    @pytest.mark.parametrize("command", ["engage", "release"])
    def test_a_refusal_explains_itself_on_stderr(self, command, state_file, capsys):
        cli.main([command, "--by", " ", "--reason", "why"])

        assert "must say something" in capsys.readouterr().err

    @pytest.mark.parametrize("command", ["engage", "release"])
    def test_a_refusal_prints_nothing_on_stdout(self, command, state_file, capsys):
        cli.main([command, "--by", " ", "--reason", "why"])

        assert capsys.readouterr().out == ""

    @pytest.mark.parametrize("command", ["engage", "release"])
    def test_by_is_required_by_the_parser(self, command, state_file):
        with pytest.raises(SystemExit):
            cli.main([command, "--reason", "why"])

    @pytest.mark.parametrize("command", ["engage", "release"])
    def test_reason_is_required_by_the_parser(self, command, state_file):
        with pytest.raises(SystemExit):
            cli.main([command, "--by", "aziz"])

    @pytest.mark.parametrize("command", ["engage", "release"])
    def test_a_refusal_is_not_audited(self, command, state_file, silent_audit):
        cli.main([command, "--by", " ", "--reason", "why"])

        assert silent_audit == []

    def test_a_refusal_does_not_disturb_an_existing_halt(
        self, state_file, capsys, silent_audit
    ):
        run(["engage", "--by", "aziz", "--reason", "rolling"], capsys)

        cli.main(["release", "--by", "  ", "--reason", "verified"])

        assert store.load(state_file).engaged is True

    def test_a_refusal_does_not_disturb_an_existing_release(
        self, state_file, capsys, silent_audit
    ):
        run(["release", "--by", "aziz", "--reason", "verified"], capsys)

        cli.main(["engage", "--by", "  ", "--reason", "rolling"])

        assert store.load(state_file).engaged is False


class TestTheSwitchMovesWhenTheDatabaseIsDown:
    def test_a_failing_audit_does_not_stop_the_write(
        self, state_file, capsys, monkeypatch
    ):
        monkeypatch.setattr(cli, "_audit", lambda *a: "not audited (OSError: down)")

        run(["engage", "--by", "aziz", "--reason", "why"], capsys)

        assert store.load(state_file).engaged is True

    def test_a_failing_audit_is_reported_not_hidden(
        self, state_file, capsys, monkeypatch
    ):
        monkeypatch.setattr(cli, "_audit", lambda *a: "not audited (OSError: down)")

        _, body = run(["engage", "--by", "aziz", "--reason", "why"], capsys)

        assert body["audit"].startswith("not audited")

    def test_a_failing_audit_still_returns_zero(
        self, state_file, capsys, monkeypatch
    ):
        monkeypatch.setattr(cli, "_audit", lambda *a: "not audited (OSError: down)")

        code, _ = run(["engage", "--by", "aziz", "--reason", "why"], capsys)

        assert code == 0

    def test_a_release_survives_a_failing_audit(
        self, state_file, capsys, monkeypatch
    ):
        monkeypatch.setattr(cli, "_audit", lambda *a: "not audited (OSError: down)")

        run(["release", "--by", "aziz", "--reason", "verified"], capsys)

        assert store.load(state_file).engaged is False

    def test_the_audit_helper_names_the_real_exception(self, monkeypatch):
        # The bug this replaced reported "the database was not reachable" for
        # an ImportError raised by naming a symbol that never existed. The
        # class name is in the string so a wrong cause cannot hide again.
        from app.db import session as db_session

        def explode():
            raise RuntimeError("no connection")

        monkeypatch.setattr(db_session, "session_scope", explode, raising=False)

        assert "RuntimeError" in cli._audit("engage", "aziz", "why")

    def test_the_audit_helper_never_raises(self, monkeypatch):
        from app.db import session as db_session

        def explode():
            raise OSError("down")

        monkeypatch.setattr(db_session, "session_scope", explode, raising=False)

        assert isinstance(cli._audit("release", "aziz", "why"), str)

    def test_the_audit_helper_reports_not_audited_on_failure(self, monkeypatch):
        from app.db import session as db_session

        def explode():
            raise OSError("down")

        monkeypatch.setattr(db_session, "session_scope", explode, raising=False)

        assert cli._audit("engage", "aziz", "why").startswith("not audited")

    def test_session_scope_is_the_name_that_exists(self):
        # The named cause of the original bug: `SessionLocal` does not exist
        # in that module and never has.
        from app.db import session as db_session

        assert hasattr(db_session, "session_scope")


class TestTheCommandSurface:
    def test_no_command_is_refused(self):
        with pytest.raises(SystemExit):
            cli.main([])

    def test_an_unknown_command_is_refused(self):
        with pytest.raises(SystemExit):
            cli.main(["disarm", "--by", "aziz", "--reason", "why"])

    def test_status_takes_no_attribution(self, state_file):
        with pytest.raises(SystemExit):
            cli.main(["status", "--by", "aziz"])

    def test_there_is_no_route_that_releases(self):
        # The module's central claim: releasing is a human act at the host,
        # and a route is a thing a script can call. If a release endpoint is
        # ever added, this fails and the docstring has to be rewritten first.
        from pathlib import Path

        api = Path(__file__).resolve().parents[1] / "app" / "api"
        offenders = [
            path.name
            for path in api.rglob("*.py")
            if "killswitch" in (body := path.read_text(encoding="utf-8"))
            and "disengage" in body
        ]

        assert offenders == []
