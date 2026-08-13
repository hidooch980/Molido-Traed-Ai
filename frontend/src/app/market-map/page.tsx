import { Empty, Offline, Panel, Stat, StatusBadge } from "@/components/ui";
import { api } from "@/lib/api";
import { getT } from "@/lib/locale";

export const dynamic = "force-dynamic";

/**
 * Which instruments are secretly one bet.
 *
 * Sorted by absolute correlation, so a −0.9 pair sits beside a +0.9 one: both
 * are a single shared risk and only the direction differs. Sorting by signed
 * value would bury the short side of every pair at the bottom of the page.
 *
 * Pairs nobody could measure get their own panel rather than being omitted. An
 * omitted pair reads as an uncorrelated one, which is exactly the assumption
 * that makes a book look diversified while it is one position.
 */
export default async function MarketMapPage() {
  const { t } = await getT();
  const map = await api.marketMap(40);
  if (!map.ok) return <Offline error={map.error} />;

  const { pairs, unmeasured, clustered_pairs, cluster_threshold } = map.data;

  return (
    <div className="space-y-4">
      <header>
        <h1 className="text-xl font-bold">{t("marketMap.title")}</h1>
        <p className="text-xs ink-3 mt-0.5">{t("marketMap.subtitle")}</p>
      </header>

      <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
        <Stat label={t("marketMap.measured")} value={String(map.data.measured_pairs)} />
        <Stat
          label={t("marketMap.clustered")}
          value={String(clustered_pairs)}
          tone={clustered_pairs > 0 ? "warning" : "good"}
          hint={`|r| >= ${cluster_threshold}`}
        />
        <Stat
          label={t("marketMap.unmeasured")}
          value={String(unmeasured.length)}
          tone={unmeasured.length > 0 ? "warning" : "good"}
          hint={t("marketMap.unmeasuredHint")}
        />
        <Stat
          label={t("marketMap.snapshot")}
          value={map.data.oldest_snapshot?.slice(0, 10) ?? "—"}
          hint={t("marketMap.snapshotHint")}
        />
      </div>

      <Panel title={t("marketMap.pairs")} subtitle={t("marketMap.pairsSubtitle")}>
        {pairs.length === 0 ? (
          <Empty>{t("marketMap.noPairs")}</Empty>
        ) : (
          <div className="scroll-x">
            <table className="data">
              <thead>
                <tr>
                  <th>{t("marketMap.pair")}</th>
                  <th>{t("marketMap.correlation")}</th>
                  <th>{t("marketMap.alignedBars")}</th>
                  <th>{t("marketMap.oneBet")}</th>
                </tr>
              </thead>
              <tbody>
                {pairs.map((pair) => (
                  <tr key={`${pair.a}-${pair.b}`}>
                    <td className="font-semibold num">
                      {pair.a} · {pair.b}
                    </td>
                    <td className="num ink-2">{pair.correlation.toFixed(3)}</td>
                    <td className="num ink-3">{pair.aligned_bars ?? "—"}</td>
                    <td>
                      <StatusBadge
                        status={pair.clustered ? "warning" : "good"}
                        label={pair.clustered ? t("marketMap.yes") : t("marketMap.no")}
                      />
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Panel>

      {unmeasured.length > 0 && (
        <Panel
          title={t("marketMap.couldNotMeasure")}
          subtitle={t("marketMap.couldNotMeasureSubtitle")}
        >
          <ul className="p-4 space-y-1.5 text-xs ink-3">
            {unmeasured.map((reason) => (
              <li key={reason}>{reason}</li>
            ))}
          </ul>
        </Panel>
      )}

      <Panel title={t("marketMap.whyItMatters")}>
        <p className="p-4 text-xs ink-3 leading-relaxed">{map.data.note}</p>
      </Panel>
    </div>
  );
}
