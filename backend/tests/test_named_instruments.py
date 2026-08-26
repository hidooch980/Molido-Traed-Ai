"""Symbols whose class cannot be read off their shape.

The classifier works by pattern: six characters split into two currency codes,
or a known crypto prefix. That covers most of a foreign exchange universe and
none of an energy or index one - `USOIL` is five characters and its base is a
grade of crude rather than a currency, and `US500` names a thing nobody can
hold. Eight of this deployment's instruments fell through every rule and were
filed under `other`, which is the class that means nobody knows what this is.

Refusing to guess is right and stays. What these tests hold is the difference
between a symbol nobody recognises and a symbol nobody had named yet.
"""

from __future__ import annotations

import pytest

from app.core.enums import AssetClass
from app.services.instruments import classify_symbol, upsert_instrument


class TestClassification:
    @pytest.mark.parametrize(
        "symbol,expected",
        [
            ("USOIL", AssetClass.COMMODITY),
            ("UKOIL", AssetClass.COMMODITY),
            ("NGAS", AssetClass.COMMODITY),
            ("COPPER", AssetClass.METAL),
            ("US500", AssetClass.INDEX),
            ("US100", AssetClass.INDEX),
            ("US30", AssetClass.INDEX),
            ("US2000", AssetClass.INDEX),
        ],
    )
    def test_the_named_instruments_land_in_a_real_class(self, symbol, expected):
        assert classify_symbol(symbol)[0] is expected

    def test_the_patterns_still_work(self):
        assert classify_symbol("EURUSD")[0] is AssetClass.FOREX
        assert classify_symbol("XAUUSD")[0] is AssetClass.METAL
        assert classify_symbol("BTCUSD")[0] is AssetClass.CRYPTO

    def test_an_unrecognised_symbol_is_still_refused(self):
        """The principle the named table must not erode.

        A class invented for an unknown instrument is worse than no class:
        it routes the thing to a holiday calendar and a set of trading hours
        chosen for something else entirely.
        """
        assert classify_symbol("QQZZWW")[0] is AssetClass.OTHER
        assert classify_symbol("NOTATHING")[0] is AssetClass.OTHER

    def test_an_index_has_no_base_to_name(self):
        """Filling it with the ticker again would be inventing a holding."""
        asset_class, base, quote = classify_symbol("US500")
        assert asset_class is AssetClass.INDEX
        assert base is None
        assert quote == "USD"

    def test_the_named_table_is_checked_before_any_pattern(self):
        """A name should never be subject to a rule that might match it.

        This is not hypothetical: a six character named symbol would otherwise
        be split into two three letter codes first.
        """
        assert classify_symbol("COPPER")[0] is AssetClass.METAL


class TestFillingAnUnclassifiedInstrument:
    def test_an_existing_other_is_corrected_on_the_next_pass(self, session):
        """Otherwise the fix only ever reaches instruments nobody has seen.

        Eight symbols arrived before the classifier knew their names. The rule
        that never overwrites a class would have kept them in `other`
        permanently, while the code that could have named them ran past them
        on every collection cycle.
        """
        first = upsert_instrument(session, "US500", asset_class=AssetClass.OTHER)
        assert first.asset_class is AssetClass.OTHER

        again = upsert_instrument(session, "US500")
        assert again.id == first.id
        assert again.asset_class is AssetClass.INDEX

    def test_the_market_code_follows_the_corrected_class(self, session):
        """A stale calendar is the quiet half of a wrong class.

        `other` resolves to the foreign exchange calendar, which is open
        around the clock on weekdays. An index left pointing at it goes on
        being reported as tradeable through every exchange holiday, and the
        class on the screen would look right while the hours behind it were
        somebody else's.
        """
        stale = upsert_instrument(session, "US500", asset_class=AssetClass.OTHER)
        assert stale.market_code == "FX"

        fixed = upsert_instrument(session, "US500")
        assert fixed.asset_class is AssetClass.INDEX
        assert fixed.market_code == "XNYS"

    def test_a_chosen_class_is_never_overwritten(self, session):
        """The guard is on the stored value, not on the classifier's confidence.

        Somebody who deliberately filed an instrument as a future has made a
        decision, and a pattern that disagrees is not entitled to undo it.
        """
        chosen = upsert_instrument(session, "US500", asset_class=AssetClass.FUTURE)
        assert chosen.asset_class is AssetClass.FUTURE

        again = upsert_instrument(session, "US500")
        assert again.id == chosen.id
        assert again.asset_class is AssetClass.FUTURE

    def test_an_instrument_that_stays_unknown_is_left_alone(self, session):
        unknown = upsert_instrument(session, "QQZZWW")
        assert unknown.asset_class is AssetClass.OTHER

        again = upsert_instrument(session, "QQZZWW")
        assert again.id == unknown.id
        assert again.asset_class is AssetClass.OTHER
