import { Offline, Panel, Stat } from "@/components/ui";
import { api } from "@/lib/api";
import { getT } from "@/lib/locale";

export const dynamic = "force-dynamic";

/**
 * The limits, published so they can be planned against.
 *
 * A limit nobody can see is a limit nobody can plan against, and one that can
 * be edited in the moment it binds is not a limit at all. The hard table is
 * frozen in code; this page reports it and offers no way to change it.
 *
 * The split between hard and soft is the point. Hard limits are safety and
 * have no override anywhere in the system. Soft limits are policy: they reduce
 * what is permitted rather than refusing it, and they can be tuned per account
 * without touching the floor.
 */
export default async function RiskPage() {
  const { t } = await getT();
  const limits = await api.riskLimits();
  if (!limits.ok) return <Offline error={limits.error} />;

  const { hard, soft, portfolio } = limits.data;

  const pct = (v: number) => `${(v * 100).toFixed(0)}%`;

  return (
    <div className="space-y-6">
      <header className="page-header">
        <div className="min-w-0">
          <h1 className="display">{t("risk.title")}</h1>
          <p className="page-lede">{t("risk.subtitle")}</p>
        </div>
      </header>

      <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
        <Stat
          label={t("risk.maxDrawdown")}
          value={pct(hard.max_total_drawdown_pct)}
          tone="warning"
          hint={t("risk.hardHint")}
        />
        <Stat label={t("risk.maxRiskPerTrade")} value={`${hard.max_risk_per_trade_r} R`} />
        <Stat label={t("risk.maxDailyLoss")} value={`${hard.max_daily_loss_r} R`} />
        <Stat
          label={t("risk.maxDataAge")}
          value={`${hard.max_data_age_bars} ${t("risk.bars")}`}
          hint={t("risk.staleHint")}
        />
      </div>

      <Panel title={t("risk.hard")} subtitle={t("risk.hardSubtitle")}>
        <div className="scroll-x">
          <table className="data">
            <thead>
              <tr>
                <th>{t("risk.limit")}</th>
                <th>{t("risk.value")}</th>
              </tr>
            </thead>
            <tbody>
              {Object.entries(hard).map(([name, value]) => (
                <tr key={name}>
                  <td className="font-semibold num">{name}</td>
                  <td className="num ink-2">{value}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Panel>

      <Panel title={t("risk.soft")} subtitle={t("risk.softSubtitle")}>
        <div className="scroll-x">
          <table className="data">
            <thead>
              <tr>
                <th>{t("risk.limit")}</th>
                <th>{t("risk.value")}</th>
              </tr>
            </thead>
            <tbody>
              {Object.entries(soft).map(([name, value]) => (
                <tr key={name}>
                  <td className="font-semibold num">{name}</td>
                  <td className="num ink-2">{value}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Panel>

      <Panel title={t("risk.portfolio")} subtitle={t("risk.portfolioSubtitle")}>
        <div className="scroll-x">
          <table className="data">
            <thead>
              <tr>
                <th>{t("risk.limit")}</th>
                <th>{t("risk.value")}</th>
              </tr>
            </thead>
            <tbody>
              {Object.entries(portfolio).map(([name, value]) => (
                <tr key={name}>
                  <td className="font-semibold num">{name}</td>
                  <td className="num ink-2">{value}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Panel>

      <Panel title={t("risk.whyFrozen")}>
        <p className="p-4 text-xs ink-3 leading-relaxed">{t("risk.whyFrozenBody")}</p>
      </Panel>
    </div>
  );
}
