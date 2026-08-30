import { LiveTrading } from "@/components/LiveTrading";
import { Offline, Panel, Stat, StatusBadge } from "@/components/ui";
import { api } from "@/lib/api";
import { getT } from "@/lib/locale";

export const dynamic = "force-dynamic";

/**
 * What is open at the broker — read from the terminal, not from this system's
 * own record of what it thinks it opened.
 *
 * The two disagree exactly when it matters: an order that filled while the
 * reply was lost, a position the broker's own stop closed, a manual trade
 * somebody placed in the terminal. The broker's answer is the one the account
 * is judged on, so it is the one shown.
 */
export default async function PositionsPage() {
  const { t } = await getT();
  const [view, realised] = await Promise.all([api.positions(), api.realised(30)]);
  if (!view.ok) return <Offline error={view.error} />;

  // Handed to the live view as its first reading, so the page does not open
  // empty and fill in a second later - on a page about open risk, a moment of
  // "no positions" is the wrong thing to show even briefly.
  const firstReading = {
    stamped_at: new Date().toISOString(),
    positions: view.data,
    realised: realised.ok ? realised.data : null,
    unreachable: realised.ok ? [] : ["realised"],
  };

  const { available, reason, positions, account, note } = view.data;

  // Summed from the positions rather than read as `equity - balance`: those
  // two agree only while nothing else moves equity, and a number that agrees
  // by coincidence stops agreeing without warning.
  // Grouped from the positions already on screen. No new endpoint and no
  // change to anything the trading path touches - the symbol and the profit
  // are both in the payload, and nothing was reading them together.
  const bySymbol = positions.reduce<Record<string, { profit: number; count: number }>>(
    (grouped, row) => {
      const symbol = typeof row.symbol === "string" ? row.symbol : "?";
      const profit = typeof row.profit === "number" ? row.profit : 0;
      const seen = grouped[symbol] ?? { profit: 0, count: 0 };
      grouped[symbol] = { profit: seen.profit + profit, count: seen.count + 1 };
      return grouped;
    },
    {},
  );
  // Worst first: the losers are what a reader needs to find, and sorting by
  // name buries them among instruments that are behaving.
  const symbolRows = Object.entries(bySymbol).sort(
    (a, b) => a[1].profit - b[1].profit,
  );

  const floating = positions.length
    ? positions.reduce(
        (total, row) => total + (typeof row.profit === "number" ? row.profit : 0),
        0,
      )
    : null;

  return (
    <div className="space-y-4">
      <header>
        <h1 className="text-xl font-bold">{t("positions.title")}</h1>
        <p className="text-xs ink-3 mt-0.5 max-w-3xl">{t("positions.subtitle")}</p>
      </header>

      {/* Refreshes itself while the tab is open. Everything below is correct
          as of the request; this is correct as of five seconds ago and says
          which. */}
      <LiveTrading initial={firstReading as never} />

      {!available ? (
        /* Not an empty table. "No positions" and "we cannot see the account"
           look identical in a blank list, and only one of them is fine. */
        <Panel title={t("positions.unavailable")}>
          <p className="p-4 text-xs ink-3 leading-relaxed">{reason}</p>
        </Panel>
      ) : (
        <>
          <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
            <Stat label={t("positions.open")} value={String(positions.length)} />
            <Stat label={t("positions.account")} value={String(account?.login ?? "—")} />
            <Stat label={t("positions.server")} value={account?.server ?? "—"} />
            <Stat
              label={t("positions.equity")}
              value={account?.equity != null ? account.equity.toLocaleString() : "—"}
              hint={
                account?.balance != null
                  ? `${t("positions.balance")} ${account.balance.toLocaleString()}`
                  : undefined
              }
            />
            {/* Floating profit, which nothing showed before - the numbers were
                in the payload and the reader had to subtract balance from
                equity by hand. Summed from the positions rather than derived
                from the two account figures, because the terminal is the thing
                being asked and a subtraction is a second opinion. */}
            <Stat
              label={t("positions.floating")}
              value={
                floating != null
                  ? `${floating > 0 ? "+" : ""}${floating.toFixed(2)}`
                  : "—"
              }
              tone={
                floating == null || floating === 0
                  ? undefined
                  : floating > 0
                    ? "good"
                    : "warning"
              }
              hint={t("positions.floatingHint")}
            />
          </div>

          {/* Closed trades. Reports why it is empty rather than showing a
              zero: an account with nothing closed and a terminal that is not
              publishing its history look identical in a zero, and only one of
              them is about trading. */}
          {realised.ok && (
            <Panel
              title={t("positions.realised")}
              subtitle={t("positions.realisedHint")}
            >
              {!realised.data.available ? (
                <div className="p-4 space-y-1">
                  <StatusBadge status="info" label={t("positions.notPublished")} />
                  <p className="text-xs ink-3 leading-relaxed">
                    {realised.data.reason}
                  </p>
                </div>
              ) : (
                <div className="p-4 space-y-3">
                  <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
                    <Stat
                      label={t("positions.net")}
                      value={`${(realised.data.net ?? 0) > 0 ? "+" : ""}${(
                        realised.data.net ?? 0
                      ).toFixed(2)}`}
                      tone={
                        (realised.data.net ?? 0) === 0
                          ? undefined
                          : (realised.data.net ?? 0) > 0
                            ? "good"
                            : "warning"
                      }
                      hint={t("positions.netHint")}
                    />
                    <Stat
                      label={t("positions.trades")}
                      value={String(realised.data.trades ?? 0)}
                    />
                    <Stat
                      label={t("positions.swap")}
                      value={(realised.data.swap ?? 0).toFixed(2)}
                    />
                    <Stat
                      label={t("positions.commission")}
                      value={(realised.data.commission ?? 0).toFixed(2)}
                    />
                  </div>
                  {realised.data.by_symbol.length > 0 && (
                    <div className="scroll-x">
                      <table className="data">
                        <thead>
                          <tr>
                            <th>{t("positions.symbol")}</th>
                            <th>{t("positions.trades")}</th>
                            <th>{t("positions.net")}</th>
                            <th>{t("positions.hitRate")}</th>
                          </tr>
                        </thead>
                        <tbody>
                          {realised.data.by_symbol.map((row) => (
                            <tr key={row.symbol}>
                              <td className="font-medium">{row.symbol}</td>
                              <td className="num ink-3">{row.trades}</td>
                              <td
                                className="num"
                                style={{
                                  color:
                                    row.net > 0
                                      ? "var(--good)"
                                      : row.net < 0
                                        ? "var(--warning)"
                                        : "var(--ink-2)",
                                }}
                              >
                                {row.net > 0 ? "+" : ""}
                                {row.net.toFixed(2)}
                              </td>
                              {/* Blank until five trades. A hit rate from two
                                  is a coin flip wearing a percentage. */}
                              <td className="num ink-3">
                                {row.hit_rate != null
                                  ? `${(row.hit_rate * 100).toFixed(0)}%`
                                  : "—"}
                              </td>
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    </div>
                  )}
                  <p className="text-xs ink-3 leading-relaxed">
                    {realised.data.note}
                  </p>
                </div>
              )}
            </Panel>
          )}

          {symbolRows.length > 0 && (
            <Panel
              title={t("positions.bySymbol")}
              subtitle={t("positions.bySymbolHint")}
            >
              <div className="scroll-x">
                <table className="data">
                  <thead>
                    <tr>
                      <th>{t("positions.symbol")}</th>
                      <th>{t("positions.count")}</th>
                      <th>{t("positions.floating")}</th>
                    </tr>
                  </thead>
                  <tbody>
                    {symbolRows.map(([symbol, totals]) => (
                      <tr key={symbol}>
                        <td className="font-medium">{symbol}</td>
                        <td className="num ink-3">{totals.count}</td>
                        <td
                          className="num"
                          style={{
                            color:
                              totals.profit > 0
                                ? "var(--good)"
                                : totals.profit < 0
                                  ? "var(--warning)"
                                  : "var(--ink-2)",
                          }}
                        >
                          {totals.profit > 0 ? "+" : ""}
                          {totals.profit.toFixed(2)}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </Panel>
          )}

          <Panel title={t("positions.open")}>
            {positions.length === 0 ? (
              <div className="p-4 space-y-1">
                <StatusBadge status="good" label={t("positions.flat")} />
                <p className="text-xs ink-3 leading-relaxed">{t("positions.flatNote")}</p>
              </div>
            ) : (
              <div className="scroll-x">
                <table className="data">
                  <thead>
                    <tr>
                      {Object.keys(positions[0]).map((column) => (
                        <th key={column}>{column}</th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {positions.map((row, index) => (
                      <tr key={index}>
                        {Object.values(row).map((cell, cellIndex) => (
                          <td key={cellIndex} className="num">
                            {String(cell)}
                          </td>
                        ))}
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </Panel>
        </>
      )}

      <p className="text-xs ink-3 leading-relaxed">{note}</p>
    </div>
  );
}
