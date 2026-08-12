import Link from "next/link";

import { Empty, Offline, Panel, StatusBadge } from "@/components/ui";
import { api } from "@/lib/api";
import { getT } from "@/lib/locale";

export const dynamic = "force-dynamic";

export default async function DataQualityPage({
  searchParams,
}: {
  searchParams: Promise<{ instrument?: string }>;
}) {
  const params = await searchParams;
  const { t } = await getT();
  const instruments = await api.instruments();
  if (!instruments.ok) return <Offline error={instruments.error} />;

  if (instruments.data.length === 0) {
    return (
      <Panel title={t("quality.title")}>
        <Empty>
          {t("markets.empty")}
        </Empty>
      </Panel>
    );
  }

  const selectedId = params.instrument ?? instruments.data[0].id;
  const quality = await api.dataQuality(selectedId);

  return (
    <div className="space-y-4">
      <header className="flex items-end justify-between gap-4 flex-wrap">
        <div>
          <h1 className="text-xl font-bold">{t("quality.title")}</h1>
          <p className="text-xs ink-3 mt-0.5">
            {t("quality.subtitle")}
          </p>
        </div>
        {instruments.data.length > 1 && (
          <div className="flex gap-1.5">
            {instruments.data.map((x) => (
              <Link
                key={x.id}
                href={`/data-quality?instrument=${x.id}`}
                className="pill"
                style={{
                  color: x.id === selectedId ? "var(--accent)" : "var(--ink-3)",
                  borderColor: x.id === selectedId ? "var(--accent)" : "var(--border-strong)",
                }}
              >
                {x.symbol}
              </Link>
            ))}
          </div>
        )}
      </header>

      {!quality.ok ? (
        <Offline error={quality.error} />
      ) : (
        <>
          <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
            {quality.data.datasets.map((d) => (
              <div key={`${d.provider_id}-${d.timeframe}`} className="panel p-4">
                <div className="flex items-baseline justify-between gap-2">
                  <span className="font-semibold text-sm">
                    {quality.data.symbol} {d.timeframe}
                  </span>
                  <StatusBadge
                    status={d.is_training_eligible ? "good" : "warning"}
                    label={d.is_training_eligible ? t("quality.eligible") : t("quality.blocked")}
                  />
                </div>
                <div className="text-[2rem] leading-none font-semibold mt-2 num">
                  {(d.score * 100).toFixed(1)}%
                </div>
                {/* Coverage bar: stored vs expected, with the 2px gap the spec asks
                    for between the fill and its track. */}
                <div
                  className="mt-3 h-1.5 rounded-full overflow-hidden"
                  style={{ background: "var(--panel-raised)" }}
                >
                  <div
                    className="h-full rounded-full"
                    style={{
                      width: `${Math.min(100, (d.actual_bars / Math.max(d.expected_bars, 1)) * 100)}%`,
                      background: d.is_training_eligible ? "var(--good)" : "var(--warning)",
                    }}
                  />
                </div>
                <div className="text-xs ink-3 mt-1.5 num">
                  {d.actual_bars.toLocaleString()} / {d.expected_bars.toLocaleString()}{" "}
                  {t("quality.coverage")} · {d.open_findings} {t("quality.findings")}
                </div>
              </div>
            ))}
            {quality.data.datasets.length === 0 && (
              <div className="panel p-4 text-sm ink-3">
{t("quality.notEvaluated")}
              </div>
            )}
          </div>

          <Panel title={t("quality.findings")} subtitle={`${quality.data.findings.length}`}>
            {quality.data.findings.length === 0 ? (
              <Empty>{t("common.empty")}</Empty>
            ) : (
              <div className="scroll-x">
                <table className="data">
                  <thead>
                    <tr>
                      <th>{t("quality.issue")}</th>
                      <th>{t("quality.severity")}</th>
                      <th>{t("quality.windowStart")}</th>
                      <th>{t("quality.rows")}</th>
                      <th style={{ whiteSpace: "normal" }}>{t("quality.expected")}</th>
                      <th style={{ whiteSpace: "normal" }}>{t("quality.observed")}</th>
                    </tr>
                  </thead>
                  <tbody>
                    {quality.data.findings.map((f) => (
                      <tr key={f.id}>
                        <td className="font-medium">{t(`issue.${f.issue}`)}</td>
                        <td>
                          <StatusBadge status={f.severity} label={t(`severity.${f.severity}`)} />
                        </td>
                        <td className="num ink-2">
                          {f.window_start.slice(0, 16).replace("T", " ")}
                        </td>
                        <td className="num">{f.affected_rows}</td>
                        <td className="ink-3" style={{ whiteSpace: "normal" }}>
                          {f.expected ?? "—"}
                        </td>
                        <td className="ink-3" style={{ whiteSpace: "normal" }}>
                          {f.observed ?? "—"}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </Panel>
        </>
      )}
    </div>
  );
}
