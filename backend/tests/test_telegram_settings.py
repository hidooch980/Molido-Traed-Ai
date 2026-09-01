"""The chat channel, configured from the site and reaching every admin."""

import pytest

from app.core.errors import ValidationFailedError
from app.services import telegram_settings


class TestTheTokenIsStoredAndNeverReturned:
    def test_a_saved_token_comes_back_masked(self, session):
        channel = telegram_settings.save(
            session, token="123456:AAHsecretsecretsecret", chat_ids=["55"]
        )

        payload = channel.as_dict()
        assert payload["configured"] is True
        assert "secret" not in str(payload)
        assert payload["masked_token"].startswith("123456:A")

    def test_a_token_with_no_colon_is_refused(self, session):
        with pytest.raises(ValidationFailedError):
            telegram_settings.save(session, token="not-a-token")

    def test_clearing_the_token_is_different_from_leaving_it(self, session):
        telegram_settings.save(session, token="1:AA", chat_ids=["7"])

        untouched = telegram_settings.save(session, chat_ids=["7", "8"])
        assert untouched.token == "1:AA"

        cleared = telegram_settings.save(session, token="")
        assert cleared.token == ""


class TestEveryAdminIsReached:
    def test_multiple_chat_ids_are_kept_in_order(self, session):
        channel = telegram_settings.save(
            session, token="1:AA", chat_ids=["100", "-200", "300"]
        )

        assert channel.chat_ids == ("100", "-200", "300")
        assert channel.as_dict()["recipients"] == 3

    def test_a_group_id_is_negative_and_still_valid(self, session):
        channel = telegram_settings.save(session, token="1:AA", chat_ids=["-1001234"])

        assert channel.chat_ids == ("-1001234",)

    def test_a_username_is_refused_rather_than_dropped(self, session):
        """Silently discarding it is a person who thinks they are on the
        alert list and is not."""
        with pytest.raises(ValidationFailedError):
            telegram_settings.save(session, token="1:AA", chat_ids=["@someone"])

    def test_duplicates_collapse(self, session):
        channel = telegram_settings.save(session, token="1:AA", chat_ids=["9", "9"])

        assert channel.chat_ids == ("9",)


class TestConfigurationSources:
    def test_no_configuration_is_not_ready(self, session):
        channel = telegram_settings.load(session)

        assert channel.ready is False
        assert channel.as_dict()["configured"] is False

    def test_switched_off_is_a_state_not_an_absence(self, session):
        from app.integrations import telegram

        telegram_settings.save(
            session, token="1:AA", chat_ids=["5"], enabled=False
        )

        ready, reason = telegram.configured(session)
        assert ready is False
        assert "switched off" in reason

    def test_a_configured_channel_is_ready(self, session):
        from app.integrations import telegram

        telegram_settings.save(session, token="1:AA", chat_ids=["5"])

        ready, _ = telegram.configured(session)
        assert ready is True


class TestSendingReachesEachRecipientSeparately:
    def test_one_stale_id_does_not_silence_the_others(self, session, monkeypatch):
        from datetime import UTC, datetime

        from app.integrations import notify, telegram

        telegram_settings.save(session, token="1:AA", chat_ids=["1", "2", "3"])
        seen = []

        def fake_post(method, payload, *, token=None):
            seen.append(payload["chat_id"])
            return (payload["chat_id"] != "2", "chat not found")

        monkeypatch.setattr(telegram, "_post", fake_post)

        delivery = telegram.send(
            notify.Message(
                urgency=notify.Urgency.INFO,
                title="t",
                body="b",
                at=datetime.now(UTC),
            ),
            session=session,
        )

        assert seen == ["1", "2", "3"]
        assert delivery.sent is True
        assert delivery.chat_id == "1,3"
        assert "2: chat not found" in delivery.reason
