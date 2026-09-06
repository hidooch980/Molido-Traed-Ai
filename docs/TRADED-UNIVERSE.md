# The instruments the accounts may carry

Set on 6 September 2026 by the owner. Twenty pairs, in the owner's own order,
with the owner's own grades. **The grades came from the owner's judgement, not
from a measurement in this repository**, and that is why they do nothing except
decide membership: nothing here sizes a position, relaxes a gate or breaks a
tie by grade. A number without a measurement behind it must not reach the risk
layer, and a letter is a number wearing a hat.

| # | pair | grade | # | pair | grade |
|---|---|---|---|---|---|
| 1 | XAU/USD | A+ | 11 | AUD/JPY | A |
| 2 | EUR/USD | A+ | 12 | EUR/GBP | A |
| 3 | GBP/USD | A+ | 13 | CAD/JPY | B+ |
| 4 | USD/JPY | A+ | 14 | CHF/JPY | B+ |
| 5 | GBP/JPY | A | 15 | EUR/CHF | B+ |
| 6 | AUD/USD | A | 16 | EUR/AUD | B+ |
| 7 | USD/CAD | A | 17 | EUR/CAD | B |
| 8 | USD/CHF | A | 18 | GBP/CHF | B |
| 9 | NZD/USD | A | 19 | GBP/AUD | B |
| 10 | EUR/JPY | A | 20 | AUD/NZD | B |

## Where it takes effect, and where it deliberately does not

`MOLIDO_TRADED_SYMBOLS` narrows **execution only**, at the order gate in
`app/workers/autotrade.py`. Everything upstream is untouched: all thirty-two
watchlist symbols are still collected, still ranked, and every decision is
still written to the journal.

That split is not tidiness, it is forced. The cross-sectional rule stops being
a ranking below twenty instruments (`MIN_CROSS_SECTION`), and only nineteen of
these twenty exist as an analysis series — gold is ranked on the futures
contract, `GCFUT`, and filled in spot `XAUUSD`. Narrowing the universe at the
ranking would therefore either break the measurement or, because the code
discards a narrowing that leaves too little, silently do nothing at all while
looking applied. The second is the worse failure and the harder to notice.

Keeping the ranking wide also keeps the evidence: a refused decision is still
journalled and still resolved, so "how would the eight instruments we stopped
trading have done" stays an arithmetic question rather than a lost one.

## Gold is named by the instrument that fills

The list is written in execution names. `XAUUSD` is what the terminal trades
and what the setting must say; a list written in analysis names would refuse
the one instrument it was written to allow — and it is the cheapest thing the
account can cross, 0.029 R against EURUSD's 0.062.

## What was dropped

Eight pairs (NZDJPY, EURNZD, GBPCAD, AUDCAD, AUDCHF, NZDCAD, NZDCHF, CADCHF),
silver and platinum, and the two crypto series. They are still collected, so
the decision is reversible by editing one variable, and the history does not
develop a hole in the meantime.

One consequence worth knowing: crypto was the only instrument open at
weekends. With it out of the book, a Saturday with no orders is the market
being shut rather than anything being wrong — which is what the market-hours
accounting in `app/workers/health_report.py` already reports.

## To change it

Edit `MOLIDO_TRADED_SYMBOLS` in `infra/.env.prod` and recreate the collector -
compose reads the env file when the command starts, so a running container
keeps the value it was created with. Empty means no restriction.
