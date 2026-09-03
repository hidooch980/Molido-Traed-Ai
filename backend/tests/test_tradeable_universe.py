"""Decide only on instruments the broker actually offers.

The snapshot is filled from a free data provider that carries symbols this
broker does not: crypto, metal futures, and a dozen thin currencies -
nineteen of forty-nine on this deployment. A brain takes two picks a side, so
a cycle where both of one brain's shorts are BTCUSD and GCFUT is a brain that
contributed nothing: its opinion is discarded at the order gate with "the
terminal publishes no contract specification", after it has already spent its
picks. Two accounts had never sent an order in their lives, and a quarter of
everything they were offered was of that kind.
"""

from __future__ import annotations

import json

import pytest

from app.providers import metatrader


def bridge_with(tmp_path, key: str, symbols: list[dict]):
    r"""A directory shaped like a live terminal's Common\Files.

    The heartbeat and the account are not decoration. `symbols()` refuses to
    answer for a terminal that is not publishing or has nobody logged in -
    "every price it shows is cached from a session that ended" - and neither
    kind of terminal should get a vote on what the fleet may trade. Writing
    both here is what makes this a test of the filter rather than a test of
    the staleness guard.
    """
    from datetime import UTC, datetime

    directory = tmp_path / key
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "molido_symbols.json").write_text(
        json.dumps({"symbols": symbols}), encoding="utf-8"
    )
    now = datetime.now(UTC).strftime("%Y.%m.%d %H:%M:%S")
    (directory / "molido_heartbeat.json").write_text(
        json.dumps(
            {
                "published_at": now,
                "connected": True,
                "trade_allowed": True,
                "refresh_seconds": 20,
            }
        ),
        encoding="utf-8",
    )
    (directory / "molido_account.json").write_text(
        json.dumps(
            {
                "published_at": now,
                "login": 5055372785,
                "server": "MetaQuotes-Demo",
                "currency": "USD",
                "balance": 1000.0,
                "equity": 1000.0,
                "leverage": 100,
                "trade_allowed": True,
                "trade_mode": 0,
                "connected": True,
            }
        ),
        encoding="utf-8",
    )
    return directory


def usable(name: str) -> dict:
    return {"name": name, "tick_value": 1.0, "tick_size": 1e-05}


class TestWhatCountsAsTradeable:
    def test_a_symbol_with_a_usable_specification_counts(self, tmp_path):
        dirs = {"term-b": bridge_with(tmp_path, "b", [usable("EURUSD")])}

        assert metatrader.tradeable_symbols(dirs) == frozenset({"EURUSD"})

    def test_one_terminal_offering_it_is_enough(self, tmp_path):
        """Accounts differ in what they may trade, and that is the account's
        own filter to apply, not this one's."""
        dirs = {
            "term-b": bridge_with(tmp_path, "b", [usable("EURUSD")]),
            "term-c": bridge_with(tmp_path, "c", [usable("XAUUSD")]),
        }

        assert metatrader.tradeable_symbols(dirs) == frozenset({"EURUSD", "XAUUSD"})

    def test_a_symbol_with_no_tick_value_does_not_count(self, tmp_path):
        """It is published but cannot be sized, which at the order gate is
        indistinguishable from not being offered."""
        dirs = {
            "term-b": bridge_with(
                tmp_path, "b", [usable("EURUSD"), {"name": "BTCUSD", "tick_size": 0.01}]
            )
        }

        assert metatrader.tradeable_symbols(dirs) == frozenset({"EURUSD"})

    def test_a_zero_tick_size_does_not_count(self, tmp_path):
        dirs = {
            "term-b": bridge_with(
                tmp_path,
                "b",
                [usable("EURUSD"), {"name": "GCFUT", "tick_value": 1.0, "tick_size": 0}],
            )
        }

        assert metatrader.tradeable_symbols(dirs) == frozenset({"EURUSD"})

    def test_a_bridge_that_publishes_nothing_contributes_nothing(self, tmp_path):
        empty = tmp_path / "empty"
        empty.mkdir()
        dirs = {"term-b": bridge_with(tmp_path, "b", [usable("EURUSD")]), "term-h": empty}

        assert metatrader.tradeable_symbols(dirs) == frozenset({"EURUSD"})

    def test_a_terminal_that_is_not_publishing_gets_no_vote(self, tmp_path):
        """Its symbol file may still be on disk from a session that ended.
        A dead terminal must not widen what the fleet believes it can buy."""
        stale = tmp_path / "stale"
        stale.mkdir()
        # The symbol file is on disk from a session that ended; nothing else
        # is, so the bridge reports the terminal as not usable.
        (stale / "molido_symbols.json").write_text(
            json.dumps({"symbols": [usable("XAUUSD")]}), encoding="utf-8"
        )
        dirs = {"term-b": bridge_with(tmp_path, "b", [usable("EURUSD")]), "term-x": stale}

        assert metatrader.tradeable_symbols(dirs) == frozenset({"EURUSD"})

    def test_no_bridges_at_all_is_empty_rather_than_an_error(self, tmp_path):
        """Empty is what the caller checks for to fail open. Raising here
        would stop a cycle over a narrowing that is only an optimisation."""
        assert metatrader.tradeable_symbols({}) == frozenset()


class TestTheNarrowingFailsOpen:
    def test_the_real_deployment_numbers(self):
        """Nineteen of the forty-nine ranked symbols are not offered by this
        broker. The list is the one read off term-f on 2026-09-03."""
        from app.brain import crosssection

        not_offered = {
            "BTCUSD", "ETHUSD", "GCFUT", "HGFUT", "PLFUT", "SIFUT",
            "USDCZK", "USDDKK", "USDHKD", "USDHUF", "USDILS", "USDINR",
            "USDMXN", "USDNOK", "USDPLN", "USDSGD", "USDTHB", "USDTRY",
            "USDZAR",
        }

        assert len(not_offered) == 19
        assert not_offered < crosssection.RANKED_UNIVERSE
        assert len(crosssection.RANKED_UNIVERSE - not_offered) == 30

    def test_the_measured_universe_is_not_touched(self):
        """`UNIVERSE_VERSION` says adding to it is a decision for the next
        measurement with its own start date. Shrinking it would change what
        every past measurement means, silently."""
        from app.brain import crosssection

        assert len(crosssection.RANKED_UNIVERSE) == 49
        assert "BTCUSD" in crosssection.RANKED_UNIVERSE

    def test_the_source_narrows_before_it_ranks(self):
        """Filtering the candidates alone would let the incumbent rank
        against forty-nine while the others ranked against thirty, and the
        whole basis of the comparison is that they differ only in what they
        choose."""
        import inspect

        from app.workers import forward

        source = inspect.getsource(forward.record_cycle)
        narrows = source.index("tradeable_symbols()")
        ranks = source.index("crosssection.rank(")

        assert narrows < ranks

    def test_it_keeps_the_snapshot_when_too_little_would_be_left(self):
        """Below the cross-section minimum the ranking is not a ranking, and
        a narrowing that produces a worse measurement than no narrowing
        should not happen silently."""
        import inspect

        from app.workers import forward

        source = inspect.getsource(forward.record_cycle)

        assert "MIN_FOR_INSTANT" in source
        assert "dropped = []" in source
