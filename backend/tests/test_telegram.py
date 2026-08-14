"""Sending to a chat channel, and the four things that must stay true.

None of the rules here is new. Each one already exists somewhere in this
codebase - the allowlist from the command parser, the cooldown from incident
memory, the redaction from the notifier, and "unconfigured means off" from the
webhook secret. This is where they meet an outbound network call, which is
where they get quietly dropped.

Nothing in this file touches the network. `_post` is replaced, so the decision
about whether to send is tested exactly as production makes it while the send
itself is a function that records.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from app.integrations import notify, telegram
from app.integrations.notify import Urgency
from app.ops import incidents as incident_memory

NOW = datetime(2026, 8, 14, 12, 0, tzinfo=UTC)


@pytest.fixture()
def sent(monkeypatch):
    """Records what would have gone out, and never leaves the process."""
    calls: list[tuple[str, dict]] = []

    def fake_post(method, payload):
        calls.append((method, payload))
        return True, "delivered"

    monkeypatch.setattr(telegram, "_post", fake_post)
    return calls


@pytest.fixture()
def configured(monkeypatch):
    from app.core.config import get_settings

    settings = get_settings()
    monkeypatch.setattr(settings, "telegram_bot_token", "test-token", raising=False)
    monkeypatch.setattr(settings, "telegram_chat_id", "@Molidoo", raising=False)
    return settings


def message(title="Feed stale", body="EURUSD H1 has not updated"):
    return notify.Message(urgency=Urgency.WARNING, title=title, body=body, at=NOW)


class TestUnconfiguredMeansOff:
    def test_no_token_refuses_and_says_so(self, monkeypatch, sent):
        from app.core.config import get_settings

        monkeypatch.setattr(get_settings(), "telegram_bot_token", "", raising=False)

        result = telegram.send(message())

        assert result.sent is False
        assert "not configured to send" in result.reason
        assert sent == [], "nothing may be attempted when unconfigured"

    def test_a_token_with_no_channel_is_also_refused(self, monkeypatch, sent):
        from app.core.config import get_settings

        settings = get_settings()
        monkeypatch.setattr(settings, "telegram_bot_token", "test-token", raising=False)
        monkeypatch.setattr(settings, "telegram_chat_id", "", raising=False)

        result = telegram.send(message())

        assert result.sent is False
        assert "nowhere to send" in result.reason


class TestTheChannelIsReadOnly:
    @pytest.mark.parametrize("text", ["/status", "/drawdown", "/why_no_trade", "health"])
    def test_a_question_is_accepted(self, text):
        assert telegram.answer(text)["accepted"] is True

    @pytest.mark.parametrize(
        "text", ["/buy EURUSD", "/close all", "/set risk 5", "/execute", "/disable_kill_switch"]
    )
    def test_an_instruction_is_refused(self, text):
        """Anyone holding the bot token is indistinguishable from the owner,
        and the token sits in a config file on a host that gets brute-forced
        daily."""
        reply = telegram.answer(text)

        assert reply["accepted"] is False
        assert "execute permission" in reply["note"]

    def test_a_refusal_lists_what_is_allowed(self):
        """A bot that says only "no" teaches nobody what it does."""
        reply = telegram.answer("/buy EURUSD")

        assert reply["allowed"] == sorted(notify.READ_ONLY_COMMANDS)

    def test_an_unknown_command_does_not_raise_at_the_caller(self):
        """A chat message is not a request that deserves a stack trace; the
        refusal is the reply."""
        reply = telegram.answer("/nonsense")

        assert reply["accepted"] is False
        assert reply["reason"]


class TestDeduplication:
    def test_a_message_without_a_fingerprint_always_sends(self, configured, sent, session):
        """Right for a message a person asked for, wrong for one a checker
        produces - so the caller states which it is."""
        telegram.send(message(), session=session, now=NOW)
        telegram.send(message(), session=session, now=NOW)

        assert len(sent) == 2

    def test_a_repeat_inside_the_cooldown_is_suppressed(self, configured, sent, session):
        incident = incident_memory.record(
            session,
            incident_memory.Report(source="collector", summary="feed stale"),
            now=NOW,
        )

        first = telegram.send(
            message(), session=session, fingerprint=incident.fingerprint, now=NOW
        )
        second = telegram.send(
            message(),
            session=session,
            fingerprint=incident.fingerprint,
            now=NOW + timedelta(minutes=5),
        )

        assert first.sent is True
        assert second.sent is False
        assert second.suppressed is True
        assert len(sent) == 1

    def test_it_speaks_again_after_the_cooldown(self, configured, sent, session):
        incident = incident_memory.record(
            session,
            incident_memory.Report(source="collector", summary="feed stale"),
            now=NOW,
        )
        telegram.send(message(), session=session, fingerprint=incident.fingerprint, now=NOW)

        later = NOW + incident_memory.ALERT_COOLDOWN + timedelta(minutes=1)
        again = telegram.send(
            message(), session=session, fingerprint=incident.fingerprint, now=later
        )

        assert again.sent is True
        assert len(sent) == 2

    def test_suppression_is_not_reported_as_failure(self, configured, sent, session):
        """A suppressed alert worked as designed. Reporting it as an error
        trains somebody to widen the cooldown until it does nothing."""
        incident = incident_memory.record(
            session,
            incident_memory.Report(source="collector", summary="feed stale"),
            now=NOW,
        )
        telegram.send(message(), session=session, fingerprint=incident.fingerprint, now=NOW)

        result = telegram.send(
            message(), session=session, fingerprint=incident.fingerprint, now=NOW
        )

        assert result.sent is False
        assert result.suppressed is True


class TestNothingLeaks:
    def test_the_delivery_never_carries_the_token(self, configured, sent, session):
        result = telegram.send(message(), session=session, now=NOW)

        assert "test-token" not in str(result.as_dict())

    def test_a_failure_reports_the_api_not_the_request(self, configured, monkeypatch, session):
        """An error containing the URL would put the token in whatever caught
        it."""
        monkeypatch.setattr(
            telegram, "_post", lambda method, payload: (False, "chat not found")
        )

        result = telegram.send(message(), session=session, now=NOW)

        assert result.sent is False
        assert result.reason == "chat not found"
        assert "test-token" not in str(result.as_dict())

    def test_an_over_long_message_is_truncated_and_says_so(self, configured, sent, session):
        """Telegram refuses anything longer, and a silent refusal is an alert
        nobody receives."""
        telegram.send(message(body="x" * 9000), session=session, now=NOW)

        text = sent[0][1]["text"]

        assert len(text) <= telegram.MAX_MESSAGE
        assert text.endswith("[truncated]")


class TestTheCheckDoesNotNotifyAnybody:
    def test_check_uses_getme_rather_than_sending(self, configured, sent):
        """A health check that messages the channel every time it runs has
        become its own outage."""
        telegram.check()

        assert [method for method, _ in sent] == ["getMe"]

    def test_check_on_an_unconfigured_deployment_says_so(self, monkeypatch):
        from app.core.config import get_settings

        monkeypatch.setattr(get_settings(), "telegram_bot_token", "", raising=False)

        state = telegram.check()

        assert state["configured"] is False
        assert "not configured" in state["reason"]
