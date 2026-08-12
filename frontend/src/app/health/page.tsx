import { Offline, Panel, Stat, StatusBadge } from "@/components/ui";
import { api } from "@/lib/api";
import { getT } from "@/lib/locale";

export const dynamic = "force-dynamic";

export default async function HealthPage() {
  const { t } = await getT();
  const health = await api.health();
  if (!health.ok) return <Offline error={health.error} />;

  const { status, version, environment, safe_mode, safe_mode_reasons, dependencies } =
    health.data;

  return (
    <div className="space-y-4">
      <header>
        <h1 className="text-xl font-bold">{t("health.title")}</h1>
        <p className="text-xs ink-3 mt-0.5">
          {t("health.subtitle")}
        </p>
      </header>

      <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
        <Stat label={t("health.status")} value={status} tone={status === "ok" ? "good" : "warning"} />
        <Stat label={t("health.version")} value={version} />
        <Stat label={t("health.environment")} value={environment} />
        <Stat
          label={t("home.safeMode")}
          value={safe_mode ? "engaged" : "clear"}
          tone={safe_mode ? "warning" : "good"}
          hint={safe_mode ? safe_mode_reasons.join(", ") : t("home.safeClear")}
        />
      </div>

      <Panel title={t("health.dependencies")} subtitle={t("health.dependenciesSubtitle")}>
        <div className="scroll-x">
          <table className="data">
            <thead>
              <tr>
                <th>{t("health.dependency")}</th>
                <th>{t("health.state")}</th>
                <th>{t("health.latency")}</th>
                <th>{t("health.detail")}</th>
              </tr>
            </thead>
            <tbody>
              {dependencies.map((dep) => (
                <tr key={dep.name}>
                  <td className="font-semibold">{dep.name}</td>
                  <td>
                    <StatusBadge
                      status={dep.healthy ? "good" : "critical"}
                      label={dep.healthy ? t("health.healthy") : t("health.down")}
                    />
                  </td>
                  <td className="num ink-2">
                    {dep.latency_ms != null ? `${dep.latency_ms} ms` : "—"}
                  </td>
                  <td className="ink-3">{dep.detail ?? "—"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Panel>

      <Panel title={t("health.notMeasured")}>
        <p className="p-4 text-xs ink-3 leading-relaxed">
          {t("health.notMeasuredBody")}
        </p>
      </Panel>
    </div>
  );
}
