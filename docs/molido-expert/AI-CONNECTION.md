# Molido AI connection guide

The Expert reads **real** bridge data only. If nothing is configured or the status is stale, the dashboard shows **Disconnected** and `0/51` agents. It will not invent a live council.

## Token (never in source)
1. Preferred: paste the token into the EA input `AiBridgeToken` (Advanced).
2. Or write the token alone on one line in the terminal Common Files path:
   `...\MetaQuotes\Terminal\Common\Files\molido_ai_token.txt`
3. Do not put the token in the repository or in `GlobalVariable` (MT5 GVs are numeric only).

## File bridge (no WebRequest)
The server/agent host may write:
- `molido_ai_status.json` — example:
  `{"connected":true,"ok":true,"mode":"HYBRID","agents_on":3,"agents_total":51,"council":"hold","analysis":"range","learning":"idle","risk":"balanced","Scalping":"ok","Trend":"ok"}`
- `molido_ai_signals.json` — reserved for future validated signal IDs (dedup + Risk Brain). New entries are refused while disconnected.

Heartbeats older than `AiStaleSec` (default 180s) flip the UI to Disconnected. Open-trade management and risk caps stay local.

## HTTPS bridge
Set `AiBridgeUrl` to a status endpoint. The EA sends `Authorization: Bearer <token>` when a token is present. You must also allow the URL in WebRequest (see WEBREQUEST.md).
