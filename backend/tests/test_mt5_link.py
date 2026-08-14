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
