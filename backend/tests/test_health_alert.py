"""A stale cycle reaches Telegram; a healthy one sends nothing."""

from __future__ import annotations

from datetime import UTC, datetime

from app.integrations import telegram
from app.workers import health_report

NOW = datetime(2026, 9, 15, 12, 0, tzinfo=UTC)


def _capture(monkeypatch, healthy, text):
    sent = []
    monkeypatch.setattr(health_report, "report", lambda session, now=None: (healthy, text))

    def fake_send(message, *, session=None, fingerprint=None, now=None):
        sent.append((message, fingerprint))
        return telegram.Delivery(sent=True)

    monkeypatch.setattr(telegram, "send", fake_send)
    return sent


def test_healthy_sends_nothing(monkeypatch):
    sent = _capture(monkeypatch, True, "all cycles fresh")

    result = health_report.alert(session=object(), now=NOW)

    assert result == {"healthy": True, "sent": False, "reason": None}
    assert sent == []


def test_stale_alerts_with_a_fingerprint_naming_the_jobs(monkeypatch):
    text = "cycles\nSTALE: resolve - each has missed at least two of its own runs"
    sent = _capture(monkeypatch, False, text)

    result = health_report.alert(session=object(), now=NOW)

    assert result["healthy"] is False and result["sent"] is True
    message, fingerprint = sent[0]
    assert message.body == text
    assert fingerprint == "health:STALE: resolve - each has missed at least two of its own runs"
