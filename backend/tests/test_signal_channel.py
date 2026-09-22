"""Trade signals to a Telegram channel, from what the terminals publish."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from app.core.errors import ValidationFailedError
from app.integrations import signal_channel as sc
from app.services import telegram_settings

NOW = datetime(2026, 9, 23, 9, 0, tzinfo=UTC)


def pos(ticket, symbol="EURUSD", side="buy", entry=1.1000, stop=1.0950, target=1.1100):
    return {
        "ticket": ticket,
        "symbol": symbol,
        "side": side,
        "price_open": entry,
        "stop": stop,
        "target": target,
        "volume": 1.0,
    }


def deal(ticket, symbol="EURUSD", side="sell", price=1.1100, net=500.0):
    return {"ticket": ticket, "symbol": symbol, "side": side, "price": price, "net": net}


class Outbox:
    def __init__(self, ok=True):
        self.sent: list[str] = []
        self.ok = ok

    def __call__(self, text: str) -> bool:
        self.sent.append(text)
        return self.ok


def books(**by_key):
    return {k: v if isinstance(v, sc.Book) else sc.Book(True, *v) for k, v in by_key.items()}


def test_the_first_look_posts_nothing():
    out = Outbox()
    state = sc.step(None, books(b=([pos(1)], [deal(9)])), now=NOW, send=out)

    assert out.sent == []
    assert "b:1" in state["known"]
    assert "9" in state["used_deals"]


def test_a_new_position_is_posted_once_as_a_signal():
    out = Outbox()
    state = sc.step(None, books(b=([], [])), now=NOW, send=out)

    state = sc.step(state, books(b=([pos(2)], [])), now=NOW, send=out)
    state = sc.step(state, books(b=([pos(2)], [])), now=NOW + timedelta(minutes=1), send=out)

    assert len(out.sent) == 1
    assert "سیگنال خرید EURUSD" in out.sent[0]
    assert "ورود: 1.1" in out.sent[0]
    assert "حد ضرر: 1.095" in out.sent[0]
    assert "حد سود: 1.11" in out.sent[0]


def test_a_second_account_on_the_same_idea_is_not_posted_again():
    out = Outbox()
    state = sc.step(None, books(b=([], []), c=([], [])), now=NOW, send=out)

    state = sc.step(state, books(b=([pos(2)], []), c=([pos(3)], [])), now=NOW, send=out)

    assert len(out.sent) == 1


def test_the_same_idea_after_the_window_is_a_new_signal():
    out = Outbox()
    state = sc.step(None, books(b=([], [])), now=NOW, send=out)
    state = sc.step(state, books(b=([pos(2)], [])), now=NOW, send=out)
    later = NOW + sc.SAME_SIGNAL_WINDOW + timedelta(minutes=1)

    sc.step(state, books(b=([pos(2), pos(5)], [])), now=later, send=out)

    assert len(out.sent) == 2


def test_a_closed_signal_is_posted_with_its_result_in_r():
    out = Outbox()
    state = sc.step(None, books(b=([], [])), now=NOW, send=out)
    state = sc.step(state, books(b=([pos(2)], [])), now=NOW, send=out)

    state = sc.step(state, books(b=([], [deal(40, price=1.1100)])), now=NOW, send=out)

    assert "بسته شد: خرید EURUSD" in out.sent[-1]
    assert "سود +2.00R" in out.sent[-1]
    assert out.sent[-1].startswith("✅")
    assert state["signals"] == {}


def test_a_losing_sell_reads_as_a_loss():
    out = Outbox()
    state = sc.step(None, books(b=([], [])), now=NOW, send=out)
    state = sc.step(
        state, books(b=([pos(2, side="sell", entry=1.1, stop=1.105, target=1.09)], [])),
        now=NOW, send=out,
    )

    sc.step(state, books(b=([], [deal(41, side="buy", price=1.105, net=-500)])), now=NOW, send=out)

    assert out.sent[-1].startswith("❌")
    assert "ضرر -1.00R" in out.sent[-1]


def test_positions_open_before_the_channel_are_never_announced_as_closed():
    out = Outbox()
    state = sc.step(None, books(b=([pos(1)], [])), now=NOW, send=out)

    sc.step(state, books(b=([], [deal(42)])), now=NOW, send=out)

    assert out.sent == []


def test_an_unreadable_terminal_closes_nothing():
    out = Outbox()
    state = sc.step(None, books(b=([], [])), now=NOW, send=out)
    state = sc.step(state, books(b=([pos(2)], [])), now=NOW, send=out)

    state = sc.step(state, {"b": sc.Book(False)}, now=NOW, send=out)

    assert len(out.sent) == 1
    assert "b:2" in state["signals"]


def test_a_failed_send_is_retried_next_time():
    failing = Outbox(ok=False)
    state = sc.step(None, books(b=([], [])), now=NOW, send=failing)
    state = sc.step(state, books(b=([pos(2)], [])), now=NOW, send=failing)
    assert state["signals"] == {}

    working = Outbox()
    sc.step(state, books(b=([pos(2)], [])), now=NOW, send=working)
    assert len(working.sent) == 1


def test_no_channel_configured_does_nothing(session):
    assert sc.run(session)["reason"] == "no signal channel is configured"


@pytest.mark.parametrize(
    ("given", "stored"),
    [
        ("@molido_signals", "@molido_signals"),
        ("https://t.me/molido_signals", "@molido_signals"),
        ("-1001234567890", "-1001234567890"),
        ("", ""),
    ],
)
def test_the_channel_is_saved_from_the_site(session, given, stored):
    channel = telegram_settings.save(session, token="1:AA", chat_ids=["5"], signal_channel=given)

    assert channel.signal_channel == stored
    assert channel.as_dict()["signal_channel"] == stored


def test_a_malformed_channel_is_refused(session):
    with pytest.raises(ValidationFailedError):
        telegram_settings.save(session, signal_channel="my channel")
