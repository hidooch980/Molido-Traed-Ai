import Link from "next/link";

import { Empty, Offline, Panel, Pill } from "@/components/ui";
import { api } from "@/lib/api";
import { getT } from "@/lib/locale";

export const dynamic = "force-dynamic";

/**
 * Every instrument this platform watches.
 *
 * **All of them, which it did not used to be.** Session status was fetched one
 * instrument at a time, so each row cost an HTTP round trip and the page
 * defended itself by rendering only the first twenty-five. The API sorts
 * alphabetically, so that cap quietly hid everything from NZDCHF onward - the
 * metals, the energy contracts, the index futures, most of the crypto. The
 * count in the panel header said "25 / 43" and was perfectly honest, and
 * somebody looking for gold on a page called markets still could not find it.
 *
 * The cap is gone because its reason is: one batch call now answers for the
 * whole universe. That also fixes something subtler than the missing rows -
 * forty-three separate calls each evaluated `now` at a slightly different
 * instant, so two markets either side of an open could disagree about what
 * time it was.
 */
export default async function MarketsPage() {
  const { t } = await getT();
  const [result, statuses] = await Promise.all([
    api.instruments(),
    api.allSessionStatus(),
  ]);
  if (!result.ok) return <Offline error={result.error} />;

  // Keyed by instrument, because the two lists are sorted the same way today
  // and matching them by position would be a silent mismatch the day either
  // one changes its ordering or drops an inactive row.
  const byInstrument = new Map(
    statuses.ok ? statuses.data.map((s) => [s.instrument_id, s]) : [],
  );
  const shown = result.data;

  return (
    <div className="space-y-6">
      <header className="page-header">
        <div className="min-w-0">
          <h1 className="display">{t("markets.title")}</h1>
          <p className="page-lede">{t("markets.subtitle")}</p>
        </div>
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
                {shown.map((instrument) => {
                  const status = byInstrument.get(instrument.id);
                  return (
                    <tr key={instrument.id}>
                      <td className="font-semibold">{instrument.symbol}</td>
                      <td className="ink-2">{instrument.name}</td>
                      <td className="ink-3">{t(`asset.${instrument.asset_class}`)}</td>
                      <td className="ink-3">{instrument.quote_currency ?? "—"}</td>
                      <td className="ink-3">{status ? status.market_code : "—"}</td>
                      <td>
                        {status ? (
                          <Pill tone={status.is_open ? "good" : "muted"}>
                            <span
                              className="dot"
                              style={{
                                background: status.is_open
                                  ? "var(--good)"
                                  : "var(--ink-3)",
                              }}
                            />
                            {status.is_open ? t("common.open") : t("common.closed")}
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
