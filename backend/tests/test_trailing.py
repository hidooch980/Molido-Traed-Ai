"""Tightening a stop, and refusing every way of loosening one.

A trailing stop has exactly one way to cost money: moving a stop away from
the price. Everything else it can get wrong costs a missed improvement,
which is what the position already had. So most of these tests are about the
refusals rather than the moves.
"""

from __future__ import annotations

import pytest

from app.workers import trailing


class TestWhereTheStopBelongs:
    def test_a_long_that_has_not_earned_it_is_left_alone(self):
        """Below the start, the stop stays where the sizing put it. A trail
        that begins immediately is a tighter stop wearing the original
        stop's name."""
        where, why = trailing.proposed_stop(
            side="buy", entry=1.1000, stop=1.0900, price=1.1050
        )

        assert where is None
        assert "0.50 R ahead" in why

    def test_a_long_one_r_ahead_locks_in_part_of_it(self):
        where, why = trailing.proposed_stop(
            side="buy", entry=1.1000, stop=1.0900, price=1.1100
        )

        # 100 points of distance, trailing 60 behind the price.
        assert where == pytest.approx(1.1040)
        assert "1.00 R ahead" in why

    def test_a_short_trails_from_above(self):
        where, _why = trailing.proposed_stop(
            side="sell", entry=1.1000, stop=1.1100, price=1.0900
        )

        assert where == pytest.approx(1.0960)

    def test_the_new_stop_is_ahead_of_entry_not_at_break_even(self):
        """At 1 R ahead with a 0.6 lag the stop lands at +0.4 R. Break-even
        would hand the trade back on the next ordinary wobble."""
        entry, stop = 1.1000, 1.0900
        where, _why = trailing.proposed_stop(
            side="buy", entry=entry, stop=stop, price=1.1100
        )

        locked = (where - entry) / abs(entry - stop)
        assert locked == pytest.approx(0.4)


class TestItNeverWidens:
    def test_a_long_stop_is_never_lowered(self):
        """The position ran to 2 R, then fell back. The stop stays where the
        earlier move put it."""
        where, why = trailing.proposed_stop(
            side="buy", entry=1.1000, stop=1.1090, price=1.1120
        )

        assert where is None
        assert "below the stop already set" in why

    def test_a_short_stop_is_never_raised(self):
        where, why = trailing.proposed_stop(
            side="sell", entry=1.1000, stop=1.0910, price=1.0880
        )

        assert where is None
        assert "above the stop already set" in why

    def test_a_losing_position_is_never_touched(self):
        """The one case where a widening stop is most tempting and most
        expensive."""
        where, why = trailing.proposed_stop(
            side="buy", entry=1.1000, stop=1.0900, price=1.0950
        )

        assert where is None
        assert "R ahead" in why

    def test_a_position_with_no_distance_is_refused(self):
        where, why = trailing.proposed_stop(
            side="buy", entry=1.1000, stop=1.1000, price=1.2000
        )

        assert where is None
        assert "R is undefined" in why


class Bridge:
    def __init__(self, login="111", positions=None, available=True, quotes=None):
        self._login = login
        self._positions = positions or []
        self._available = available
        self._quotes = quotes if quotes is not None else {}

    def account(self):
        return {"available": self._available, "login": self._login}

    def positions(self):
        return {"positions": self._positions}

    def symbols(self):
        return {
            "available": True,
            "symbols": [
                {"name": name, "bid": bid, "ask": ask}
                for name, (bid, ask) in self._quotes.items()
            ],
        }


class Broker:
    def __init__(self):
        self.calls = []

    def amend(self, ticket, *, stop=None, target=None):
        self.calls.append((ticket, stop, target))
        return type("R", (), {"reason": "stop moved", "state": "filled"})()


def winner(**over):
    # Target at 1.5x the stop distance, which is the deployed geometry - and
    # what `original_risk` reads once the stop itself has been moved.
    row = {
        "ticket": "1",
        "symbol": "EURUSD",
        "side": "buy",
        "price_open": 1.1000,
        "stop": 1.0900,
        "target": 1.1150,
        "price_current": 1.1100,
    }
    row.update(over)
    return row


class TestTheSweep:
    def test_it_does_nothing_unless_an_account_asks(self):
        """The forward record measures a fixed geometry. Turning this on
        everywhere would end that measurement and replace it with an
        unmeasured one."""
        report = trailing.run(Bridge(positions=[winner()]), Broker(), logins=None)

        assert report.moves == []
        assert "trailing is not enabled for any account" in report.skipped

    def test_an_account_that_is_not_enabled_is_left_alone(self):
        report = trailing.run(
            Bridge(login="222", positions=[winner()]), Broker(), logins={"111"}
        )

        assert report.moves == []

    def test_a_dry_run_proposes_and_sends_nothing(self):
        broker = Broker()

        report = trailing.run(
            Bridge(positions=[winner()]), broker, logins={"111"}, dry_run=True
        )

        assert len(report.moves) == 1
        assert report.moves[0].sent is False
        assert broker.calls == []

    def test_a_live_run_sends_the_amend(self):
        broker = Broker()

        report = trailing.run(
            Bridge(positions=[winner()]), broker, logins={"111"}, dry_run=False
        )

        assert broker.calls == [("1", pytest.approx(1.1040), None)]
        assert report.moves[0].sent is True

    def test_only_the_stop_is_sent(self):
        """The target is what the measurement is scored against. Moving it
        would change the trade being measured, not the floor under it."""
        broker = Broker()

        trailing.run(Bridge(positions=[winner()]), broker, logins={"111"}, dry_run=False)

        _ticket, _stop, target = broker.calls[0]
        assert target is None

    def test_a_position_with_no_stop_is_skipped_not_given_one(self):
        """A position with no stop is a separate defect with its own alarm.
        Inventing one here would silence it."""
        broker = Broker()

        report = trailing.run(
            Bridge(positions=[winner(stop=0)]), broker, logins={"111"}, dry_run=False
        )

        assert broker.calls == []
        assert "no stop on the position" in report.skipped

    def test_a_tiny_improvement_is_not_worth_a_round_trip(self):
        """Each amend is a file, a claim, a venue call and a log line. A few
        points every cycle forever is a cost with no benefit.

        The stop has already been trailed to 1.1045. Price has crept four
        points; the trail would move it to 1.1049, which is not worth a
        round trip.
        """
        broker = Broker()

        report = trailing.run(
            Bridge(positions=[winner(stop=1.1045, price_current=1.1109)]),
            broker,
            logins={"111"},
            dry_run=False,
        )

        assert broker.calls == []
        assert "the improvement is smaller than one step" in report.skipped

    def test_the_trail_does_not_accelerate_once_the_stop_has_moved(self):
        """The bug this class exists to prevent. After the first move,
        `entry - stop` is locked-in profit rather than risk, and measuring
        against it makes every later pass think the trade is further ahead
        than it is - the trail then tightens until it chokes the position.

        Entry 1.1000, original risk 100 points, stop already trailed to
        1.1040. At 1.1150 the trail belongs 60 points back, at 1.1090 - not
        at 1.1126, which is where a stop-derived distance would put it.
        """
        where, _why = trailing.proposed_stop(
            side="buy",
            entry=1.1000,
            stop=1.1040,
            price=1.1150,
            risk=trailing.original_risk(entry=1.1000, stop=1.1040, target=1.1150),
        )

        assert where == pytest.approx(1.1090)


class TestTheRiskThatWasSizedAgainst:
    def test_the_target_carries_it_after_the_stop_has_moved(self):
        """The target is the one level that never moves, and it sits at a
        fixed multiple of the original stop distance."""
        assert trailing.original_risk(
            entry=1.1000, stop=1.1040, target=1.1150
        ) == pytest.approx(0.0100)

    def test_without_a_target_it_falls_back_to_the_stop(self):
        """Correct only before the first move, which is the only case where
        there is nothing else to read."""
        assert trailing.original_risk(
            entry=1.1000, stop=1.0900, target=None
        ) == pytest.approx(0.0100)

    def test_an_unreadable_bridge_does_not_stop_the_sweep(self):
        class Broken(Bridge):
            def positions(self):
                raise OSError("gone")

        report = trailing.run(Broken(), Broker(), logins={"111"}, dry_run=False)

        assert report.moves == []
        assert any("could not be read" in k for k in report.skipped)

    def test_a_broker_that_cannot_amend_says_so(self):
        class Paper:
            pass

        report = trailing.run(
            Bridge(positions=[winner()]), Paper(), logins={"111"}, dry_run=False
        )

        assert report.moves[0].sent is False
        assert "cannot amend" in report.moves[0].result


class TestTheExpertRefusesToo:
    """The rule is enforced at the venue as well, where no mistake on this
    side can reach past it."""

    @staticmethod
    def source():
        import pathlib

        here = pathlib.Path(__file__).resolve().parents[2]
        return (here / "infra" / "mql5" / "MolidoBridge.mq5").read_text(
            encoding="utf-8", errors="ignore"
        )

    def test_the_expert_has_an_amend_command(self):
        assert "amend_ticket" in self.source()

    def test_the_expert_refuses_a_widening_stop(self):
        text = self.source()

        assert "a buy stop may only rise" in text
        assert "a sell stop may only fall" in text

    def test_the_expert_refuses_a_stop_through_the_market(self):
        assert "on the wrong side of the market" in self.source()

    def test_the_expert_honours_the_broker_minimum(self):
        assert "inside the broker minimum" in self.source()


class TestTheWildcard:
    """The owner switched trailing on for the whole fleet on 2026-09-07.

    Written as a wildcard rather than a list of logins because a list goes
    stale the moment an account is added - and it goes stale silently, with
    the setting still reading as switched on while the new account runs
    unprotected. A FundedNext account was being added the same hour."""

    def test_the_wildcard_covers_an_account_nobody_listed(self):
        broker = Broker()

        report = trailing.run(
            Bridge(login="34838666", positions=[winner()]),
            broker,
            logins={trailing.EVERY_LOGIN},
            dry_run=False,
        )

        assert len(broker.calls) == 1
        assert report.moves[0].sent

    def test_an_unavailable_account_is_still_left_alone(self):
        """The wildcard says every account, not every terminal. A terminal
        with no account attached publishes stale positions or none, and
        amending against that is guessing."""
        broker = Broker()

        report = trailing.run(
            Bridge(available=False, positions=[winner()]),
            broker,
            logins={trailing.EVERY_LOGIN},
            dry_run=False,
        )

        assert broker.calls == []
        assert report.moves == []

    def test_an_empty_setting_still_means_off(self):
        """The wildcard has to be written down. Nothing here is on by
        default."""
        report = trailing.run(Bridge(positions=[winner()]), Broker(), logins=set())

        assert report.moves == []


class TestTheQuoteComesFromTheBook:
    """The position payload has never carried a current price. The first
    version of this worker read a `price_current` field that does not exist,
    so on 2026-09-07 it examined twelve live positions across four accounts,
    moved none of them, and reported a successful sweep.

    Every test above passed throughout, because the fake published the field
    the real bridge does not. So these use a position shaped like the real
    one - no price on it at all."""

    def live(self, **over):
        row = winner()
        row.pop("price_current")
        row.update(over)
        return row

    def test_a_long_is_measured_against_the_bid(self):
        """What it would close at. The ask would count a spread the trade has
        not paid, and count it as progress."""
        broker = Broker()

        report = trailing.run(
            Bridge(
                positions=[self.live()],
                quotes={"EURUSD": (1.1100, 1.1103)},
            ),
            broker,
            logins={trailing.EVERY_LOGIN},
            dry_run=False,
        )

        assert len(broker.calls) == 1
        assert report.moves[0].price == 1.1100

    def test_a_short_is_measured_against_the_ask(self):
        broker = Broker()
        short = self.live(
            side="sell", price_open=1.1000, stop=1.1100, target=1.0850
        )

        report = trailing.run(
            # Comfortably past 1 R, so this test is about which side of the
            # book is read and not about the boundary.
            Bridge(positions=[short], quotes={"EURUSD": (1.0847, 1.0850)}),
            broker,
            logins={trailing.EVERY_LOGIN},
            dry_run=False,
        )

        assert len(broker.calls) == 1
        assert report.moves[0].price == 1.0850

    def test_a_symbol_with_no_quote_is_skipped_rather_than_guessed(self):
        broker = Broker()

        report = trailing.run(
            Bridge(positions=[self.live()], quotes={}),
            broker,
            logins={trailing.EVERY_LOGIN},
            dry_run=False,
        )

        assert broker.calls == []
        assert "the bridge published no quote, entry or ticket" in report.skipped

    def test_an_unreadable_quote_file_is_not_the_whole_sweep(self):
        class Broken(Bridge):
            def symbols(self):
                raise OSError("molido_symbols.json is half-written")

        report = trailing.run(
            Broken(positions=[self.live()]),
            Broker(),
            logins={trailing.EVERY_LOGIN},
            dry_run=False,
        )

        assert report.considered == 1
        assert report.moves == []
