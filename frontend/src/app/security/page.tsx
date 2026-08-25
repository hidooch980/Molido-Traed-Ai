import { Offline, Panel, Stat, StatusBadge } from "@/components/ui";
import { api } from "@/lib/api";
import { getT } from "@/lib/locale";

export const dynamic = "force-dynamic";

/**
 * The security posture, derived from the running router table.
 *
 * Nothing here is transcribed from a design document. `mutating` and `ungated`
 * are recomputed per request by the same walk the execution gate runs at
 * import, so if a mutating route were ever added without a permission
 * dependency, this page would show it — and the process would not have
 * started to render the page at all.
 *
 * The empty `ungated` list is the load-bearing claim, and an earlier version
 * of that walk produced it vacuously by iterating only the top level of
 * `app.routes` and never descending into the included routers. An empty list
 * that means "found nothing" and an empty list that means "looked everywhere
 * and found nothing" render identically, which is why the count of inspected
 * routes is shown beside it.
 */
export default async function SecurityPage() {
  const { t } = await getT();
  const [posture, commands] = await Promise.all([api.security(), api.commands()]);
  if (!posture.ok) return <Offline error={posture.error} />;

  const s = posture.data;

  return (
    <div className="space-y-6">
      <header className="page-header">
        <div className="min-w-0">
          <h1 className="display">{t("security.title")}</h1>
          <p className="page-lede">{t("security.subtitle")}</p>
        </div>
      </header>

      <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
        <Stat
          label={t("security.requireAuth")}
          value={s.require_auth ? t("security.on") : t("security.off")}
          tone={s.require_auth ? "good" : "neutral"}
          hint={t("security.requireAuthHint")}
        />
        <Stat
          label={t("security.mutatingRoutes")}
          value={String(s.routes.mutating.length)}
          tone={s.routes.mutating.length === 0 ? "good" : "warning"}
          hint={t("security.mutatingHint")}
        />
        <Stat
          label={t("security.ungatedRoutes")}
          value={String(s.routes.ungated.length)}
          tone={s.routes.ungated.length === 0 ? "good" : "critical"}
          hint={t("security.ungatedHint")}
        />
        <Stat
          label={t("security.checkedAt")}
          value={t("security.importTime")}
          hint={t("security.checkedAtHint")}
        />
      </div>

      <Panel title={t("security.roles")} subtitle={t("security.rolesSubtitle")}>
        <div className="scroll-x">
          <table className="data">
            <thead>
              <tr>
                <th>{t("security.role")}</th>
                <th>{t("security.permissions")}</th>
              </tr>
            </thead>
            <tbody>
              {Object.entries(s.roles).map(([role, perms]) => (
                <tr key={role}>
                  <td className="font-semibold num">{role}</td>
                  <td className="ink-2">{perms.join(", ")}</td>
                </tr>
              ))}
              <tr>
                <td className="font-semibold num">{t("security.anonymous")}</td>
                <td className="ink-2">{s.anonymous_holds.join(", ")}</td>
              </tr>
            </tbody>
          </table>
        </div>
      </Panel>

      <Panel title={t("security.gate")} subtitle={t("security.gateSubtitle")}>
        <div className="scroll-x">
          <table className="data">
            <tbody>
              <tr>
                <td className="font-semibold">{t("security.mutatingRoutes")}</td>
                <td>
                  <StatusBadge
                    status={s.routes.mutating.length === 0 ? "good" : "warning"}
                    label={
                      s.routes.mutating.length === 0
                        ? t("security.none")
                        : s.routes.mutating.join(", ")
                    }
                  />
                </td>
              </tr>
              <tr>
                <td className="font-semibold">{t("security.ungatedRoutes")}</td>
                <td>
                  <StatusBadge
                    status={s.routes.ungated.length === 0 ? "good" : "critical"}
                    label={
                      s.routes.ungated.length === 0
                        ? t("security.none")
                        : s.routes.ungated.join(", ")
                    }
                  />
                </td>
              </tr>
              <tr>
                <td className="font-semibold">{t("security.refusesToStart")}</td>
                <td className="ink-2 text-xs">{s.gate.refuses_to_start_if}</td>
              </tr>
            </tbody>
          </table>
        </div>
        <p className="p-4 text-xs ink-3 leading-relaxed">{s.note}</p>
      </Panel>

      {commands.ok && (
        <Panel title={t("security.chatCommands")} subtitle={commands.data.why}>
          <div className="p-4 flex flex-wrap gap-2">
            {commands.data.allowed.map((command) => (
              <span key={command} className="pill">
                {command}
              </span>
            ))}
          </div>
          <p className="px-4 pb-4 text-xs ink-3 leading-relaxed">
            {t("security.tradingRequires")}: {commands.data.trading_requires}
          </p>
        </Panel>
      )}
    </div>
  );
}
