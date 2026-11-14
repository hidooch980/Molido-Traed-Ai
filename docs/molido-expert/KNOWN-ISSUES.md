# Known issues — Molido Expert 2.0 / 2.01

- Rocket Hunter, Smart Money, Sentiment, Capital and a live 51-agent council are **not implemented** as local strategies. The groups panel shows them only when the bridge file/URL provides real status; otherwise they stay Disconnected. Rocket has no working toggle.
- Incoming AI trade signals from `molido_ai_signals.json` are reserved; auto entries from unverified remote signals are not executed in this release. Local strategies and manual BUY/SELL (through Risk Brain) are.
- Auto-update still requires a verified sha256 **and** a walk-forward gate of PASS. The Expert gate is PENDING because no new walk-forward was run. Do not invent backtest numbers.
- Language toggle in the header is FA/EN at runtime (`g_ui_lang`). Arabic/Turkish stay on the Advanced `Language` input; switching FA/EN in the header overrides that input until the EA is reloaded.
- The dashboard leaves at least ~280px of the chart visible (panel cap 460px). Body sections scroll; use the ^ / v buttons. Trade buttons (BUY / SELL / CLOSE POSITION / CLOSE ALL) and SC/NX/TR/AU sit in the Trade Control card, so they may be below the first screen. The sticky footer is the safety row only: Auto, Stop new, and red KILL (not next to BUY).
- News Filter (NX) defaults **off** on Expert (`MOLIDO_USE_NEWS false`). Fibo stays off.
- Strategy performance is "no data" until the account has closed deals with a Molido magic or a `molido*` comment.
- Risk Brain still refuses a second position on the same symbol, requires a mandatory stop and target, and blocks new entries when the symbol tick is older than 60 seconds (`DEMO_STALE_SECONDS`). That is intentional. A 0.01 demo BUY on Saturday 14 Nov 2026 was blocked with `missing: fresh market data`.
- Deleting `molido_ai_status.json` does not instantly flip the UI to Disconnected; the link is marked stale after `AiStaleSec` (180s). A status file with `"connected": false` disconnects on the next timer tick.
