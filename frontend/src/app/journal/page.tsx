import { Offline, Panel, Stat, StatusBadge } from "@/components/ui";
import { api } from "@/lib/api";
import { getT } from "@/lib/locale";

export const dynamic = "force-dynamic";

/**
 * Every decision the system recorded, on both price series, and the only
 * comparison that matters.
 *
 * The headline is the rule against the random control on the same bars, never
 * the rule's hit rate on its own. A rule that beats breakeven while matching a
 * coin flip has beaten nothing — and this project already published one
 * CONFIRMED that missed exactly that, on a 50.84% hit rate whose control scored
 * 50.32%.
 *
 * Both arms are shown side by side for the same reason they are written in one
 * call: it must be impossible to read one without the other. Both *series* are
 * shown for a second reason — the public feed and the broker quote the same
 * instrument 33-39% of a stop distance apart, and the edge being looked for is
 * 0.021 R. A page showing one number would be showing a result from a market
 * nobody can trade in, and nothing on it would say so.
 */
const SOURCES = ["yfinance", "metatrader"] as const;

export default async function JournalPage() {
  const { t } = await getT();
  const view = await api.journal();
  if (!view.ok) return <Offline error={view.error} />;

  const {
    arms,
    comparison,
    by_source,
    paired_by_source,
    paired_by_timeframe,
    why_one_timeframe,
    edge_lost_to_real_prices,
    why_two_series,
    note,
  } = view.data;

  const label = (source: string) =>
    source === "metatrader" ? t("journal.broker") : t("journal.public");

  const rows = SOURCES.map((source) => ({
    source,
    name: label(source),
    counts: arms?.[source] ?? {},
    result: by_source?.[source],
    paired: paired_by_source?.[source],
  })).filter((r) => (r.result?.rule?.trials ?? 0) > 0);

  const measured = rows.length > 0;
  const recorded = SOURCES.reduce(
    (sum, s) => sum + (arms?.[s]?.rule?.recorded ?? 0),
    0,
  );
  const open = SOURCES.reduce(
    (sum, s) => sum + (arms?.[s]?.rule?.still_open ?? 0),
    0,
  );
  const control = SOURCES.reduce(
    (sum, s) => sum + (arms?.[s]?.control?.recorded ?? 0),
    0,
  );

  return (
    <div className="space-y-6">
      <header className="page-header">
        <div className="min-w-0">
          <h1 className="display">{t("journal.title")}</h1>
        <p className="text-xs ink-3 mt-0.5 max-w-3xl">{t("journal.subtitle")}</p>
      </div>
      </header>

      <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
        <Stat
          label={t("journal.ruleRecorded")}
          value={String(recorded)}
          hint={`${open} ${t("journal.stillOpen")} · ${t("journal.seriesHint")}`}
        />
        <Stat
          label={t("journal.controlRecorded")}
          value={String(control)}
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
          hint={`${t("journal.public")} · ${t("journal.edgeHint")}`}
        />
        {/* Not folded into the edge figure. What the broker's prices cost is a
            separate measurement, and averaging it into the headline would hide
            the one number neither series gives on its own. */}
        <Stat
          label={t("journal.slippage")}
          value={
            edge_lost_to_real_prices != null
              ? `${(edge_lost_to_real_prices * 100).toFixed(2)}%`
              : t("journal.notYet")
          }
          tone={
            edge_lost_to_real_prices == null
              ? undefined
              : edge_lost_to_real_prices < 0
                ? "warning"
                : "good"
          }
          hint={t("journal.slippageHint")}
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
                  <th>{t("journal.series")}</th>
                  <th>{t("journal.arm")}</th>
                  <th>{t("journal.trials")}</th>
                  <th>{t("journal.wins")}</th>
                  <th>{t("journal.hitRate")}</th>
                </tr>
              </thead>
              <tbody>
                {rows.flatMap((row) =>
                  (["rule", "control"] as const).map((arm) => (
                    <tr key={`${row.source}-${arm}`}>
                      <td className="ink-3">
                        {arm === "rule" ? row.name : ""}
                      </td>
                      <td className="font-medium">
                        {arm === "rule" ? t("journal.rule") : t("journal.control")}
                      </td>
                      <td className="num">{row.result[arm].trials}</td>
                      <td className="num">{row.result[arm].wins}</td>
                      <td className="num">
                        {row.result[arm].hit_rate != null
                          ? `${(row.result[arm].hit_rate * 100).toFixed(2)}%`
                          : "—"}
                      </td>
                    </tr>
                  )),
                )}
              </tbody>
            </table>
          </div>
        )}
      </Panel>

      {measured && (
        <Panel title={t("journal.verdict")}>
          <div className="p-4 space-y-3">
            {rows.map((row) => {
              /* `significant` is abs(z): true whether the rule beat the coin
                 flip or lost to it. Painting that green labelled a losing
                 series a success. The verdict string carries the sign. */
              const worse = row.result.verdict?.includes("worse") ?? false;
              const beat = (row.result.significant ?? false) && !worse;
              return (
              <div key={row.source} className="space-y-1">
                <StatusBadge
                  status={worse ? "bad" : beat ? "good" : "warning"}
                  label={`${row.name} — ${
                    worse
                      ? t("journal.worseThanControl")
                      : beat
                        ? t("journal.distinguishable")
                        : t("journal.notDistinguishable")
                  }`}
                />
                <p className="text-xs ink-3 leading-relaxed">
                  z = {row.result.z_score ?? "—"} · {t("journal.needs")} 1.96
                </p>
              </div>
              );
            })}
          </div>
        </Panel>
      )}

      {measured && (
        <Panel title={t("journal.paired")} subtitle={t("journal.pairedSubtitle")}>
          <div className="p-4 space-y-3">
            {rows.map((row) => (
              <div key={row.source} className="space-y-1">
                {row.paired && row.paired.t_statistic != null ? (
                  <>
                    <StatusBadge
                      status={
                        row.paired.t_statistic >= row.paired.required_t
                          ? "good"
                          : "warning"
                      }
                      label={`${row.name} — ${row.paired.verdict}`}
                    />
                    <p className="text-xs ink-3 leading-relaxed">
                      t = {row.paired.t_statistic} · {t("journal.needs")}{" "}
                      {row.paired.required_t} ·{" "}
                      {t("journal.pairedMean")}{" "}
                      {row.paired.mean_difference_r ?? "—"} R ·{" "}
                      {row.paired.instants} {t("journal.pairedInstants")} (
                      {row.paired.pairs} {t("journal.pairedPairs")})
                    </p>
                  </>
                ) : (
                  <StatusBadge
                    status="info"
                    label={`${row.name} — ${t("journal.pairedNotMeasured")}`}
                  />
                )}
              </div>
            ))}
            <p className="text-xs ink-3 leading-relaxed">
              {t("journal.pairedCoarse")}
            </p>
          </div>
        </Panel>
      )}

      {paired_by_timeframe && Object.keys(paired_by_timeframe).length > 0 && (
        <Panel
          title={t("journal.byTimeframe")}
          subtitle={t("journal.byTimeframeSubtitle")}
        >
          <div className="scroll-x">
            <table className="data">
              <thead>
                <tr>
                  <th>{t("journal.timeframe")}</th>
                  <th>{t("journal.pairedInstants")}</th>
                  <th>{t("journal.pairedMean")}</th>
                  <th>t</th>
                  <th>{t("journal.needs")}</th>
                  <th>{t("journal.scope")}</th>
                </tr>
              </thead>
              <tbody>
                {Object.entries(paired_by_timeframe).map(([tf, card]) => (
                  <tr key={tf}>
                    <td className="font-medium">{tf}</td>
                    <td className="num">{card.instants}</td>
                    <td className="num">
                      {card.mean_difference_r != null
                        ? `${card.mean_difference_r} R`
                        : "—"}
                    </td>
                    <td className="num">{card.t_statistic ?? "—"}</td>
                    <td className="num">{card.required_t}</td>
                    <td className="ink-3">
                      {card.pre_registered
                        ? t("journal.preRegistered")
                        : t("journal.exploratory")}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <p className="p-4 pt-3 text-xs ink-3 leading-relaxed">
            {why_one_timeframe}
          </p>
        </Panel>
      )}

      <Panel title={t("journal.whyTwo")}>
        <p className="p-4 text-xs ink-3 leading-relaxed">{why_two_series}</p>
      </Panel>

      <p className="text-xs ink-3 leading-relaxed">{note}</p>
      <p className="text-xs ink-3 leading-relaxed">{comparison.note}</p>
    </div>
  );
}
