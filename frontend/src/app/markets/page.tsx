import Link from "next/link";

import { Empty, Offline, Panel, Pill } from "@/components/ui";
import { api, type Instrument, type SessionStatus } from "@/lib/api";
import { getT } from "@/lib/locale";

export const dynamic = "force-dynamic";

/**
 * Every instrument this platform watches, grouped the way a terminal groups
 * them.
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
 *
 * **Grouped rather than listed, because forty-three alphabetical rows is a
 * list you scan and a set of categories is a place you look.** MetaTrader
 * organises the same universe as Forex, Metals, Indexes and so on, and
 * somebody arriving from that terminal is already carrying that map. Gold sits
 * under metals in both.
 *
 * The order below is fixed rather than by size. A layout that reshuffles when
 * an instrument is added is one nobody can build a habit on, and the whole
 * value of a category is knowing where to look before you look.
 */

/** Categories in reading order. Anything not named here follows, by name. */
const GROUP_ORDER = [
  "forex",
  "metal",
  "index",
  "commodity",
  "crypto",
  "stock",
  "future",
  "bond",
  // Last deliberately, and visible rather than hidden: `other` means the
  // classifier did not recognise the symbol, which is a thing an operator
  // should see rather than a bucket to sweep into.
  "other",
];

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
  const byInstrument = new Map<string, SessionStatus>(
    statuses.ok ? statuses.data.map((s) => [s.instrument_id, s]) : [],
  );

  const groups = new Map<string, Instrument[]>();
  for (const instrument of result.data) {
    const key = instrument.asset_class;
    const bucket = groups.get(key);
    if (bucket) bucket.push(instrument);
    else groups.set(key, [instrument]);
  }

  // Named groups first in their fixed order, then anything the enum grew
  // since this list was written - a new asset class must appear somewhere
  // rather than vanish because nobody updated an array.
  const ordered = [
    ...GROUP_ORDER.filter((key) => groups.has(key)),
    ...[...groups.keys()].filter((key) => !GROUP_ORDER.includes(key)).sort(),
  ];

  const openCount = result.data.filter(
    (i) => byInstrument.get(i.id)?.is_open,
  ).length;

  return (
    <div className="space-y-6">
      <header className="page-header">
        <div className="min-w-0">
          <h1 className="display">{t("markets.title")}</h1>
          <p className="page-lede">{t("markets.subtitle")}</p>
        </div>
      </header>

      {result.data.length === 0 ? (
        <Panel title={t("markets.universe")}>
          <Empty>{t("markets.empty")}</Empty>
        </Panel>
      ) : (
        ordered.map((key) => {
          const rows = groups.get(key) ?? [];
          const open = rows.filter((i) => byInstrument.get(i.id)?.is_open).length;
          return (
            <Panel
              key={key}
              title={t(`asset.${key}`)}
              // Open over total, per group. A metals section reading "0 / 3"
              // on a Sunday is the answer to a question somebody would
              // otherwise ask by clicking into three pages.
              subtitle={`${open} / ${rows.length} ${t("common.open")}`}
            >
              <div className="scroll-x">
                <table className="data">
                  <thead>
                    <tr>
                      <th>{t("markets.symbol")}</th>
                      <th>{t("markets.name")}</th>
                      <th>{t("markets.quote")}</th>
                      <th>{t("markets.marketCode")}</th>
                      <th>{t("markets.session")}</th>
                      <th />
                    </tr>
                  </thead>
                  <tbody>
                    {rows.map((instrument) => {
                      const status = byInstrument.get(instrument.id);
                      return (
                        <tr key={instrument.id}>
                          <td className="font-semibold" dir="ltr">
                            {instrument.symbol}
                          </td>
                          <td className="ink-2">{instrument.name}</td>
                          <td className="ink-3" dir="ltr">
                            {instrument.quote_currency ?? "—"}
                          </td>
                          <td className="ink-3" dir="ltr">
                            {status ? status.market_code : "—"}
                          </td>
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
                                {status.is_open
                                  ? t("common.open")
                                  : t("common.closed")}
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
            </Panel>
          );
        })
      )}

      <p className="text-xs ink-3">
        {t("markets.total")
          .replace("{n}", String(result.data.length))
          .replace("{open}", String(openCount))
          .replace("{groups}", String(ordered.length))}
      </p>
    </div>
  );
}
