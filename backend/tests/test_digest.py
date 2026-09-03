"""The question that should not have started with the operator.

"Where is my 196,000 account?" - and the answer was that it had been in a
restart loop for twenty minutes and nothing had said so. `systemctl` read
"active" throughout, because a service restarted every ten seconds is
active.
"""

from __future__ import annotations

from datetime import UTC, datetime

from app.ops import digest

NOW = datetime(2026, 9, 4, 6, 0, tzinfo=UTC)


def a_digest(**fields) -> digest.Digest:
    return digest.Digest(at=NOW, **fields)


class TestTroubleComesFirst:
    def test_a_silent_terminal_is_the_first_line(self):
        """A digest that led with yesterday's profit while a terminal was
        down would bury the only line worth acting on."""
        text = a_digest(
            silent_terminals=["term-g"],
            accounts=[{"terminal": "term-f", "equity": 4964.0, "positions": 9, "orders": 3}],
        ).as_text()

        assert text.splitlines()[0].startswith("⚠ not publishing: term-g")

    def test_a_healthy_fleet_says_nothing_about_publishing(self):
        text = a_digest(
            accounts=[{"terminal": "term-f", "equity": 4964.0, "positions": 9, "orders": 3}]
        ).as_text()

        assert "not publishing" not in text

    def test_trouble_is_reportable_on_its_own(self):
        assert a_digest(silent_terminals=["term-g"]).has_trouble
        assert not a_digest().has_trouble


class TestSilenceIsAFinding:
    def test_an_account_that_traded_nothing_still_gets_a_line(self):
        """A digest that only listed activity would be shortest on exactly
        the day the fleet stopped working."""
        text = a_digest(
            accounts=[{"terminal": "term-b", "equity": 50.0, "positions": 0, "orders": 0}]
        ).as_text()

        assert "term-b" in text
        assert "no orders" in text

    def test_the_forward_record_line_is_always_there(self):
        """It is the only number that matters over months, and a day with no
        trading is still a day the record grew."""
        text = a_digest(decisions_recorded=1200, resolved_today=41).as_text()

        assert "1200 decision(s) recorded" in text
        assert "41 resolved" in text


class TestTheRefusalFamilies:
    def test_the_council_is_one_gate_not_a_dozen_arithmetics(self):
        """Without collapsing, the top reasons are "5 brains want the other
        side against 2" and "4 against 3" as separate findings, and the
        council - which is one gate - never appears as the answer."""
        assert digest._family(
            "5 brains want the other side against 2 for it (donchian-breakout)"
        ) == digest._family(
            "4 brains want the other side against 3 for it (rsi-mean-reversion)"
        )

    def test_each_gate_reads_as_itself(self):
        pairs = {
            "the size rounds to zero at this risk": "the computed size rounds to zero lots at this risk",
            "cost exceeded the measured edge": "spread and slippage cost 0.278 R against a 0.034 R ceiling",
            "news exposure could not be checked": "WTI cannot be split into currencies, so its news exposure cannot be checked",
            "the account already holds it": "the account already holds a position in it",
            "the terminal publishes no specification": "the terminal publishes no contract specification",
        }
        for family, raw in pairs.items():
            assert digest._family(raw) == family, raw

    def test_an_unknown_reason_survives_rather_than_vanishing(self):
        """A gate added later must still show up, even before anybody
        teaches this function about it."""
        assert digest._family("some new gate refused it") == "some new gate refused it"


class TestTheMessageItself:
    def test_the_net_of_the_day_is_summed_not_listed(self):
        text = a_digest(
            closed=[
                {"terminal": "term-g", "symbol": "XAUUSD", "net": -3747.60},
                {"terminal": "term-g", "symbol": "CADJPY", "net": 563.84},
            ]
        ).as_text()

        assert "closed today: 2" in text
        assert "-3,183.76" in text

    def test_it_is_short_enough_to_finish(self):
        """A digest nobody finishes reading is a digest nobody reads."""
        text = a_digest(
            silent_terminals=["term-g"],
            accounts=[
                {"terminal": f"term-{k}", "equity": 1000.0, "positions": 2, "orders": 1}
                for k in "bcdefg"
            ],
            closed=[{"terminal": "term-g", "symbol": "EURUSD", "net": 1.0}] * 9,
            refusals=[("the council outvoted it", 40), ("cost exceeded the measured edge", 12)],
            decisions_recorded=900,
            resolved_today=30,
        ).as_text()

        assert len(text.splitlines()) < 25

    def test_at_most_three_refusal_families_are_named(self):
        assert digest.TOP_REASONS == 3


class TestItReportsAndNeverActs:
    def test_nothing_here_closes_or_restarts_anything(self):
        """A daily summary that could also intervene is two features sharing
        one schedule, and the one that intervenes would run at whatever hour
        the summary happened to be set to."""
        import ast
        import inspect

        # Parsed, not grepped. The module's own docstring says the word
        # "systemctl" while explaining the outage this exists for, and a test
        # that searched the text would fail on its own explanation - which is
        # the second time today a test has asserted against prose instead of
        # code.
        tree = ast.parse(inspect.getsource(digest))
        called = {
            node.func.attr if isinstance(node.func, ast.Attribute) else getattr(node.func, "id", "")
            for node in ast.walk(tree)
            if isinstance(node, ast.Call)
        }

        for forbidden in ("commit", "flush", "add", "delete", "run", "check_output", "Popen"):
            assert forbidden not in called, f"the digest calls {forbidden}()"


class TestTheSendPath:
    def test_an_unconfigured_channel_is_a_state_not_a_failure(self, monkeypatch):
        """This runs unattended at six in the morning. A timer that reports
        failure every day because the token is not set yet trains the
        operator to ignore it."""
        import app.ops.digest as module

        monkeypatch.setattr(module, "build", lambda *a, **k: a_digest())

        class Refused:
            sent = False
            reason = "no bot token is configured"

        import app.integrations.telegram as telegram

        monkeypatch.setattr(telegram, "send", lambda *a, **k: Refused())
        outcome = module.send()

        assert outcome["sent"] is False
        assert "token" in outcome["reason"]

    def test_a_dry_run_composes_without_sending(self, monkeypatch):
        import app.ops.digest as module

        monkeypatch.setattr(module, "build", lambda *a, **k: a_digest(decisions_recorded=7))

        def must_not_send(*_a, **_k):
            raise AssertionError("a dry run sent a message")

        import app.integrations.telegram as telegram

        monkeypatch.setattr(telegram, "send", must_not_send)
        outcome = module.send(dry_run=True)

        assert outcome["dry_run"] is True
        assert "7 decision(s) recorded" in outcome["text"]

    def test_the_daily_digest_is_not_deduplicated(self, monkeypatch):
        """Suppressing a repeat would silence it on exactly the quiet week
        where it is the only sign the system is still running."""
        import inspect

        import app.ops.digest as module

        source = inspect.getsource(module.send)

        assert "fingerprint" not in source.replace("# No fingerprint", "")

    def test_only_trouble_raises_the_urgency(self, monkeypatch):
        import app.integrations.notify as notify
        import app.ops.digest as module

        seen = {}

        class Sent:
            sent = True
            reason = None

        import app.integrations.telegram as telegram

        def capture(message, **_k):
            seen["urgency"] = message.urgency
            return Sent()

        monkeypatch.setattr(telegram, "send", capture)

        monkeypatch.setattr(module, "build", lambda *a, **k: a_digest())
        module.send()
        assert seen["urgency"] is notify.Urgency.INFO

        monkeypatch.setattr(module, "build", lambda *a, **k: a_digest(silent_terminals=["term-g"]))
        module.send()
        assert seen["urgency"] is notify.Urgency.WARNING
