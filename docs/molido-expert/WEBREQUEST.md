# WebRequest setup guide

1. In MT5: Tools > Options > Expert Advisors.
2. Check "Allow WebRequest for listed URL".
3. Add the exact origin of `AiBridgeUrl` (and existing `PublishUrl` / `ConfigUrl` if you use them), for example `https://your-host.example`.
4. Restart the terminal after changing the list.
5. If WebRequest returns an error, the Expert falls back to the Common Files status file. A failed or missing URL is shown as Disconnected, not as a fake connection.
