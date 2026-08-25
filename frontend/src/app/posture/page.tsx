import { Offline, Panel, Stat, StatusBadge } from "@/components/ui";
import { api } from "@/lib/api";
import { getT } from "@/lib/locale";

export const dynamic = "force-dynamic";

/**
 * The screen an operator opens when something feels wrong.
 *
 * It answers one question — can this deployment trade right now, and if not,
 * what is stopping it — and it answers from the running configuration rather
 * than from anything cached. A posture page that reports what was true at boot
 * is the page that reassures somebody during the incident it should be
 * flagging, so both panels are `force-dynamic`.
 *
 * The readiness panel below is deliberately a different question from health.
 * Health says the process answers; readiness says the process is safe to trade
 * with, and a deployment can be entirely healthy and entirely unready.
 */
export default async function PosturePage() {
  const { t } = await getT();
  const [posture, readiness] = await Promise.all([api.posture(), api.readiness()]);

  if (!posture.ok) return <Offline error={posture.error} />;

  const { can_trade, blockers, policy, routes, operational_rows } = posture.data;

  const grades = { blocking: "critical", important: "warning", advisory: "info" } as const;

  return (
    <div className="space-y-6">
      <header className="page-header">
        <div className="min-w-0">
          <h1 className="display">{t("posture.title")}</h1>
          <p className="page-lede">{t("posture.subtitle")}</p>
        </div>
      </header>

      <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
        <Stat
          label={t("posture.canTrade")}
          value={can_trade ? t("posture.yes") : t("posture.no")}
          tone={can_trade ? "warning" : "good"}
          hint={can_trade ? t("posture.canTradeHint") : t("posture.cannotTradeHint")}
        />
        <Stat
          label={t("posture.execution")}
          value={policy.execution_enabled ? t("posture.on") : t("posture.off")}
          tone={policy.execution_enabled ? "warning" : "good"}
        />
        <Stat
          label={t("posture.dryRun")}
          value={policy.dry_run ? t("posture.on") : t("posture.off")}
          tone={policy.dry_run ? "good" : "warning"}
        />
        <Stat
          label={t("posture.auth")}
          value={policy.require_auth ? t("posture.on") : t("posture.off")}
          // Not a fault: with no mutating route, auth being off is the
          // deployment's actual shape rather than a gap in it.
          tone={policy.require_auth ? "good" : "neutral"}
          hint={t("posture.authHint")}
        />
      </div>

      <Panel title={t("posture.blockers")} subtitle={t("posture.blockersSubtitle")}>
        {blockers.length === 0 ? (
          <p className="p-4 text-xs ink-3">{t("posture.noBlockers")}</p>
        ) : (
          <ul className="p-4 space-y-2 text-xs ink-2">
            {blockers.map((blocker) => (
              <li key={blocker} className="flex gap-2.5">
                <span style={{ color: "var(--good)" }} aria-hidden="true">
                  ●
                </span>
                <span>{blocker}</span>
              </li>
            ))}
          </ul>
        )}
      </Panel>

      <Panel title={t("posture.gate")} subtitle={t("posture.gateSubtitle")}>
        <div className="p-4 grid gap-3 sm:grid-cols-2 text-xs">
          <div>
            <div className="eyebrow mb-1">{t("posture.mutatingRoutes")}</div>
            <div className="num ink-2">
              {routes.mutating.length === 0 ? t("posture.none") : routes.mutating.join(", ")}
            </div>
          </div>
          <div>
            <div className="eyebrow mb-1">{t("posture.ungatedRoutes")}</div>
            <div className="num" style={{ color: routes.ungated.length ? "var(--bad)" : undefined }}>
              {routes.ungated.length === 0 ? t("posture.none") : routes.ungated.join(", ")}
            </div>
          </div>
        </div>
      </Panel>

      {readiness.ok && (
        <Panel
          title={t("posture.readiness")}
          subtitle={`${readiness.data.passed} / ${readiness.data.total} — ${
            readiness.data.safe_to_trade ? t("posture.noBlocking") : t("posture.hasBlocking")
          }`}
        >
          <div className="scroll-x">
            <table className="data">
              <thead>
                <tr>
                  <th>{t("posture.check")}</th>
                  <th>{t("posture.grade")}</th>
                  <th>{t("posture.result")}</th>
                  <th>{t("posture.detail")}</th>
                </tr>
              </thead>
              <tbody>
                {readiness.data.checks.map((check) => (
                  <tr key={check.name}>
                    <td className="font-semibold num">{check.name}</td>
                    <td>
                      <StatusBadge status={grades[check.grade]} label={t(`posture.${check.grade}`)} />
                    </td>
                    <td>
                      <StatusBadge
                        status={check.passed ? "good" : "critical"}
                        label={check.passed ? t("posture.pass") : t("posture.fail")}
                      />
                    </td>
                    <td className="ink-3">{check.detail}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <p className="px-4 py-3 text-xs ink-3 leading-relaxed">{readiness.data.note}</p>
        </Panel>
      )}

      <Panel title={t("posture.operational")} subtitle={t("posture.operationalSubtitle")}>
        <div className="scroll-x">
          <table className="data">
            <thead>
              <tr>
                <th>{t("posture.table")}</th>
                <th>{t("posture.rows")}</th>
              </tr>
            </thead>
            <tbody>
              {Object.entries(operational_rows).map(([table, rows]) => (
                <tr key={table}>
                  <td className="font-semibold num">{table}</td>
                  <td className="num ink-2">
                    {rows < 0 ? t("posture.unreadable") : rows.toLocaleString()}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Panel>
    </div>
  );
}
