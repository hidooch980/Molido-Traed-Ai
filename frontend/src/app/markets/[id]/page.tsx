import Link from "next/link";

import PriceChart from "@/components/PriceChart";
import { InstrumentLinks } from "@/components/InstrumentLinks";
import { Empty, Offline, Panel, Sparkline, Stat, StatusBadge } from "@/components/ui";
import { api } from "@/lib/api";
import { getT } from "@/lib/locale";

export const dynamic = "force-dynamic";

/** Features worth surfacing first: trend, momentum, volatility, structure. */
const HEADLINE_FEATURES = [
  { name: "close_over_sma_20", labelKey: "detail.closeOverSma", digits: 4 },
  { name: "rsi_14", labelKey: "detail.rsi", digits: 1 },
  { name: "atr_14_pct", labelKey: "detail.atrPct", digits: 4 },
  { name: "position_in_range_20", labelKey: "detail.rangePosition", digits: 3 },
];

export default async function InstrumentPage({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const { id } = await params;
  const { t } = await getT();

  const [instruments, bars, features, quality, session] = await Promise.all([
    api.instruments(),
    api.bars(id, "H1", 400),
    api.features(id, "H1", 200),
    api.dataQuality(id),
    api.sessionStatus(id),
  ]);

  if (!bars.ok) return <Offline error={bars.error} />;

  const instrument = instruments.ok ? instruments.data.find((x) => x.id === id) : undefined;
  const points = bars.data.bars.map((b) => ({ t: b.event_time, c: b.close }));
  const rows = features.ok ? features.data.rows : [];
  const latest = rows[rows.length - 1];
  const dataset = quality.ok ? quality.data.datasets[0] : undefined;

  return (
    <div className="space-y-6">
      <header className="flex items-end justify-between gap-4 flex-wrap">
        <div>
          <Link href="/markets" className="text-xs ink-3">
            ← {t("nav.markets")}
          </Link>
          <h1 className="display">
            {bars.data.symbol}
            <span className="ink-3 font-normal text-sm ms-2">{instrument?.name}</span>
          </h1>
          <p className="text-xs ink-3 mt-0.5 num">
            as-of {bars.data.as_of.slice(0, 19).replace("T", " ")} UTC · {bars.data.count}{" "}
            {t("detail.barsVisible")}
          </p>
        </div>
        <div className="flex items-center gap-2">
          {session.ok && (
            <StatusBadge
              status={session.data.is_open ? "good" : "info"}
              label={session.data.is_open ? t("common.open") : t("common.closed")}
            />
          )}
          <StatusBadge
            status={bars.data.training_eligible ? "good" : "warning"}
            label={bars.data.training_eligible ? t("home.eligible") : t("quality.blocked")}
          />
        </div>
      </header>

      <InstrumentLinks
        instrumentId={id}
        symbol={instrument?.symbol}
        current="/markets"
        t={t}
      />

      <Panel
        title={`${bars.data.symbol} · ${bars.data.timeframe} close`}
        subtitle={t("home.priceSubtitle")}
      >
        <PriceChart points={points} />
      </Panel>

      <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
        {HEADLINE_FEATURES.map((spec) => {
          const series = rows
            .map((r) => r.values[spec.name])
            .filter((v): v is number => typeof v === "number");
          const value = latest?.values[spec.name];
          return (
            <Stat
              key={spec.name}
              label={t(spec.labelKey)}
              value={typeof value === "number" ? value.toFixed(spec.digits) : "—"}
              hint={
                series.length > 1 ? `${series.length} ${t("detail.materializedPoints")}` : t("detail.notMaterialized")
              }
              chart={series.length > 1 ? <Sparkline values={series} /> : undefined}
            />
          );
        })}
      </div>

      <div className="grid gap-4 lg:grid-cols-2">
        <Panel
          title={t("detail.featureValues")}
          subtitle={
            features.ok
              ? `${features.data.materialized_values.toLocaleString()} values across ` +
                `${features.data.materialized_features} features`
              : undefined
          }
        >
          {rows.length === 0 ? (
            <Empty>
              {t("detail.nothingMaterialized")}
            </Empty>
          ) : (
            <div className="scroll-x scroll-y" style={{ maxHeight: 340 }}>
              <table className="data">
                <thead>
                  <tr>
                    <th>{t("detail.bar")}</th>
                    {HEADLINE_FEATURES.map((f) => (
                      <th key={f.name}>{t(f.labelKey)}</th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {[...rows]
                    .reverse()
                    .slice(0, 60)
                    .map((row) => (
                      <tr key={row.event_time}>
                        <td className="num ink-2">
                          {row.event_time.slice(0, 16).replace("T", " ")}
                        </td>
                        {HEADLINE_FEATURES.map((f) => {
                          const v = row.values[f.name];
                          return (
                            <td key={f.name} className="num">
                              {typeof v === "number" ? (
                                v.toFixed(f.digits)
                              ) : (
                                <span className="ink-3" title={t("detail.insufficient")}>
                                  —
                                </span>
                              )}
                            </td>
                          );
                        })}
                      </tr>
                    ))}
                </tbody>
              </table>
            </div>
          )}
        </Panel>

        <Panel title={t("quality.title")} subtitle={t("detail.findingsFor")}>
          {!quality.ok || quality.data.findings.length === 0 ? (
            <Empty>{t("common.empty")}</Empty>
          ) : (
            <>
              {dataset && (
                <div className="px-4 py-3 flex items-center gap-4 border-b" style={{ borderColor: "var(--border)" }}>
                  <div>
                    <div className="eyebrow">{t("quality.score")}</div>
                    <div className="text-xl font-semibold num">
                      {(dataset.score * 100).toFixed(1)}%
                    </div>
                  </div>
                  <div className="text-xs ink-3">
                    {dataset.actual_bars.toLocaleString()} / {dataset.expected_bars.toLocaleString()}{" "}
                    {t("quality.coverage")}
                  </div>
                </div>
              )}
              <div className="scroll-x scroll-y" style={{ maxHeight: 280 }}>
                <table className="data">
                  <thead>
                    <tr>
                      <th>{t("quality.issue")}</th>
                      <th>{t("quality.severity")}</th>
                      <th>{t("quality.windowStart")}</th>
                      <th>{t("quality.rows")}</th>
                    </tr>
                  </thead>
                  <tbody>
                    {quality.data.findings.map((f) => (
                      <tr key={f.id}>
                        <td>{t(`issue.${f.issue}`)}</td>
                        <td>
                          <StatusBadge status={f.severity} label={t(`severity.${f.severity}`)} />
                        </td>
                        <td className="num ink-3">
                          {f.window_start.slice(0, 16).replace("T", " ")}
                        </td>
                        <td className="num">{f.affected_rows}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </>
          )}
        </Panel>
      </div>
    </div>
  );
}
