import { Empty, Offline, Panel, Pill } from "@/components/ui";
import { api, type AgentRole } from "@/lib/api";
import { getT } from "@/lib/locale";

export const dynamic = "force-dynamic";

const TONE: Record<AgentRole["status"], "good" | "warning" | "muted"> = {
  IMPLEMENTED: "good",
  PARTIAL: "warning",
  NOT_IMPLEMENTED: "muted",
};

export default async function AgentCommandCenter() {
  const { t } = await getT();
  const registry = await api.agentRegistry();
  if (!registry.ok) return <Offline error={registry.error} />;
  const { agents, status_counts: counts } = registry.data;

  const groups = new Map<string, AgentRole[]>();
  for (const role of agents) groups.set(role.group, [...(groups.get(role.group) ?? []), role]);

  return (
    <div className="space-y-6">
      <header>
        <h1 className="display">{t("agents.title")}</h1>
        <p className="text-xs ink-3 mt-0.5 max-w-2xl">{t("agents.subtitle")}</p>
        <div className="flex gap-2 mt-2 flex-wrap">
          <Pill tone="good">IMPLEMENTED {counts.IMPLEMENTED ?? 0}</Pill>
          <Pill tone="warning">PARTIAL {counts.PARTIAL ?? 0}</Pill>
          <Pill tone="muted">NOT_IMPLEMENTED {counts.NOT_IMPLEMENTED ?? 0}</Pill>
          <Pill>{registry.data.mode}</Pill>
        </div>
        <p className="text-xs ink-3 mt-2 max-w-3xl">{registry.data.note}</p>
      </header>
      {agents.length === 0 ? (
        <Panel title={t("agents.title")}>
          <Empty>{t("agents.empty")}</Empty>
        </Panel>
      ) : (
        [...groups.entries()].map(([group, roles]) => (
          <Panel key={group} title={group}>
            <table className="w-full text-sm">
              <thead>
                <tr className="text-left ink-3 text-xs">
                  <th>ID</th>
                  <th>{t("agents.name")}</th>
                  <th>L</th>
                  <th>{t("agents.status")}</th>
                  <th>{t("agents.modules")}</th>
                </tr>
              </thead>
              <tbody>
                {roles.map((r) => (
                  <tr key={r.id} className="align-top border-t" title={r.notes}>
                    <td className="mono">{r.id}</td>
                    <td>
                      <div>{r.name_fa}</div>
                      <div className="text-xs ink-3">{r.name_en}</div>
                    </td>
                    <td>L{r.permission_level}</td>
                    <td>
                      <Pill tone={TONE[r.status]}>{r.status}</Pill>
                    </td>
                    <td className="text-xs mono ink-3">{r.modules.join(", ") || "—"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </Panel>
        ))
      )}
    </div>
  );
}
