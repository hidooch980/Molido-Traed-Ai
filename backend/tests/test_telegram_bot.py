"""The chat side: Persian answers, buttons, and the door that stays shut."""

from app.integrations import telegram_bot
from app.services import telegram_settings


class TestTheDoorStaysShut:
    """A keyboard is a convenience for typing, never a second entrance."""

    def test_every_button_is_on_the_read_only_allowlist(self):
        from app.integrations import notify

        for row in telegram_bot.KEYBOARD:
            for _label, command in row:
                assert command in notify.READ_ONLY_COMMANDS

    def test_a_command_outside_the_allowlist_is_refused(self, session):
        reply = telegram_bot.answer_command(session, "/buy EURUSD 1.0")

        assert "نمی‌شناسم" in reply.text

    def test_a_trade_verb_dressed_as_a_button_is_still_refused(self, session):
        """The callback payload goes through the same check as typed text."""
        reply = telegram_bot.answer_command(session, "close_all")

        assert "نمی‌شناسم" in reply.text


class TestItAnswersInPersian:
    def test_help_lists_what_it_can_do(self, session):
        reply = telegram_bot.answer_command(session, "/help")

        assert "دستورها" in reply.text
        assert "/status" in reply.text
        assert "سفارشی ثبت کند" in reply.text

    def test_every_allowlisted_command_answers(self, session):
        from app.integrations import notify

        for command in sorted(notify.READ_ONLY_COMMANDS):
            reply = telegram_bot.answer_command(session, command)
            # Either a real answer or a named failure - never silence, and
            # never the "unknown command" line, which would mean the
            # allowlist and this module had drifted apart.
            assert reply.text.strip()
            assert "نمی‌شناسم" not in reply.text

    def test_a_failing_answer_is_named_rather_than_swallowed(
        self, session, monkeypatch
    ):
        def explode(_session):
            raise RuntimeError("the bridge is unreadable")

        monkeypatch.setitem(telegram_bot.ANSWERS, "status", explode)

        reply = telegram_bot.answer_command(session, "status")

        assert "the bridge is unreadable" in reply.text


class TestOnlyAdminsAreAnswered:
    def poll_with(self, session, monkeypatch, update):
        calls = []

        def fake_api(method, payload, *, token=None):
            calls.append((method, payload))
            if method == "getUpdates":
                return True, {"ok": True, "result": [update]}
            return True, {"ok": True}

        from app.integrations import telegram

        monkeypatch.setattr(telegram, "api_call", fake_api)
        monkeypatch.setattr(telegram_bot, "_write_offset", lambda _v: None)
        monkeypatch.setattr(telegram_bot, "_read_offset", lambda: 0)
        telegram_settings.save(session, token="1:AA", chat_ids=["500"])
        report = telegram_bot.poll(session)
        return report, calls

    def test_a_stranger_gets_one_sentence_and_no_data(self, session, monkeypatch):
        report, calls = self.poll_with(
            session,
            monkeypatch,
            {
                "update_id": 1,
                "message": {"chat": {"id": 999}, "text": "/status"},
            },
        )

        assert report["refused"] == 1
        assert report["answered"] == 0
        sent = [p for m, p in calls if m == "sendMessage"]
        assert len(sent) == 1
        assert "ادمین‌های ثبت‌شده" in sent[0]["text"]

    def test_an_admin_is_answered_with_the_keyboard(self, session, monkeypatch):
        report, calls = self.poll_with(
            session,
            monkeypatch,
            {
                "update_id": 2,
                "message": {"chat": {"id": 500}, "text": "/help"},
            },
        )

        assert report["answered"] == 1
        sent = [p for m, p in calls if m == "sendMessage"][0]
        assert "reply_markup" in sent
        assert "inline_keyboard" in sent["reply_markup"]

    def test_a_button_press_is_answered_like_a_typed_command(
        self, session, monkeypatch
    ):
        report, calls = self.poll_with(
            session,
            monkeypatch,
            {
                "update_id": 3,
                "callback_query": {
                    "id": "cb1",
                    "data": "help",
                    "message": {"chat": {"id": 500}},
                },
            },
        )

        assert report["answered"] == 1
        assert any(m == "answerCallbackQuery" for m, _ in calls)

    def test_an_unconfigured_channel_polls_nothing(self, session):
        report = telegram_bot.poll(session)

        assert report["polled"] == 0
        assert "not configured" in report["reason"]
