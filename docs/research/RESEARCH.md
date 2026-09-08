# QUANT FX ALPHA LAB — research notebook

Opened 2026-09-07, against the brief's 34 sections.

Rule 3 of that brief governs this file: **where there is no data, it says
DATA NOT AVAILABLE and invents nothing.** Every number below was produced by
running something, and the command that produced it is written beside it.

---

## 0. Why this does not start from zero

The brief asks for a shared, cost-aware, cluster-corrected measurement
harness with rules plugged into it. **That harness already exists in this
repository** and is the valuable part. §27 of the brief — "do not optimize
before baseline" — means the first job is to find out what it already says,
not to write new rules on top of an unmeasured foundation.

What was verified present on 2026-09-07, by reading and running it:

| brief asks for | where it lives | state |
|---|---|---|
| point-in-time cut, no lookahead | `app/learning/measure.py` | present; shares `_outcome` with the live resolver so the two cannot drift |
| random control at the same instant | `measure.py` | present; every rule is scored against a coin flip on the same instrument at the same instant |
| one move is one observation | `measure.py`, and now `scorecard.py` | present on the backtest side; **added to the forward side on 2026-09-07** |
| costs charged against the stop (§10) | `measure.COST_R`, `robustness.CostLevel` | present, at three severities: base, stressed, extreme |
| walk-forward (§15) | `app/learning/geometry.py` | present |
| bootstrap and placebo (§16) | `app/learning/edge_report.py` | present: block bootstrap and a sign-flipped null |
| regime and slice analysis (§17) | `app/learning/robustness.py` | present: by hour, session, weekday, year, period, regime |
| pre-registration and proof (§33) | `app/learning/edge.py` | present: PROVEN / PENDING_FORWARD / REJECTED, and a live-trading gate that reads them |
| rules as interchangeable hypotheses (§8) | `app/learning/rules.py` | present: 8 registered, `PROPOSED` for ones not yet trading |

What the brief asks for that is *not* present is in §4 below.

---

## 1. The state of the evidence, measured

### 1.1 Registry — is anything proven?

```
docker exec molidotrade-collector-1 python -c \
  "from app.learning import edge; print(edge.live_trading_allowed())"
```

```
live trading allowed: False
PROVEN: 0
PENDING_FORWARD: 1   cross-sectional-stretch
REJECTED: 1          mean-reversion-50
```

`cross-sectional-stretch` beats its control by **+0.0086 R** at **z = 3.69**
and earns **+0.0111 R** net of costs on held-out history. It fails on one
thing only: it has been confirmed on held-out *history*, never on data
generated after the hypothesis was written down.

`mean-reversion-50` is rejected at z = 1.10 — not distinguishable from noise.

### 1.2 Forward record — 2026-09-07

| brain | resolved decisions | independent instants | at a time |
|---|---|---|---|
| short-horizon-reversal | 15 | 5 | 3.0 |
| cross-sectional-stretch | 9 | 6 | 1.5 |
| trend-following | 2 | 2 | 1.0 |
| rsi-mean-reversion | 1 | 1 | 1.0 |
| stochastic-reversion | 1 | 1 | 1.0 |
| time-series-momentum | 1 | 1 | 1.0 |
| carry-differential | 0 | 0 | — |
| donchian-breakout | 0 | 0 | — |

**16 independent instants across eight brains**, against a floor of 50 per
brain at which a hit rate becomes answerable at all. Verdict for every one of
them: `insufficient`.

**DATA NOT AVAILABLE** for any forward claim about any brain.

### 1.3 Why the raw count was misleading

29 resolved rule-arm decisions existed, and 26 of them were JPY crosses —
CHFJPY, CADJPY, GBPJPY, NZDJPY, EURJPY, USDJPY — opened within a few hours,
all leaning the same way on one yen move, all stopped out together. Read as
26 trials, that is a devastating verdict on the rules. Read honestly, it is
one trade that lost.

The live accounts were protected from this: `portfolio.MAX_SAME_CURRENCY_POSITIONS`
is 3, and the heaviest currency leg on any open account was exactly 3. The
*measurement* was not protected, and the correction landed in `8fc66f1`.

### 1.4 How much evidence is needed, and how fast it arrives

With the measured per-trade standard deviation of **1.0264 R**:

| to distinguish from zero at z = 1.96 | trades needed |
|---|---|
| +0.0111 R (net of costs) | **32,846** |
| +0.0086 R (over control) | **54,718** |

At the observed rate of independent instants, reaching the much lower
50-instant floor takes:

| brain | instants/day | days to 50 |
|---|---|---|
| cross-sectional-stretch | 2.0 | 25 |
| short-horizon-reversal | 1.7 | 30 |
| trend-following | 0.7 | 75 |
| rsi-mean-reversion, stochastic-reversion, time-series-momentum | 0.3 | 150 |
| carry-differential, donchian-breakout | 0.0 | never at this rate |

These are two different bars and both are true. Fifty instants makes the
*question* answerable. Thirty-three thousand trades is what confirming *this
particular small edge* costs. The distance between those two numbers is the
honest headline of this project.

---

## 2. Baseline: every registered rule through the harness

H1, two years, 800 bootstrap draws, Bonferroni-corrected for 8 hypotheses.
Per-rule output goes to `RESULTS.md`.

First one complete — **donchian-breakout, H1, 2 years**:

```
t = -0.87 (needs 1.96)
net -0.1008 R at base cost, -0.1308 R at extreme
placebo: 335 of 800 sign-flipped draws reached it, p = 0.419
bootstrap 95%: [-0.3049, +0.1024]  — contains zero
every slice too thin to print (13 of them)

VERDICT  robustness: NOT_ROBUST   registry: not registered
LABEL    🔴 REJECT (on H1, this sample)
```

This also answers a standing question. `donchian-breakout` has never produced
a live order candidate; it is not only silent, it has nothing to be loud
about.

---

## 3. Universe and timeframes

The brief names 30 FX pairs plus XAUUSD and XAGUSD (§2) and six timeframes
(§3). What this deployment collects and decides on is in
`docs/TRADED-UNIVERSE.md`. The gap between the two is an open item to be
measured, not asserted here.

---

## 4. What the brief asks for that does not exist yet

By strategy family (§4 of the brief), counting registered rules:

| family | brief lists | registered here |
|---|---|---|
| Trend Following | 9 variants | 1 — `trend-following` |
| Momentum | 5 variants | 2 — `time-series-momentum`, `cross-sectional-stretch` |
| Mean Reversion | 6 variants | 3 — `short-horizon-reversal`, `rsi-mean-reversion`, `stochastic-reversion` |
| Breakout | 6 variants | 1 — `donchian-breakout` |
| Market Structure | 5 variants | **0** |
| Volatility | 5 variants | **0** |
| Carry | 4 variants | 1 — `carry-differential` |
| Statistical | 6 variants | **0** |
| Hybrid | 8 combinations | **0** |

Three whole families have no representative. That is where new work belongs,
and it goes into `rules.PROPOSED` — never straight into `CANDIDATES`, because
`forward.record_forward` iterates `CANDIDATES` on every cycle, so adding a
rule there is not proposing it, it is deploying it.

---

## 5. Where the first full pass ended

Eleven rules measured through one harness, on M15, H1 and D1, corrected for
the number of hypotheses tried, with costs charged at three severities, a
sign-flipped placebo, a block bootstrap, a block reshuffle, random omission
and a two-bar execution delay.

**NO ROBUST EDGE FOUND.** That is section 24 of the brief, and it is the
honest answer rather than a placeholder for one.

| label | rules |
|---|---|
| 🟢 DEPLOY CANDIDATE | none |
| 🟡 RESEARCH FURTHER | none |
| 🔴 REJECT | all eleven, on every timeframe measured |

`time-series-momentum` held 🟡 for a day. On daily bars it survived everything
thrown at it — t = 5.34 over 7,356 trades, intact at four times the measured
cost, intact two bars late, positive in 100% of omission draws, never
reproduced by a sign-flipped null. Walked forward over four folds of twenty
years it returns a **walk-forward efficiency of 0.084**: less than a tenth of
what training promises survives outside it, each fold picks a different
geometry, and the out-of-sample results swing from +0.77 R to −0.93 R with
the most recent fold the worst.

That is what the brief means by robustness over backtest profit, and it is
why the label moved to 🔴.

**Nothing is above red.**

### 5.1 More trades was measured too

The request was for a lower timeframe and many more trades. On M5 the sample
is twenty times the H1 one — 1,284 independent instants against 492, six
thousand trades where H1 had dozens — so the statistical bar is *easier* to
clear. Nothing cleared it, and `trend-following`, which holds the best
positive t on H1, is significantly negative on M5.

`measure.cost_in_r` explains it without needing a new experiment: R is
defined by the stop distance, and the spread does not shrink when the bars
do. More trades is the same knowledge behind a taller fence.

## 6. What the pass changed about the measurement itself

Four defects were found in the apparatus, all of the same family — a count of
rows mistaken for a count of evidence — and all found by asking the brief's
Rule 2 of a number that looked good.

| # | defect | effect |
|---|---|---|
| 1 | the forward journal counted 29 correlated decisions as 29 | 26 were one yen move |
| 2 | two rules needed more history than the harness gave | unmeasurable while trading live |
| 3 | the reshuffle dealt overlapping instants as independent | condemned every rule at the 99th percentile |
| 4 | `carry-differential` held 2 books over 865 instants | its t was about two bets |

The first three are corrected in code. The fourth cannot be corrected
automatically — a rule that holds a good position for months is not thereby
wrong — so the persistence is now printed beside every t.

## 7. Log

| date | what | result |
|---|---|---|
| 2026-09-07 | audited the harness against the brief's 34 sections | most of §10, §14–17, §33 already implemented |
| 2026-09-07 | corrected forward measurement to cluster by instant | `8fc66f1` |
| 2026-09-07 | built the journal → verdict path (`weekly.verdicts`) | 8 brains, 0 edges, 16 instants |
| 2026-09-07 | measured donchian-breakout, H1, 2y | NOT_ROBUST, 🔴 |
| 2026-09-08 | a rule now declares the history it needs | two live rules became measurable at all |
| 2026-09-08 | wrote the three missing families | all 🔴, none close |
| 2026-09-08 | Monte Carlo and §21 ratios | `bf7ea63` |
| 2026-09-08 | corrected the reshuffle to use blocks | it was measuring itself |
| 2026-09-08 | execution delay, both arms | no rule is a latency artifact |
| 2026-09-08 | counted distinct books per rule | the best rule on H1 had four decisions |

## 8. Still open

| item | why it is not done |
|---|---|
| H4 (§3) | no H4 bars are collected; derivable from H1 the way `aggregate.daily_from_hourly` derives D1 |
| M30 (§3) | added recently — 38k bars against H1's 553k, too few for a one-year window |
| news dependence (§18) | not implemented; `robustness.by_hour` is the half of it that exists |
| XAGUSD (§2) | not yet checked against the collected universe |
| walk-forward efficiency (§15) | `geometry.py` walks forward; the efficiency ratio is not computed |
