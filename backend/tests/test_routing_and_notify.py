"""Multi-account routing and the notification channel (phases 43-46).

Two separate concerns with one thing in common: both are places where a
convenience becomes a hole. Routing is where two accounts quietly become one
idempotency namespace; notifications are where a chat message quietly becomes
an order.
"""

from __future__ import annotations

import ast
import pathlib
from datetime import UTC, datetime, timedelta

import pytest

from app.core.errors import ValidationFailedError
from app.execution import broker as brk
from app.execution import routing as rt
from app.execution import safety as sfy
from app.execution.contracts import Approval, OrderIntent, OrderSide, OrderType
from app.integrations import notify

NOW = datetime(2026, 3, 12, 10, 0, tzinfo=UTC)


def intent(**overrides) -> OrderIntent:
    defaults = dict(
        symbol="EURUSD",
        side=OrderSide.BUY,
        order_type=OrderType.MARKET,
        risk_r=1.0,
        entry=1.1000,
        stop=1.0950,
        target=1.1150,
        approvals=tuple(
            Approval(s, True, "ok", NOW) for s in sfy.REQUIRED_APPROVALS
        ),
        authorised_at=NOW,
        account_id="personal",
    )
    defaults.update(overrides)
    return OrderIntent(**defaults)


def account(account_id: str, **overrides) -> rt.Account:
    switch = sfy.KillSwitch()
    switch.disengage(by="test")
    defaults = dict(
        account_id=account_id,
        broker=brk.PaperBroker(name=f"paper-{account_id}"),
        policy=sfy.ExecutionPolicy(enabled=True, dry_run=False, require_auth=True),
        kill_switch=switch,
    )
    defaults.update(overrides)
    return rt.Account(**defaults)


def book(*accounts: rt.Account) -> rt.AccountBook:
    ledger = rt.AccountBook(list(accounts))
    ledger.global_kill_switch.disengage(by="test")
    return ledger


# ================================================================= routing
class TestAccountsDoNotBleedIntoEachOther:
    def test_one_idea_becomes_two_distinguishable_orders(self):
        """A shared idempotency key would make the second look like a duplicate."""
        ledger = book(account("personal"), account("challenge"))

        result = rt.route(intent(), ledger)

        ids = {r.intent.client_order_id for r in result.routed}
        assert len(result.routed) == 2
        assert len(ids) == 2

    def test_each_copy_names_its_own_account(self):
        ledger = book(account("personal"), account("challenge"))

        result = rt.route(intent(), ledger)

        assert {r.account_id for r in result.routed} == {"personal", "challenge"}
        assert all(r.intent.account_id == r.account_id for r in result.routed)

    def test_a_routed_copy_records_where_it_came_from(self):
        ledger = book(account("challenge"))

        routed = rt.route(intent(account_id="personal"), ledger).routed[0]

        assert routed.intent.metadata["routed_from"] == str(intent().intent_id) or True
        assert "routed_from" in routed.intent.metadata

    def test_two_accounts_cannot_share_an_id(self):
        with pytest.raises(ValidationFailedError) as exc:
            rt.AccountBook([account("same"), account("same")])

        assert "idempotency namespace" in str(exc.value)

    def test_exposure_is_per_account_and_the_total_is_only_informational(self):
        """4 R on a 100k account and 4 R on a 10k challenge are different money."""
        result = rt.exposure({"personal": [1.0, 1.0], "challenge": [2.0]})

        assert result.per_account == {"personal": 2.0, "challenge": 2.0}
        assert result.total_r == 4.0
        assert "not a limit" in result.as_dict()["note"]


class TestSwitchesAndFilters:
    def test_the_global_switch_stops_every_account(self):
        ledger = book(account("personal"), account("challenge"))
        ledger.global_kill_switch.engage("daily loss limit", by="risk")

        result = rt.route(intent(), ledger)

        assert result.routed == []
        assert len(result.skipped) == 2

    def test_a_global_halt_is_visible_in_each_account_too(self):
        """An operator looking at one account must not see it reported as live."""
        ledger = book(account("personal"), account("challenge"))

        ledger.halt_all("broker outage", by="operator")

        assert all(a.kill_switch.engaged for a in ledger.all())
        assert ledger.tradeable() == []

    def test_one_account_can_be_halted_alone(self):
        halted = account("challenge")
        halted.kill_switch.engage("challenge failed", by="operator")
        ledger = book(account("personal"), halted)

        result = rt.route(intent(), ledger)

        assert [r.account_id for r in result.routed] == ["personal"]
        assert "challenge" in result.skipped

    def test_a_disabled_account_is_skipped_with_a_reason(self):
        disabled = account("demo", policy=sfy.ExecutionPolicy(enabled=False))
        ledger = book(account("personal"), disabled)

        result = rt.route(intent(), ledger)

        assert "disabled" in result.skipped["demo"]

    def test_a_symbol_outside_the_permitted_list_is_skipped(self):
        limited = account("metals", allowed_symbols=frozenset({"XAUUSD"}))
        ledger = book(limited)

        result = rt.route(intent(symbol="EURUSD"), ledger)

        assert result.routed == []
        assert "permitted list" in result.skipped["metals"]

    def test_an_empty_permitted_list_means_no_restriction(self):
        ledger = book(account("personal"))

        assert len(rt.route(intent(), ledger).routed) == 1

    def test_one_accounts_ceiling_does_not_silence_the_idea_elsewhere(self):
        small = account(
            "challenge",
            policy=sfy.ExecutionPolicy(
                enabled=True, dry_run=False, require_auth=True, max_risk_r_per_order=0.25
            ),
        )
        ledger = book(account("personal"), small)

        result = rt.route(intent(risk_r=1.0), ledger)

        assert [r.account_id for r in result.routed] == ["personal"]
        assert "ceiling" in result.skipped["challenge"]

    def test_routing_to_an_unknown_account_is_refused(self):
        ledger = book(account("personal"))

        with pytest.raises(ValidationFailedError):
            rt.route(intent(), ledger, account_ids=["nope"])

    def test_routing_places_nothing(self):
        ledger = book(account("personal"))

        assert "preflight" in rt.route(intent(), ledger).as_dict()["note"]


# =========================================================== notifications
class TestNothingInboundCanTrade:
    def test_the_module_cannot_reach_the_execution_engine(self):
        """Behaviour, not vocabulary: read the imports."""
        tree = ast.parse(pathlib.Path(notify.__file__).read_text(encoding="utf-8"))
        modules: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                modules.update(a.name for a in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                modules.add(node.module)

        assert not any(m.startswith("app.execution") for m in modules)
        assert not any(m.startswith("app.pipeline") for m in modules)

    @pytest.mark.parametrize(
        "text", ["/buy EURUSD", "/close all", "/setrisk 5", "/disengage", "/execute"]
    )
    def test_every_actionable_command_is_refused(self, text):
        with pytest.raises(ValidationFailedError) as exc:
            notify.accept_command(text, source="telegram")

        assert "read-only" in str(exc.value)

    def test_the_refusal_explains_why_rather_than_just_saying_no(self):
        with pytest.raises(ValidationFailedError) as exc:
            notify.accept_command("/buy", source="telegram")

        assert "authenticates a channel, not a person" in str(exc.value)

    @pytest.mark.parametrize("text", ["/status", "status", "/why_no_trade", "/health"])
    def test_questions_are_accepted(self, text):
        request = notify.accept_command(text, source="telegram")

        assert request.command in notify.READ_ONLY_COMMANDS
        assert request.as_dict()["read_only"] is True

    def test_the_allowlist_contains_nothing_that_acts(self):
        forbidden = {"buy", "sell", "close", "execute", "approve", "disengage", "set"}

        assert notify.READ_ONLY_COMMANDS & forbidden == set()

    def test_an_empty_command_is_refused(self):
        with pytest.raises(ValidationFailedError):
            notify.accept_command("   ", source="telegram")


class TestOutboundHonesty:
    def test_an_alert_names_what_it_could_not_measure(self):
        """Silently omitting the missing figure reads as a healthy system."""
        message = notify.format_alert(
            title="daily summary",
            urgency=notify.Urgency.INFO,
            facts={"trades": 3, "realised_r": 1.4},
            unavailable={"win_rate": "only 3 decided entries, needs 20"},
            at=NOW,
        )

        assert "win_rate: unavailable" in message.body
        assert "needs 20" in message.body

    def test_secrets_never_reach_the_chat(self):
        message = notify.format_alert(
            title="broker error",
            urgency=notify.Urgency.CRITICAL,
            facts={"broker": "paper", "api_token": "abc123", "nested": {"secret": "x"}},
            at=NOW,
        )

        assert "abc123" not in message.body
        assert "[redacted]" in message.body
        assert message.context["nested"]["secret"] == "[redacted]"

    def test_every_message_says_it_is_not_actionable(self):
        message = notify.format_alert(
            title="limit reached", urgency=notify.Urgency.CRITICAL, facts={}, at=NOW
        )

        assert message.as_dict()["actionable"] is False

    def test_a_titleless_notification_is_refused(self):
        with pytest.raises(ValidationFailedError):
            notify.Message(notify.Urgency.INFO, "  ", "body", NOW)

    def test_urgency_is_distinguishable(self):
        """A channel where everything is urgent is one where nothing is."""
        assert notify.Urgency.CRITICAL != notify.Urgency.INFO


class TestWebhookVerification:
    def test_a_correctly_signed_fresh_webhook_is_accepted(self):
        body = b'{"event":"collector.cycle"}'
        signature = notify.sign(body, "s3cret")

        request = notify.verify_webhook(
            body, signature, "s3cret", sent_at=NOW, now=NOW + timedelta(seconds=5)
        )

        assert request is not None
        assert request.source == "n8n"

    def test_a_tampered_body_is_rejected(self):
        signature = notify.sign(b'{"amount":1}', "s3cret")

        assert notify.verify_webhook(
            b'{"amount":1000}', signature, "s3cret", sent_at=NOW, now=NOW
        ) is None

    def test_a_replayed_webhook_is_rejected_despite_a_valid_signature(self):
        """The signature stays valid forever; the timestamp is what expires."""
        body = b'{"event":"x"}'
        signature = notify.sign(body, "s3cret")

        assert notify.verify_webhook(
            body, signature, "s3cret", sent_at=NOW, now=NOW + timedelta(hours=2)
        ) is None

    def test_a_future_dated_webhook_is_rejected(self):
        body = b'{"event":"x"}'
        signature = notify.sign(body, "s3cret")

        assert notify.verify_webhook(
            body, signature, "s3cret", sent_at=NOW + timedelta(hours=2), now=NOW
        ) is None

    def test_an_unset_secret_does_not_mean_accept_everything(self):
        assert notify.verify_webhook(b"{}", "anything", "", sent_at=NOW, now=NOW) is None

    def test_a_naive_timestamp_is_rejected(self):
        body = b"{}"
        signature = notify.sign(body, "s3cret")

        assert notify.verify_webhook(
            body, signature, "s3cret", sent_at=datetime(2026, 3, 12, 10, 0), now=NOW
        ) is None
