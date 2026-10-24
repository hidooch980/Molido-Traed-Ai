# FTMO 10K — 14-day trial and day-15 review

Status: implementation prepared; trial activation, account mapping and server
rollout have not been verified. The holder reports an FTMO account already
active in a terminal. Use that account after confirming its product, initial
balance and expiry in Account MetriX. Do not create or reset an account as part
of deployment. Never put account passwords or tokens in this repository.

## Objective and phase lock

The immediate objective is a measured, reproducible trial with no rule breaches.
The longer-term aspiration is USD 100,000 monthly payouts, with a weekly target
considered only after sustained monthly results. Neither is a promised return
or a reason to increase risk. Trial profits are simulated and not withdrawable.
Fourteen days alone cannot establish a durable trading edge.

- Phase 0: verify the existing account, establish baseline equity, record expiry,
  identify its terminal and journal mapping, fix readiness reporting.
- Phase 1: test on the existing USD 10,000 2-Step Free Trial, after account-specific
  risk settings are verified on the running server.
- Phase 2: day-15 review of results and defects.
- Phase 3: after trial review and holder authorization, the paid 2-Step
  Challenge (10% target), then Verification (5% target), using their own
  rulebooks and provider conditions. No fixed deadline to force a pass.
- Phase 4: after FTMO approval and the holder's account agreement, operate
  the eligible FTMO Account and measure actual monthly payouts after the
  provider share and expenses. Evaluation profits are not payouts.
- No automatic purchase, account promotion, live-money enablement or risk increase.
- Phase lock: do not advance on elapsed time or target profit alone. Missing
  records or unresolved execution defects keep the next phase closed.

## Provider objectives (verified 2026-10-25)

Source: https://ftmo.com/en/ftmo-free-trial/

| Item | 2-Step Free Trial on USD 10,000 |
| --- | --- |
| Profit target | 5% / USD 500, closed positions |
| Daily loss amount | 5% of initial capital / USD 500 |
| Total loss floor | static, USD 9,000 equity |
| Minimum trading days | 2 |
| Duration | 14 calendar days; use the broker's actual expiry |

The provider can end the trial early when objectives are met, a rule is
breached, or no trade is placed in the first seven days. Day 15 is our review,
not an extra trading day. Daily loss includes floating P/L, commissions and
swaps and resets on the provider's CE(S)T boundary, not Tehran midnight.

The existing `ftmo-challenge-2step-phase1` profile is the PAID challenge (10%
target, four trading days); `ftmo-strictest` is a fallback, not the Free Trial.
Do not silently label either as the trial. Until the exact trial rulebook and
calendar expiry are represented on the server, report those limits separately
from the challenge engine. Do not use `max_trading_days=14` as a calendar expiry:
that engine field counts days traded, not elapsed days.

## Proposed internal limits — not automatically applied

| Control | Proposed limit |
| --- | --- |
| Per-order risk | at most 0.25% of equity, capped at USD 25 |
| Aggregate risk to broker stops | at most USD 50 |
| Internal daily stop | USD 100 loss including floating P/L and costs |
| Internal total stop/review | equity at or below USD 9,600 |

These controls require account-specific enforcement and inspection before the
trial starts. The existing risk percentage setting alone does not enforce all
four. Do not change deployment-wide settings for other active accounts. Do not
increase a permitted position just to satisfy the broker's minimum lot size.
No mandatory daily profit target, martingale or loss-recovery sizing.

## Records needed from the active server

Capture a baseline before changing the tested strategy, then use the same
strategy version and risk policy throughout the trial. Any strategy change
starts a new evaluation segment; preserve the earlier record.

- Product, initial balance, terminal identifier, start and broker expiry.
- Deployed Git SHA and account-specific strategy/risk policy.
- Account balance/equity snapshots and deposits/withdrawals/resets, if any.
- Broker fills: timestamps, symbol, side, volume, entry/exit, stops, commission,
  swap, realized profit, slippage, rejection and retry events.
- Peak-to-trough equity drawdown; daily loss at provider boundaries; simultaneous
  exposure and stop coverage. Risk at stops is not a guarantee against gaps.
- Journal decisions and controls, labelled by strategy, feed and timeframe.

## Read-only review endpoints

Use the existing authenticated session; a 401 is missing access, not an empty
record. The public health endpoint proves connectivity, not order flow or profit.

- `/health/ready`
- `/api/v1/learning/journal`
- `/api/v1/learning/calibration`
- `/api/v1/learning/real-money`
- `/api/v1/decisions/readiness`

The readiness fix clusters simultaneous matched decisions, keeps feeds and
timeframes apart, excludes retracted/excluded evidence and requires positive
gross results plus registered costed forward evidence for the same strategy.
It does not infer that non-simultaneous/overlapping decisions are independent,
or that a journal R value equals realized broker net profit. The sizing probe
exercises one understated gold tick-value case offline; it is not a full broker
specification audit. No execution switches or orders are changed by this patch.

## Day-15 decision

Report realized net P/L, costs, floating P/L, maximum equity drawdown, daily
breaches, count of actual fills, duplicate/missing orders, feed outages and
stop coverage. Report unmatched/missing data explicitly. Separately describe
statistical uncertainty and dependence between trades. A passed FTMO trial
is not proof of a profitable strategy and does not unlock real-money trading.
