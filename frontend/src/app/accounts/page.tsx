import { Offline, Panel, Stat, StatusBadge } from "@/components/ui";
import { api } from "@/lib/api";
import { getT } from "@/lib/locale";

export const dynamic = "force-dynamic";

/**
 * Who may do what, and which tier includes it — two questions, drawn apart.
 *
 * They get confused constantly, and the confusion is expensive in both
 * directions. An admin on the free tier holds the execute permission and still
 * cannot reach live execution; a viewer on the paid tier can open every page
 * and still cannot place an order. Neither is a bug, and both look like one
 * until the axes are drawn on the same table.
 *
 * The role rows are read from the same table the dependency enforces, not a
 * copy kept beside it. A published permission matrix that drifts from the
 * enforced one is worse than none: it tells an auditor the system does
 * something it stopped doing.
 *
 * Measurement sits in the free tier on purpose, and the page says so. The part
 * of this system worth trusting is the part that says "no proven edge", and
 * behind a paywall that would be selling confidence rather than evidence.
 */
export default async function AccountsPage() {
  const { t } = await getT();
  const [roles, plans, matrix] = await Promise.all([
    api.roles(),
    api.plans(),
    api.accessMatrix(),
  ]);
  if (!roles.ok) return <Offline error={roles.error} />;

  const tierTone = (plan: string) =>
    plan === "free" ? "good" : plan === "conditional" ? "warning" : "neutral";

  return (
    <div className="space-y-4">
      <header>
        <h1 className="text-xl font-bold">{t("access.title")}</h1>
        <p className="text-xs ink-3 mt-0.5 max-w-3xl">{t("access.subtitle")}</p>
      </header>

      <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
        <Stat label={t("access.roles")} value={String(roles.data.roles.length)} />
        <Stat
          label={t("access.permissions")}
          value={roles.data.permissions.join(", ")}
          hint={t("access.permissionsHint")}
        />
        <Stat
          label={t("access.tiers")}
          value={plans.ok ? String(plans.data.plans.length) : "—"}
          hint={t("access.tiersHint")}
        />
        <Stat
          label={t("access.billing")}
          value={t("access.none")}
          tone="neutral"
          hint={t("access.billingHint")}
        />
      </div>

      <Panel title={t("access.rolesTable")} subtitle={t("access.rolesSubtitle")}>
        <div className="scroll-x">
          <table className="data">
            <thead>
              <tr>
                <th>{t("access.role")}</th>
                <th>{t("access.permissions")}</th>
                <th>{t("access.canExecute")}</th>
              </tr>
            </thead>
            <tbody>
              {roles.data.roles.map((row) => (
                <tr key={row.role}>
                  <td className="font-semibold num">{row.role}</td>
                  <td className="ink-2">{row.permissions.join(", ")}</td>
                  <td>
                    <StatusBadge
                      status={row.can_execute ? "warning" : "good"}
                      label={row.can_execute ? t("access.yes") : t("access.no")}
                    />
                  </td>
                </tr>
              ))}
              <tr>
                <td className="font-semibold num">{t("access.anonymous")}</td>
                <td className="ink-2">{roles.data.anonymous_holds.join(", ")}</td>
                <td>
                  <StatusBadge status="good" label={t("access.no")} />
                </td>
              </tr>
            </tbody>
          </table>
        </div>
        <p className="p-4 text-xs ink-3 leading-relaxed">{roles.data.note}</p>
      </Panel>

      {plans.ok && (
        <Panel title={t("access.catalogue")} subtitle={t("access.catalogueSubtitle")}>
          <div className="scroll-x">
            <table className="data">
              <thead>
                <tr>
                  <th>{t("access.feature")}</th>
                  <th>{t("access.tier")}</th>
                  <th>{t("access.condition")}</th>
                  <th>{t("access.why")}</th>
                </tr>
              </thead>
              <tbody>
                {plans.data.features.map((feature) => (
                  <tr key={feature.feature}>
                    <td className="font-semibold num">{feature.feature}</td>
                    <td>
                      <StatusBadge status={tierTone(feature.plan)} label={feature.plan} />
                    </td>
                    <td className="ink-3 num">{feature.condition ?? "—"}</td>
                    <td
                      className="ink-2 text-xs"
                      style={{ whiteSpace: "normal", minWidth: "22rem" }}
                    >
                      {feature.why}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <p className="p-4 text-xs ink-3 leading-relaxed">{plans.data.billing}</p>
        </Panel>
      )}

      {matrix.ok && (
        <Panel title={t("access.matrix")} subtitle={t("access.matrixSubtitle")}>
          <div className="scroll-x">
            <table className="data">
              <thead>
                <tr>
                  <th>{t("access.role")}</th>
                  <th>{t("access.tier")}</th>
                  <th>{t("access.holdsExecute")}</th>
                  <th>{t("access.tierIncludes")}</th>
                  <th>{t("access.couldOrder")}</th>
                </tr>
              </thead>
              <tbody>
                {matrix.data.matrix.map((row) => (
                  <tr key={`${row.role}-${row.plan}`}>
                    <td className="font-semibold num">{row.role}</td>
                    <td className="ink-3 num">{row.plan}</td>
                    <td className="ink-2">
                      {row.holds_execute_permission ? t("access.yes") : t("access.no")}
                    </td>
                    <td className="ink-2">
                      {row.plan_includes_live_execution ? t("access.yes") : t("access.no")}
                    </td>
                    <td>
                      <StatusBadge
                        status={row.could_place_an_order ? "warning" : "good"}
                        label={row.could_place_an_order ? t("access.yes") : t("access.no")}
                      />
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <p className="p-4 text-xs ink-3 leading-relaxed">{matrix.data.note}</p>
          <p className="px-4 pb-4 text-xs" style={{ color: "var(--good)" }}>
            {matrix.data.still_refused_here}
          </p>
        </Panel>
      )}

      <Panel title={t("access.whyMeasurementIsFree")}>
        <p className="p-4 text-xs ink-3 leading-relaxed">
          {t("access.whyMeasurementIsFreeBody")}
        </p>
      </Panel>
    </div>
  );
}
