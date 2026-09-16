import TradeChart, { type ChartPosition } from "@/components/TradeChart";
import { TradingViewSettings } from "@/components/TradingViewSettings";
import { Empty, Offline, Panel, Stat } from "@/components/ui";
import { api } from "@/lib/api";
import { getT } from "@/lib/locale";

export const dynamic = "force-dynamic";

/**
 * TradingView, both directions it can go without a broker partnership:
 * a TradingView chart with the bot's open positions drawn on it, and a
 * webhook that records TradingView alerts. Alerts never place an order.
 */
export default async function TradingViewPage({
  searchParams,
}: {
  searchParams: Promise<{ instrument?: string; timeframe?: string }>;
}) {
  const { t } = await getT();
  const params = await searchParams;
  const [instruments, state, book] = await Promise.all([
    api.instruments(),
    api.tradingview(),
    api.positions(),
  ]);
  if (!instruments.ok) return <Offline error={instruments.error} />;
  if (!state.ok) return <Offline error={state.error} />;

  const selectedId = params.instrument ?? instruments.data[0]?.id;
  const selected = instruments.data.find((x) => x.id === selectedId);
  const timeframe = params.timeframe === "M15" ? "M15" : "H1";
  const bars = selectedId ? await api.bars(selectedId, timeframe, 500) : null;

  const open = book.ok ? book.data.positions : [];
  const heldSymbols = new Set(open.map((p) => String(p.symbol)));
  const positions: ChartPosition[] = open
    .filter((p) => String(p.symbol) === selected?.symbol)
    .map((p) => ({
      side: String(p.side),
      price_open: Number(p.price_open),
      stop: p.stop == null ? null : Number(p.stop),
      target: p.target == null ? null : Number(p.target),
      volume: Number(p.volume),
      label: String(p.terminal ?? ""),
    }));

  const data = state.data;

  return (
    <div className="space-y-6">
      <header className="page-header">
        <div className="min-w-0">
          <h1 className="display">{t("tradingview.title")}</h1>
          <p className="page-lede">{t("tradingview.subtitle")}</p>
        </div>
      </header>

      <div className="flex flex-wrap gap-1.5">
        {instruments.data.map((x) => (
          <a
            key={x.id}
            href={`/tradingview?instrument=${x.id}&timeframe=${timeframe}`}
            className="pill"
            style={{
              color: x.id === selectedId ? "var(--accent)" : "var(--ink-3)",
              borderColor: x.id === selectedId ? "var(--accent)" : "var(--border-strong)",
              fontWeight: heldSymbols.has(x.symbol) ? 700 : undefined,
            }}
          >
            {x.symbol}
            {heldSymbols.has(x.symbol) ? " •" : ""}
          </a>
        ))}
      </div>

      {!bars ? (
        <Panel title={t("tradingview.chart")}>
          <Empty>{t("markets.empty")}</Empty>
        </Panel>
      ) : !bars.ok ? (
        <Offline error={bars.error} />
      ) : bars.data.bars.length < 2 ? (
        <Panel title={selected?.symbol ?? ""}>
          <Empty>{t("charts.tooFewBars")}</Empty>
        </Panel>
      ) : (
        <Panel
          title={`${selected?.symbol ?? ""} · ${timeframe}`}
          subtitle={`${positions.length} ${t("tradingview.openHere")}${
            book.ok ? "" : ` · ${t("tradingview.positionsUnavailable")}`
          }`}
          actions={
            <div className="flex gap-1.5">
              {(["H1", "M15"] as const).map((tf) => (
                <a
                  key={tf}
                  href={`/tradingview?instrument=${selectedId}&timeframe=${tf}`}
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
          }
        >
          <div className="p-3">
            <TradeChart
              candles={bars.data.bars.map((b) => ({
                t: b.event_time,
                o: b.open,
                h: b.high,
                l: b.low,
                c: b.close,
              }))}
              positions={positions}
              labels={{
                entry: t("tradingview.entry"),
                stop: t("tradingview.stop"),
                target: t("tradingview.target"),
              }}
            />
          </div>
          <p className="px-4 pb-4 text-xs ink-3 leading-relaxed">{t("tradingview.chartNote")}</p>
        </Panel>
      )}

      <div className="grid gap-3 sm:grid-cols-3">
        <Stat
          label={t("tradingview.webhook")}
          value={data.configured ? t("tradingview.ready") : t("tradingview.notReady")}
          tone={data.configured ? "good" : "warning"}
        />
        <Stat label={t("tradingview.received")} value={String(data.total)} />
        <Stat label={t("tradingview.tradesFromAlerts")} value={t("tradingview.never")} />
      </div>

      <Panel title={t("tradingview.connect")} subtitle={t("tradingview.connectHint")}>
        <TradingViewSettings
          configured={data.configured}
          hint={data.secret_hint}
          path={data.webhook_path}
          labels={{
            webhookUrl: t("tradingview.webhookUrl"),
            secret: t("tradingview.secret"),
            noSecret: t("tradingview.noSecret"),
            activeSecret: t("tradingview.activeSecret"),
            make: t("tradingview.make"),
            remake: t("tradingview.remake"),
            making: t("tradingview.making"),
            shownOnce: t("tradingview.shownOnce"),
            message: t("tradingview.message"),
            messageHint: t("tradingview.messageHint"),
            signInFirst: t("tradingview.signInFirst"),
            failed: t("tradingview.failed"),
          }}
        />
      </Panel>

      <Panel title={t("tradingview.alerts")}>
        {data.alerts.length === 0 ? (
          <Empty>{t("tradingview.noAlerts")}</Empty>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="ink-3 text-xs">
                  <th className="text-start p-2">{t("tradingview.time")}</th>
                  <th className="text-start p-2">{t("tradingview.symbol")}</th>
                  <th className="text-start p-2">{t("tradingview.action")}</th>
                  <th className="text-start p-2">{t("tradingview.price")}</th>
                  <th className="text-start p-2">{t("tradingview.timeframe")}</th>
                  <th className="text-start p-2">{t("tradingview.text")}</th>
                </tr>
              </thead>
              <tbody>
                {data.alerts.map((a) => (
                  <tr key={a.id} className="border-t" style={{ borderColor: "var(--border)" }}>
                    <td className="p-2 tabular-nums" dir="ltr">
                      {a.received_at?.replace("T", " ").slice(0, 16)}
                    </td>
                    <td className="p-2" dir="ltr">{a.symbol || "—"}</td>
                    <td className="p-2">{a.action || "—"}</td>
                    <td className="p-2 tabular-nums" dir="ltr">{a.price ?? "—"}</td>
                    <td className="p-2" dir="ltr">{a.timeframe || "—"}</td>
                    <td className="p-2">{a.message}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Panel>
    </div>
  );
}
