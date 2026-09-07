# RESULTS — baseline measurements

Every row here came out of `app.learning.edge_report`. The command is given
above each block. Nothing is copied from elsewhere and nothing is estimated.

Bonferroni-corrected for 8 hypotheses throughout, so the bar is **t = 3.44**,
not 1.96.

---

## 1. All eight registered rules, H1, two years, broker series

```
docker exec molidotrade-collector-1 python -m app.learning.edge_report \
  --rule <name> --timeframe H1 --years 2 --draws 800 --hypotheses 8
```

| rule | t (clustered) | needs | placebo p | bootstrap 95% | verdict | label |
|---|---|---|---|---|---|---|
| carry-differential | **3.63** | 3.44 | 0.00125 | contains zero | NOT_ROBUST | 🟡 |
| stochastic-reversion | 1.60 | 3.44 | 0.09488 | contains zero | NOT_ROBUST | 🔴 |
| short-horizon-reversal | 1.24 | 3.44 | 0.21348 | contains zero | NOT_ROBUST | 🔴 |
| rsi-mean-reversion | 0.76 | 3.44 | 0.43695 | contains zero | NOT_ROBUST | 🔴 |
| cross-sectional-stretch | 0.20 | 3.44 | 0.83645 | contains zero | NOT_ROBUST | 🔴 |
| donchian-breakout | −0.87 | 3.44 | 0.41948 | contains zero | NOT_ROBUST | 🔴 |
| trend-following | 2.29 | 3.44 | 0.02743 | [−0.1930, +0.4057] | NOT_ROBUST | 🟡 |
| time-series-momentum | **−7.14** | 3.44 | 0.00249 | [−0.6972, −0.1584] | NOT_ROBUST | 🔴 **negative** |

The last two rows did not exist until the harness was fixed — see §3.

**Nothing on H1 is robust.** `carry-differential` is the only rule to clear
the corrected t, and its bootstrap interval still spans zero.

`donchian-breakout` is worth naming separately: it is the rule that has never
produced a live order candidate. It is not only silent, it has nothing to be
loud about — t = −0.87, net −0.1008 R at base cost and −0.1308 R at extreme,
and a sign-flipped null reproduces it as often as not.

---

## 2. time-series-momentum on its own horizon

```
docker exec molidotrade-collector-1 python -m app.learning.edge_report \
  --rule time-series-momentum --provider yfinance --timeframe D1 \
  --years 20 --draws 400 --hypotheses 8
```

```
instants 2715   trades 7356   (2.71 per instant)
t 5.34 clustered, 9.84 unclustered (inflation 1.8x)
required t 3.44 for 8 hypothesis(es)

cost stress:
  base      cost 0.010 R   net +0.0965 R   survives
  stressed  cost 0.020 R   net +0.0865 R   survives
  extreme   cost 0.040 R   net +0.0665 R   survives

placebo: 0 of 400 sign-flipped draws reached 0.1065 R, p = 0.00249
bootstrap: median +0.1133 R, 95% [-0.0475, +0.3026]  <- contains zero

FINDINGS
  - negative in 7 of 24 slices: year:2016, 2017, 2018, 2020, 2024, 2025
  - the block bootstrap interval contains zero

VERDICT  robustness: NOT_ROBUST
LABEL    🟡 RESEARCH FURTHER
```

This is the strongest thing measured in this project so far. It clears the
corrected t, it survives execution costing **four times** the measured
figure, and a sign-flipped null never once reproduced it in 400 draws. It
still fails, on two counts that matter: the bootstrap interval spans zero,
and it is negative in seven of twenty-four slices including two of the last
three years.

Under the brief's §33 that is 🟡, not 🟢. It is worth forward testing, and it
is not a deploy candidate.

### 2.1 The operational finding

The same rule on H1 is **significantly negative**: t = −7.14, bootstrap
95% [−0.6972, −0.1584], entirely below zero.

That is not a contradiction. `lookback = 252` is twelve months of daily bars
and ten days of hourly ones. Twelve-month momentum and ten-day momentum are
different hypotheses, and at ten days the published effect is reversal, not
continuation — which is what the number says.

**It has been trading H1**, the horizon on which it measures significantly
negative, and nobody could have known because until 2026-09-07 the harness
could not run it at all.

---

## 3. Why two rules had no measurement before today

`measure.measure` cut every snapshot to a fixed `min_history = 80` bars.
`trend-following` needs 101 and `time-series-momentum` needs 253, so every
instrument was skipped at every instant, and the report said "no measurement:
no instant in the window could be ranked" — on both providers and on every
timeframe tried.

Each rule now declares what it needs and the harness takes the larger of that
and its floor (`rules.history_needed`, commit `e715923`).

| rule | bars needed |
|---|---|
| time-series-momentum | 253 |
| trend-following | 101 |
| donchian-breakout | 57 |
| rsi-mean-reversion | 16 |
| stochastic-reversion | 14 |
| short-horizon-reversal | 6 |
| carry-differential, cross-sectional-stretch | 1 |

---

## 4. Data not available

| brief asks | state |
|---|---|
| H4 (§3) | **no H4 bars are collected at all** — `no H4 bars from yfinance` |
| M5, M15, M30 rule measurements (§3) | not yet run |
| XAGUSD (§2) | not yet checked against the collected universe |
| Monte Carlo beyond bootstrap and placebo (§16) | trade reshuffling, execution delay, random omission not implemented |
| news-event dependence (§18) | not implemented |
| Sharpe, Sortino, Calmar, recovery factor (§21) | not computed by `edge_report` |

These are gaps, not failures, and none of them is filled by guessing.

---

## 5. The three families that had no representative

Written 2026-09-08 into `rules.PROPOSED` — Market Structure, Volatility and
Statistical. Each carries a hypothesis, a deterministic entry, and published
rather than tuned parameters.

```
docker exec molidotrade-collector-1 python -m app.learning.edge_report \
  --rule <name> --timeframe H1 --years 2 --draws 400 --hypotheses 11
```

| rule | family | instants | t | needs | placebo p | bootstrap 95% | label |
|---|---|---|---|---|---|---|---|
| swing-structure | Market Structure | 461 | −1.31 | 3.61 | 0.209 | [−0.3742, +0.2178] | 🔴 |
| volatility-expansion | Volatility | 147 | −0.92 | 3.61 | 0.347 | [−0.2707, +0.1488] | 🔴 |
| residual-reversion | Statistical | 399 | −0.16 | 3.61 | 0.840 | [−0.2324, +0.2699] | 🔴 |

**NO ROBUST EDGE FOUND** in any of the three. None is close; every bootstrap
interval spans zero and no placebo p approaches significance.

They stay in `PROPOSED`. A rule that has not earned a forward record does not
get one, because being in `CANDIDATES` means the forward loop writes its
decisions on every cycle — that is deployment, not proposal.

### 5.1 What `residual-reversion` demonstrated on the way

Its clustering inflation is **8.1x** — the largest measured anywhere in this
project. The uncorrected t is −1.26; corrected for the fact that its picks at
one instant are one move seen several ways, it is −0.16.

Nothing about the rule made that visible in advance. It is what the
correction added on 2026-09-07 exists to catch, and it caught it on the first
rule measured after it landed.

---

## 6. Monte Carlo — sections 16 and 21

Added 2026-09-08 (`app/learning/montecarlo.py`). The report already had a
block bootstrap and a sign-flipped placebo; those answer *is the mean
distinguishable from zero*. These answer the two questions an account holder
has to live with, and they are seeded so two runs agree (§28).

### 6.1 time-series-momentum, D1, 20 years

```
monte carlo (seed 20260908):
  drawdown observed 222.0833 R, median 21.2024, 95th 31.9911, worst 67.6131
  the order that happened sits at the 100.0th percentile of orders
  dropping 20% at random leaves a positive edge in 100.0% of draws
  sharpe 0.1025  sortino 0.1588  calmar 0.0005  profit factor 1.3837
```

Two findings, pulling in opposite directions.

**The edge is real and broad.** Dropping a fifth of the sample at random
leaves it positive in **100% of 2,000 draws**. It is not carried by a handful
of instants; combined with t = 5.34, survival of 4x costs and a placebo that
never reproduced it, this is the most solid measurement in the project.

**And it is uninvestable as it stands.** The observed worst peak-to-trough
fall is **222 R**. Reshuffling the *same trades* into a random order gives a
median of 21 R and a worst of 68 R across 2,000 orders — the sequence that
actually happened is worse than every single one of them.

That is not bad luck. It means the losses arrive **together**, in long
consecutive runs, which is exactly what the slice table already hinted at
(negative in 2016, 2017, 2018, 2020, 2024, 2025). Calmar of 0.0005 says the
same thing in one number: the per-instant edge is nothing beside the hole it
has to climb out of.

On a $200,000 challenge account with a 10% total-drawdown rule, a 222 R
excursion at 0.75% risk per trade is not survivable. **The edge exists and
the account would be gone before it paid.**

This is the finding the previous tooling could not produce. A bootstrap over
instants deliberately destroys their order, so it can never see this; that is
what reshuffling is for, and it took one run to show it.

### 6.2 What the ratios are, and are not

They are computed on the **edge** — the rule minus its control at the same
instant — never on the raw return, for the same reason as everything else
here: a raw return carries whatever the market did to everything.

They are **not annualised**. The instants are not evenly spaced: the rule
fires when it fires and markets shut at weekends, so a sparse series and a
dense one would be multiplied by different constants for reasons having
nothing to do with either edge. A per-instant Sharpe compares two rules on
this sample honestly; an annualised one compares them to a convention.

Calmar and recovery factor are `None` when there was no drawdown at all,
rather than a large number. A strategy that never fell has no ratio to a
fall.
