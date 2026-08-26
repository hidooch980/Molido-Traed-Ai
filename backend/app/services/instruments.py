"""Canonical instrument resolution (spec §7).

Brokers decorate the same instrument in incompatible ways: `EURUSD.m`,
`EURUSD-ECN`, `EURUSDmicro`, `XAUUSD_i`. Normalization strips the decoration to
find the canonical instrument, while the broker's own contract properties stay
on `BrokerSymbol` — those are load-bearing for sizing and must never be
inferred from the canonical record.
"""

from __future__ import annotations

import re
import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.enums import AssetClass
from app.core.errors import NotFoundError
from app.models.instruments import BrokerSymbol, Instrument
from app.services.sessions import default_market_code

# Broker suffixes/prefixes that carry account-type information, not identity.
_DECORATION_RE = re.compile(
    r"[._\-#]?(?:micro|mini|cent|spot|ecn|pro|raw|std|stp|sb|fx|m|c|i|z|r)$",
    re.IGNORECASE,
)
_NON_ALNUM_RE = re.compile(r"[^A-Z0-9]")
#: Three-letter base plus three-letter quote. Symbols already this shape are
#: never treated as decorated.
_CANONICAL_LENGTH = 6

# Widened past the majors on purpose. This set is not a statement about which
# currencies matter - it decides whether `classify_symbol` can fill in
# `base_currency` and `quote_currency`, and `portfolio.py` reads currency
# exposure from exactly those two columns. A pair whose quote is missing here
# is classified `other` with no currencies, so its dollar leg is invisible to
# the currency cap: USDCZK, USDHUF, USDILS and USDTHB were all spelled
# correctly and all contributed zero measured dollar exposure.
_MAJOR_CURRENCIES = {
    "USD", "EUR", "GBP", "JPY", "CHF", "AUD", "NZD", "CAD",
    "SEK", "NOK", "DKK", "PLN", "TRY", "ZAR", "MXN", "SGD", "HKD", "CNH",
    "CZK", "HUF", "ILS", "THB", "INR", "IDR", "KRW", "PHP", "MYR", "RUB",
    "BRL", "CLP", "COP", "PEN", "TWD", "VND", "AED", "SAR", "EGP", "NGN",
    "RON", "BGN", "HRK", "ISK", "UAH", "KZT", "PKR", "BDT", "LKR", "CNY",
}
_METALS = {"XAU", "XAG", "XPT", "XPD"}
_CRYPTO = {"BTC", "ETH", "XRP", "LTC", "BCH", "ADA", "SOL", "DOGE", "DOT"}

#: Instruments whose class cannot be read off their shape, listed by name.
#:
#: These are not guesses. The classifier below refuses to invent a class from
#: an unrecognised symbol, and it is right to - but "unrecognised" and
#: "unnamed" are different things, and every symbol here was chosen
#: deliberately when the watchlist was written. Leaving them to fall through
#: put eight of this deployment's instruments into `other`: the whole of the
#: energy complex and every index future, filed under the class that means
#: "nobody knows what this is".
#:
#: Quote currency is carried because these all price in dollars and a screen
#: that cannot say so has to print a dash.
_NAMED: dict[str, tuple[AssetClass, str | None, str]] = {
    # Energy. The base is the grade rather than a currency, which is exactly
    # why the six-character rule cannot reach them.
    "USOIL": (AssetClass.COMMODITY, "WTI", "USD"),
    "UKOIL": (AssetClass.COMMODITY, "BRENT", "USD"),
    "NGAS": (AssetClass.COMMODITY, "NATGAS", "USD"),
    # An industrial metal rather than a precious one, and `metal` says more
    # about it than `commodity` does.
    "COPPER": (AssetClass.METAL, "COPPER", "USD"),
    # Equity index futures. No base instrument exists to name - an index is
    # not a thing you can hold - so the base stays empty rather than being
    # filled with the ticker again.
    "US500": (AssetClass.INDEX, None, "USD"),
    "US100": (AssetClass.INDEX, None, "USD"),
    "US30": (AssetClass.INDEX, None, "USD"),
    "US2000": (AssetClass.INDEX, None, "USD"),
}


def normalize_symbol(raw_symbol: str) -> str:
    """Reduce a broker symbol to its canonical form.

    Conservative by design: it removes known decoration and punctuation, and
    otherwise leaves the symbol alone. A wrong merge of two distinct
    instruments is far more damaging than an unmerged duplicate, which an
    operator can map explicitly.
    """
    upper = raw_symbol.strip().upper()
    bare = _NON_ALNUM_RE.sub("", upper)

    # A symbol that is already exactly six alphanumeric characters is a
    # plausible pair as it stands, so nothing is taken off the end of it. The
    # optional separator in the decoration pattern otherwise let a bare
    # trailing letter in {m,c,i,z,r,...} count as broker decoration: USDINR
    # became USDIN and USDZAR became USDZA, both in production.
    if len(bare) == _CANONICAL_LENGTH and bare == upper:
        return bare

    # Peeled one suffix at a time, stopping the moment what is left is a
    # plausible pair. Stripping the whole trailing run at once took USDINR.m
    # down to USDIN, because the run matched the ".m" and then the "R" in front
    # of it - the guard above cannot help once a separator is in play.
    candidate = upper
    while True:
        peeled = _DECORATION_RE.sub("", candidate, count=1)
        if peeled == candidate:
            break
        cleaned = _NON_ALNUM_RE.sub("", peeled)
        if len(cleaned) < _CANONICAL_LENGTH:
            break
        candidate = peeled
        if len(cleaned) == _CANONICAL_LENGTH:
            break

    return _NON_ALNUM_RE.sub("", candidate) or bare


def classify_symbol(symbol: str) -> tuple[AssetClass, str | None, str | None]:
    """Best-effort (asset_class, base, quote) from a canonical symbol.

    Returns `OTHER` with no currencies when the shape is unrecognised rather
    than guessing — an unknown instrument is a prompt for operator input, not
    a place for invention.
    """
    # Checked first. `US500` is five characters and would fall through every
    # rule below it, but more to the point a named instrument should never be
    # subject to a pattern that might coincidentally match it.
    named = _NAMED.get(symbol)
    if named is not None:
        asset_class, base, quote = named
        return asset_class, base, quote

    if len(symbol) == 6:
        base, quote = symbol[:3], symbol[3:]
        if base in _METALS and quote in _MAJOR_CURRENCIES:
            return AssetClass.METAL, base, quote
        if base in _CRYPTO and quote in _MAJOR_CURRENCIES:
            return AssetClass.CRYPTO, base, quote
        if base in _MAJOR_CURRENCIES and quote in _MAJOR_CURRENCIES:
            return AssetClass.FOREX, base, quote
    for crypto in _CRYPTO:
        if symbol.startswith(crypto):
            quote = symbol[len(crypto):]
            if quote in _MAJOR_CURRENCIES or quote in {"USDT", "USDC"}:
                return AssetClass.CRYPTO, crypto, quote
    return AssetClass.OTHER, None, None


def get_instrument(session: Session, instrument_id: uuid.UUID) -> Instrument:
    instrument = session.get(Instrument, instrument_id)
    if instrument is None:
        raise NotFoundError("Instrument not found", instrument_id=str(instrument_id))
    return instrument


def get_instrument_by_symbol(session: Session, symbol: str) -> Instrument | None:
    return session.scalar(select(Instrument).where(Instrument.symbol == normalize_symbol(symbol)))


def upsert_instrument(
    session: Session,
    symbol: str,
    *,
    name: str = "",
    asset_class: AssetClass | None = None,
    base_currency: str | None = None,
    quote_currency: str | None = None,
    exchange: str | None = None,
    timezone: str = "Etc/UTC",
    trading_hours: list | None = None,
) -> Instrument:
    """Create or update a canonical instrument. Idempotent on symbol."""
    canonical = normalize_symbol(symbol)
    inferred_class, inferred_base, inferred_quote = classify_symbol(canonical)

    instrument = session.scalar(select(Instrument).where(Instrument.symbol == canonical))
    if instrument is None:
        resolved_class = asset_class or inferred_class
        instrument = Instrument(
            symbol=canonical,
            name=name or canonical,
            asset_class=resolved_class,
            base_currency=base_currency or inferred_base,
            quote_currency=quote_currency or inferred_quote,
            exchange=exchange,
            # Which holiday calendar applies follows from the asset class;
            # an operator can override it afterwards.
            market_code=default_market_code(resolved_class),
            timezone=timezone,
            trading_hours=trading_hours or [],
        )
        session.add(instrument)
        session.flush()
        return instrument

    # Fill gaps only; never overwrite operator-curated values with guesses.
    if name and instrument.name in ("", canonical):
        instrument.name = name
    if asset_class is not None:
        instrument.asset_class = asset_class
    if base_currency and not instrument.base_currency:
        instrument.base_currency = base_currency
    if quote_currency and not instrument.quote_currency:
        instrument.quote_currency = quote_currency

    # `other` is the absence of a classification, not one anybody chose, so
    # replacing it is filling a gap - the same rule as every line around it.
    #
    # Without this the fix is only ever applied to instruments nobody has seen
    # yet. Eight of this deployment's symbols arrived before the classifier
    # knew their names and would have stayed filed under "nobody knows what
    # this is" permanently, while the code that could have said so ran past
    # them on every cycle. A curated class is still never touched: the guard
    # is on the stored value being `other`, not on the inferred one being
    # confident.
    if instrument.asset_class == AssetClass.OTHER and inferred_class != AssetClass.OTHER:
        instrument.asset_class = inferred_class
        # Follows from the class, and would otherwise keep pointing at the
        # calendar `other` resolves to - so a metal would go on trading
        # through a metals holiday.
        instrument.market_code = default_market_code(inferred_class)
        if inferred_base and not instrument.base_currency:
            instrument.base_currency = inferred_base
        if inferred_quote and not instrument.quote_currency:
            instrument.quote_currency = inferred_quote
    if exchange and not instrument.exchange:
        instrument.exchange = exchange
    if trading_hours and not instrument.trading_hours:
        instrument.trading_hours = trading_hours
    session.flush()
    return instrument


def resolve_broker_symbol(
    session: Session,
    tenant_id: uuid.UUID,
    broker_code: str,
    raw_symbol: str,
) -> BrokerSymbol | None:
    """Look up a broker symbol strictly within one tenant."""
    return session.scalar(
        select(BrokerSymbol).where(
            BrokerSymbol.tenant_id == tenant_id,
            BrokerSymbol.broker_code == broker_code,
            BrokerSymbol.raw_symbol == raw_symbol,
        )
    )


def link_broker_symbol(
    session: Session,
    tenant_id: uuid.UUID,
    broker_code: str,
    raw_symbol: str,
    *,
    contract_size: float | None = None,
    digits: int | None = None,
    point: float | None = None,
    tick_size: float | None = None,
    tick_value: float | None = None,
    volume_min: float | None = None,
    volume_max: float | None = None,
    volume_step: float | None = None,
    margin_rules: dict | None = None,
    spread_model: dict | None = None,
    trading_hours: list | None = None,
) -> BrokerSymbol:
    """Map a broker's raw symbol to a canonical instrument for one tenant."""
    instrument = upsert_instrument(session, raw_symbol)
    existing = resolve_broker_symbol(session, tenant_id, broker_code, raw_symbol)
    if existing is None:
        existing = BrokerSymbol(
            tenant_id=tenant_id,
            instrument_id=instrument.id,
            broker_code=broker_code,
            raw_symbol=raw_symbol,
        )
        session.add(existing)

    existing.instrument_id = instrument.id
    for field_name, value in (
        ("contract_size", contract_size),
        ("digits", digits),
        ("point", point),
        ("tick_size", tick_size),
        ("tick_value", tick_value),
        ("volume_min", volume_min),
        ("volume_max", volume_max),
        ("volume_step", volume_step),
    ):
        if value is not None:
            setattr(existing, field_name, value)
    if margin_rules is not None:
        existing.margin_rules = margin_rules
    if spread_model is not None:
        existing.spread_model = spread_model
    if trading_hours is not None:
        existing.trading_hours = trading_hours

    session.flush()
    return existing
