"""Adding an account by buttons: one question at a time, password never kept."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta

import pytest

from app.integrations import telegram_bot
from app.integrations import telegram_wizard as tw
from app.services import challenge_accounts, telegram_settings

SECRET = "S3cr3t-pass"
BOOK = "ftmo-challenge-2step-phase1"


@pytest.fixture(autouse=True)
def queue(tmp_path, monkeypatch):
    from app.core import config

    directory = tmp_path / "mt5-queue"
    monkeypatch.setattr(config.get_settings(), "mt5_queue_dir", str(directory))
    return directory


def requests(queue):
    return [json.loads(p.read_text()) for p in queue.glob("*.request.json")]


class Chat:
    """Drives the real poll, one update per call."""

    def __init__(self, session, monkeypatch, chat_id=500):
        from app.integrations import telegram

        self.session, self.chat_id, self.calls = session, chat_id, []
        self.update = None

        def fake_api(method, payload, *, token=None, timeout=None):
            self.calls.append((method, payload))
            if method == "getUpdates":
                return True, {"ok": True, "result": [self.update]}
            return True, {"ok": True}

        monkeypatch.setattr(telegram, "api_call", fake_api)
        monkeypatch.setattr(telegram_bot, "_write_offset", lambda _v: True)
        monkeypatch.setattr(telegram_bot, "_read_offset", lambda: 0)
        telegram_settings.save(session, token="1:AA", chat_ids=["500"])

    def _run(self, update):
        self.calls.clear()
        self.update = {"update_id": 1, **update}
        telegram_bot.poll(self.session)
        [sent] = [p for m, p in self.calls if m == "sendMessage"]
        return sent

    def say(self, text):
        return self._run({"message": {"message_id": 9, "chat": {"id": self.chat_id}, "text": text}})

    def tap(self, data):
        return self._run(
            {"callback_query": {"id": "c", "data": data, "message": {"chat": {"id": self.chat_id}}}}
        )

    def deleted(self):
        return [p for m, p in self.calls if m == "deleteMessage"]


def buttons(sent):
    return [b["callback_data"] for r in sent.get("reply_markup", {}).get("inline_keyboard", []) for b in r]


def test_broker_account_added_step_by_step(session, monkeypatch, queue):
    chat = Chat(session, monkeypatch)
    assert "wiz broker" in buttons(chat.say(telegram_bot.MANAGE_LABEL))

    assert "Login" in chat.tap("wiz broker")["text"]
    assert "سرور" in chat.say("1520012345")["text"]
    assert "Master" in chat.say("FTMO-Demo2")["text"]

    reply = chat.say(SECRET)
    assert chat.deleted() == [{"chat_id": "500", "message_id": 9}]
    assert SECRET not in reply["text"] and "ثبت شد" in reply["text"]
    assert requests(queue) == [{"login": "1520012345", "server": "FTMO-Demo2", "password": SECRET}]
    assert SECRET not in tw._path().read_text()


def test_the_password_is_never_in_the_state_file(session, monkeypatch):
    chat = Chat(session, monkeypatch)
    chat.tap("wiz broker")
    chat.say("1520012345")
    chat.say("FTMO-Demo2")
    assert "FTMO-Demo2" in tw._path().read_text()
    chat.say(SECRET)
    assert tw._load() == {}


def test_a_bad_login_is_asked_again(session, monkeypatch, queue):
    chat = Chat(session, monkeypatch)
    chat.tap("wiz broker")
    assert "فقط عدد" in chat.say("abc")["text"]
    assert requests(queue) == []


def test_cancel_ends_the_flow(session, monkeypatch, queue):
    chat = Chat(session, monkeypatch)
    chat.tap("wiz broker")
    assert "لغو" in chat.tap("wiz cancel")["text"]
    # Plain text now goes to the normal router, not the wizard.
    chat.say("1520012345")
    assert tw._load() == {}


def test_a_key_instead_of_an_answer_ends_the_flow(session, monkeypatch):
    chat = Chat(session, monkeypatch)
    chat.tap("wiz broker")
    chat.say("/status")
    assert tw._load() == {}


def test_a_flow_expires(session):
    now = datetime(2026, 9, 23, 10, 0, tzinfo=UTC)
    tw.handle(session, "500", "wiz broker", is_command=False, now=now)
    later = now + tw.EXPIRES_AFTER + timedelta(seconds=1)
    assert tw.handle(session, "500", "1520012345", is_command=False, now=later) is None


def test_prop_account_by_buttons(session, monkeypatch):
    chat = Chat(session, monkeypatch)
    kinds = buttons(chat.tap("wiz prop"))
    assert "wiz kind challenge" in kinds and "wiz kind live" in kinds
    chat.tap("wiz kind challenge")
    assert f"wiz book {BOOK}" in buttons(chat.say("100,000"))
    chat.tap(f"wiz book {BOOK}")
    assert "ثبت شد" in chat.say("FTMO 100k")["text"]

    tenant = challenge_accounts.default_tenant(session)
    [view] = challenge_accounts.listing(session, tenant_id=tenant)
    assert (view.account.label, view.account.kind, view.account.rulebook_key) == (
        "FTMO 100k", "challenge", BOOK,
    )


def test_live_account_skips_the_rulebook(session, monkeypatch):
    chat = Chat(session, monkeypatch)
    chat.tap("wiz prop")
    chat.tap("wiz kind live")
    assert "نام حساب" in chat.say("5000")["text"]
    assert "ثبت شد" in chat.say("My Broker")["text"]


def test_a_bad_balance_is_asked_again(session, monkeypatch):
    chat = Chat(session, monkeypatch)
    chat.tap("wiz prop")
    chat.tap("wiz kind live")
    assert "بزرگ‌تر از صفر" in chat.say("-3")["text"]
    assert "بزرگ‌تر از صفر" in chat.say("nan-ish")["text"]


def test_every_rulebook_button_fits_telegram(session):
    for [(_label, data)] in tw._rulebook_buttons():
        assert len(data.encode()) <= 64


def test_a_stranger_cannot_start_a_flow(session, monkeypatch):
    chat = Chat(session, monkeypatch, chat_id=999)
    chat.tap("wiz broker")
    assert tw._load() == {}
