# Known issues — Molido Expert 2.0

- Rocket Hunter, Smart Money, Sentiment, Capital and a live 51-agent council are **not implemented** as local strategies. The groups panel shows them only when the bridge file/URL provides real status; otherwise they stay Disconnected.
- Incoming AI trade signals from `molido_ai_signals.json` are reserved; auto entries from unverified remote signals are not executed in this release. Local strategies and manual BUY/SELL (through Risk Brain) are.
- Auto-update still requires a verified sha256 **and** a walk-forward gate of PASS. The Expert gate is PENDING because no new walk-forward was run. Do not invent backtest numbers.
- Language toggle in the header is FA/EN at runtime (`g_ui_lang`). Arabic/Turkish stay on the Advanced `Language` input; switching FA/EN in the header overrides that input until the EA is reloaded.
- The dashboard is sized to about 40% of the chart width and a fitted height so candles stay visible. Very short chart windows use a scrollable body; use the ^ / v buttons.
- Strategy performance is "no data" until the account has closed deals with a Molido magic or a `molido*` comment.
- DemoSize / Risk Brain still refuse a second position on the same symbol and require a mandatory stop. That is intentional.
