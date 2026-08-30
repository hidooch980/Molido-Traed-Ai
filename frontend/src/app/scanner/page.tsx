import Link from "next/link";

import { Empty, Offline, Panel, StatusBadge } from "@/components/ui";
import { api } from "@/lib/api";
import { getT } from "@/lib/locale";

export const dynamic = "force-dynamic";

/**
 * Every instrument's measured state, side by side. Deliberately unranked.
 *
 * A scanner sorted by conviction would lead with the one number this system
 * has measured to carry almost no information: over 718 resolved setups, high
 * conviction hit 30.5% and low conviction 27.4%, a difference of z = 0.70.
 * Sorting by it would dress that noise as a recommendation.
 *
 * So the rows are alphabetical and the columns are facts — how old the feed
 * is, what the structure profile measured, which profiles exist at all. What
 * to do about any of it is the chain's job, and the chain has its own page.
 */
export default async function ScannerPage() {
  const { t } = await getT();
  const scan = await api.scanner(60);
  if (!scan.ok) return <Offline error={scan.error} />;

  const { instruments, without_profiles } = scan.data;

  const ageLabel = (seconds: number | null) => {
    if (seconds === null) return t("scanner.unknown");
    const minutes = seconds / 60;
    return minutes < 90 ? `${minutes.toFixed(0)}m` : `${(minutes / 60).toFixed(1)}h`;
  };

  return (
    <div className="space-y-6">
      <header className="page-header">
        <div className="min-w-0">
          <h1 className="display">{t("scanner.title")}</h1>
          <p className="page-lede">{t("scanner.subtitle")}</p>
        </div>
      </header>

      <Panel
        title={t("scanner.instruments")}
        subtitle={`${instruments.length} · ${without_profiles.length} ${t(
          "scanner.withoutProfiles",
        )}`}
      >
        {instruments.length === 0 ? (
          <Empty>{t("markets.empty")}</Empty>
        ) : (
          <div className="scroll-x">
            <table className="data">
              <thead>
                <tr>
                  <th>{t("scanner.symbol")}</th>
                  <th>{t("scanner.assetClass")}</th>
                  <th>{t("scanner.feedAge")}</th>
                  <th>{t("scanner.tendency")}</th>
                  <th>{t("scanner.autocorrelation")}</th>
                  <th>{t("scanner.profiles")}</th>
                </tr>
              </thead>
              <tbody>
                {instruments.map((row) => (
                  <tr key={row.instrument_id}>
                    <td className="font-semibold num">
                      <Link href={`/brain?instrument=${row.instrument_id}`}>{row.symbol}</Link>
                    </td>
                    <td className="ink-3">{row.asset_class}</td>
                    <td className="num">
                      <StatusBadge
                        status={
                          row.data_age_seconds === null
                            ? "warning"
                            : row.data_age_seconds < 5400
                              ? "good"
                              : "warning"
                        }
                        label={ageLabel(row.data_age_seconds)}
                      />
                    </td>
                    <td className="ink-2">{row.tendency ?? "—"}</td>
                    <td className="num ink-3">
                      {row.autocorrelation !== null ? row.autocorrelation.toFixed(4) : "—"}
                    </td>
                    <td className="ink-3">
                      {row.profiles_available.length > 0
                        ? row.profiles_available.join(", ")
                        : t("scanner.none")}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Panel>

      <Panel title={t("scanner.whyUnranked")}>
        <p className="p-4 text-xs ink-3 leading-relaxed">{t("scanner.whyUnrankedBody")}</p>
      </Panel>
    </div>
  );
}
