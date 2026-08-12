import Link from "next/link";

import { Empty, Offline, Panel, Pill } from "@/components/ui";
import { api } from "@/lib/api";
import { getT } from "@/lib/locale";

export const dynamic = "force-dynamic";

// Rows rendered per page. Kept small because each row costs one session call.
const PAGE_SIZE = 25;

export default async function MarketsPage() {
  const { t } = await getT();
  const result = await api.instruments();
  if (!result.ok) return <Offline error={result.error} />;

  // Session status is fetched only for the rows actually shown. With 50+
  // instruments the previous "one request per row" version issued 50 API calls
  // per page load; the market's open/closed state is not worth that.
  const shown = result.data.slice(0, PAGE_SIZE);
  const sessions = await Promise.all(
    shown.map((instrument) => api.sessionStatus(instrument.id)),
  );

  return (
    <div className="space-y-4">
      <header>
        <h1 className="text-xl font-bold">{t("markets.title")}</h1>
        <p className="text-xs ink-3 mt-0.5">
          {t("markets.subtitle")}
        </p>
      </header>

      <Panel title={t("markets.universe")} subtitle={`${shown.length} / ${result.data.length}`}>
        {result.data.length === 0 ? (
          <Empty>
            {t("markets.empty")}
          </Empty>
        ) : (
          <div className="scroll-x">
            <table className="data">
              <thead>
                <tr>
                  <th>{t("markets.symbol")}</th>
                  <th>{t("markets.name")}</th>
                  <th>{t("markets.class")}</th>
                  <th>{t("markets.quote")}</th>
                  <th>{t("markets.marketCode")}</th>
                  <th>{t("markets.session")}</th>
                  <th />
                </tr>
              </thead>
              <tbody>
                {shown.map((instrument, i) => {
                  const status = sessions[i];
                  return (
                    <tr key={instrument.id}>
                      <td className="font-semibold">{instrument.symbol}</td>
                      <td className="ink-2">{instrument.name}</td>
                      <td className="ink-3">{t(`asset.${instrument.asset_class}`)}</td>
                      <td className="ink-3">{instrument.quote_currency ?? "—"}</td>
                      <td className="ink-3">{status?.ok ? status.data.market_code : "—"}</td>
                      <td>
                        {status?.ok ? (
                          <Pill tone={status.data.is_open ? "good" : "muted"}>
                            <span
                              className="dot"
                              style={{
                                background: status.data.is_open
                                  ? "var(--good)"
                                  : "var(--ink-3)",
                              }}
                            />
                            {status.data.is_open ? t("common.open") : t("common.closed")}
                          </Pill>
                        ) : (
                          <span className="ink-3 text-xs">—</span>
                        )}
                      </td>
                      <td>
                        <Link
                          href={`/markets/${instrument.id}`}
                          className="text-xs"
                          style={{ color: "var(--accent)" }}
                        >
                          {t("common.detail")} ←
                        </Link>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
      </Panel>
    </div>
  );
}
