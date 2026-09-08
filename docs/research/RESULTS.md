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
monte carlo (seed 20260908, blocks of 83 instants):
  drawdown observed 222.0833 R, median 141.5774, 95th 221.0685, worst 299.0982
  the order that happened sits at the 95.1th percentile of orders
  dropping 20% at random leaves a positive edge in 100.0% of draws
  sharpe 0.1025  sortino 0.1588  calmar 0.0005  profit factor 1.3837
```

**The edge is real and broad.** Dropping a fifth of the sample at random
leaves it positive in **100% of draws**. It is not carried by a handful of
instants; with t = 5.34, survival of 4x costs and a placebo that never
reproduced it, this is the most solid measurement in the project.

**And it is uninvestable as it stands.** The worst peak-to-trough fall was
**222 R**, and reshuffling the same trades in blocks says that is not bad
luck: a *typical* ordering still produces **141 R**, and the 95th percentile
of orderings is 221 R. The hole is a property of the strategy, not of the
sequence it happened to arrive in.

On a $200,000 challenge account with a 10% total-drawdown rule, a 141 R
excursion at 0.75% risk per trade is not survivable. **The edge exists and
the account would be gone before it paid.** Calmar of 0.0005 says the same
thing in one number.

#### A correction, and why the block length is the whole test

The first version of this section reported the observed drawdown at the
**100th** percentile of reshuffled orders and concluded that the losses
arrive together in runs no random ordering comes close to. That was an
artifact of the test, not a property of the strategy.

Consecutive instants are not independent: a decision at one instant and the
next both resolve over the bars that follow, so they share outcome bars.
Shuffling them one at a time destroys that overlap while the observed path
keeps it, so the real path looks extreme by construction. The tell was that
it said the same thing about every rule — four in a row at the 99th or 100th
percentile is a test measuring itself.

Reshuffling in blocks of `horizon_instants`, the length the bootstrap already
uses and for the same reason, it now discriminates:

| rule | observed drawdown | percentile of orderings |
|---|---|---|
| carry-differential | 118.0 R | 99.1 — genuinely clustered |
| time-series-momentum (D1) | 222.1 R | 95.1 |
| trend-following | 46.7 R | 24.2 — ordinary |
| short-horizon-reversal | 22.0 R | 18.8 — mildly lucky |

The corrected reading of time-series-momentum is worse for deployment, not
better: the problem was never an unlucky sequence, it is the size of the hole
under any sequence.

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

---

## 7. Execution delay — the third leg of §16

A fill a bar late is not a cost. The order goes on at a different price, so
the stop and the target sit somewhere else and different bars decide it.
Both arms are delayed together — delaying the rule while its control fills
instantly would measure the delay rather than the rule.

The question is not hypothetical: this deployment reaches its terminals
through a file dropped on a Wine filesystem, claimed and answered by an
expert on a chart.

### 7.1 time-series-momentum, D1

| fill | edge | t |
|---|---|---|
| prompt | +0.1065 R | 5.34 |
| one bar late | +0.1013 R | 5.09 |
| two bars late | +0.0996 R | 5.00 |

Intact. It is not a latency artifact.

### 7.2 Every H1 rule

| rule | 1 bar late | 2 bars late |
|---|---|---|
| carry-differential | +0.2007 R, t 3.60 | +0.1934 R, t 3.52 |
| trend-following | +0.1148 R, t 2.08 | +0.0972 R, t 1.69 |
| stochastic-reversion | +0.1161 R, t 1.87 | +0.1070 R, t 1.72 |
| short-horizon-reversal | +0.0645 R, t 1.34 | +0.0771 R, t 1.58 |
| rsi-mean-reversion | +0.0731 R, t 1.00 | +0.0779 R, t 1.06 |

**None of them collapses.** Not one rule here owes its reading to being
filled promptly, and two of them read slightly *better* two bars late than
one. Latency is not what is wrong with this book.

That is a clean negative result and worth having: it removes an entire class
of explanation, and it means the file-drop bridge — which nobody could
otherwise vouch for on this evidence — is not costing the measurement
anything.

### 7.3 What survives what

For the one candidate worth the row:

| stress | time-series-momentum, D1 |
|---|---|
| costs at 4x measured | survives, +0.0665 R |
| losing a fifth of the sample | positive in 100% of draws |
| two-bar execution delay | +0.0996 R, t 5.00 |
| a sign-flipped null | never reproduced in 400 draws |
| **its own drawdown** | **fails — 141 R on a typical ordering** |
| **year slices** | **fails — negative in 7 of 24** |

---

## 8. How often does the rule actually decide anything?

`carry-differential` looked like the find of the week: on **M15** over a year
it read t = 5.13 and survived execution costed at four times the measured
figure — better than its own H1 reading of 3.63.

A macro signal has no business being stronger on fifteen-minute bars than on
hourly ones, so it was counted rather than believed. Over 865 M15 instants it
produced **two distinct books** and changed its mind twice. The t of 5.13 is
about two bets.

Neither existing correction reaches this. Clustering by instant fixes *one
move seen from several angles at the same moment*; this is *one bet seen at
eight hundred consecutive moments*. The block bootstrap used blocks of 62
instants while the signal persisted for 432 — seven times longer.

So the measurement now counts distinct books and prints the persistence
beside the t (commit `4bdb40e`):

### 8.1 Every rule on H1, two years

| rule | instants | distinct books | instants per change of mind | t |
|---|---|---|---|---|
| **carry-differential** | 441 | **4** | **110.2** | 3.63 |
| trend-following | 438 | 118 | 3.7 | 2.38 |
| cross-sectional-stretch | 492 | 362 | 1.4 | 0.17 |
| short-horizon-reversal | 501 | 448 | 1.1 | 1.24 |
| donchian-breakout | 179 | 156 | 1.1 | −0.87 |
| rsi-mean-reversion | 365 | 407† | ~1 | 0.86 |
| stochastic-reversion | 402 | 474† | ~1 | 1.60 |

† measured before the count was corrected to run over kept instants only
(`3e08047`); the ratio for these two is ~1 either way.

**Only `carry-differential` is affected.** Every other rule changes its book
roughly every instant, so its t is computed over as many decisions as it
claims. The one rule that cleared the corrected t bar on H1 is the one rule
whose sample was not what it appeared.

### 8.2 What this does to the H1 table

`carry-differential` was the only rule to clear t = 3.44 on H1, and §1 already
noted its bootstrap interval spans zero. With four decisions behind it, the t
should not be read as evidence at all.

**That leaves nothing on H1 that clears its bar on an honest sample.**

### 8.3 The same error, three times in two days

| where | rows counted | evidence there really was |
|---|---|---|
| forward journal | 29 resolved decisions | 26 of them one yen move |
| Monte Carlo reshuffle | 2,715 independent draws | consecutive instants share outcome bars |
| carry-differential | 865 instants | 2 books |

Each was found by the same question — *is this number of rows the same as
this number of observations?* — and each answer was no. The first two are
corrected in code. The third cannot be corrected automatically, because a
rule that holds a good position for months is not thereby wrong; it is made
impossible to miss instead.

---

## 9. Walk-forward: the one candidate does not survive it

Section 15 of the brief, run on the only rule that had reached 🟡.

```
docker exec molidotrade-collector-1 python /tmp/wf.py
  # time-series-momentum, yfinance D1, 20 years, 4 folds
```

```
folds 4, scored 4, positive 2
in-sample net      +0.2224 R
out-of-sample net  +0.0186 R
walk-forward efficiency  0.084
```

| training window | it chose | out of sample |
|---|---|---|
| 2011-08 → 2013-07 | stop 15.0, target 1.5 | **+0.3546** |
| 2015-06 → 2017-04 | stop 2.5, target 0.5 | −0.1197 |
| 2019-03 → 2021-01 | stop 10.0, target 1.0 | **+0.7722** |
| 2022-12 → 2024-10 | stop 10.0, target 1.0 | **−0.9329** |

**Efficiency of 0.084** — less than a tenth of what training promises is
delivered outside it. And the average hides the worse fact: each fold chooses
a *different* geometry, the results swing from +0.77 to −0.93, and the most
recent fold is the worst of the four.

That agrees with the year slices, which were already negative in 2024 and
2025.

**`time-series-momentum` moves from 🟡 to 🔴.** There is now no candidate at
any label above red.

---

## 10. The scalping question, answered by measurement

The request was more trades on a lower timeframe. M5, one year, every rule
that ranks there, Bonferroni-corrected for 18 hypotheses (bar t = 3.61):

| rule | instants | trades | t | verdict |
|---|---|---|---|---|
| cross-sectional-stretch | 1,284 | 4,301 | 3.32 | NOT_ROBUST |
| rsi-mean-reversion | 1,059 | 2,352 | 1.84 | NOT_ROBUST |
| short-horizon-reversal | 1,323 | 6,049 | 1.76 | NOT_ROBUST |
| stochastic-reversion | 1,186 | 2,837 | 1.59 | NOT_ROBUST |
| donchian-breakout | 537 | 905 | 0.43 | NOT_ROBUST |
| trend-following | 1,243 | 3,131 | **−4.98** | NOT_ROBUST |

The request was met exactly and it did not work. The M5 sample is **twenty
times larger** than H1's — 1,284 independent instants against 492, thousands
of trades instead of dozens — so the statistical bar is easier to clear
there, not harder. Nothing cleared it.

Two readings worth keeping:

**`cross-sectional-stretch` is the best of them at t = 3.32.** That is the
brain this project's own code calls "the baseline that is known to fail", and
it still does not clear 3.61.

**`trend-following` is significantly *negative* on M5** (t = −4.98, net
−0.1692 R at base cost) while holding the best positive t on H1 (2.38). The
same shape as `time-series-momentum`: a rule works on its own horizon and
inverts on a shorter one.

This is not a shortage of data — 3,131 trades is plenty. It is the spread.
`measure.cost_in_r` says why in one line: R is defined by the stop distance,
and *the spread does not shrink when the bars do*. The average bar range on
this deployment is 9.02 pips at H1 and 4.18 at M15 against a 1.4 pip EURUSD
spread, so the same signal pays roughly twice as much per decision at M15 and
several times as much at M5.

**More trades is not more knowledge.** It is the same knowledge behind a
taller fence.

---

## 11. Does agreement earn anything?

The brief's Hybrid family (§4), asked as one question rather than eight
pairings: **do two weak rules clear a bar together?**

It is not an idle question here. `MOLIDO_CONSENSUS_REQUIRED` makes the live
order gate wait for N brains to agree, and until now nothing had measured
whether agreement is worth the wait — `measure` takes one rule, and the gate
is not one. `rules.Agreement` is that one rule.

H1, two years, broker series.

| pair | instants | trades | edge R | t |
|---|---|---|---|---|
| carry + trend | 73 | 82 | **+0.2740** | 1.77 |
| rsi + stochastic | 242 | 339 | +0.1248 | 1.43 |
| donchian + trend | 34 | 37 | −0.1103 | −0.42 |
| trend + rsi | 43 | 48 | **−0.3198** | −1.28 |

| each half alone | instants | edge R | t |
|---|---|---|---|
| carry-differential | 441 | +0.2203 | **3.99** |
| trend-following | 441 | +0.1597 | 2.73 |
| stochastic-reversion | 408 | +0.1047 | 1.75 |
| rsi-mean-reversion | 381 | +0.0662 | 0.99 |
| donchian-breakout | 184 | −0.0362 | −0.36 |

**Agreement improves the edge per trade and destroys the sample.** The best
pair is `carry + trend`:

```
edge per trade   +0.2740   against  +0.2203 alone    better
instants              73   against       441 alone    six times fewer
t                   1.77   against      3.99 alone    half
```

Six times fewer chances for twenty-five percent more edge. That is the
failure mode written into `Agreement`'s docstring before any of this ran, and
it is the one a table of edges alone would hide: **a hybrid can be better per
trade and worse to own.**

Two more readings:

`trend + rsi` — the brief's own "Trend + Mean Reversion regime filter" — is
the **worst** of the four at −0.3198. Two rules that think in opposite
directions are not saying much when they agree.

`rsi + stochastic` keeps the most instants (242 of ~400) precisely because
the two agree so often, which is the other half of the hypothesis: rules that
overlap heavily preserve the sample and add nothing, because they know one
thing between them.

**For the live gate:** `MOLIDO_CONSENSUS_REQUIRED` is 1, which is off. This
table is the first evidence anyone has had about what raising it would cost —
roughly six-sevenths of the sample, for an edge improvement too small to pay
for it.

---

## 12. A session filter that looked justified and is not

The slice tables in §1 showed Tokyo as the weakest session for every rule
that printed one, and a mechanism was ready to explain it: `cost_in_r` is the
spread over the stop distance, the stop comes from ATR, so smaller bars mean
a larger cost in R for the same spread.

**The mechanism is real.** Measured over two years of H1 bars without looking
at any edge:

| session | mean range | cost, against New York |
|---|---|---|
| tokyo | 17.23 | **1.49x** |
| london | 19.22 | 1.34x |
| **overlap** (12–17 UTC) | **57.88** | **0.44x** |
| new-york | 25.71 | 1.00x |

That is a 3.4x spread in cost between the cheapest and dearest hours, and it
makes a specific prediction about a slice nobody had read: the overlap fell
below the printing threshold in every report so far, and the cost table says
it should be the **best** session for every rule.

### 12.1 The prediction fails

| rule | tokyo | london | overlap | new-york |
|---|---|---|---|---|
| carry-differential | +0.1450 | +0.2691 | **+0.2774** | +0.2277 |
| trend-following | **+0.2126** | +0.0314 | +0.1481 | +0.2031 |
| short-horizon-reversal | +0.0039 | −0.0955 | −0.0369 | **+0.2875** |
| rsi-mean-reversion | +0.0893 | −0.0097 | **−0.0982** | +0.2103 |
| stochastic-reversion | +0.0286 | +0.1160 | **−0.0942** | **+0.3479** |
| cross-sectional-stretch | −0.1346 | +0.2492 | −0.1619 | +0.1093 |

The overlap is best for one rule and **worst for three**. Tokyo, the dearest
session, is the best one for `trend-following`. There is no session ordering
that survives adding the fourth column.

**No session filter.** It would have looked entirely justified from the first
table.

### 12.2 Why the first table lied

It printed only slices above `MIN_SLICE`, which is a selected subset — and
the one session the cost mechanism cared about was the one selection removed.
Six rules across four sessions is twenty-four cells; taking the best cell per
rule out of noise produces a table that looks exactly like this one.

That is the second time in two days that reading a partial table told a story
the full table denies, and it is the same family as counting rows instead of
observations: **a subset chosen by a threshold is not a sample.**

### 12.3 What the cost table is still good for

The allocation is upside down and that part does not depend on the edges at
all. Decisions per session, per rule:

| session | cost | decisions |
|---|---|---|
| tokyo | 1.49x | 119–163, the most |
| new-york | 1.00x | 103–139 |
| london | 1.34x | 86–116 |
| overlap | **0.44x** | **70–100, the fewest** |

The system spends most of its decisions where each one costs 1.49x and
fewest where it costs 0.44x. That is a fact about the clock and the ranking,
not about any edge, and it survives §12.1 being negative.
