"""The golden-hour map: each brain's journal edge, cut by trading session."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from app.learning import session_map as sm
from app.learning.robustness import required_t
from app.models.journal import ARM_CONTROL, ARM_RULE, JournalEntry

#: A Monday. Hours below are UTC; tokyo 0-6, london 7-11, overlap 12-16, new-york 17-23.
START = datetime(2026, 9, 7, tzinfo=UTC)
HOUR = {"tokyo": 2, "london": 9, "overlap": 14, "new-york": 20}


def _row(
    session,
    i,
    *,
    r,
    where="london",
    strategy="tsm",
    symbol=None,
    arm=ARM_RULE,
    source="metatrader",
    timeframe="H1",
    day=None,
    hours_open=1,
):
    opened = START + timedelta(days=i if day is None else day, hours=HOUR[where])
    session.add(
        JournalEntry(
            symbol=symbol or f"S{i}",
            decision="long",
            opened_at=opened,
            closed_at=opened + timedelta(hours=hours_open),
            arm=arm,
            strategy=strategy,
            r_multiple=r,
            price_source=source,
            timeframe=timeframe,
            during={},
        )
    )


def _fill(session, where, returns, *, strategy="tsm", offset=0, **kw):
    for n, r in enumerate(returns):
        _row(session, offset + n, r=r, where=where, strategy=strategy, **kw)


def _cell(result, strategy, where):
    [cell] = [c for c in result.cells if c.strategy == strategy and c.session == where]
    return cell


def _earning(n):
    # Mean +0.85 R with spread: wins of 1.5 and losses of -1 at roughly 3:1.
    return [1.5 if k % 4 else -1.0 for k in range(n)]


def _bleeding(n):
    return [-1.0 if k % 4 else 1.0 for k in range(n)]


def test_a_session_that_earns_after_cost_and_beats_its_control_is_golden(session):
    _fill(session, "london", _earning(120))
    _fill(session, "london", [0.0, 0.1, -0.1] * 10, arm=ARM_CONTROL, offset=500)
    session.flush()

    result = sm.build(session)
    cell = _cell(result, "tsm", "london")

    assert cell.positions == 120
    assert cell.net_r is not None and cell.net_r > 0
    assert cell.verdict(result.bar) == sm.GOLDEN
    assert "tsm@london" in result.as_dict()["golden"]


def test_a_session_that_bleeds_after_cost_is_proposed_for_removal(session):
    _fill(session, "tokyo", _bleeding(120))
    session.flush()

    result = sm.build(session)

    assert _cell(result, "tsm", "tokyo").verdict(result.bar) == sm.AVOID
    assert result.as_dict()["avoid"] == ["tsm@tokyo"]
    assert "پیشنهاد حذف: tsm در توکیو" in sm.compose(result)


def test_an_edge_that_does_not_beat_its_own_control_is_not_golden(session):
    _fill(session, "london", _earning(120))
    _fill(session, "london", [1.5] * 30, arm=ARM_CONTROL, offset=500)  # the coin did better
    session.flush()

    result = sm.build(session)
    assert _cell(result, "tsm", "london").verdict(result.bar) == sm.UNCLEAR


def test_below_the_minimum_nothing_is_said_either_way(session):
    _fill(session, "tokyo", _bleeding(sm.MIN_POSITIONS - 1))
    session.flush()

    result = sm.build(session)
    cell = _cell(result, "tsm", "tokyo")

    assert cell.thin
    assert cell.verdict(result.bar) == sm.THIN
    assert result.as_dict()["avoid"] == []
    assert "حکمی نیست" in sm.compose(result)
    assert "هیچ جلسه‌ای معنادار نشد" in sm.compose(result)


def test_every_session_is_listed_even_when_empty(session):
    _fill(session, "overlap", _earning(10))
    session.flush()

    result = sm.build(session)
    assert [c.session for c in result.cells] == list(sm.SESSIONS)
    assert _cell(result, "tsm", "new-york").positions == 0
    assert _cell(result, "tsm", "new-york").mean_r is None


def test_the_bar_rises_with_the_number_of_thick_cells(session):
    _fill(session, "tokyo", _earning(120), strategy="a")
    _fill(session, "london", _earning(120), strategy="a", offset=200)
    _fill(session, "tokyo", _earning(120), strategy="b", offset=400)
    _fill(session, "new-york", _earning(5), strategy="b", offset=600)  # thin: not a hypothesis
    session.flush()

    result = sm.build(session)
    assert result.tested == 3
    assert result.bar == required_t(3)
    assert result.bar > 1.96


def test_repeats_of_one_position_count_once_in_the_session_it_opened(session):
    # Same brain, symbol, side: the second opens while the first is still open.
    _row(session, 0, r=1.0, where="tokyo", symbol="EURUSD", day=0, hours_open=30)
    _row(session, 1, r=1.0, where="london", symbol="EURUSD", day=0, hours_open=30)
    session.flush()

    result = sm.build(session)
    assert _cell(result, "tsm", "tokyo").positions == 1
    assert _cell(result, "tsm", "london").positions == 0


def test_other_prices_timeframes_and_unresolved_rows_stay_out(session):
    _row(session, 0, r=1.0, source="public")
    _row(session, 1, r=1.0, timeframe="M15")
    _row(session, 2, r=None)
    _row(session, 3, r=1.0)
    session.flush()

    result = sm.build(session)
    assert _cell(result, "tsm", "london").positions == 1


def test_an_empty_journal_says_so_and_proposes_nothing(session):
    result = sm.build(session)
    assert result.cells == []
    assert result.tested == 0
    assert "هنوز هیچ پوزیشن حل‌شده‌ای" in sm.compose(result)
    assert result.as_dict()["golden"] == [] and result.as_dict()["avoid"] == []


def test_a_naive_timestamp_is_read_as_utc(session):
    session.add(
        JournalEntry(
            symbol="X",
            decision="long",
            opened_at=datetime(2026, 9, 7, 20, 0),
            closed_at=datetime(2026, 9, 7, 21, 0),
            arm=ARM_RULE,
            strategy="tsm",
            r_multiple=1.0,
            price_source="metatrader",
            timeframe="H1",
            during={},
        )
    )
    session.flush()

    assert _cell(sm.build(session), "tsm", "new-york").positions == 1
