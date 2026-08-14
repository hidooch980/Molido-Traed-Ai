import { Offline, Panel, StatusBadge } from "@/components/ui";
import { api } from "@/lib/api";
import { getT } from "@/lib/locale";

export const dynamic = "force-dynamic";

/**
 * The order state machine, and the one state people get wrong.
 *
 * UNKNOWN is not a failure. A submission that timed out may have filled, and
 * treating that as a rejection is how a system opens a second position on top
 * of one it does not know it has. The page leads with that because it is the
 * whole reason the machine has more than three states.
 */
export default async function OrdersPage() {
  const { t } = await getT();
  const states = await api.orderStates();
  if (!states.ok) return <Offline error={states.error} />;

  const { states: all, terminal, transitions } = states.data;

  return (
    <div className="space-y-4">
      <header>
        <h1 className="text-xl font-bold">{t("orders.title")}</h1>
        <p className="text-xs ink-3 mt-0.5 max-w-3xl">{t("orders.subtitle")}</p>
      </header>

      <Panel title={t("orders.unknownTitle")}>
        <p className="p-4 text-xs ink-3 leading-relaxed">{t("orders.unknownBody")}</p>
      </Panel>

      <Panel title={t("orders.machine")} subtitle={t("orders.machineSubtitle")}>
        <div className="scroll-x">
          <table className="data">
            <thead>
              <tr>
                <th>{t("orders.state")}</th>
                <th>{t("orders.kind")}</th>
                <th>{t("orders.canBecome")}</th>
              </tr>
            </thead>
            <tbody>
              {all.map((state) => {
                const isTerminal = terminal.includes(state);
                const next = transitions[state] ?? [];
                return (
                  <tr key={state}>
                    <td className="font-medium">{state}</td>
                    <td>
                      <StatusBadge
                        status={isTerminal ? "good" : "info"}
                        label={isTerminal ? t("orders.terminal") : t("orders.open")}
                      />
                    </td>
                    <td className="ink-3">
                      {/* An empty cell would read as "unknown". A terminal
                          state has nowhere to go, and saying so is different
                          from saying nothing. */}
                      {next.length ? next.join(", ") : t("orders.nowhere")}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      </Panel>

      <p className="text-xs ink-3 leading-relaxed">{t("orders.note")}</p>
    </div>
  );
}
