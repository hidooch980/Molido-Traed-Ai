"""Prevent trial evidence from being promoted into unsupported live readiness."""
from datetime import timedelta
from types import SimpleNamespace

from app.learning import edge
from app.ops import real_money
from tests.test_real_money_probes import NOW, journal


def record(session, *, count=220, same_instant=False, rule=-1.0, control=-2.0):
    for i in range(count):
        opened = NOW if same_instant else NOW - timedelta(hours=i + 1)
        symbol = f"PAIR{i}" if same_instant else "EURUSD"
        for arm, value in (("rule", rule + (i % 2) * 0.1), ("control", control)):
            journal(session, strategy="trial", arm=arm, symbol=symbol, opened=opened, r=value)


def register(monkeypatch):
    monkeypatch.setattr(edge, "PROVEN", (SimpleNamespace(
        key="trial", verdict=SimpleNamespace(proven=True),
    ),))


def test_one_cross_section_is_not_220_independent_observations(session, monkeypatch):
    register(monkeypatch)
    record(session, same_instant=True, rule=1.0, control=0.0)
    assert real_money._a_brain_beats_its_control(session, NOW).passed is False


def test_beating_a_worse_loser_is_not_profitability(session, monkeypatch):
    register(monkeypatch)
    record(session)
    finding = real_money._a_brain_beats_its_control(session, NOW)
    assert finding.passed is False
    assert "positive gross returns" in finding.detail


def test_costed_registry_and_positive_forward_record_are_both_needed(session, monkeypatch):
    record(session, rule=1.0, control=0.0)
    monkeypatch.setattr(edge, "PROVEN", ())
    assert real_money._a_brain_beats_its_control(session, NOW).passed is False
    register(monkeypatch)
    assert real_money._a_brain_beats_its_control(session, NOW).passed is True


def test_opposite_price_sources_cannot_form_a_pair(session):
    for i in range(220):
        opened = NOW - timedelta(hours=i + 1)
        journal(session, strategy="trial", arm="rule", symbol="EURUSD", opened=opened, r=1.0)
        journal(session, strategy="trial", arm="control", symbol="EURUSD", opened=opened, r=0.0)
    from sqlalchemy import select

    from app.models.journal import JournalEntry
    for row in session.scalars(select(JournalEntry).where(JournalEntry.arm == "control")):
        row.price_source = "metatrader"
    session.flush()
    assert real_money._a_brain_beats_its_control(session, NOW).passed is False


def test_retracted_evidence_cannot_pass(session, monkeypatch):
    register(monkeypatch)
    record(session, rule=1.0, control=0.0)
    from sqlalchemy import select

    from app.models.journal import JournalEntry
    for row in session.scalars(select(JournalEntry)):
        row.after = {"retracted": "stale feed"}
    session.flush()
    assert real_money._a_brain_beats_its_control(session, NOW).passed is False
