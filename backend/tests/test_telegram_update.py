"""/update from Telegram writes a request for the host, after a one-time code."""

from __future__ import annotations

import json
import re
from datetime import UTC, datetime, timedelta

from app.integrations import notify, telegram_bot, telegram_update
from app.services import telegram_settings

NOW = datetime(2026, 9, 23, 8, 0, tzinfo=UTC)
ADMIN = "500"


def code_from(text: str) -> str:
    return re.search(r"/update_confirm (\d{6})", text).group(1)


def test_update_issues_a_code_and_writes_no_request():
    text = telegram_update.start(ADMIN, now=NOW)

    assert re.search(r"`/update_confirm \d{6}`", text)
    assert not telegram_update.request_file().exists()


def test_the_right_code_from_the_same_chat_writes_the_request():
    code = code_from(telegram_update.start(ADMIN, now=NOW))

    text = telegram_update.confirm(ADMIN, f"/update_confirm {code}", now=NOW + timedelta(minutes=1))

    assert "ثبت شد" in text
    request = json.loads(telegram_update.request_file().read_text())
    assert request["requested_by"] == ADMIN


def test_a_code_is_single_use():
    code = code_from(telegram_update.start(ADMIN, now=NOW))
    telegram_update.confirm(ADMIN, f"/update_confirm {code}", now=NOW)
    telegram_update.request_file().unlink()

    text = telegram_update.confirm(ADMIN, f"/update_confirm {code}", now=NOW)

    assert "اول /update" in text
    assert not telegram_update.request_file().exists()


def test_a_wrong_code_writes_nothing_and_spends_the_code():
    code = code_from(telegram_update.start(ADMIN, now=NOW))
    wrong = f"{(int(code) + 1) % 1_000_000:06d}"

    assert "درست نیست" in telegram_update.confirm(ADMIN, f"/update_confirm {wrong}", now=NOW)
    # The right one no longer works either: one try per code.
    assert "اول /update" in telegram_update.confirm(ADMIN, f"/update_confirm {code}", now=NOW)
    assert not telegram_update.request_file().exists()


def test_a_code_from_another_chat_is_refused():
    code = code_from(telegram_update.start(ADMIN, now=NOW))

    text = telegram_update.confirm("777", f"/update_confirm {code}", now=NOW)

    assert "درست نیست" in text
    assert not telegram_update.request_file().exists()


def test_an_expired_code_is_refused():
    code = code_from(telegram_update.start(ADMIN, now=NOW))

    text = telegram_update.confirm(ADMIN, f"/update_confirm {code}", now=NOW + timedelta(minutes=6))

    assert "منقضی" in text
    assert not telegram_update.request_file().exists()


def test_confirm_without_update_first_says_so():
    assert "اول /update" in telegram_update.confirm(ADMIN, "/update_confirm 123456", now=NOW)


def test_other_text_is_not_an_update_command():
    assert telegram_update.handle(ADMIN, "/status") is None
    assert telegram_update.handle(ADMIN, "") is None


def test_update_stays_out_of_the_read_only_allowlist():
    """It is not a question, so it must never pass through the door that
    answers questions - and the webhook path, which authenticates a channel
    rather than a person, keeps refusing it."""
    assert "update" not in notify.READ_ONLY_COMMANDS
    assert "update_confirm" not in notify.READ_ONLY_COMMANDS


class TestThroughThePoll:
    def poll(self, session, monkeypatch, chat_id, text):
        calls = []

        def fake_api(method, payload, *, token=None, timeout=None):
            calls.append((method, payload))
            if method == "getUpdates":
                update = {"update_id": 1, "message": {"chat": {"id": chat_id}, "text": text}}
                return True, {"ok": True, "result": [update]}
            return True, {"ok": True}

        from app.integrations import telegram

        monkeypatch.setattr(telegram, "api_call", fake_api)
        monkeypatch.setattr(telegram_bot, "_write_offset", lambda _v: True)
        monkeypatch.setattr(telegram_bot, "_read_offset", lambda: 0)
        telegram_settings.save(session, token="1:AA", chat_ids=[ADMIN])
        telegram_bot.poll(session)
        return [p for m, p in calls if m == "sendMessage"]

    def test_an_admin_can_request_an_update_end_to_end(self, session, monkeypatch):
        [first] = self.poll(session, monkeypatch, int(ADMIN), "/update")
        code = code_from(first["text"])

        [second] = self.poll(session, monkeypatch, int(ADMIN), f"/update_confirm {code}")

        assert "ثبت شد" in second["text"]
        assert telegram_update.request_file().exists()

    def test_a_stranger_cannot_request_an_update(self, session, monkeypatch):
        [only] = self.poll(session, monkeypatch, 999, "/update")

        assert "ادمین‌های ثبت‌شده" in only["text"]
        assert not (telegram_update.request_file().parent / "update-code.json").exists()
