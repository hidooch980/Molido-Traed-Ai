import Link from "next/link";

import { InstrumentLinks } from "@/components/InstrumentLinks";
import { Empty, Offline, Panel, Pill } from "@/components/ui";
import { api } from "@/lib/api";
import { getT } from "@/lib/locale";

export const dynamic = "force-dynamic";

/** Percentile bar: a five-point distribution drawn as a range with a median mark. */
function Distribution({
  percentiles,
  format,
}: {
  percentiles: Record<string, number>;
  format: (v: number) => string;
}) {
  const p5 = percentiles.p5;
  const p95 = percentiles.p95;
  const span = p95 - p5 || 1;
  const pos = (v: number) => `${Math.max(0, Math.min(100, ((v - p5) / span) * 100))}%`;

  return (
    <div>
      <div
        className="relative h-2 rounded-full"
        style={{ background: "var(--panel-raised)" }}
      >
        {/* interquartile range */}
        <div
          className="absolute h-full rounded-full"
          style={{
            insetInlineStart: pos(percentiles.p25),
            width: `${((percentiles.p75 - percentiles.p25) / span) * 100}%`,
            background: "var(--series-1)",
            opacity: 0.35,
          }}
        />
        {/* median */}
        <div
          className="absolute w-0.5 h-full"
          style={{ insetInlineStart: pos(percentiles.p50), background: "var(--series-1)" }}
        />
      </div>
      <div className="flex justify-between text-[0.625rem] ink-3 num mt-1">
        <span>{format(p5)}</span>
        <span style={{ color: "var(--ink-2)" }}>{format(percentiles.p50)}</span>
        <span>{format(p95)}</span>
      </div>
    </div>
  );
}

function pct(v: number): string {
  return `${(v * 100).toFixed(3)}%`;
}

function isPercentileBlock(value: unknown): value is Record<string, number> {
  return (
    typeof value === "object" &&
    value !== null &&
    "p50" in (value as Record<string, unknown>)
  );
}

export default async function SymbolDnaPage({
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
      <Panel title={t("dna.title")}>
        <Empty>
          {t("markets.empty")}
        </Empty>
      </Panel>
    );
  }

  const selectedId = params.instrument ?? instruments.data[0].id;
  const selectedSymbol = instruments.data.find((x) => x.id === selectedId)?.symbol;
  const dna = await api.symbolDna(selectedId);

  const byKind = dna.ok
    ? Object.fromEntries(dna.data.profiles.map((p) => [p.kind, p]))
    : {};
  const volatility = byKind.volatility;
  const structure = byKind.structure;
  const session = byKind.session;
  const liquidity = byKind.liquidity;

  return (
    <div className="space-y-6">
      <header className="flex items-end justify-between gap-4 flex-wrap">
        <div>
          <h1 className="display">{t("dna.title")}</h1>
          <p className="page-lede">
{t("dna.subtitle")}
          </p>
        </div>
        {instruments.data.length > 1 && (
          <div className="flex gap-1.5">
            {instruments.data.map((x) => (
              <Link
                key={x.id}
                href={`/symbol-dna?instrument=${x.id}`}
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

      <InstrumentLinks
        instrumentId={selectedId}
        symbol={selectedSymbol}
        current="/symbol-dna"
        t={t}
      />

      {!dna.ok ? (
        <Offline error={dna.error} />
      ) : dna.data.profiles.length === 0 ? (
        <Panel title={t("dna.emptyTitle")}>
          <Empty>
            {t("dna.empty")}
          </Empty>
        </Panel>
      ) : (
        <>
          <div className="grid gap-4 lg:grid-cols-2">
            {volatility && (
              <Panel
                title={t("dna.volatility")}
                subtitle={`${volatility.sample_size.toLocaleString()} ${t("common.bars")}`}
              >
                <div className="p-4 space-y-4">
                  {Object.entries(volatility.data).map(([key, value]) =>
                    isPercentileBlock(value) ? (
                      <div key={key}>
                        <div className="eyebrow mb-1.5">{key.replace(/_/g, " ")}</div>
                        <Distribution percentiles={value} format={pct} />
                      </div>
                    ) : null,
                  )}
                  <div className="text-xs ink-3">
                    {t("dna.distributionNote")}
                  </div>
                </div>
              </Panel>
            )}

            {structure && (
              <Panel
                title={t("dna.structure")}
                subtitle={`${structure.sample_size.toLocaleString()} ${t("common.bars")}`}
              >
                <div className="p-4 space-y-3">
                  <div className="flex items-center gap-3">
                    <span className="eyebrow">{t("dna.tendency")}</span>
                    <Pill tone={structure.data.tendency === "persistent" ? "good" : "muted"}>
                      {String(structure.data.tendency ?? "unknown")}
                    </Pill>
                    <span className="text-xs ink-3 num">
                      {t("dna.autocorr")}{" "}
                      {typeof structure.data.return_autocorrelation_lag1 === "number"
                        ? structure.data.return_autocorrelation_lag1.toFixed(4)
                        : "—"}
                    </span>
                  </div>
                  <div className="flex items-center gap-3">
                    <span className="eyebrow">{t("dna.upBars")}</span>
                    <span className="num text-sm">
                      {typeof structure.data.up_bar_share === "number"
                        ? `${(structure.data.up_bar_share * 100).toFixed(1)}%`
                        : "—"}
                    </span>
                  </div>
                  {isPercentileBlock(structure.data.body_ratio) && (
                    <div>
                      <div className="eyebrow mb-1.5">{t("dna.body")}</div>
                      <Distribution
                        percentiles={structure.data.body_ratio}
                        format={(v) => v.toFixed(2)}
                      />
                    </div>
                  )}
                  <p className="text-xs ink-3">
                    {t("dna.measureNote")}
                  </p>
                </div>
              </Panel>
            )}
          </div>

          <div className="grid gap-4 lg:grid-cols-2">
            {session && (
              <Panel
                title={t("dna.sessionActivity")}
                subtitle={t("dna.sessionNote")}
              >
                <div className="scroll-x">
                  <table className="data">
                    <thead>
                      <tr>
                        <th>{t("markets.session")}</th>
                        <th>{t("common.bars")}</th>
                        <th>{t("dna.share")}</th>
                        <th>{t("dna.meanRange")}</th>
                      </tr>
                    </thead>
                    <tbody>
                      {Object.entries(session.data)
                        .filter(([, v]) => typeof v === "object" && v !== null)
                        .map(([name, raw]) => {
                          const entry = raw as Record<string, number>;
                          const busiest = session.data.busiest_session === name;
                          return (
                            <tr key={name}>
                              <td className="font-medium">
                                {t(`session.${name}`)}
                                {busiest && (
                                  <span
                                    className="ms-2 text-[0.625rem]"
                                    style={{ color: "var(--accent)" }}
                                  >
                                    {t("dna.busiest")}
                                  </span>
                                )}
                              </td>
                              <td className="num">{entry.bars}</td>
                              <td className="num ink-2">
                                {(entry.share_of_bars * 100).toFixed(1)}%
                              </td>
                              <td className="num">{pct(entry.mean_range_pct)}</td>
                            </tr>
                          );
                        })}
                    </tbody>
                  </table>
                </div>
              </Panel>
            )}

            {liquidity && (
              <Panel title={t("dna.liquidity")} subtitle={t("dna.liquiditySubtitle")}>
                <div className="p-4 space-y-3">
                  {Object.entries(liquidity.data).map(([name, raw]) => {
                    const entry = raw as Record<string, unknown>;
                    return (
                      <div key={name}>
                        <div className="flex items-center gap-2">
                          <span className="eyebrow">{name}</span>
                          {entry.available ? (
                            <Pill tone="good">{t("dna.available")}</Pill>
                          ) : (
                            <Pill tone="muted">{t("dna.notReported")}</Pill>
                          )}
                        </div>
                        {entry.available ? (
                          isPercentileBlock(entry.percentiles) && (
                            <div className="mt-1.5">
                              <Distribution
                                percentiles={entry.percentiles}
                                format={(v) => v.toFixed(2)}
                              />
                            </div>
                          )
                        ) : (
                          <div className="text-xs ink-3 mt-0.5">{String(entry.reason)}</div>
                        )}
                      </div>
                    );
                  })}
                </div>
              </Panel>
            )}
          </div>

          <Panel
            title={t("dna.notComputed")}
            subtitle={t("dna.notComputedSubtitle")}
          >
            <ul className="p-4 space-y-1.5 text-xs">
              {Object.entries(dna.data.unavailable).map(([facet, reason]) => (
                <li key={facet} className="flex gap-2.5">
                  <span className="ink-3" aria-hidden="true">
                    ○
                  </span>
                  <span>
                    <strong className="font-semibold">{facet.replace(/_/g, " ")}</strong>
                    <span className="ink-3"> — {reason}</span>
                  </span>
                </li>
              ))}
            </ul>
            <p className="px-4 pb-4 text-xs ink-3">
              {t("dna.notComputedBody")}
            </p>
          </Panel>
        </>
      )}
    </div>
  );
}
