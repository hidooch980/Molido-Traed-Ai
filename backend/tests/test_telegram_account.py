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


# ------------------------------------------------ delete / activate / deactivate


@pytest.fixture
def switch_dir(tmp_path, monkeypatch):
    from app.execution import account_switch

    directory = tmp_path / "accounts"
    monkeypatch.setattr(account_switch, "DEFAULT_STATE_DIR", directory)
    return directory


KNOWN = lambda: ["main", "term-j"]  # noqa: E731


def test_other_text_is_not_a_manage_command():
    assert ta.handle_manage("500", "/status") is None
    assert ta.handle_manage("500", "") is None


def test_delete_needs_confirmation_before_anything_is_queued(queue):
    answer = ta.handle_manage("500", "/delaccount term-j", now=NOW)
    assert answer.buttons == [[("✅ تأیید", "delaccount term-j confirm"), ta.CANCEL]]
    assert requests(queue) == []


def test_confirmed_delete_queues_a_clear_and_reports_back(queue):
    text = ta.handle_manage("500", "/delaccount term-j confirm", now=NOW)
    assert "ثبت شد" in text
    assert requests(queue) == [{"action": "clear", "terminal": "term-j"}]

    sent = []
    ta.check_pending(
        lambda chat, t: sent.append((chat, t)),
        now=NOW,
        result_for=lambda rid: {"known": True, "applied": True, "cleared": True},
    )
    assert sent == [("500", "✅ حساب ترمینال term-j حذف شد.")]
    assert ta._load() == {}


def test_a_failed_delete_is_reported_with_the_reason(queue):
    ta.handle_manage("500", "/delaccount term-j confirm", now=NOW)
    sent = []
    ta.check_pending(
        lambda c, t: sent.append(t),
        now=NOW,
        result_for=lambda rid: {"known": True, "applied": False, "reason": "no such terminal"},
    )
    assert sent[0].startswith("❌") and "no such terminal" in sent[0]


def test_delete_of_a_bad_terminal_name_is_refused(queue):
    assert "حذف نشد" in ta.handle_manage("500", "/delaccount ../etc confirm", now=NOW)
    assert requests(queue) == []


def test_deactivate_pauses_at_once_and_is_attributed(switch_dir):
    from app.execution import account_switch

    text = ta.handle_manage("500", "/deactivate term-j", known_accounts=KNOWN)
    assert "متوقف" in text
    allowed, why = account_switch.state("term-j")
    assert not allowed and "telegram:500" in why


def test_activate_needs_confirmation(switch_dir):
    from app.execution import account_switch

    ta.handle_manage("500", "/deactivate term-j", known_accounts=KNOWN)
    answer = ta.handle_manage("500", "/activate term-j", known_accounts=KNOWN)
    assert answer.buttons[0][0] == ("✅ تأیید", "activate term-j confirm")
    assert account_switch.state("term-j")[0] is False

    text = ta.handle_manage("500", "/activate term-j confirm", known_accounts=KNOWN)
    assert "فعال شد" in text
    assert account_switch.state("term-j")[0] is True


def test_an_unknown_account_is_refused_and_nothing_written(switch_dir):
    text = ta.handle_manage("500", "/deactivate ghost", known_accounts=KNOWN)
    assert "تعریف نشده" in text
    assert not switch_dir.exists() or not any(switch_dir.iterdir())


def test_bare_switch_command_lists_states(switch_dir):
    ta.handle_manage("500", "/deactivate main", known_accounts=KNOWN)
    answer = ta.handle_manage("500", "/activate", known_accounts=KNOWN)
    assert "main — ⏸ متوقف" in answer.text and "term-j — 🟢 فعال" in answer.text
    assert answer.buttons[0] == [("▶️ فعال main", "activate main"), ("🗑 حذف main", "delaccount main")]
    assert answer.buttons[1][0] == ("⏸ توقف term-j", "deactivate term-j")


def test_every_menu_button_is_a_handled_command(switch_dir):
    for row in ta.menu().buttons:
        for _label, data in row:
            assert data == "manage" or data.startswith(("wiz ", "prop")) or (
                ta.handle_manage("500", data, known_accounts=KNOWN) is not None
            )


def test_a_stranger_cannot_delete_or_switch(session, monkeypatch, queue, switch_dir):
    TestThroughThePoll().poll(session, monkeypatch, 999, "/delaccount term-j confirm")
    TestThroughThePoll().poll(session, monkeypatch, 999, "/deactivate main")
    assert requests(queue) == []
    assert not switch_dir.exists()


def test_an_admin_delete_goes_through_the_poll(session, monkeypatch, queue):
    calls = TestThroughThePoll().poll(session, monkeypatch, 500, "/delaccount term-j confirm")
    assert requests(queue) == [{"action": "clear", "terminal": "term-j"}]
    assert not any(m == "deleteMessage" for m, _ in calls)


class TestButtons:
    def poll(self, session, monkeypatch, update):
        calls = []

        def fake_api(method, payload, *, token=None, timeout=None):
            calls.append((method, payload))
            if method == "getUpdates":
                return True, {"ok": True, "result": [update]}
            return True, {"ok": True}

        from app.integrations import telegram

        monkeypatch.setattr(telegram, "api_call", fake_api)
        monkeypatch.setattr(telegram_bot, "_write_offset", lambda _v: True)
        monkeypatch.setattr(telegram_bot, "_read_offset", lambda: 0)
        telegram_settings.save(session, token="1:AA", chat_ids=["500"])
        telegram_bot.poll(session)
        return [p for m, p in calls if m == "sendMessage"]

    def tap(self, session, monkeypatch, data, chat=500):
        update = {
            "update_id": 1,
            "callback_query": {"id": "c", "data": data, "message": {"chat": {"id": chat}}},
        }
        return self.poll(session, monkeypatch, update)

    def test_the_manage_key_is_on_the_persistent_keyboard(self):
        rows = telegram_bot._reply_keyboard()["keyboard"]
        assert rows[-1] == [{"text": telegram_bot.MANAGE_LABEL}]

    def test_the_manage_key_opens_the_menu_with_buttons(self, session, monkeypatch):
        update = {"update_id": 1, "message": {"chat": {"id": 500}, "text": telegram_bot.MANAGE_LABEL}}
        [sent] = self.poll(session, monkeypatch, update)
        assert "/addaccount" in sent["text"]
        data = [b["callback_data"] for r in sent["reply_markup"]["inline_keyboard"] for b in r]
        assert "activate" in data and "prop" in data

    def test_tapping_add_only_explains_and_queues_nothing(self, session, monkeypatch, queue):
        [sent] = self.tap(session, monkeypatch, f"addaccount 1520012345 FTMO-Demo2 {SECRET}")
        assert "Master" in sent["text"]
        assert requests(queue) == []

    def test_the_confirm_button_deletes(self, session, monkeypatch, queue):
        [sent] = self.tap(session, monkeypatch, "delaccount term-j")
        confirm = sent["reply_markup"]["inline_keyboard"][0][0]["callback_data"]
        assert requests(queue) == []
        self.tap(session, monkeypatch, confirm)
        assert requests(queue) == [{"action": "clear", "terminal": "term-j"}]

    def test_a_stranger_tapping_confirm_is_refused(self, session, monkeypatch, queue):
        self.tap(session, monkeypatch, "delaccount term-j confirm", chat=999)
        assert requests(queue) == []

    def test_an_oversized_button_is_dropped_not_sent(self):
        answer = ta.Answer("x", [[("ok", "prop"), ("long", "x" * 65)]])
        assert telegram_bot._as_reply(answer).buttons == ((("ok", "prop"),),)
