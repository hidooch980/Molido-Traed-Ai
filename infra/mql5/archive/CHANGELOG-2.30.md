# Molido Expert 2.30 — change log (Master V2)

Demo account 68531270 only. Real accounts stay locked (`MOLIDO_REAL_SUPPORTED` false).
Previous 2.20 sources and ex5 are in `infra/mql5/archive/expert-2.20/` and `/workspace/deliver/molido-expert/rollback-2.20/`.

Shared defaults (`MaxLots` 2.00, `UsePartialTP`/`UseTrailing`/`UseBreakEven` true, `DEMO_HARD_MAX_LOTS` 2.0) are unchanged for Master and other EAs. Expert-only behaviour is gated with `#ifdef MOLIDO_EXPERT_UI`.

## C1 — Expert policy module and inputs
- **File:** `infra/mql5/MolidoExpertPolicy.mqh` (new), `infra/mql5/Molido_Expert.mq5`
- **Before:** no Expert-specific risk/session/lot/instance policy; version 2.20
- **Change:** version 2.30; new input group “Expert 2.30 safety”; policy helpers for metals, lot caps, min TP-R, instance lock, daily safe-mode
- **Reason:** apply approved loss-analysis fixes only on Molido_Expert
- **Impact:** Expert compile path only; Master/other EAs do not include this module
- **Test:** compile Expert 0 errors; pytest unique-magic/version/sha
- **Result:** pending compile
- **Rollback:** restore 2.20 mq5 (no policy include/inputs) and drop this header

## C2 — Metals risk, London filter, per-trade loss cap
- **File:** `MolidoExpertPolicy.mqh`, hook in `MolidoDemoScalper.mqh` (`DemoReview`, `DemoSizeLots`)
- **Before:** metals sized at the shared 0.5% / 2.00 lot cap; no London filter; no USD loss cap (three metal SL hits of about −1000 USD each on 16–17 Nov)
- **Change:** default `ExpertMetalRiskPct=0.15`; block new metal entries 07:00–16:00 GMT when `ExpertBlockMetalsInLondon=true`; cap per-trade loss at min(0.25% balance, 300 USD) and clamp lots so SL loss cannot exceed that
- **Reason:** metals produced almost all of the demo loss
- **Impact:** tighter Expert sizing only; Risk Brain caps are never loosened
- **Test:** backtest if feasible; live journal should show London block and smaller metal lots
- **Result:** pending
- **Rollback:** restore 2.20 scalper + drop policy hooks

## C3 — Symmetric SL/TP, partial/trail optional (default off)
- **File:** `MolidoExpertPolicy.mqh`, `MolidoProtect.mqh` (`DemoPartialTakeProfit`), `MolidoSmart.mqh` (`DemoManagePositions`), `MolidoDemoScalper.mqh` / `MolidoExpertExec.mqh` (`ExpertEnsureMinTp`)
- **Before:** `UsePartialTP`/`UseTrailing`/`UseBreakEven` default on for all EAs; winners often closed by trail or `molido-tp1` instead of full TP
- **Change:** Expert defaults `ExpertUsePartialTP/Trailing/BreakEven=false`; `ExpertMinTpR=1.5` enforced after SL/TP are set
- **Reason:** trailing/partials shrunk winners while losses ran to full SL
- **Impact:** Expert only; other EAs keep previous defaults
- **Test:** compile; no invented stats
- **Result:** pending
- **Rollback:** restore 2.20 protect/smart/exec hooks

## C4 — Lower, symbol-scaled lot cap
- **File:** policy + `DemoEffectiveMaxLots` / `DemoSizeLots` / `ExpertManualTrade`
- **Before:** hard cap 2.00 lots; 19 of 23 fills used 2.00 lots
- **Change:** Expert ceilings `ExpertMaxLots=0.50`, metals `0.20`, index/FX `0.50`, then money-cap clamp
- **Reason:** 2.00-lot metal stops were ~1000 USD each
- **Impact:** Expert only; shared `MaxLots` input unchanged
- **Test:** compile; sizing path uses `g_ex_lots_symbol` so AutoSymbol gold is not sized on `_Symbol`
- **Result:** pending
- **Rollback:** restore 2.20 sizer

## C5 — Single-instance GlobalVariable lock
- **File:** policy, `MolidoRuntime.mqh` OnInit/OnTimer/OnDeinit, scalper tick hook, `ExpertManualTrade`
- **Before:** two Expert charts (XAUUSD and EURUSD) both ran AutoSymbol
- **Change:** `ExpertSingleInstance=true` lock (`Molido.Expert.LockLogin/LockChart/LockHb`), 90s heartbeat, standby does not trade; skipped in Strategy Tester
- **Reason:** duplicate instance
- **Impact:** Expert only; VPS step will remove the EURUSD Expert chart
- **Test:** attach on XAUUSD only; second chart should log standby
- **Result:** pending
- **Rollback:** restore 2.20 runtime hooks

## C6 — Safe-mode daily reset
- **File:** `MolidoProtect.mqh` (`DemoSafeModeStopped`, `ProtectConsecutiveLosses` under ifdef), policy `ExpertTodayLossStreak` / `ExpertSafeModeStopped`
- **Before:** trailing loss streak had no date check, so “stop until next day” never lifted (18–20 Nov all blocked)
- **Change:** Expert counts only current server-date OUT deals of magic 685409; next trading day starts at 0
- **Reason:** bug in the advertised daily reset
- **Impact:** Expert only
- **Test:** after a 3-loss day, first tick of the next server date must allow entries (subject to other filters)
- **Result:** pending
- **Rollback:** restore 2.20 protect

## C7 — Version, gate, hashes, tests
- **File:** `Molido_Expert.gate.json` (still `backtest: PENDING`), sha256 sidecars, `backend/tests/test_ea_remote_config.py`
- **Before:** version 2.20, stale `MolidoExpertUI.mqh.sha256` (file bytes were already `baf63088…` in 2.20; sidecar said `f32094fc…`)
- **Change:** version/gate 2.30; sidecars for touched sources + new policy; UI sidecar corrected to match unchanged file bytes
- **Reason:** tests compare sidecar to file bytes
- **Impact:** test-only / metadata
- **Test:** pytest `test_ea_remote_config.py`
- **Result:** pending
- **Rollback:** restore 2.20 gate and sidecars

## Not changed
- Real-account hard block remains false
- Rocket Hunter remains unimplemented/off
- Remote auto-execution of `molido_ai_signals.json` remains reserved
- Auto-update gate remains PENDING (no walk-forward PASS)
- Other EAs’ ex5 files are not overwritten on the VPS
- UI 2.2 layout is unchanged

## C8 — Higher-TF trend filter
- **File:** `MolidoExpertPolicy.mqh` (`ExpertTrendAligned`), inputs in `Molido_Expert.mq5`
- **Before:** AutoSymbol could sell metals against the higher-timeframe trend (22 of 23 fills were sells)
- **Change:** `ExpertUseTrendFilter=true` (default on): new entries must agree with H1 and H4 EMA50/200 (`ExpertTrendRequireBoth=true`)
- **Reason:** quality — avoid counter-trend entries
- **Impact:** Expert only; switchable
- **Test:** compile; journal reason "against H1/H4 EMA..." when blocked
- **Rollback:** set `ExpertUseTrendFilter=false` or restore previous policy

## C9 — Spread and ATR volatility filters
- **File:** policy `ExpertSpreadAtrOk`
- **Before:** shared 15% ATR spread cap only; no low/high ATR skip
- **Change:** `ExpertUseSpreadFilter=true` (default 10% ATR); `ExpertUseAtrFilter=true` skips ATR below 0.5x or above 2.0x its 50-bar average
- **Reason:** skip abnormal spread and dead/chaotic volatility
- **Impact:** Expert only; tightens, never loosens the shared cap
- **Rollback:** turn the two inputs off

## C10 — Optional MT5 calendar news filter
- **File:** policy `ExpertNewsBlocked`
- **Before:** Expert compiled with `MOLIDO_USE_NEWS=false`, so the news strategy did not gate entries
- **Change:** optional high-impact calendar window +/-30 min for the symbol's currencies (metals include USD). **Default OFF** because the broker calendar is often empty; fails open if the feed returns no events
- **Reason:** user asked for a news filter only if reliable
- **Rollback:** leave `ExpertUseNewsFilter=false`

## C11 — Break-even at +1R and modest ATR trail after +1.5R
- **File:** policy `ExpertManageExits`, hook in `MolidoSmart.mqh`
- **Before:** old partial/trail defaults were turned off so winners were not shrunk; no R-based BE
- **Change:** `ExpertUseBeAtR=true` moves SL to entry at +1R; `ExpertUseAtrTrail=true` trails by 1.0 ATR after +1.5R; original TP is never removed or crossed. Old `ExpertUsePartialTP/Trailing/BreakEven` stay false
- **Reason:** lock risk after 1R without cutting full TP
- **Rollback:** turn the two new inputs off

## C12 — Solid safe-mode reset + dashboard
- **File:** policy safe-mode GV/cooldown, `MolidoExpertUI.mqh` risk card, `DemoSafeModeLine`
- **Before:** Expert already counted only today's losses; no cooldown backup; dashboard badge did not say when the stop lifts
- **Change:** stop also expires at the next server day or after `ExpertSafeModeCooldownHours=24`; a GlobalVariable records when it engaged; history-select failure does not silently lift a same-day stop; risk card shows "حالت امن" off / reduce / STOP until timestamp
- **Reason:** trading had stayed frozen after the Nov losses; user needs the state visible and auto-clear
- **Rollback:** restore previous policy/UI snippets

## C13 — SP2L and FVG confirmation filters (optional, default off)
- **File:** `infra/mql5/MolidoV2Filters.mqh` (new), hooks in policy `ExpertQualityAllow`, inputs `InpUseSP2LFilter` / `InpUseFVGFilter` in `Molido_Expert.mq5`, dashboard strategy list in `MolidoExpertUI.mqh`
- **Before:** no SP2L / FVG confirmation
- **Change:** port TESTED detection from `agents/stage-23-v2-engines` (spike+P-Gap, leg1/leg2, HL/LH, invalidation; 3-bar FVG + SM04 mitigation). Used only as confirmation of an existing entry direction. Closed M15 bars only (no bar 0, no repaint). Entry/SL/TP placement stays RESEARCH and is not emitted. Both inputs default **false**. Thresholds (1.8 ATR / 0.5 body / 2.5 ATR spike) remain the Python RESEARCH defaults and are not claimed as verified edges. Dashboard shows SP2L/FVG on/off in the left strategy list and on the Settings tab. Rocket Hunter stays unimplemented.
- **Reason:** user asked to include SP2L and Spike & Imbalance as optional confirmation, not standalone entries
- **Impact:** Expert only; no change to default live behaviour until the inputs are switched on
- **Test:** compile 0 errors; backtest variant with both filters on if feasible
- **Rollback:** leave both inputs false, or drop the include hook

## C14 - hotfix: scalper never traded in the first 2.30 build (22 Nov 2026)

A stray `return;` after the single-instance gate in `DemoScalperOnTick` (under `MOLIDO_EXPERT_UI`) made the Expert return before any entry logic. Found because 12-month tester runs showed 0 trades. Removed; the gate is now a single `if(...) return;`. Rebuilt ex5 501474 bytes, 0 errors. Live demo 68531270 restarted on the fixed build. Earlier 2.30 ex5 (463110 bytes) must not be used.
