"""Host scripts reach Telegram with a namespaced fingerprint."""

from __future__ import annotations

import contextlib

from app.db import session as db_session
from app.integrations import telegram
from app.ops import host_alert


def test_send_namespaces_the_fingerprint(monkeypatch):
    calls = []

    @contextlib.contextmanager
    def fake_scope():
        yield object()

    def fake_send(message, *, session=None, fingerprint=None, now=None):
        calls.append((message.title, message.body, fingerprint))
        return telegram.Delivery(sent=True)

    monkeypatch.setattr(db_session, "session_scope", fake_scope)
    monkeypatch.setattr(telegram, "send", fake_send)

    assert host_alert.send("restart", "collector unhealthy", "autoheal:collector")["sent"]
    assert calls == [("MolidoTrade — restart", "collector unhealthy", "host:autoheal:collector")]


def test_missing_arguments_is_a_usage_error():
    assert host_alert.main(["only-title"]) == 2
