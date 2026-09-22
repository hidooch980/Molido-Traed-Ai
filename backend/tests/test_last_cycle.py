"""The last order cycle's per-account outcome, and `/why_no_trade` reading it."""

from __future__ import annotations

import os
import pathlib

from app.execution import last_cycle
from app.integrations import telegram_bot


def test_a_written_record_reads_back():
    last_cycle.write(
        orders=0,
        accounts=2,
        reason=None,
        per_account={"term-c": "kill switch: engaged by owner", "term-d": 3},
    )
    record, missing = last_cycle.read()
    assert missing == ""
    assert record["accounts"] == 2
    assert record["per_account"]["term-c"] == "kill switch: engaged by owner"


def test_no_record_says_so_rather_than_nothing():
    record, missing = last_cycle.read()
    assert record is None
    assert "no order cycle" in missing


def test_a_corrupt_record_is_reported_not_raised():
    pathlib.Path(os.environ["MOLIDO_LAST_CYCLE_FILE"]).write_text("{not json", encoding="utf-8")
    record, missing = last_cycle.read()
    assert record is None
    assert "could not be read" in missing


def test_an_unwritable_location_never_breaks_the_cycle(monkeypatch, tmp_path):
    blocker = tmp_path / "a-file"
    blocker.write_text("x")
    monkeypatch.setenv("MOLIDO_LAST_CYCLE_FILE", str(blocker / "sub" / "record.json"))
    last_cycle.write(orders=0, accounts=0, reason=None, per_account={})  # must not raise
    assert last_cycle.read()[0] is None


def test_why_no_trade_shows_a_refusal_made_before_any_signal(session):
    """An account refused at authorization writes no journal row; the answer
    used to say the market was probably closed."""
    last_cycle.write(
        orders=0,
        accounts=1,
        reason=None,
        per_account={"term-j": "order authorization: operational_readiness: disk_headroom"},
    )
    text = telegram_bot.answer_command(session, "/why_no_trade").text

    assert "term-j" in text
    assert "disk_headroom" in text
    assert "این همان بسته بودن بازار است" not in text


def test_why_no_trade_summarises_a_skip_list(session):
    last_cycle.write(
        orders=1,
        accounts=1,
        reason=None,
        per_account={"term-b": {"orders": 1, "skipped": 4, "mostly": {"fleet cap": 3}}},
    )
    text = telegram_bot.answer_command(session, "/why_no_trade").text
    assert "term-b: 1 سفارش، 4 رد — 3× fleet cap" in text


def test_why_no_trade_says_when_no_cycle_was_recorded(session):
    text = telegram_bot.answer_command(session, "/why_no_trade").text
    assert "ثبت نشده" in text


def test_the_collect_cycle_writes_the_record(monkeypatch):
    import asyncio

    from app.workers import collector

    class Report:
        def as_payload(self):
            return {}

    monkeypatch.setattr(collector, "run_cycle", Report)
    for step in ("sample_equity", "ingest_broker_bars", "record_forward",
                 "resolve_forward", "tighten_stops"):
        monkeypatch.setattr(collector, step, dict)
    monkeypatch.setattr(
        collector,
        "send_orders",
        lambda: {
            "orders": 0,
            "accounts": 1,
            "by_account": {"term-c": {"orders": 0, "refused": "kill switch: engaged"}},
        },
    )

    asyncio.run(collector.collect({}))

    record, _ = last_cycle.read()
    assert record["per_account"] == {"term-c": "kill switch: engaged"}
