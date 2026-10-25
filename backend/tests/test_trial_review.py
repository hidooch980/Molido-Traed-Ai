"""Evidence is grouped honestly and cannot silently authorize trading."""
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from app.integrations import notify, telegram_bot
from app.learning import trial_review
from app.models.journal import JournalEntry

NOW = datetime(2026, 10, 25, 12, tzinfo=UTC)


def entry(session, *, symbol="EURUSD", timeframe="M10", arm="rule", r=1.0,
          source="metatrader", strategy="trial", opened=NOW, **kwargs):
    row = JournalEntry(symbol=symbol, timeframe=timeframe, arm=arm, r_multiple=r,
                       price_source=source, strategy=strategy, opened_at=opened,
                       decision="long", before={}, during={}, **kwargs)
    session.add(row)
    session.flush()
    return row


def group(report, timeframe="M10"):
    return next(p for p in report["timeframes"] if p["timeframe"] == timeframe)


def test_empty_journal_is_missing_evidence_not_zero_profit(session):
    report = trial_review.build_report(session, now=NOW)
    assert [p["timeframe"] for p in report["timeframes"]] == ["M1", "M5", "M10", "M15", "M30"]
    assert all(not p["available"] for p in report["timeframes"])
    assert report["broker_net_profit"] is None
    assert report["actual_payouts"] is None
    assert report["live_promotion_authorized"] is False
    assert report["reference_plan"]["plan_only"] is True


def test_reference_trial_is_not_the_paid_phase_one(session):
    plan = trial_review.build_report(session, now=NOW)["reference_plan"]
    assert (plan["profit_target_pct"], plan["minimum_trading_days"],
            plan["calendar_duration_days"]) == (0.05, 2, 14)


def test_simultaneous_symbols_count_as_one_paired_instant(session):
    for symbol, r in (("EURUSD", 1.0), ("GBPUSD", 3.0)):
        entry(session, symbol=symbol, r=r)
        entry(session, symbol=symbol, arm="control", r=0)
    measured = group(trial_review.build_report(session, now=NOW))["groups"][0]
    assert measured["signal_rows"] == 2
    assert measured["decision_instants"] == measured["paired_instants"] == 1
    assert measured["mean_difference_from_control_r"] == 2


def test_sources_cannot_supply_opposite_arms_of_one_pair(session):
    entry(session)
    entry(session, arm="control", source="yfinance", r=0)
    groups = group(trial_review.build_report(session, now=NOW))["groups"]
    assert len(groups) == 2
    assert all(g["paired_instants"] == 0 for g in groups)


def test_strategy_and_timeframe_results_are_not_pooled(session):
    entry(session, r=1)
    entry(session, strategy="other", r=-1)
    entry(session, timeframe="M5", r=4)
    report = trial_review.build_report(session, now=NOW)
    assert len(group(report)["groups"]) == 2
    assert group(report, "M5")["groups"][0]["gross_signal_mean_r"] == 4


def test_excluded_and_retracted_rows_never_support_a_result(session):
    entry(session, symbol="EURUSD", outcome="excluded")
    entry(session, symbol="GBPUSD", after={"retracted": "stale"})
    report = trial_review.build_report(session, now=NOW)
    assert report["excluded_rows"] == 2
    assert group(report)["available"] is False


def test_unresolved_and_nonfinite_values_are_not_zero_returns(session):
    entry(session, symbol="EURUSD", r=None)
    entry(session, symbol="GBPUSD", r=float("inf"))
    report = trial_review.build_report(session, now=NOW)
    measured = group(report)["groups"][0]
    assert measured["gross_signal_mean_r"] is None
    assert measured["unresolved_signal_rows"] == 1
    assert report["invalid_results"] == 1


def test_window_rejects_future_and_old_rows(session):
    entry(session, symbol="EURUSD", opened=NOW + timedelta(seconds=1))
    entry(session, symbol="GBPUSD", opened=NOW - timedelta(days=15))
    assert trial_review.build_report(session, now=NOW)["rows_read"] == 0


def test_row_cap_is_reported_as_incomplete(session, monkeypatch):
    monkeypatch.setattr(trial_review, "MAX_ROWS", 1)
    entry(session, symbol="EURUSD")
    entry(session, symbol="GBPUSD")
    report = trial_review.build_report(session, now=NOW)
    assert report["truncated"] is True
    assert report["rows_read"] == 1
    assert report["live_promotion_authorized"] is False


@pytest.mark.parametrize("days", [0, 91])
def test_invalid_windows_are_refused(session, days):
    with pytest.raises(ValueError):
        trial_review.build_report(session, days=days, now=NOW)


def test_telegram_alias_stays_on_read_only_path(session, monkeypatch):
    monkeypatch.setitem(telegram_bot.ANSWERS, "why_no_trade", lambda s: "a known refusal")
    assert "a known refusal" in telegram_bot.answer_command(session, "/whynotrade").text
    assert notify.accept_command("/whynotrade", source="telegram").command == "why_no_trade"
    assert "`/why_no_trade`" in telegram_bot.answer_command(session, "/help").text


def test_review_command_does_not_claim_income(session):
    reply = telegram_bot.answer_command(session, "/trialreview")
    assert "سود حساب FTMO یا برداشت نیست" in reply.text
    assert "نمی‌شناسم" not in reply.text


def test_api_is_read_only_and_validates_window(session):
    from app.db.session import get_db
    from app.main import app
    app.dependency_overrides[get_db] = lambda: session
    try:
        with TestClient(app) as client:
            response = client.get("/api/v1/learning/trial-review")
            assert response.status_code == 200
            assert response.json()["live_promotion_authorized"] is False
            assert client.get("/api/v1/learning/trial-review?days=91").status_code == 422
            assert client.post("/api/v1/learning/trial-review").status_code == 405
    finally:
        app.dependency_overrides.clear()
