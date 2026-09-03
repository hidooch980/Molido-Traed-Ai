import Link from "next/link";

import { Empty, Offline, Panel, Stat, StatusBadge } from "@/components/ui";
import { api } from "@/lib/api";
import { getT } from "@/lib/locale";

export const dynamic = "force-dynamic";

/**
 * One terminal: what it holds, and what it has done.
 *
 * The fleet table answers whether they are all alive. It cannot answer the
 * question anybody asks next - what is *this* account doing - and reaching
 * that meant opening the positions page, the journal page and the orders
 * page and matching logins by eye across three tables that are each sorted
 * differently.
 *
 * Everything here is read for this terminal alone. Open positions come from
 * its own bridge, decisions from the journal under its own account key, so
 * nothing on this page is the fleet's answer wearing one member's name.
 *
 * Open positions come first. A closed trade is history and can be read at
 * leisure; an open one is money currently at risk, and it is what somebody
 * opening this page during a drawdown came to see.
 */
export default async function TerminalPage({
  params,
}: {
  params: Promise<{ terminal: string }>;
}) {
  const { terminal } = await params;
  const { t } = await getT();
  const detail = await api.terminalDetail(terminal);

  if (!detail.ok) return <Offline error={detail.error} />;

  const { account, positions, decisions, summary, state } = detail.data;
  const connected = account?.available === true;

  const money = (value: number | null | undefined, digits = 2) =>
    value === null || value === undefined
      ? "—"
      : Number(value).toLocaleString("en-US", {
          minimumFractionDigits: digits,
          maximumFractionDigits: digits,
        });

  // Floating profit and loss, summed from what the terminal reports rather
  // than from anything this system believes it opened.
  const floating = positions.reduce((total, p) => total + Number(p.profit ?? 0), 0);

  return (
    <div className="space-y-6">
      <header className="page-header">
        <div className="min-w-0">
          <h1 className="display" dir="ltr">
            {terminal}
          </h1>
          <p className="page-lede">
            {connected
              ? `${account?.login} · ${account?.server}`
              : t("terminalDetail.notConnected")}
          </p>
        </div>
        <Link href="/brokers" className="text-xs underline underline-offset-2 ink-3">
          {t("terminalDetail.backToFleet")}
        </Link>
      </header>

      <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
        <Stat
          label={t("terminalDetail.balance")}
          value={connected ? money(account?.balance) : "—"}
          hint={account?.currency ?? undefined}
        />
        <Stat
          label={t("terminalDetail.equity")}
          value={connected ? money(account?.equity) : "—"}
          // Equity below balance is the open book carrying its entry spread,
          // which is a cost rather than a result.
          tone={
            connected && Number(account?.equity) < Number(account?.balance)
              ? "warning"
              : "neutral"
          }
        />
        <Stat
          label={t("terminalDetail.openPositions")}
          value={String(positions.length)}
          hint={`${floating >= 0 ? "+" : ""}${money(floating)}`}
          tone={floating < 0 ? "warning" : "good"}
        />
        <Stat
          label={t("terminalDetail.resolved", { days: String(summary.days) })}
          value={
            summary.resolved > 0
              ? `${summary.total_r >= 0 ? "+" : ""}${summary.total_r} R`
              : "—"
          }
          hint={
            summary.hit_rate === null
              ? t("terminalDetail.nothingResolved")
              : t("terminalDetail.hitRate", {
                  wins: String(summary.wins),
                  resolved: String(summary.resolved),
                  rate: `${Math.round(summary.hit_rate * 100)}%`,
                })
          }
          tone={summary.total_r < 0 ? "warning" : "good"}
        />
      </div>

      <Panel
        title={t("terminalDetail.positions")}
        subtitle={t("terminalDetail.positionsSubtitle")}
      >
        {positions.length === 0 ? (
          <Empty>{t("terminalDetail.noPositions")}</Empty>
        ) : (
          <div className="scroll-x">
            <table className="data">
              <thead>
                <tr>
                  <th>{t("terminalDetail.symbol")}</th>
                  <th>{t("terminalDetail.side")}</th>
                  <th className="num">{t("terminalDetail.volume")}</th>
                  <th className="num">{t("terminalDetail.entry")}</th>
                  <th className="num">{t("terminalDetail.stop")}</th>
                  <th className="num">{t("terminalDetail.target")}</th>
                  <th className="num">{t("terminalDetail.reward")}</th>
                  <th className="num">{t("terminalDetail.floating")}</th>
                </tr>
              </thead>
              <tbody>
                {positions.map((p) => {
                  const entry = Number(p.price_open);
                  const stopDistance = Math.abs(entry - Number(p.stop));
                  const targetDistance = Math.abs(Number(p.target) - entry);
                  // Printed rather than assumed: the deployment's geometry is
                  // one number in a constant, and what a position is actually
                  // carrying is a different fact about a trade already open.
                  const reward =
                    stopDistance > 0 ? (targetDistance / stopDistance).toFixed(2) : "—";
                  return (
                    <tr key={String(p.ticket)}>
                      <td className="font-semibold" dir="ltr">
                        {p.symbol}
                      </td>
                      <td>
                        <StatusBadge
                          status={p.side === "buy" ? "good" : "warning"}
                          label={
                            p.side === "buy"
                              ? t("terminalDetail.buy")
                              : t("terminalDetail.sell")
                          }
                        />
                      </td>
                      <td className="num">{p.volume}</td>
                      <td className="num">{p.price_open}</td>
                      <td className="num">{p.stop || "—"}</td>
                      <td className="num">{p.target || "—"}</td>
                      <td className="num">{reward}</td>
                      <td
                        className="num"
                        style={{
                          color:
                            Number(p.profit) < 0 ? "var(--bad)" : "var(--good)",
                        }}
                      >
                        {Number(p.profit) >= 0 ? "+" : ""}
                        {money(p.profit)}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
      </Panel>

      <Panel
        title={t("terminalDetail.decisions")}
        subtitle={t("terminalDetail.decisionsSubtitle", { days: String(summary.days) })}
      >
        {decisions.length === 0 ? (
          <Empty>{t("terminalDetail.noDecisions")}</Empty>
        ) : (
          <div className="scroll-x">
            <table className="data">
              <thead>
                <tr>
                  <th>{t("terminalDetail.opened")}</th>
                  <th>{t("terminalDetail.symbol")}</th>
                  <th>{t("terminalDetail.side")}</th>
                  <th>{t("terminalDetail.brain")}</th>
                  <th>{t("terminalDetail.timeframe")}</th>
                  <th>{t("terminalDetail.outcome")}</th>
                  <th className="num">R</th>
                </tr>
              </thead>
              <tbody>
                {decisions.map((d) => (
                  <tr key={d.id}>
                    <td className="num" dir="ltr">
                      {d.opened_at ? d.opened_at.slice(0, 16).replace("T", " ") : "—"}
                    </td>
                    <td className="font-semibold" dir="ltr">
                      {d.symbol}
                    </td>
                    <td>
                      {d.decision === "long"
                        ? t("terminalDetail.buy")
                        : t("terminalDetail.sell")}
                    </td>
                    <td dir="ltr" className="ink-3">
                      {d.strategy}
                    </td>
                    <td dir="ltr" className="ink-3">
                      {d.timeframe}
                    </td>
                    <td>
                      {d.outcome ? (
                        <StatusBadge
                          status={d.outcome === "win" ? "good" : "critical"}
                          label={
                            d.outcome === "win"
                              ? t("terminalDetail.win")
                              : t("terminalDetail.loss")
                          }
                        />
                      ) : (
                        // Not a result. An entry the market has not answered
                        // yet, which is a different thing from a flat one.
                        <span className="ink-3 text-xs">
                          {t("terminalDetail.stillOpen")}
                        </span>
                      )}
                    </td>
                    <td
                      className="num"
                      style={{
                        color:
                          d.r_multiple === null || d.r_multiple === undefined
                            ? undefined
                            : Number(d.r_multiple) < 0
                              ? "var(--bad)"
                              : "var(--good)",
                      }}
                    >
                      {d.r_multiple === null || d.r_multiple === undefined
                        ? "—"
                        : Number(d.r_multiple).toFixed(2)}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Panel>

      <p className="text-xs ink-3">{detail.data.note}</p>
      {!connected && state?.reason && (
        <p className="text-xs ink-3">{state.reason}</p>
      )}
    </div>
  );
}
