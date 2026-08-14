import { Offline, Panel, Stat, StatusBadge } from "@/components/ui";
import { api } from "@/lib/api";
import { getT } from "@/lib/locale";

export const dynamic = "force-dynamic";

/**
 * Every decision the system recorded, and the only comparison that matters.
 *
 * The headline is the rule against the random control on the same bars, never
 * the rule's hit rate on its own. A rule that beats breakeven while matching a
 * coin flip has beaten nothing — and this project already published one
 * CONFIRMED that missed exactly that, on a 50.84% hit rate whose control scored
 * 50.32%.
 *
 * Both arms are shown side by side for the same reason they are written in one
 * call: it must be impossible to read one without the other.
 */
export default async function JournalPage() {
  const { t } = await getT();
  const view = await api.journal();
  if (!view.ok) return <Offline error={view.error} />;

  const { arms, comparison, note } = view.data;
  const rule = arms.rule;
  const control = arms.control;
  const measured = comparison.rule?.trials > 0;

  return (
    <div className="space-y-4">
      <header>
        <h1 className="text-xl font-bold">{t("journal.title")}</h1>
        <p className="text-xs ink-3 mt-0.5 max-w-3xl">{t("journal.subtitle")}</p>
      </header>

      <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
        <Stat
          label={t("journal.ruleRecorded")}
          value={String(rule?.recorded ?? 0)}
          hint={`${rule?.still_open ?? 0} ${t("journal.stillOpen")}`}
        />
        <Stat
          label={t("journal.controlRecorded")}
          value={String(control?.recorded ?? 0)}
          hint={t("journal.controlHint")}
        />
        <Stat
          label={t("journal.edge")}
          value={
            comparison.edge_over_control != null
              ? `${(comparison.edge_over_control * 100).toFixed(2)}%`
              : "—"
          }
          tone={comparison.significant ? "good" : "warning"}
          hint={t("journal.edgeHint")}
        />
        <Stat
          label={t("journal.needed")}
          value={String(comparison.trials_needed_for_2pp)}
          hint={t("journal.neededHint")}
        />
      </div>

      <Panel title={t("journal.comparison")} subtitle={t("journal.comparisonSubtitle")}>
        {!measured ? (
          /* Not a table of zeros. An empty measurement is not a measurement of
             zero, and a row of 0.00% would be read as a result. */
          <div className="p-4 space-y-1">
            <StatusBadge status="info" label={t("journal.nothingYet")} />
            <p className="text-xs ink-3 leading-relaxed">{t("journal.nothingYetNote")}</p>
          </div>
        ) : (
          <div className="scroll-x">
            <table className="data">
              <thead>
                <tr>
                  <th>{t("journal.arm")}</th>
                  <th>{t("journal.trials")}</th>
                  <th>{t("journal.wins")}</th>
                  <th>{t("journal.hitRate")}</th>
                </tr>
              </thead>
              <tbody>
                <tr>
                  <td className="font-medium">{t("journal.rule")}</td>
                  <td className="num">{comparison.rule.trials}</td>
                  <td className="num">{comparison.rule.wins}</td>
                  <td className="num">
                    {comparison.rule.hit_rate != null
                      ? `${(comparison.rule.hit_rate * 100).toFixed(2)}%`
                      : "—"}
                  </td>
                </tr>
                <tr>
                  <td className="font-medium">{t("journal.control")}</td>
                  <td className="num">{comparison.control.trials}</td>
                  <td className="num">{comparison.control.wins}</td>
                  <td className="num">
                    {comparison.control.hit_rate != null
                      ? `${(comparison.control.hit_rate * 100).toFixed(2)}%`
                      : "—"}
                  </td>
                </tr>
              </tbody>
            </table>
          </div>
        )}
      </Panel>

      {measured && (
        <Panel title={t("journal.verdict")}>
          <div className="p-4 space-y-2">
            <StatusBadge
              status={comparison.significant ? "good" : "warning"}
              label={
                comparison.significant
                  ? t("journal.distinguishable")
                  : t("journal.notDistinguishable")
              }
            />
            <p className="text-xs ink-3 leading-relaxed">
              z = {comparison.z_score ?? "—"} · {t("journal.needs")} 1.96
            </p>
          </div>
        </Panel>
      )}

      <p className="text-xs ink-3 leading-relaxed">{note}</p>
      <p className="text-xs ink-3 leading-relaxed">{comparison.note}</p>
    </div>
  );
}
