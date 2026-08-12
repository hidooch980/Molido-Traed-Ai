import Link from "next/link";

import { Empty, Offline, Panel, Pill } from "@/components/ui";
import { api } from "@/lib/api";
import { getT } from "@/lib/locale";

export const dynamic = "force-dynamic";

function pct(v: number | undefined | null, digits = 2): string {
  return typeof v === "number" ? `${(v * 100).toFixed(digits)}%` : "—";
}

export default async function MemoryPage({
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
      <Panel title={t("memory.title")}>
        <Empty>{t("markets.empty")}</Empty>
      </Panel>
    );
  }

  const selectedId = params.instrument ?? instruments.data[0].id;
  const memory = await api.memory(selectedId);

  const labelFor: Record<string, string> = {
    short: t("memory.short"),
    medium: t("memory.medium"),
    long: t("memory.long"),
  };

  return (
    <div className="space-y-4">
      <header className="flex items-end justify-between gap-4 flex-wrap">
        <div>
          <h1 className="text-xl font-bold">{t("memory.title")}</h1>
          <p className="text-xs ink-3 mt-0.5 max-w-2xl">{t("memory.subtitle")}</p>
        </div>
        {instruments.data.length > 1 && (
          <div className="flex gap-1.5 flex-wrap max-w-lg justify-end">
            {instruments.data.slice(0, 12).map((x) => (
              <Link
                key={x.id}
                href={`/memory?instrument=${x.id}`}
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

      {!memory.ok ? (
        <Offline error={memory.error} />
      ) : (
        <>
          <div className="grid gap-4 lg:grid-cols-3">
            {memory.data.horizons.map((h) => (
              <Panel
                key={h.horizon}
                title={labelFor[h.horizon] ?? h.horizon}
                subtitle={
                  h.available
                    ? `${h.bars?.toLocaleString()} ${t("common.bars")}`
                    : undefined
                }
              >
                {!h.available ? (
                  <div className="p-4 text-sm ink-3">
                    {t("memory.unavailable")}
                    <div className="text-xs mt-1 num">{h.reason}</div>
                  </div>
                ) : (
                  <div className="p-4 space-y-2.5">
                    <div className="flex items-center gap-2">
                      <Pill tone={h.trend === "sideways" ? "muted" : "good"}>
                        {h.trend ?? "—"}
                      </Pill>
                      <span className="text-xs ink-3 num">
                        {t("memory.strength")}{" "}
                        {typeof h.trend_strength === "number"
                          ? h.trend_strength.toFixed(2)
                          : "—"}
                      </span>
                    </div>
                    <dl className="grid grid-cols-2 gap-x-4 gap-y-1.5 text-xs">
                      {[
                        [t("memory.return"), pct(h.return_pct)],
                        [t("memory.vol"), pct(h.realized_vol, 3)],
                        [
                          t("memory.position"),
                          typeof h.position_in_range === "number"
                            ? h.position_in_range.toFixed(3)
                            : "—",
                        ],
                        [t("memory.drawdown"), pct(h.max_drawdown_pct)],
                        [t("memory.runup"), pct(h.max_runup_pct)],
                      ].map(([label, value]) => (
                        <div key={label} className="flex justify-between gap-2">
                          <dt className="ink-3">{label}</dt>
                          <dd className="num">{value}</dd>
                        </div>
                      ))}
                    </dl>
                  </div>
                )}
              </Panel>
            ))}
          </div>

          <Panel title={t("memory.agreement")}>
            <div className="p-4 space-y-2">
              <div className="flex items-center gap-2">
                {memory.data.agreement.aligned === true ? (
                  <Pill tone="good">{t("memory.aligned")}</Pill>
                ) : memory.data.agreement.aligned === false ? (
                  <Pill tone="muted">{t("memory.conflict")}</Pill>
                ) : (
                  <Pill tone="muted">—</Pill>
                )}
                <span className="text-xs ink-3 num">
                  {JSON.stringify(memory.data.agreement.trends ?? {})}
                </span>
              </div>
              <p className="text-xs ink-3 leading-relaxed">{t("memory.agreementNote")}</p>
            </div>
          </Panel>
        </>
      )}
    </div>
  );
}
