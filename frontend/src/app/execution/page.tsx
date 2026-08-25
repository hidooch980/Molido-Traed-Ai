import { Empty, Offline, Panel, Stat, StatusBadge } from "@/components/ui";
import { api } from "@/lib/api";
import { getT } from "@/lib/locale";

export const dynamic = "force-dynamic";

/**
 * The execution posture, read from the running process rather than from a doc.
 *
 * Everything on this page is a refusal, and that is the honest picture: the
 * kill switch defaults engaged, the only broker is a simulator, no account is
 * registered, and no route in this API can place an order. A page that
 * rendered a green "ready to trade" badge over that would be the single most
 * expensive lie the interface could tell.
 *
 * The two booleans at the bottom are the ones worth reading twice. They are
 * not settings — they are properties the execution gate re-derives from the
 * live router table at import, and the app refuses to boot if either becomes
 * false without a permission dependency behind it.
 */
export default async function ExecutionPage() {
  const { t } = await getT();
  const [policy, accounts] = await Promise.all([api.executionPolicy(), api.accounts()]);
  if (!policy.ok) return <Offline error={policy.error} />;

  const p = policy.data;

  return (
    <div className="space-y-6">
      <header className="page-header">
        <div className="min-w-0">
          <h1 className="display">{t("execution.title")}</h1>
          <p className="page-lede">{t("execution.subtitle")}</p>
        </div>
      </header>

      <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
        <Stat
          label={t("execution.enabled")}
          value={p.execution_enabled ? t("execution.on") : t("execution.off")}
          tone={p.execution_enabled ? "warning" : "good"}
          hint={t("execution.enabledHint")}
        />
        <Stat
          label={t("execution.killSwitch")}
          value={
            p.kill_switch_default_engaged ? t("execution.engaged") : t("execution.disengaged")
          }
          tone={p.kill_switch_default_engaged ? "good" : "warning"}
          hint={p.kill_switch_reason}
        />
        <Stat
          label={t("execution.broker")}
          value={p.broker.name}
          tone={p.broker.simulated ? "good" : "warning"}
          hint={p.broker.simulated ? t("execution.simulated") : t("execution.live")}
        />
        <Stat
          label={t("execution.maxRisk")}
          value={`${p.max_risk_r_per_order} R`}
          hint={t("execution.maxRiskHint")}
        />
      </div>

      <Panel title={t("execution.approvals")} subtitle={t("execution.approvalsSubtitle")}>
        <div className="p-4 flex flex-wrap gap-2">
          {p.required_approvals.map((layer) => (
            <span key={layer} className="pill">
              {layer}
            </span>
          ))}
        </div>
        <p className="px-4 pb-4 text-xs ink-3 leading-relaxed">
          {t("execution.stalenessBody").replace(
            "{seconds}",
            String(p.max_authorisation_age_seconds),
          )}
        </p>
      </Panel>

      <Panel title={t("execution.accounts")} subtitle={t("execution.accountsSubtitle")}>
        {!accounts.ok || accounts.data.accounts.length === 0 ? (
          <div className="p-4 space-y-2">
            <Empty>{t("execution.noAccounts")}</Empty>
            {accounts.ok && <p className="text-xs ink-3 leading-relaxed">{accounts.data.reason}</p>}
          </div>
        ) : (
          <div className="p-4 text-xs ink-2">{accounts.data.tradeable.join(", ")}</div>
        )}
      </Panel>

      <Panel title={t("execution.whatTheApiCannotDo")}>
        <div className="scroll-x">
          <table className="data">
            <tbody>
              <tr>
                <td className="font-semibold">{t("execution.canPlaceOrders")}</td>
                <td>
                  <StatusBadge
                    status={p.api_can_place_orders ? "warning" : "good"}
                    label={p.api_can_place_orders ? t("execution.yes") : t("execution.no")}
                  />
                </td>
              </tr>
              <tr>
                <td className="font-semibold">{t("execution.canDisengageKill")}</td>
                <td>
                  <StatusBadge
                    status={p.api_can_disengage_kill_switch ? "warning" : "good"}
                    label={
                      p.api_can_disengage_kill_switch ? t("execution.yes") : t("execution.no")
                    }
                  />
                </td>
              </tr>
              <tr>
                <td className="font-semibold">{t("execution.dryRun")}</td>
                <td>
                  <StatusBadge
                    status={p.dry_run ? "good" : "warning"}
                    label={p.dry_run ? t("execution.yes") : t("execution.no")}
                  />
                </td>
              </tr>
            </tbody>
          </table>
        </div>
        <p className="p-4 text-xs ink-3 leading-relaxed">{p.note}</p>
      </Panel>
    </div>
  );
}
