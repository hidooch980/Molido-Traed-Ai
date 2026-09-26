"""/prop from Telegram: the site's challenge-accounts table, prop and live."""

from __future__ import annotations

from app.integrations import telegram_bot
from app.integrations import telegram_prop as tp
from app.services import challenge_accounts, telegram_settings

BOOK = "ftmo-challenge-2step-phase1"


def rows(session):
    tenant = challenge_accounts.default_tenant(session)
    return {v.account.label: v.account for v in challenge_accounts.listing(session, tenant_id=tenant)}


def test_other_text_is_not_a_prop_command(session):
    assert tp.handle(session, "500", "/status") is None
    assert tp.handle(session, "500", "/propx") is None


def test_empty_listing_explains_itself(session):
    assert "هیچ حسابی" in tp.handle(session, "500", "/prop")


def test_a_prop_challenge_is_recorded_unconfirmed(session):
    text = tp.handle(session, "500", f"/prop add challenge 100000 {BOOK} FTMO 100k")
    assert "ثبت شد" in text
    account = rows(session)["FTMO 100k"]
    assert account.kind == "challenge" and account.rulebook_key == BOOK
    assert account.rules_confirmed is False


def test_a_live_account_needs_no_rulebook(session):
    assert "ثبت شد" in tp.handle(session, "500", "/prop add live 5,000 My Broker")
    account = rows(session)["My Broker"]
    assert account.kind == "live" and account.rulebook_key is None


def test_bad_input_is_refused_and_nothing_written(session):
    assert "شناخته نیست" in tp.handle(session, "500", f"/prop add bogus 100 {BOOK} X")
    assert "عدد نیست" in tp.handle(session, "500", f"/prop add challenge abc {BOOK} X")
    assert "بزرگ‌تر از صفر" in tp.handle(session, "500", f"/prop add challenge -5 {BOOK} X")
    assert "کامل نیست" in tp.handle(session, "500", "/prop add challenge 100")
    assert "انجام نشد" in tp.handle(session, "500", "/prop add challenge 100 no-such-book X")
    assert rows(session) == {}


def test_a_duplicate_label_is_refused_and_the_first_kept(session):
    tp.handle(session, "500", "/prop add live 5000 Same")
    assert "انجام نشد" in tp.handle(session, "500", "/prop add live 9000 Same")
    assert float(rows(session)["Same"].starting_balance) == 5000


def test_off_is_immediate_on_needs_confirm(session):
    tp.handle(session, "500", "/prop add live 5000 Acc One")
    assert "غیرفعال شد" in tp.handle(session, "500", "/prop off Acc One")
    assert rows(session)["Acc One"].is_active is False

    answer = tp.handle(session, "500", "/prop on Acc One")
    assert answer.buttons[0][0][1].endswith("confirm")
    assert rows(session)["Acc One"].is_active is False
    assert "فعال شد" in tp.handle(session, "500", "/prop on Acc One confirm")
    assert rows(session)["Acc One"].is_active is True


def test_delete_needs_confirm(session):
    tp.handle(session, "500", "/prop add live 5000 Gone")
    answer = tp.handle(session, "500", "/prop del Gone")
    assert answer.buttons[0][0][1].endswith("confirm")
    assert "Gone" in rows(session)
    assert "حذف شد" in tp.handle(session, "500", "/prop del Gone confirm")
    assert "Gone" not in rows(session)


def test_an_unknown_label_is_named(session):
    assert "نیست" in tp.handle(session, "500", "/prop off Ghost")


def test_listing_shows_prop_and_live(session):
    tp.handle(session, "500", f"/prop add funded 50000 {BOOK} Funded A")
    tp.handle(session, "500", "/prop add live 5000 Own")
    tp.handle(session, "500", "/prop off Own")
    answer = tp.handle(session, "500", "/prop")
    assert "🟢 Funded A — پراپ/funded" in answer.text and "⏸ Own — عادی" in answer.text


def test_buttons_name_the_account_by_id_and_work(session):
    tp.handle(session, "500", "/prop add live 5000 " + "Long Name " * 10)
    answer = tp.handle(session, "500", "/prop")
    off, delete = answer.buttons[0]
    assert all(len(data.encode()) <= 64 for _l, data in answer.buttons[0])
    assert "غیرفعال شد" in tp.handle(session, "500", off[1])

    confirm = tp.handle(session, "500", delete[1]).buttons[0][0][1]
    assert "حذف شد" in tp.handle(session, "500", confirm)
    assert rows(session) == {}


def test_a_malformed_id_is_not_found(session):
    assert "نیست" in tp.handle(session, "500", "/prop off id:zzz")


def _poll(session, monkeypatch, chat_id, text):
    from app.integrations import telegram

    def fake_api(method, payload, *, token=None, timeout=None):
        if method == "getUpdates":
            update = {"update_id": 1, "message": {"message_id": 7, "chat": {"id": chat_id}, "text": text}}
            return True, {"ok": True, "result": [update]}
        return True, {"ok": True}

    monkeypatch.setattr(telegram, "api_call", fake_api)
    monkeypatch.setattr(telegram_bot, "_write_offset", lambda _v: True)
    monkeypatch.setattr(telegram_bot, "_read_offset", lambda: 0)
    telegram_settings.save(session, token="1:AA", chat_ids=["500"])
    telegram_bot.poll(session)


def test_through_the_poll_admin_only(session, monkeypatch):
    _poll(session, monkeypatch, 999, "/prop add live 5000 Stranger")
    assert rows(session) == {}
    _poll(session, monkeypatch, 500, "/prop add live 5000 Admin")
    assert "Admin" in rows(session)
