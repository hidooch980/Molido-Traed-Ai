import { Empty, Offline, Panel, Pill } from "@/components/ui";
import { api, type AgentAlert, type AgentHealthRow } from "@/lib/api";
import { getT } from "@/lib/locale";

export const dynamic = "force-dynamic";

const ALERT_TONE: Record<AgentAlert["level"], "critical" | "warning" | "muted"> = {
  critical: "critical",
  warning: "warning",
  info: "muted",
};

function healthTone(row: AgentHealthRow): "good" | "warning" | "critical" | "muted" {
  if (row.status === "ok") return "good";
  if (row.status === "degraded") return "critical";
  if (row.status === "stale") return "warning";
  return "muted";
}

export default async function AgentHealth() {
  const { t } = await getT();
  const [health, alerts, perf] = await Promise.all([
    api.agentHealth(),
    api.agentAlerts(),
    api.agentPerformance(),
  ]);
  if (!health.ok) return <Offline error={health.error} />;
  const analyzers = health.data.agents.filter((a) => a.status !== "not_an_analyzer");

  return (
    <div className="space-y-6">
      <header>
        <h1 className="display">{t("agentHealth.title")}</h1>
        <p className="text-xs ink-3 mt-0.5 max-w-2xl">{t("agentHealth.subtitle")}</p>
        <p className="text-xs ink-3 mt-1">
          {Object.entries(health.data.counts)
            .map(([k, v]) => `${k}: ${v}`)
            .join(" · ")}{" "}
          · {health.data.as_of}
        </p>
      </header>

      <Panel title={t("agentHealth.alerts")} subtitle={alerts.ok ? alerts.data.delivery : undefined}>
        {!alerts.ok ? (
          <Empty>{alerts.error}</Empty>
        ) : alerts.data.alerts.length === 0 ? (
          <Empty>{t("agentHealth.noAlerts")}</Empty>
        ) : (
          <ul className="space-y-1 text-sm">
            {alerts.data.alerts.map((a, i) => (
              <li key={`${a.source}-${i}`} className="flex gap-2 items-start">
                <Pill tone={ALERT_TONE[a.level]}>{a.level}</Pill>
                <span className="ink-3">{a.source}</span>
                <span>{a.message}</span>
              </li>
            ))}
          </ul>
        )}
      </Panel>

      <Panel title={t("agentHealth.agents")}>
        {analyzers.every((a) => a.status === "never_run") ? (
          <Empty>{t("agentHealth.noRuns")}</Empty>
        ) : (
          <table className="w-full text-xs">
            <tbody>
              {analyzers.map((a) => (
                <tr key={a.id} className="border-t border-white/5">
                  <td className="py-1 pr-2 font-mono">{a.id}</td>
                  <td className="pr-2">
                    <Pill tone={healthTone(a)}>{a.status}</Pill>
                  </td>
                  <td className="pr-2">{a.runs ?? "—"}</td>
                  <td className="pr-2">
                    {typeof a.error_rate === "number" ? `${(a.error_rate * 100).toFixed(0)}%` : "—"}
                  </td>
                  <td className="pr-2">{typeof a.avg_ms === "number" ? `${a.avg_ms} ms` : "—"}</td>
                  <td className="pr-2">{a.last_recommendation ?? "—"}</td>
                  <td className="ink-3">{a.last_error ?? a.last_run_at ?? ""}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </Panel>

      <Panel title={t("agentHealth.performance")} subtitle={perf.ok ? perf.data.note : undefined}>
        {!perf.ok || perf.data.agents.length === 0 ? (
          <Empty>{perf.ok ? t("agentHealth.noRuns") : perf.error}</Empty>
        ) : (
          <table className="w-full text-xs">
            <tbody>
              {perf.data.agents.map((p) => (
                <tr key={p.id} className="border-t border-white/5">
                  <td className="py-1 pr-2 font-mono">{p.id}</td>
                  <td className="pr-2">{p.calls}</td>
                  <td className="pr-2">
                    {p.hit_rate === null ? "—" : `${(p.hit_rate * 100).toFixed(0)}%`}
                  </td>
                  <td className="pr-2">
                    {p.avg_signed_move_pct === null ? "—" : `${p.avg_signed_move_pct}%`}
                  </td>
                  <td className="ink-3">{p.enough_data ? "" : "n<30"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </Panel>
    </div>
  );
}
