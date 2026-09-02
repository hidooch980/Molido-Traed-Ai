"""The queue between two users that are not the same user.

Every bug in this file was found by submitting a deliberately wrong login
through the real path before handing the form to anybody. None of them was
visible from either side alone: the API wrote a file it could read, the agent
looked for a file with a different name, and both were individually correct.
"""

from __future__ import annotations

import json
import os
import stat

import pytest

from app.core.errors import ValidationFailedError
from app.services import mt5_link


@pytest.fixture()
def queue(tmp_path, monkeypatch):
    monkeypatch.setattr(mt5_link, "queue_dir", lambda: tmp_path)
    return tmp_path


class TestTheQueueIsReadableByTheOtherSide:
    def test_a_written_request_is_group_readable(self, queue):
        """0600 looks like the careful choice and silently makes the queue
        write-only: the agent runs as a different user in a shared group and
        could not read what the API had just written."""
        request = mt5_link.validate("12345678", "Broker-Demo", "secret")
        result = mt5_link.submit(request)

        path = queue / f"{result.request_id}.request.json"
        mode = stat.S_IMODE(os.stat(path).st_mode)

        assert result.queued is True
        assert mode & stat.S_IRGRP, f"mode {oct(mode)} is not group-readable"

    def test_the_payload_round_trips(self, queue):
        request = mt5_link.validate("12345678", "Broker-Demo", "secret")
        result = mt5_link.submit(request)

        written = json.loads(
            (queue / f"{result.request_id}.request.json").read_text(encoding="utf-8")
        )

        assert written == {
            "login": "12345678",
            "server": "Broker-Demo",
            "password": "secret",
        }


class TestTheResultFilenameMatchesWhatIsLookedFor:
    def test_the_api_finds_a_result_the_agent_would_write(self, queue):
        """The agent named it with `with_suffix('.result.json')` on
        `<id>.request.json`, which replaces only the final `.json` and produces
        `<id>.request.result.json`. The API looked for `<id>.result.json`,
        found nothing, and reported "no request or result exists with that id"
        about a request that had been applied."""
        request = mt5_link.validate("12345678", "Broker-Demo", "secret")
        result = mt5_link.submit(request)

        # Exactly the name the agent writes now.
        (queue / f"{result.request_id}.result.json").write_text(
            json.dumps({"applied": True, "connected": False}), encoding="utf-8"
        )

        found = mt5_link.result_for(result.request_id)

        assert found["known"] is True
        assert found["applied"] is True

    def test_a_pending_request_is_not_reported_as_unknown(self, queue):
        """"Not applied yet" and "no such request" send the reader to different
        places: one is a slow agent, the other is a lost request."""
        request = mt5_link.validate("12345678", "Broker-Demo", "secret")
        result = mt5_link.submit(request)

        found = mt5_link.result_for(result.request_id)

        assert found["known"] is False
        assert found["pending"] is True
        assert "not picked this up yet" in found["reason"]

    def test_an_invented_id_is_reported_as_unknown(self, queue):
        found = mt5_link.result_for("20260814T000000-deadbeef")

        assert found["known"] is False
        assert found["pending"] is False


class TestValidationProtectsTheConfigFile:
    @pytest.mark.parametrize("bad", ["12", "abcdefgh", "1234567890123", ""])
    def test_a_login_that_is_not_digits_is_refused(self, queue, bad):
        from app.core.errors import ValidationFailedError

        with pytest.raises(ValidationFailedError):
            mt5_link.validate(bad, "Broker-Demo", "secret")

    def test_a_newline_in_the_server_is_refused(self, queue):
        """It would let a caller write extra sections into an ini file the
        terminal reads at startup."""
        from app.core.errors import ValidationFailedError

        with pytest.raises(ValidationFailedError):
            mt5_link.validate("12345678", "Broker\n[Experts]\nAllowLiveTrading=1", "x")

    def test_a_newline_in_the_password_is_refused_without_echoing_it(self, queue):
        from app.core.errors import ValidationFailedError

        with pytest.raises(ValidationFailedError) as exc:
            mt5_link.validate("12345678", "Broker-Demo", "secret\nmore")

        assert "secret" not in str(exc.value)


class TestTheShapesBrokersActuallyIssue:
    """Real registration output, not invented examples.

    Two demo accounts were opened while this was being built and both are in
    here: a MetaQuotes one and a RoboMarkets one. A validator that rejects the
    format its users are handed is worse than no validator, because the error
    points at them rather than at itself.
    """

    @pytest.mark.parametrize(
        "login,server",
        [
            ("111099517", "MetaQuotes-Demo"),
            ("501165913", "RoboMarketsCY-Pro"),
            ("12345678", "ICMarketsSC-Demo"),
            ("9876543", "Pepperstone-Demo01"),
            ("1234", "FTMO-Server"),
            ("123456789012", "Exness-MT5Trial8"),
        ],
    )
    def test_it_accepts_what_brokers_issue(self, queue, login, server):
        request = mt5_link.validate(login, server, "whatever-they-set")

        assert request.login == login
        assert request.server == server

    @pytest.mark.parametrize(
        "password",
        [
            "SrDuP@K8",
            "@aNp56Ow",
            "a b c d",
            "Ünïcødé-Ü",
            "'; DROP TABLE users; --",
            "x" * 200,
        ],
    )
    def test_it_accepts_the_passwords_brokers_generate(self, queue, password):
        """Broker-generated passwords carry punctuation, and a validator that
        rejects them sends somebody to change a password that was fine."""
        request = mt5_link.validate("111099517", "MetaQuotes-Demo", password)

        assert request.password == password

    def test_a_password_with_punctuation_survives_the_queue(self, queue):
        """It travels through JSON and into an ini file. Either could mangle
        it, and a mangled password fails authentication with a message about
        the account rather than about the transport."""
        password = "SrDuP@K8"
        result = mt5_link.submit(
            mt5_link.validate("111099517", "MetaQuotes-Demo", password)
        )

        written = json.loads(
            (queue / f"{result.request_id}.request.json").read_text(encoding="utf-8")
        )

        assert written["password"] == password

    def test_surrounding_whitespace_is_trimmed(self, queue):
        """Copied from a registration screen, values arrive with spaces, and a
        trailing space in a server name is an hour of debugging."""
        request = mt5_link.validate("  111099517  ", "  MetaQuotes-Demo  ", "secret")

        assert request.login == "111099517"
        assert request.server == "MetaQuotes-Demo"

    def test_the_password_is_not_trimmed(self, queue):
        """A leading or trailing space may be part of it, and silently removing
        one produces an authentication failure nobody can explain."""
        request = mt5_link.validate("111099517", "MetaQuotes-Demo", " secret ")

        assert request.password == " secret "


class TestTwoRequestsDoNotCollide:
    def test_each_request_gets_its_own_id(self, queue):
        first = mt5_link.submit(mt5_link.validate("111099517", "MetaQuotes-Demo", "a"))
        second = mt5_link.submit(mt5_link.validate("501165913", "RoboMarketsCY-Pro", "b"))

        assert first.request_id != second.request_id
        assert len(list(queue.glob("*.request.json"))) == 2

    def test_a_request_is_never_visible_half_written(self, queue):
        """Written under a temporary name and renamed into place. The agent
        globs for finished requests, and a rename is atomic on one filesystem -
        so it cannot read half a file and log into half an account."""
        result = mt5_link.submit(
            mt5_link.validate("111099517", "MetaQuotes-Demo", "secret")
        )

        assert (queue / f"{result.request_id}.request.json").exists()
        assert not list(queue.glob("*.partial"))


class TestTheQueueReportsItsOwnState:
    def test_a_missing_directory_is_reported_not_crashed(self, tmp_path, monkeypatch):
        monkeypatch.setattr(mt5_link, "queue_dir", lambda: tmp_path / "absent")

        state = mt5_link.agent_state()

        assert state["reachable"] is False
        assert "not mounted" in state["reason"]

    def test_depth_is_published_rather_than_summarised(self, queue):
        """A queue nobody is draining looks exactly like an empty one from this
        side, so the count is reported instead of a verdict."""
        for i in range(3):
            mt5_link.submit(mt5_link.validate(f"1110995{i}7", "MetaQuotes-Demo", "x"))

        state = mt5_link.agent_state()

        assert state["reachable"] is True
        assert state["pending_requests"] == 3


class TestNamingATerminal:
    """A request may name which terminal it is for, and a clear must.

    The name rides in the same file the login does, so the validation is
    about injection into a file a host agent reads - not about taste.
    """

    def test_a_named_terminal_rides_in_the_payload(self, queue):
        request = mt5_link.LinkRequest(
            login="12345678", server="Broker-Demo", password="s", terminal="term-c"
        )
        result = mt5_link.submit(request)

        written = json.loads(
            (queue / f"{result.request_id}.request.json").read_text()
        )
        assert written["terminal"] == "term-c"

    def test_an_unnamed_request_carries_no_terminal_key_at_all(self, queue):
        """Absent, not empty. The agent treats a missing key as "pick the
        first free terminal", and an empty string would be a name lookup that
        fails."""
        request = mt5_link.validate("12345678", "Broker-Demo", "s")
        result = mt5_link.submit(request)

        written = json.loads(
            (queue / f"{result.request_id}.request.json").read_text()
        )
        assert "terminal" not in written

    def test_a_terminal_name_with_a_path_in_it_is_refused(self, queue):
        from app.core.errors import ValidationFailedError

        with pytest.raises(ValidationFailedError):
            mt5_link.validate_terminal("../etc")

    def test_blank_means_none(self, queue):
        assert mt5_link.validate_terminal("  ") is None
        assert mt5_link.validate_terminal(None) is None


class TestClearingATerminal:
    def test_a_clear_carries_the_action_and_no_credential(self, queue):
        result = mt5_link.submit(mt5_link.validate_clear("term-d"))

        written = json.loads(
            (queue / f"{result.request_id}.request.json").read_text()
        )
        assert written == {"action": "clear", "terminal": "term-d"}

    def test_a_clear_with_no_terminal_is_refused(self, queue):
        """There is no safe default to log out. A blank field must not
        disconnect an account nobody meant to touch."""
        from app.core.errors import ValidationFailedError

        with pytest.raises(ValidationFailedError):
            mt5_link.validate_clear(None)


class TestStoppingIsNotForgetting:
    """Disconnect and delete were the same call until parking an account for
    an afternoon meant re-typing its password to get it back - and a system
    that makes people re-type passwords trains them to keep passwords
    somewhere convenient."""

    def test_a_stop_carries_no_credential(self):
        request = mt5_link.validate_power("term-g", "stop")

        assert request.as_payload() == {"action": "stop", "terminal": "term-g"}
        assert "password" not in request.as_payload()

    def test_a_start_is_its_own_action(self):
        assert mt5_link.validate_power("term-g", "start").action == "start"

    def test_clearing_is_a_different_payload_entirely(self):
        """The agent has to be able to tell them apart, because one is
        reversible without a password and the other is not."""
        stop = mt5_link.validate_power("term-g", "stop").as_payload()
        clear = mt5_link.validate_clear("term-g").as_payload()

        assert stop["action"] != clear["action"]

    def test_an_unknown_verb_is_refused_here_not_at_the_agent(self):
        """The agent would have to answer with a result file nobody is
        waiting for."""
        with pytest.raises(ValidationFailedError) as caught:
            mt5_link.validate_power("term-g", "restart")

        assert "not something that can be done" in str(caught.value)

    def test_a_blank_terminal_is_refused(self):
        """Acting on a default terminal from an empty field would touch an
        account nobody meant to."""
        with pytest.raises(ValidationFailedError):
            mt5_link.validate_power("", "stop")

    def test_the_verb_is_read_case_insensitively(self):
        assert mt5_link.validate_power("term-g", "STOP").action == "stop"

    def test_a_power_request_can_be_submitted_like_any_other(self, tmp_path, monkeypatch):
        monkeypatch.setenv("MOLIDO_MT5_QUEUE", str(tmp_path))
        result = mt5_link.submit(mt5_link.validate_power("term-g", "stop"))

        assert result.queued is True
        # No login and no server on a power request, and the result says so
        # rather than inventing them.
        assert result.login == ""
        assert result.server == ""


class TestAPendingLoginSaysWhereItIs:
    """Seven minutes between "queued" and "done", and the page used to show
    the first word for all of them. The agent writes a stage file now; the
    result carries it while the real result is still pending, and only
    while."""

    def test_progress_is_carried_with_known_still_false(self, tmp_path, monkeypatch):
        """`known` must stay false or the page stops polling and reports a
        half-finished login as a failure."""
        monkeypatch.setattr(mt5_link, "queue_dir", lambda: tmp_path)
        (tmp_path / "abc.request.json").write_text("{}", encoding="utf-8")
        (tmp_path / "abc.progress.json").write_text(
            '{"stage": "waiting_for_account", "elapsed_seconds": 90}', encoding="utf-8"
        )

        answer = mt5_link.result_for("abc")

        assert answer["known"] is False
        assert answer["pending"] is True
        assert answer["progress"]["stage"] == "waiting_for_account"
        assert answer["progress"]["elapsed_seconds"] == 90

    def test_a_result_wins_over_any_progress(self, tmp_path, monkeypatch):
        """Once the agent has answered, a stale stage file must not be read
        beside it as if the login were still in flight."""
        monkeypatch.setattr(mt5_link, "queue_dir", lambda: tmp_path)
        (tmp_path / "abc.progress.json").write_text('{"stage": "config_written"}', encoding="utf-8")
        (tmp_path / "abc.result.json").write_text(
            '{"applied": true, "connected": true}', encoding="utf-8"
        )

        answer = mt5_link.result_for("abc")

        assert answer["known"] is True
        assert "progress" not in answer

    def test_an_unreadable_progress_file_is_ignored_not_fatal(self, tmp_path, monkeypatch):
        monkeypatch.setattr(mt5_link, "queue_dir", lambda: tmp_path)
        (tmp_path / "abc.request.json").write_text("{}", encoding="utf-8")
        (tmp_path / "abc.progress.json").write_text("not json", encoding="utf-8")

        answer = mt5_link.result_for("abc")

        assert answer["known"] is False
        assert "progress" not in answer

    def test_no_progress_file_means_the_old_answer_exactly(self, tmp_path, monkeypatch):
        monkeypatch.setattr(mt5_link, "queue_dir", lambda: tmp_path)
        (tmp_path / "abc.request.json").write_text("{}", encoding="utf-8")

        answer = mt5_link.result_for("abc")

        assert answer == {
            "known": False,
            "pending": True,
            "reason": "the host agent has not picked this up yet",
        }
