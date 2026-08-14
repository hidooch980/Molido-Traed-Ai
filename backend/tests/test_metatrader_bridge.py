"""Reading MetaTrader through the file bridge.

The state this deployment actually sat in, for hours, looking healthy: the
terminal was running, Market Watch showed live-looking prices, and every one of
them was cached from a session that had already ended. `connected: true` did
not catch it. A login of zero did.

So most of these tests are about telling three states apart - the bridge is not
running, the bridge runs with nothing behind it, the bridge has data - and
refusing to let the middle one pass as the third.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta

import pytest

from app.core.enums import Timeframe
from app.core.errors import ProviderError
from app.providers.metatrader import STALE_AFTER, MetaTraderBridge

NOW = datetime(2026, 8, 14, 12, 0, tzinfo=UTC)
STAMP = "2026.08.14 12:00:00"


@pytest.fixture()
def logs(tmp_path):
    directory = tmp_path / "logs"
    directory.mkdir()
    return directory


@pytest.fixture()
def bridge(tmp_path, logs):
    return MetaTraderBridge(tmp_path, log_directory=logs)


def write_log(directory, *lines, name="20260814.log"):
    """A terminal log, in the encoding the terminal actually writes.

    UTF-16 rather than UTF-8: reading it as UTF-8 yields text with a null byte
    between every character, which matches no pattern and fails silently.
    """
    (directory / name).write_text("\n".join(lines), encoding="utf-16")


#: Copied from the server, byte for byte, tab characters and all. A pattern
#: written against a remembered format is a pattern that matches nothing.
REAL_FAILURE = (
    "CD\t2\t09:25:03.172\tNetwork\t'111099517': authorization on "
    "MetaQuotes-Demo failed (Invalid account)"
)


def write_heartbeat(directory, stamp=STAMP, **extra):
    (directory / "molido_heartbeat.json").write_text(
        json.dumps({"published_at": stamp, "cycle": 1, **extra}), encoding="utf-8"
    )


def write_account(directory, login=501165913, connected=True, **extra):
    payload = {
        "published_at": STAMP,
        "login": login,
        "server": "RoboMarketsCY-Pro",
        "company": "RoboMarkets",
        "currency": "USD",
        "balance": 10000.0,
        "equity": 10000.0,
        "margin": 0.0,
        "free_margin": 10000.0,
        "leverage": 500,
        "trade_allowed": True,
        "connected": connected,
        **extra,
    }
    (directory / "molido_account.json").write_text(json.dumps(payload), encoding="utf-8")


def write_bars(directory, symbol="EURUSD", timeframe="H1", rows=3):
    lines = ["event_time,open,high,low,close,volume"]
    for hour in range(rows):
        lines.append(
            f"2026.08.14 0{hour}:00:00,1.1000{hour},1.1010{hour},1.0990{hour},1.1005{hour},100"
        )
    (directory / f"molido_bars_{symbol}_{timeframe}.csv").write_text(
        "\n".join(lines), encoding="utf-8"
    )


class TestTheThreeStatesStayApart:
    def test_no_heartbeat_is_not_running(self, bridge):
        state = bridge.state(now=NOW)

        assert state.running is False
        assert state.usable is False
        assert "not attached" in state.reason

    def test_a_stale_heartbeat_is_named_as_stale_not_missing(self, bridge, tmp_path):
        """A stopped expert and a missing one need different fixes, and one
        message for both sends the reader to the wrong one."""
        old = NOW - STALE_AFTER - timedelta(seconds=30)
        write_heartbeat(tmp_path, old.strftime("%Y.%m.%d %H:%M:%S"))

        state = bridge.state(now=NOW)

        assert state.running is False
        assert "stopped publishing" in state.reason

    def test_running_with_no_account_is_not_usable(self, bridge, tmp_path):
        """The exact state that looked healthy for hours: a terminal up,
        prices on screen, and all of them cached from a session that ended."""
        write_heartbeat(tmp_path)
        write_account(tmp_path, login=0, connected=False)

        state = bridge.state(now=NOW)

        assert state.running is True
        assert state.usable is False
        assert "no account is logged in" in state.reason

    def test_connected_true_with_login_zero_is_still_refused(self, bridge, tmp_path):
        """`connected` alone does not catch a cached session. The login does."""
        write_heartbeat(tmp_path)
        write_account(tmp_path, login=0, connected=True)

        assert bridge.state(now=NOW).usable is False

    def test_a_live_account_is_usable(self, bridge, tmp_path):
        write_heartbeat(tmp_path)
        write_account(tmp_path)

        state = bridge.state(now=NOW)

        assert state.usable is True
        assert state.reason is None


class TestAccount:
    def test_it_refuses_rather_than_returning_zeros(self, bridge, tmp_path):
        """Zeros would flow into a drawdown check and produce a verdict about
        an account that is not there."""
        write_heartbeat(tmp_path)
        write_account(tmp_path, login=0, connected=False)

        account = bridge.account(now=NOW)

        assert account["available"] is False
        assert "balance" not in account

    def test_balance_and_equity_are_both_published(self, bridge, tmp_path):
        """The difference between them is the open book, and a challenge is
        failed on equity."""
        write_heartbeat(tmp_path)
        write_account(tmp_path, equity=9800.0)

        account = bridge.account(now=NOW)

        assert account["balance"] == 10000.0
        assert account["equity"] == 9800.0


class TestSymbols:
    def test_a_missing_tick_value_is_flagged_not_defaulted(self, bridge, tmp_path):
        """Sizing without it is the difference between a 1% risk and a 10% one
        on anything that is not a standard lot."""
        write_heartbeat(tmp_path)
        write_account(tmp_path)
        (tmp_path / "molido_symbols.json").write_text(
            json.dumps(
                {
                    "published_at": STAMP,
                    "symbols": [
                        {"name": "EURUSD", "tick_value": 0.0, "contract_size": 100000.0},
                        {"name": "GBPUSD", "tick_value": 1.0, "contract_size": 100000.0},
                    ],
                }
            ),
            encoding="utf-8",
        )

        symbols = {s["name"]: s for s in bridge.symbols(now=NOW)["symbols"]}

        assert symbols["EURUSD"]["sizable"] is False
        assert symbols["EURUSD"]["tick_value"] is None
        assert symbols["GBPUSD"]["sizable"] is True


class TestBars:
    def test_bars_are_read_oldest_first(self, bridge, tmp_path):
        write_heartbeat(tmp_path)
        write_account(tmp_path)
        write_bars(tmp_path)

        bars = bridge.fetch_ohlcv("EURUSD", Timeframe.H1, now=NOW)

        assert len(bars) == 3
        assert bars[0].event_time < bars[-1].event_time

    def test_reading_without_an_account_raises_rather_than_returning_empty(
        self, bridge, tmp_path
    ):
        """An empty list reads as "no new bars", which is a different and much
        quieter claim than "there is no account"."""
        write_heartbeat(tmp_path)
        write_account(tmp_path, login=0, connected=False)
        write_bars(tmp_path)

        with pytest.raises(ProviderError):
            bridge.fetch_ohlcv("EURUSD", Timeframe.H1, now=NOW)

    def test_an_unpublished_symbol_says_which_ones_are(self, bridge, tmp_path):
        write_heartbeat(tmp_path)
        write_account(tmp_path)

        with pytest.raises(ProviderError) as exc:
            bridge.fetch_ohlcv("XAUUSD", Timeframe.H1, now=NOW)

        assert "Market Watch" in str(exc.value)

    def test_the_range_filters_what_was_published(self, bridge, tmp_path):
        write_heartbeat(tmp_path)
        write_account(tmp_path)
        write_bars(tmp_path, rows=3)

        bars = bridge.fetch_ohlcv(
            "EURUSD",
            Timeframe.H1,
            start=datetime(2026, 8, 14, 1, tzinfo=UTC),
            now=NOW,
        )

        assert len(bars) == 2

    def test_timestamps_are_utc(self, bridge, tmp_path):
        """The terminal writes its own clock and this deployment runs it at
        GMT+0. A naive datetime here would compare wrongly against every other
        bar in the system."""
        write_heartbeat(tmp_path)
        write_account(tmp_path)
        write_bars(tmp_path)

        bars = bridge.fetch_ohlcv("EURUSD", Timeframe.H1, now=NOW)

        assert bars[0].event_time.tzinfo is not None


class TestItReadsTheReasonRatherThanGuessingIt:
    """Two diagnoses were guessed here and both were wrong: "the expert
    stopped" when it had not, and "a failed login stops the bridge" when it
    does not - it publishes with no account behind it. The terminal had written
    the real reason to its own log the whole time."""

    def test_the_terminals_own_words_reach_the_reader(self, bridge, tmp_path, logs):
        write_log(logs, REAL_FAILURE)
        write_heartbeat(tmp_path)
        write_account(tmp_path, login=0, connected=False)

        reason = bridge.state(now=NOW).reason

        assert "Invalid account" in reason
        assert "111099517" in reason

    def test_an_invalid_account_is_not_flattened_into_login_failed(self, bridge, logs):
        """An account that does not exist and a wrong password need opposite
        actions, and no password fixes the first one."""
        write_log(logs, REAL_FAILURE)

        assert "Invalid account" in bridge.last_authorization()

    def test_the_last_attempt_wins(self, bridge, logs):
        """An earlier failure followed by a success must not be reported as the
        current state."""
        write_log(
            logs,
            REAL_FAILURE,
            "DP\t0\t09:40:11.004\tNetwork\t'501165913': authorization on "
            "RoboMarketsCY-Pro performed",
        )

        latest = bridge.last_authorization()

        assert "501165913" in latest
        assert "111099517" not in latest

    def test_no_log_says_nothing_rather_than_inventing_a_cause(self, bridge):
        """None means "MetaTrader has not said", never "everything is fine"."""
        assert bridge.last_authorization() is None

    def test_a_missing_log_directory_does_not_break_the_state(self, tmp_path):
        """The reason must survive a deployment where the log is not mounted."""
        bridge = MetaTraderBridge(tmp_path, log_directory=tmp_path / "absent")

        state = bridge.state(now=NOW)

        assert state.usable is False
        assert state.reason

    def test_a_utf8_log_does_not_raise_or_half_parse(self, bridge, logs):
        """The terminal writes UTF-16. Reading it as UTF-8 gives text with a
        null between every character, which matches nothing and fails quietly -
        so this asserts the encoding is handled, not tolerated."""
        (logs / "20260814.log").write_text(REAL_FAILURE, encoding="utf-8")

        result = bridge.last_authorization()

        assert result is None or "Invalid account" in result

    def test_a_healthy_account_reports_no_reason_even_with_an_old_failure(
        self, bridge, tmp_path, logs
    ):
        """The log keeps yesterday's failures forever. Appending one to a
        working bridge would report a problem that is over."""
        write_log(logs, REAL_FAILURE)
        write_heartbeat(tmp_path)
        write_account(tmp_path)

        state = bridge.state(now=NOW)

        assert state.usable is True
        assert state.reason is None

    def test_metaeditor_log_does_not_shadow_the_terminal_log(self, bridge, logs):
        """The real directory holds 20260813.log, 20260814.log and
        metaeditor.log. The last of those sorts highest and has no login lines
        in it, so taking the alphabetically last file reported "MetaTrader has
        not said" on a server that had said it twice."""
        write_log(logs, REAL_FAILURE, name="20260814.log")
        (logs / "metaeditor.log").write_text("nothing relevant here", encoding="utf-16")

        assert "Invalid account" in bridge.last_authorization()

    def test_the_newest_day_wins_over_an_older_one(self, bridge, logs):
        """Yesterday's failure must not outrank today's success."""
        write_log(logs, REAL_FAILURE, name="20260813.log")
        write_log(
            logs,
            "DP	0	09:40:11.004	Network	'501165913': authorization on "
            "RoboMarketsCY-Pro performed",
            name="20260814.log",
        )

        assert "501165913" in bridge.last_authorization()
