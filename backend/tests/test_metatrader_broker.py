"""The adapter that can actually place an order.

Until it existed the platform could not. `api_can_place_orders` was false, the
only adapter was a paper broker that fills nothing, and the autopilot reported
`would_send_live_orders: true` - a verdict about a path that did not exist,
reported to the user as "armed" more than once.

So these tests are about the two properties that make sending an order safe
rather than about the happy path: a request executes at most once, and an
unanswered request is UNKNOWN rather than rejected.
"""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime

import pytest

from app.execution.contracts import (
    Approval,
    OrderIntent,
    OrderSide,
    OrderState,
    OrderType,
)
from app.execution.metatrader_broker import (
    CLAIM_PREFIX,
    REQUEST_PREFIX,
    RESULT_PREFIX,
    MetaTraderBroker,
)

NOW = datetime(2026, 8, 17, 2, 0, tzinfo=UTC)


@pytest.fixture()
def broker(tmp_path):
    """A broker whose clock and sleep are fake, so tests never wait."""
    ticks = iter(range(0, 10_000))
    return MetaTraderBroker(
        directory=tmp_path,
        timeout=5.0,
        clock=lambda: next(ticks),
        sleeper=lambda _seconds: None,
    )


def intent(**overrides) -> OrderIntent:
    defaults = dict(
        symbol="EURUSD",
        side=OrderSide.BUY,
        order_type=OrderType.MARKET,
        risk_r=0.25,
        entry=1.1570,
        stop=1.1520,
        target=1.1620,
        approvals=(
            Approval(source="risk", approved=True, detail="within limits", at=NOW),
            Approval(source="strategy", approved=True, detail="ranked", at=NOW),
        ),
        authorised_at=NOW,
        account_id="68345601",
        metadata={"lots": 0.02},
    )
    defaults.update(overrides)
    return OrderIntent(**defaults)


def answer(directory, order_id, *, ok=True, ticket=555, price=1.1571, reason="filled"):
    (directory / f"{RESULT_PREFIX}{order_id}.json").write_text(
        json.dumps(
            {"id": order_id, "ok": ok, "ticket": ticket, "price": price, "reason": reason}
        ),
        encoding="utf-8",
    )


class TestItWritesARequestTheExpertCanRead:
    def test_the_request_carries_everything_the_expert_needs(self, broker, tmp_path):
        order = intent()
        broker.timeout = 0  # do not wait; the file is the subject here
        broker.submit(order)

        written = json.loads(
            (tmp_path / f"{REQUEST_PREFIX}{order.intent_id}.json").read_text()
        )
        assert written["symbol"] == "EURUSD"
        assert written["side"] == "buy"
        assert written["lots"] == 0.02
        assert written["stop"] == 1.1520

    def test_a_sell_is_written_as_a_sell(self, broker, tmp_path):
        # Levels flipped with the side: the contract refuses a sell whose stop
        # sits below its entry, which is the validation doing its job.
        order = intent(side=OrderSide.SELL, stop=1.1620, target=1.1520)
        broker.timeout = 0
        broker.submit(order)

        written = json.loads(
            (tmp_path / f"{REQUEST_PREFIX}{order.intent_id}.json").read_text()
        )
        assert written["side"] == "sell"

    def test_an_order_with_no_size_is_refused_without_writing_a_file(
        self, broker, tmp_path
    ):
        """Sizing is the caller's job. A request that cannot succeed should not
        become a pending file somebody has to explain later."""
        order = intent(metadata={})

        report = broker.submit(order)

        assert report.state is OrderState.REJECTED
        assert "not an order" in report.reason
        assert list(tmp_path.glob(f"{REQUEST_PREFIX}*")) == []


class TestATimeoutIsNotARejection:
    def test_no_answer_reports_unknown(self, broker):
        """Treating a timeout as a refusal is how a system decides an order
        failed, retries it, and ends up holding two."""
        report = broker.submit(intent())

        assert report.state is OrderState.UNKNOWN
        assert "may be live" in report.reason

    def test_the_reason_says_to_reconcile(self, broker):
        report = broker.submit(intent())

        assert "reconcile" in report.reason

    def test_an_answer_that_arrives_is_read(self, broker, tmp_path):
        order = intent()
        # The expert answers before the first poll.
        real_submit = broker.submit

        def answer_then_submit(i):
            answer(tmp_path, str(i.intent_id))
            return real_submit(i)

        report = answer_then_submit(order)

        assert report.state is OrderState.FILLED
        assert report.broker_order_id == "555"
        assert report.average_price == pytest.approx(1.1571)


class TestARejectionIsReadAsARejection:
    def test_the_expert_s_reason_survives(self, broker, tmp_path):
        order = intent()
        answer(
            tmp_path,
            str(order.intent_id),
            ok=False,
            ticket=0,
            price=0.0,
            reason="size 0.50 exceeds MaxLots 0.10",
        )

        report = broker.submit(order)

        assert report.state is OrderState.REJECTED
        assert "exceeds MaxLots" in report.reason

    def test_a_half_written_result_is_not_read_as_a_rejection(self, broker, tmp_path):
        """A file caught mid-write on one poll is normal. Reading it as a
        refusal would reject orders the terminal is in the middle of filling."""
        order = intent()
        (tmp_path / f"{RESULT_PREFIX}{order.intent_id}.json").write_text(
            '{"id": "x", "ok": tr', encoding="utf-8"
        )

        report = broker.submit(order)

        assert report.state is OrderState.UNKNOWN


class TestCancelling:
    def test_an_unclaimed_request_can_be_withdrawn(self, broker, tmp_path):
        order = intent()
        broker.timeout = 0
        broker.submit(order)

        report = broker.cancel(str(order.intent_id))

        assert report.state is OrderState.CANCELLED
        assert not (tmp_path / f"{REQUEST_PREFIX}{order.intent_id}.json").exists()

    def test_a_claimed_request_is_not_cancelled(self, broker, tmp_path):
        """Once the expert has claimed it the order may already be live, and a
        cancel that races a fill is how one position becomes two."""
        order_id = str(uuid.uuid4())
        (tmp_path / f"{CLAIM_PREFIX}{order_id}.json").write_text("{}", encoding="utf-8")

        report = broker.cancel(order_id)

        assert report.state is OrderState.UNKNOWN
        assert "race the fill" in report.reason


class TestReconcile:
    def test_it_returns_every_answered_order(self, broker, tmp_path):
        for i in range(3):
            answer(tmp_path, f"order-{i}")

        reports = broker.reconcile("68345601")

        assert len(reports) == 3
        assert all(r.state is OrderState.FILLED for r in reports)

    def test_an_empty_directory_is_not_an_error(self, broker):
        assert broker.reconcile("68345601") == []


class TestItSatisfiesTheProtocol:
    def test_it_has_every_method_the_protocol_names(self):
        """Checked by name rather than isinstance: BrokerAdapter is a plain
        Protocol, and a structural check that silently passes on a missing
        method would be worse than none."""
        from app.execution.broker import BrokerAdapter

        broker = MetaTraderBroker()
        for method in ("submit", "cancel", "status", "reconcile"):
            assert callable(getattr(broker, method)), method
        assert hasattr(BrokerAdapter, "submit")
        assert broker.name

    def test_it_describes_its_own_guarantee(self):
        """So a reader of the execution policy page learns what the channel
        does and does not promise."""
        described = MetaTraderBroker().as_dict()

        assert "cannot double" in described["note"]
        assert "UNKNOWN rather than rejected" in described["note"]


class TestThePatienceBudget:
    """The first live probe took seventy seconds to come back. The timeout was
    45, reasoned from the expert's twenty-second timer - so a real fill would
    have been reported UNKNOWN, which is the most expensive outcome this
    adapter can produce."""

    def test_it_waits_longer_than_the_slowest_observed_answer(self):
        from app.execution import metatrader_broker

        assert metatrader_broker.DEFAULT_TIMEOUT >= 70.0

    def test_waiting_longer_costs_only_the_blocked_call(self, tmp_path):
        """Giving up early costs a manual reconciliation and possibly a
        duplicated position. The asymmetry is the whole argument."""
        slept: list[float] = []
        ticks = iter(range(0, 10_000))
        broker = MetaTraderBroker(
            directory=tmp_path,
            timeout=100.0,
            clock=lambda: next(ticks),
            sleeper=slept.append,
        )

        report = broker.submit(intent())

        assert report.state is OrderState.UNKNOWN
        assert len(slept) > 50


class TestAFilledOrderReportsASize:
    """The expert answers with ok, ticket, price and reason - and no volume.
    A filled order reported as zero quantity is internally inconsistent and
    reads downstream as "nothing was filled"."""

    def test_a_fill_carries_the_requested_size(self, tmp_path):
        broker = MetaTraderBroker(directory=tmp_path)
        (tmp_path / f"{RESULT_PREFIX}abc.json").write_text(
            json.dumps({"ok": True, "ticket": 123, "price": 1.16}), encoding="utf-8"
        )

        report = broker._read_result("abc", 0.07)

        assert report.state is OrderState.FILLED
        assert report.filled_quantity == 0.07

    def test_a_rejection_carries_none_of_it(self):
        """Nothing was filled, and that zero is a real one."""
        import pathlib as _p
        import tempfile

        with tempfile.TemporaryDirectory() as where:
            root = _p.Path(where)
            (root / f"{RESULT_PREFIX}abc.json").write_text(
                json.dumps({"ok": False, "reason": "no money"}), encoding="utf-8"
            )

            report = MetaTraderBroker(directory=root)._read_result("abc", 0.07)

        assert report.state is OrderState.REJECTED
        assert report.filled_quantity == 0.0

    def test_the_payload_admits_the_size_is_not_confirmed(self, tmp_path):
        """Until the expert reports the volume it actually got, a partial fill
        arrives as a full one. Naming that beats a confident number."""
        (tmp_path / f"{RESULT_PREFIX}abc.json").write_text(
            json.dumps({"ok": True, "ticket": 1, "price": 1.16}), encoding="utf-8"
        )

        report = MetaTraderBroker(directory=tmp_path)._read_result("abc", 0.07)

        assert report.raw["volume_is_requested_not_confirmed"] is True
        assert "partial fill" in report.raw["note"]

    def test_an_unknown_size_does_not_invent_one(self, tmp_path):
        (tmp_path / f"{RESULT_PREFIX}abc.json").write_text(
            json.dumps({"ok": True, "ticket": 1, "price": 1.16}), encoding="utf-8"
        )

        report = MetaTraderBroker(directory=tmp_path)._read_result("abc")

        assert report.filled_quantity == 0.0
