import { Empty, Offline, Panel, Sparkline, Stat } from "@/components/ui";
import { api } from "@/lib/api";
import { getT } from "@/lib/locale";

export const dynamic = "force-dynamic";

/**
 * The two things a chart cannot contain.
 *
 * Every other page here draws something computed from price. These two are
 * facts about the world instead: what a central bank charges for money, and
 * where the large speculators have actually put theirs. Neither can be
 * recovered from a candle no matter how it is transformed, which is the only
 * reason this page exists as its own thing rather than as a panel on another.
 *
 * **Two different freshness stories, told separately and on purpose.** The
 * rate table is live and has no history - the upstream feed carries only the
 * newest observation per bank. The positioning table is a weekly report with a
 * three day publication lag, so its newest row is up to a week old *by design*
 * and both of its dates are shown. Presenting them as one "fundamentals" block
 * would hide that difference, and the difference is the part somebody needs in
 * order to know what they are looking at.
 *
 * **Neither table is advice.** A positive differential means a position is
 * paid to hold, not that it will rise; a crowded book means many people
 * already own the trade, not that it is about to turn. Carry unwinds
 * violently and crowded trades stay crowded for years. The page reports the
 * measurements and stops, which is the same thing the decision pages do with a
 * proposal.
 */
export default async function FundamentalsPage() {
  const { t } = await getT();

  // The euro contract is the deepest currency book at the CME, so it is the
  // one that demonstrates the shape of the data rather than a thin edge case.
  const [rates, euro] = await Promise.all([
    api.policyRates(),
    api.positioning("EUR"),
  ]);

  if (!rates.ok && !euro.ok) return <Offline error={rates.error} />;

  const rateData = rates.ok ? rates.data : null;
  const euroData = euro.ok ? euro.data : null;
  const latest = euroData?.available ? euroData.latest : undefined;

  const pct = (v: number) => `${v >= 0 ? "+" : ""}${v.toFixed(3)}%`;
  const count = (v: number) => v.toLocaleString();

  return (
    <div className="space-y-6">
      <header className="page-header">
        <div className="min-w-0">
          <h1 className="display">{t("fundamentals.title")}</h1>
          <p className="page-lede">{t("fundamentals.subtitle")}</p>
        </div>
      </header>

      {/* Headline numbers, and the two that matter most are a rate gap and a
          crowd. Both are stated with their unit, because a bare "3.35" beside
          a bare "-59,088" invites reading them as the same kind of thing. */}
      <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
        <Stat
          label={t("fundamentals.banks")}
          value={rateData?.available ? String(rateData.rates.length) : "—"}
          tone={rateData?.available ? "neutral" : "warning"}
          hint={t("fundamentals.banksHint")}
        />
        <Stat
          label={t("fundamentals.highest")}
          value={
            rateData?.available && rateData.rates.length > 0
              ? `${rateData.rates[0].rate}%`
              : "—"
          }
          hint={rateData?.rates?.[0]?.bank ?? t("fundamentals.unavailable")}
        />
        <Stat
          label={t("fundamentals.lowest")}
          value={
            rateData?.available && rateData.rates.length > 0
              ? `${rateData.rates[rateData.rates.length - 1].rate}%`
              : "—"
          }
          hint={
            rateData?.rates?.[rateData.rates.length - 1]?.bank ??
            t("fundamentals.unavailable")
          }
        />
        <Stat
          label={t("fundamentals.euroCrowd")}
          value={latest ? pct((euroData?.net_share ?? 0) * 100) : "—"}
          tone={latest ? (latest.net >= 0 ? "good" : "warning") : "warning"}
          hint={t("fundamentals.euroCrowdHint")}
        />
      </div>

      <Panel
        title={t("fundamentals.differentials")}
        subtitle={t("fundamentals.differentialsSubtitle")}
      >
        {/* Refused and empty are different answers, and this is the panel
            where confusing them costs the most: a table of zeros reads as a
            world with no interest rates in it. */}
        {!rateData?.available ? (
          <Empty>{rateData?.reason ?? t("fundamentals.unavailable")}</Empty>
        ) : rateData.differentials.length === 0 ? (
          <Empty>{t("fundamentals.noDifferentials")}</Empty>
        ) : (
          <div className="scroll-x">
            <table className="data">
              <thead>
                <tr>
                  <th>{t("fundamentals.pair")}</th>
                  <th className="num">{t("fundamentals.carry")}</th>
                  <th>{t("fundamentals.meaning")}</th>
                </tr>
              </thead>
              <tbody>
                {rateData.differentials.map((d) => (
                  <tr key={d.pair}>
                    <td dir="ltr">{d.pair}</td>
                    <td
                      className="num"
                      dir="ltr"
                      style={{
                        color:
                          d.differential >= 0 ? "var(--good)" : "var(--critical)",
                      }}
                    >
                      {pct(d.differential)}
                    </td>
                    <td className="ink-3">
                      {d.differential >= 0
                        ? t("fundamentals.paidToHold").replace("{base}", d.base)
                        : t("fundamentals.costsToHold").replace("{base}", d.base)}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Panel>

      <Panel
        title={t("fundamentals.rates")}
        subtitle={rateData?.note ?? t("fundamentals.ratesSubtitle")}
      >
        {!rateData?.available ? (
          <Empty>{rateData?.reason ?? t("fundamentals.unavailable")}</Empty>
        ) : (
          <div className="scroll-x">
            <table className="data">
              <thead>
                <tr>
                  <th>{t("fundamentals.currency")}</th>
                  <th>{t("fundamentals.bank")}</th>
                  <th className="num">{t("fundamentals.rate")}</th>
                  <th className="num">{t("fundamentals.observed")}</th>
                </tr>
              </thead>
              <tbody>
                {rateData.rates.map((r) => (
                  <tr key={r.currency}>
                    <td dir="ltr">{r.currency}</td>
                    <td className="ink-2">{r.bank}</td>
                    <td className="num" dir="ltr">
                      {r.rate}%
                    </td>
                    <td className="num ink-3" dir="ltr">
                      {r.observed}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Panel>

      <Panel
        title={t("fundamentals.positioning")}
        subtitle={euroData?.note ?? t("fundamentals.positioningSubtitle")}
      >
        {!euroData?.available || !latest ? (
          <Empty>{euroData?.reason ?? t("fundamentals.unavailable")}</Empty>
        ) : (
          <div className="space-y-4">
            {/* Both dates, side by side. The gap between them is the reason
                nothing on this page can be read as "now", and hiding either
                one would make the other look like the whole truth. */}
            <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
              <Stat
                label={t("fundamentals.heldOn")}
                value={latest.report_date}
                hint={t("fundamentals.heldOnHint")}
              />
              <Stat
                label={t("fundamentals.publishedAt")}
                value={latest.published_at.slice(0, 10)}
                hint={t("fundamentals.publishedAtHint")}
              />
              <Stat
                label={t("fundamentals.longSide")}
                value={count(latest.long)}
                tone="good"
                hint={t("fundamentals.institutions").replace(
                  "{n}",
                  String(latest.traders_long),
                )}
              />
              <Stat
                label={t("fundamentals.shortSide")}
                value={count(latest.short)}
                tone="warning"
                hint={t("fundamentals.institutions").replace(
                  "{n}",
                  String(latest.traders_short),
                )}
              />
            </div>

            {euroData.history && euroData.history.length > 1 && (
              <div className="flex items-center gap-4">
                <Sparkline
                  // Oldest to newest: the feed hands them back newest first,
                  // and a reversed series draws the crowd unwinding a position
                  // it was in fact building.
                  values={[...euroData.history]
                    .reverse()
                    .map((p) => p.net / (p.open_interest || 1))}
                />
                <span className="text-xs ink-3">
                  {t("fundamentals.weeks").replace(
                    "{n}",
                    String(euroData.history.length),
                  )}
                </span>
              </div>
            )}

            <p className="text-xs ink-3">
              {t("fundamentals.contract")}: <span dir="ltr">{latest.contract}</span>
            </p>
          </div>
        )}
      </Panel>

      <p className="text-xs ink-3">{t("fundamentals.disclaimer")}</p>
    </div>
  );
}
