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
  const [roles, plans, matrix, autopilot] = await Promise.all([
    api.roles(),
    api.plans(),
    api.accessMatrix(),
    api.autopilot(),
  ]);
  if (!roles.ok) return <Offline error={roles.error} />;

  const tierTone = (plan: string) =>
    plan === "free" ? "good" : plan === "conditional" ? "warning" : "neutral";

  return (
    <div className="space-y-6">
      <header className="page-header">
        <div className="min-w-0">
          <h1 className="display">{t("access.title")}</h1>
        <p className="text-xs ink-3 mt-0.5 max-w-3xl">{t("access.subtitle")}</p>
      </div>
      </header>

      {autopilot.ok && (
        <Panel
          title={t("autopilot.title")}
          subtitle={
            autopilot.data.mode === "live"
              ? t("autopilot.subtitleLive")
              : t("autopilot.subtitlePaper")
          }
        >
          <div className="p-4 space-y-3">
            <div className="flex flex-wrap items-center gap-2">
              <StatusBadge
                status={autopilot.data.would_send_live_orders ? "warning" : "good"}
                label={autopilot.data.mode}
              />
              {autopilot.data.edge_override_in_use && (
                <StatusBadge status="critical" label={t("autopilot.override")} />
              )}
            </div>

            <p className="text-xs ink-3 leading-relaxed">{autopilot.data.reason}</p>

            {/* Every gate, not a single boolean. Four different reasons for
                "it is not trading" would otherwise look identical, and an
                operator would have no idea which switch to reach for. */}
            <div className="scroll-x">
              <table className="data">
                <thead>
                  <tr>
                    <th>{t("autopilot.gate")}</th>
                    <th>{t("autopilot.state")}</th>
                    <th>{t("autopilot.why")}</th>
                  </tr>
                </thead>
                <tbody>
                  {Object.entries(autopilot.data.gates).map(([name, gate]) => (
                    <tr key={name}>
                      <td className="font-medium">{t(`autopilot.gate.${name}`)}</td>
                      <td>
                        <StatusBadge
                          status={gate.open ? "good" : "warning"}
                          label={gate.open ? t("autopilot.open") : t("autopilot.shut")}
                        />
                      </td>
                      <td className="text-xs ink-3">{gate.detail}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>

            {autopilot.data.context && !autopilot.data.context.complete && (
              <div className="text-xs ink-3 leading-relaxed">
                <p className="font-medium">{t("autopilot.unmeasured")}</p>
                <ul className="mt-1 space-y-0.5">
                  {autopilot.data.context.unmeasured.map((gap) => (
                    <li key={gap}>— {gap}</li>
                  ))}
                </ul>
              </div>
            )}

            {/* Kept and shown. "We tried nothing" and "we tried this and it
                did not clear the bar" are different facts, and hiding the
                second invites the same rule being proposed again as new. */}
            {autopilot.data.rejected_claims.map((claim) => (
              <div key={claim.key} className="text-xs ink-3 leading-relaxed">
                <p className="font-medium">
                  {t("autopilot.rejected")}: {claim.key}
                </p>
                <p className="mt-0.5">{claim.description}</p>
                <ul className="mt-1 space-y-0.5">
                  {claim.verdict.failures.map((failure) => (
                    <li key={failure}>— {failure}</li>
                  ))}
                </ul>
              </div>
            ))}
          </div>
        </Panel>
      )}

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
