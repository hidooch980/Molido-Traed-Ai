"""Published charges are money events, not closed-trade wins or losses."""

import json

import pytest

from app.services import realised


def publish(tmp_path, rows):
    (tmp_path / realised.DEALS_FILE).write_text(json.dumps({"deals": rows}))


def event(ticket, net, *, charge=False, fee=None):
    row = {
        "ticket": ticket, "symbol": "EURUSD", "closed_at": "2026.11.02 12:00:00",
        "profit": net if not charge else 0, "swap": 0,
        "commission": net if charge else 0, "net": net, "is_charge": charge,
    }
    if fee is not None:
        row["fee"] = fee
    return row


def test_entry_cost_is_kept_in_total_but_not_counted_as_closed_trade(tmp_path):
    publish(tmp_path, [event(1, -2, charge=True), event(2, 10)])
    result = realised.read(directory=tmp_path)
    assert result["net"] == 8
    assert len(result["deals"]) == 2  # Backwards-compatible event detail.
    assert result["trades"] == 1
    assert result["by_symbol"][0]["trades"] == 1
    assert result["charge_events"] == 1
    assert result["deal_events"] == 2


def test_positive_adjustment_is_not_a_winning_trade(tmp_path):
    publish(tmp_path, [event(i, 10 if i == 0 else -1) for i in range(5)]
            + [event(9, 3, charge=True)])
    result = realised.read(directory=tmp_path)
    symbol = result["by_symbol"][0]
    assert symbol["trades"] == 5
    assert symbol["wins"] == 1
    assert symbol["hit_rate"] == 0.2
    assert result["net"] == 9


def test_charge_only_symbol_has_no_closed_trade_or_hit_rate(tmp_path):
    publish(tmp_path, [event(1, -1, charge=True)])
    result = realised.read(directory=tmp_path)
    assert result["net"] == -1
    assert result["trades"] == 0
    assert result["by_symbol"][0]["hit_rate"] is None


@pytest.mark.parametrize("fee", [None, "bad", "NaN", "Infinity", True])
def test_unknown_fee_is_not_reported_as_zero(tmp_path, fee):
    publish(tmp_path, [event(1, 10, fee=fee), event(2, -1, fee=-0.25)])
    result = realised.read(directory=tmp_path)
    assert result["fee"] is None
    assert result["missing_fee_events"] == 1
    assert result["fees_available"] is False


def test_fee_is_reported_without_double_subtracting_published_net(tmp_path):
    # Exporter already included -0.25 in published net. Do not subtract again.
    exit_row = {**event(1, 9.75, fee=-0.25), "profit": 10}
    publish(tmp_path, [exit_row, event(2, -1, fee=0)])
    result = realised.read(directory=tmp_path)
    assert result["net"] == 8.75
    assert result["fee"] == -0.25
    assert result["fees_available"] is True
    assert result["missing_fee_events"] == 0
    assert result["history_complete"] is None


def test_empty_published_file_does_not_prove_fee_or_history_coverage(tmp_path):
    publish(tmp_path, [])
    result = realised.read(directory=tmp_path)
    assert result["net"] == 0
    assert result["fee"] is None
    assert result["fees_available"] is False
    assert result["history_complete"] is None
