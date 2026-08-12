import Link from "next/link";

import { Empty, Offline, Panel, Stat } from "@/components/ui";
import { api } from "@/lib/api";
import { getT } from "@/lib/locale";

export const dynamic = "force-dynamic";

function pct(v: number | null | undefined): string {
  return typeof v === "number" ? `${(v * 100).toFixed(2)}%` : "—";
}

export default async function EpisodesPage({
  searchParams,
}: {
  searchParams: Promise<{ instrument?: string }>;
}) {
  const { t } = await getT();
  const params = await searchParams;
  const instruments = await api.instruments();
  if (!instruments.ok) return <Offline error={instruments.error} />;
  if (instruments.data.length === 0) {
    return (
      <Panel title={t("episodes.title")}>
        <Empty>{t("markets.empty")}</Empty>
      </Panel>
    );
  }

  const selectedId = params.instrument ?? instruments.data[0].id;
  const result = await api.episodes(selectedId);

  return (
    <div className="space-y-4">
      <header className="flex items-end justify-between gap-4 flex-wrap">
        <div>
          <h1 className="text-xl font-bold">{t("episodes.title")}</h1>
          <p className="text-xs ink-3 mt-0.5 max-w-2xl">{t("episodes.subtitle")}</p>
        </div>
        {instruments.data.length > 1 && (
          <div className="flex gap-1.5 flex-wrap max-w-lg justify-end">
            {instruments.data.slice(0, 12).map((x) => (
              <Link
                key={x.id}
                href={`/episodes?instrument=${x.id}`}
                className="pill"
                style={{
                  color: x.id === selectedId ? "var(--accent)" : "var(--ink-3)",
                  borderColor:
                    x.id === selectedId ? "var(--accent)" : "var(--border-strong)",
                }}
              >
                {x.symbol}
              </Link>
            ))}
          </div>
        )}
      </header>

      {!result.ok ? (
        <Offline error={result.error} />
      ) : (
        <>
          <div className="grid gap-3 sm:grid-cols-3">
            <Stat label={t("episodes.stored")} value={result.data.stored.toLocaleString()} />
            <Stat label={t("episodes.matured")} value={result.data.matured.toLocaleString()} />
            <Stat label={t("episodes.visible")} value={result.data.count.toLocaleString()} />
          </div>

          <Panel title={t("episodes.distribution")}>
            <div className="p-4">
              {result.data.distribution.sufficient ? (
                <dl className="grid gap-x-6 gap-y-2 text-sm sm:grid-cols-3">
                  <div>
                    <dt className="eyebrow">{t("episodes.positiveShare")}</dt>
                    <dd className="num text-lg">
                      {pct(result.data.distribution.positive_share as number)}
                    </dd>
                  </div>
                  <div>
                    <dt className="eyebrow">{t("episodes.maxUp")}</dt>
                    <dd className="num text-lg">
                      {pct(result.data.distribution.mean_max_up as number)}
                    </dd>
                  </div>
                  <div>
                    <dt className="eyebrow">{t("episodes.maxDown")}</dt>
                    <dd className="num text-lg">
                      {pct(result.data.distribution.mean_max_down as number)}
                    </dd>
                  </div>
                </dl>
              ) : (
                <p className="text-sm ink-3">{t("episodes.insufficient")}</p>
              )}
              <p className="text-xs ink-3 mt-3 leading-relaxed">
                {t("episodes.directionNote")}
              </p>
            </div>
          </Panel>

          <Panel title={t("episodes.title")}>
            {result.data.episodes.length === 0 ? (
              <Empty>{t("episodes.empty")}</Empty>
            ) : (
              <div className="scroll-x scroll-y" style={{ maxHeight: 460 }}>
                <table className="data">
                  <thead>
                    <tr>
                      <th>{t("episodes.time")}</th>
                      <th>{t("episodes.ready")}</th>
                      <th>{t("episodes.entry")}</th>
                      <th>{t("episodes.maxUp")}</th>
                      <th>{t("episodes.maxDown")}</th>
                      <th>{t("episodes.forward")}</th>
                    </tr>
                  </thead>
                  <tbody>
                    {result.data.episodes.map((e) => (
                      <tr key={e.event_time}>
                        <td className="num ink-2">
                          {e.event_time.slice(0, 16).replace("T", " ")}
                        </td>
                        <td className="num ink-3">
                          {e.outcome_ready_at.slice(0, 16).replace("T", " ")}
                        </td>
                        <td className="num">{e.entry_price.toFixed(5)}</td>
                        <td className="num" style={{ color: "var(--good)" }}>
                          {pct(e.max_up_pct)}
                        </td>
                        <td className="num" style={{ color: "var(--critical)" }}>
                          {pct(e.max_down_pct)}
                        </td>
                        <td className="num">{pct(e.forward_return_pct)}</td>
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
