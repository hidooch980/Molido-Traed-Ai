import { InstrumentLinks } from "@/components/InstrumentLinks";
import PriceChart from "@/components/PriceChart";
import { Empty, Offline, Panel } from "@/components/ui";
import { api } from "@/lib/api";
import { getT } from "@/lib/locale";

export const dynamic = "force-dynamic";

/**
 * The chart, point-in-time like everything else.
 *
 * The bars come from the same `/bars` endpoint every other consumer reads, so
 * the last candle shown is the last candle that had *closed and been ingested*
 * at request time — not the forming one. A chart that draws the forming candle
 * redraws history on every refresh, and a chart that redraws history teaches
 * its reader that history moves.
 */
export default async function ChartsPage({
  searchParams,
}: {
  searchParams: Promise<{ instrument?: string; timeframe?: string }>;
}) {
  const { t } = await getT();
  const params = await searchParams;
  const instruments = await api.instruments();
  if (!instruments.ok) return <Offline error={instruments.error} />;
  if (instruments.data.length === 0) {
    return (
      <Panel title={t("charts.title")}>
        <Empty>{t("markets.empty")}</Empty>
      </Panel>
    );
  }

  const selectedId = params.instrument ?? instruments.data[0].id;
  const selected = instruments.data.find((x) => x.id === selectedId);
  const timeframe = params.timeframe === "M15" ? "M15" : "H1";
  const bars = await api.bars(selectedId, timeframe, 500);

  return (
    <div className="space-y-4">
      <header className="flex items-end justify-between gap-4 flex-wrap">
        <div>
          <h1 className="text-xl font-bold">{t("charts.title")}</h1>
          <p className="text-xs ink-3 mt-0.5">{t("charts.subtitle")}</p>
        </div>
        <div className="flex flex-wrap gap-1.5">
          {instruments.data.slice(0, 12).map((x) => (
            <a
              key={x.id}
              href={`/charts?instrument=${x.id}&timeframe=${timeframe}`}
              className="pill"
              style={{
                color: x.id === selectedId ? "var(--accent)" : "var(--ink-3)",
                borderColor: x.id === selectedId ? "var(--accent)" : "var(--border-strong)",
              }}
            >
              {x.symbol}
            </a>
          ))}
        </div>
      </header>

      <InstrumentLinks
        instrumentId={selectedId}
        symbol={selected?.symbol}
        current="/charts"
        t={t}
      />

      {!bars.ok ? (
        <Offline error={bars.error} />
      ) : bars.data.bars.length < 2 ? (
        <Panel title={selected?.symbol ?? ""}>
          <Empty>{t("charts.tooFewBars")}</Empty>
        </Panel>
      ) : (
        <Panel
          title={`${selected?.symbol ?? ""} · ${timeframe}`}
          subtitle={`${bars.data.bars.length} ${t("charts.closedBars")} · ${t(
            "charts.lastClosed",
          )} ${bars.data.bars[bars.data.bars.length - 1].event_time}`}
        >
          <div className="p-3">
            <PriceChart
              points={bars.data.bars.map((b) => ({ t: b.event_time, c: b.close }))}
              height={340}
            />
          </div>
          <div className="px-4 pb-3 flex gap-1.5">
            {(["H1", "M15"] as const).map((tf) => (
              <a
                key={tf}
                href={`/charts?instrument=${selectedId}&timeframe=${tf}`}
                className="pill"
                style={{
                  color: tf === timeframe ? "var(--accent)" : "var(--ink-3)",
                  borderColor: tf === timeframe ? "var(--accent)" : "var(--border-strong)",
                }}
              >
                {tf}
              </a>
            ))}
          </div>
          <p className="px-4 pb-4 text-xs ink-3 leading-relaxed">
            {t("charts.pitNote")}
          </p>
        </Panel>
      )}
    </div>
  );
}
