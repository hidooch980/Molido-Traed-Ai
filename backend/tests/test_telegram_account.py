"""/addaccount from Telegram: the site's queue, the password never kept."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta

import pytest

from app.integrations import telegram_account as ta
from app.integrations import telegram_bot
from app.services import telegram_settings

NOW = datetime(2026, 9, 23, 10, 0, tzinfo=UTC)
SECRET = "S3cr3t-pass"


@pytest.fixture(autouse=True)
def queue(tmp_path, monkeypatch):
    from app.core import config

    directory = tmp_path / "mt5-queue"
    monkeypatch.setattr(config.get_settings(), "mt5_queue_dir", str(directory))
    return directory


def requests(queue):
    return [json.loads(p.read_text()) for p in queue.glob("*.request.json")]


def test_bare_command_explains_itself():
    text = ta.handle("500", "/addaccount")
    assert "/addaccount" in text
    assert "Master" in text


def test_a_login_is_queued_exactly_as_the_site_would(queue):
    text = ta.handle("500", f"/addaccount 1520012345 FTMO-Demo2 {SECRET}", now=NOW)

    assert "1520012345" in text
    assert SECRET not in text
    [request] = requests(queue)
    assert request == {"login": "1520012345", "server": "FTMO-Demo2", "password": SECRET}


def test_a_terminal_may_be_named_first(queue):
    ta.handle("500", f"/addaccount term-j 1520012345 FTMO-Demo2 {SECRET}", now=NOW)

    [request] = requests(queue)
    assert request["terminal"] == "term-j"


def test_a_password_with_spaces_is_kept_whole(queue):
    ta.handle("500", "/addaccount 1520012345 FTMO-Demo2 two words", now=NOW)
    [request] = requests(queue)
    assert request["password"] == "two words"


def test_a_bad_login_is_refused_and_nothing_queued(queue):
    text = ta.handle("500", f"/addaccount 12 FTMO-Demo2 {SECRET}", now=NOW)

    assert "ثبت نشد" in text
    assert SECRET not in text
    assert requests(queue) == []


def test_missing_fields_are_refused(queue):
    assert "کامل نیست" in ta.handle("500", "/addaccount 1520012345 FTMO-Demo2", now=NOW)
    assert requests(queue) == []


def test_the_password_is_never_in_the_pending_record(queue):
    ta.handle("500", f"/addaccount 1520012345 FTMO-Demo2 {SECRET}", now=NOW)
    assert SECRET not in ta._state_path().read_text()


def test_the_result_goes_back_to_the_chat_that_asked():
    ta.handle("500", f"/addaccount 1520012345 FTMO-Demo2 {SECRET}", now=NOW)
    [request_id] = ta._load()
    sent = []

    done = ta.check_pending(
        lambda chat, text: sent.append((chat, text)),
        now=NOW + timedelta(minutes=5),
        result_for=lambda rid: {"known": True, "applied": True, "connected": True},
    )

    assert done == 1
    assert sent == [("500", "✅ حساب 1520012345 وصل شد. ربات از چرخهٔ بعد رویش کار می‌کند.")]
    assert ta._load() == {}


def test_applied_but_not_connected_is_a_failure_with_the_reason():
    ta.handle("500", f"/addaccount 1520012345 FTMO-Demo2 {SECRET}", now=NOW)
    sent = []
    ta.check_pending(
        lambda chat, text: sent.append(text),
        now=NOW,
        result_for=lambda rid: {"known": True, "applied": True, "connected": False,
                                "reason": "invalid account"},
    )
    assert sent[0].startswith("❌") and "invalid account" in sent[0]


def test_an_agent_that_never_answers_is_reported_after_twenty_minutes():
    ta.handle("500", f"/addaccount 1520012345 FTMO-Demo2 {SECRET}", now=NOW)
    sent = []
    pending = lambda rid: {"known": False, "pending": True}  # noqa: E731

    ta.check_pending(lambda c, t: sent.append(t), now=NOW + timedelta(minutes=10), result_for=pending)
    assert sent == []
    ta.check_pending(lambda c, t: sent.append(t), now=NOW + timedelta(minutes=21), result_for=pending)
    assert "۲۰ دقیقه" in sent[0]


def test_markdown_characters_in_names_are_escaped():
    assert ta._md("RoboForex_ECN") == "RoboForex\\_ECN"


class TestThroughThePoll:
    def poll(self, session, monkeypatch, chat_id, text):
        calls = []

        def fake_api(method, payload, *, token=None, timeout=None):
            calls.append((method, payload))
            if method == "getUpdates":
                update = {
                    "update_id": 1,
                    "message": {"message_id": 77, "chat": {"id": chat_id}, "text": text},
                }
                return True, {"ok": True, "result": [update]}
            return True, {"ok": True}

        from app.integrations import telegram

        monkeypatch.setattr(telegram, "api_call", fake_api)
        monkeypatch.setattr(telegram_bot, "_write_offset", lambda _v: True)
        monkeypatch.setattr(telegram_bot, "_read_offset", lambda: 0)
        telegram_settings.save(session, token="1:AA", chat_ids=["500"])
        telegram_bot.poll(session)
        return calls

    def test_an_admin_message_with_a_password_is_deleted_and_queued(
        self, session, monkeypatch, queue
    ):
        calls = self.poll(session, monkeypatch, 500, f"/addaccount 1520012345 FTMO-Demo2 {SECRET}")

        assert ("deleteMessage", {"chat_id": "500", "message_id": 77}) in calls
        replies = [p["text"] for m, p in calls if m == "sendMessage"]
        assert all(SECRET not in r for r in replies)
        assert len(requests(queue)) == 1

    def test_a_stranger_cannot_add_an_account(self, session, monkeypatch, queue):
        self.poll(session, monkeypatch, 999, f"/addaccount 1520012345 FTMO-Demo2 {SECRET}")
        assert requests(queue) == []
