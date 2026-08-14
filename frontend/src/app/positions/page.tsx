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
  const view = await api.positions();
  if (!view.ok) return <Offline error={view.error} />;

  const { available, reason, positions, account, note } = view.data;

  return (
    <div className="space-y-4">
      <header>
        <h1 className="text-xl font-bold">{t("positions.title")}</h1>
        <p className="text-xs ink-3 mt-0.5 max-w-3xl">{t("positions.subtitle")}</p>
      </header>

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
          </div>

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
