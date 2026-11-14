# Functional test checklist — Molido Expert 2.0 / 2.01

Environment: RoboForex demo login 68531270, Windows VPS terminal, XAUUSD chart. Times are Asia/Tehran (UTC+3:30).

| # | Test | Result |
|---|------|--------|
| 1 | Compile `Molido_Expert.mq5` on the VPS with 0 errors | PASS — 2.01, 0 errors, 20 warnings (pre-existing uninitialized locals in `MolidoDemoScalper.mqh`). EX5 size 364348, compiled 23:56:17 Asia/Tehran on 14 Nov 2026. Journal: `MolidoBridge 2.01: publishing every 20s`. |
| 2 | Attach on demo 68531270 XAUUSD; real-account path remains blocked in source | PASS — `Molido_Expert (XAUUSD,M5) loaded successfully` at 23:57:23 Asia/Tehran. Armed on demo 68531270, risk 0.50%, max lots 2.00, max positions 2, AllowTrading=true. `MOLIDO_REAL_SUPPORTED` remains false. |
| 3 | Dashboard visible, does not cover the full chart; FA/EN header toggle works | PASS — real shot `/workspace/deliver/molido-expert/dashboard.png` (Persian, 23:57:31). Candles remain visible. FA and EN both captured (EN window shot at 00:00:08 on 15 Nov 2026, Asia/Tehran). 2.01 grid: aligned label/value columns, equal safety buttons, no overlapping header/footer text. |
| 4 | Manual 0.01 BUY through Risk Brain, then CLOSE POSITION | BLOCK (correct) — command-file `molido_order_exbuy201.json` (0.01 XAUUSD BUY, SL 3860, TP 3910) was claimed and reviewed. Result at 23:58:50 Asia/Tehran: `ok:false`, `Risk Brain BLOCK: missing: fresh market data`. Saturday session, last XAUUSD tick older than `DEMO_STALE_SECONDS` (60). No position was opened, so no close was sent. On-chart BUY was not remotely clicked (MT5 chart buttons are not separate windows); the command-file path uses the same Risk Brain. |
| 5 | Bridge: write status file (connected) then disconnect | PASS — default UI showed Disconnected 0/51 (no file). After writing `molido_ai_status.json` with `agents_on:3`, the window shot showed Connected, Agents 3/51, council idle, analysis ready, learning on, risk BALANCED. Then wrote `{"ok":false,"connected":false}` at 00:00:25 on 15 Nov 2026 (Asia/Tehran) so the next timer drops to Disconnected. Removing the file alone would wait `AiStaleSec` (180s) before marking stale. |
| 6 | Switch two symbols or timeframes from the panel (actual chart changes) | PARTIAL — Expert ran on XAUUSD H1 (first attach) and later on XAUUSD M5 (chart period actually changed; journal and shots confirm). EURUSD H1 was open in the same terminal. The new 2.01 TF/symbol buttons were not remotely clicked in this run. |
| 7 | CPU / RAM of `terminal64` after attach | PASS — after settle, 00:00:04–00:00:14 on 15 Nov 2026 (Asia/Tehran): ~1.7% CPU over 10.1s, Working Set ~225–246 MB, paged ~332 MB. |

Screenshot: `/workspace/deliver/molido-expert/dashboard.png` (EA ChartScreenShot, Persian, disconnected default). Extra: `dashboard-window-connected.png` (full terminal, EN, Connected 3/51, XAUUSD M5 + EURUSD H1).
