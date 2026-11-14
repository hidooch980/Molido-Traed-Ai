import { Empty, Offline, Panel, Pill } from "@/components/ui";
import { api } from "@/lib/api";
import { getT } from "@/lib/locale";

export const dynamic = "force-dynamic";

function usd(v: number | null | undefined): string {
  return typeof v === "number" ? `$${v.toFixed(4)}` : "—";
}

export default async function GrokCost() {
  const { t } = await getT();
  const [gateway, today, week] = await Promise.all([
    api.gateway(),
    api.gatewayUsage(0),
    api.gatewayUsage(7),
  ]);
  if (!gateway.ok) return <Offline error={gateway.error} />;
  const g = gateway.data;

  return (
    <div className="space-y-6">
      <header>
        <h1 className="display">{t("grokCost.title")}</h1>
        <p className="text-xs ink-3 mt-0.5 max-w-2xl">{t("grokCost.subtitle")}</p>
        <div className="flex gap-2 mt-2 flex-wrap">
          <Pill tone={g.enabled ? "good" : "muted"}>
            {g.enabled ? t("grokCost.enabled") : t("grokCost.disabled", { env: g.key_env })}
          </Pill>
          <Pill tone={g.budget.mode === "NORMAL" ? "good" : "warning"}>{g.budget.mode}</Pill>
        </div>
      </header>
      <Panel title={t("grokCost.budget")}>
        <dl className="grid grid-cols-2 gap-2 text-sm max-w-xl">
          <dt className="ink-3">tokens</dt>
          <dd>{g.budget.tokens_today} / {g.budget.daily_token_limit}</dd>
          <dt className="ink-3">USD</dt>
          <dd>{usd(g.budget.usd_today)} / {usd(g.budget.daily_usd_limit)}</dd>
          <dt className="ink-3">{t("grokCost.models")}</dt>
          <dd className="mono text-xs">{Object.values(g.config.models).join(", ")}</dd>
          <dt className="ink-3">{t("grokCost.priced")}</dt>
          <dd className="mono text-xs">{g.config.priced_models.join(", ") || "—"}</dd>
        </dl>
        <p className="text-xs ink-3 mt-2">{g.source}</p>
      </Panel>
      {[
        { key: "today", label: t("grokCost.today"), view: today },
        { key: "week", label: t("grokCost.week"), view: week },
      ].map(({ key, label, view }) => (
        <Panel key={key} title={label}>
          {!view.ok ? (
            <Empty>{view.error}</Empty>
          ) : view.data.requests === 0 ? (
            <Empty>{t("grokCost.empty")}</Empty>
          ) : (
            <>
              <p className="text-sm mb-2">
                {view.data.requests} req · {view.data.total_tokens} tokens (cached{" "}
                {view.data.cached_tokens}) · {usd(view.data.cost_usd)}
                {view.data.unpriced_requests > 0 &&
                  ` · ${t("grokCost.unpriced", { n: view.data.unpriced_requests })}`}
              </p>
              <table className="w-full text-sm">
                <tbody>
                  {view.data.agents.map((a) => (
                    <tr key={a.agent_id} className="border-t">
                      <td className="mono">{a.agent_id}</td>
                      <td>{a.requests}</td>
                      <td>{a.total_tokens}</td>
                      <td>{usd(a.cost_usd)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </>
          )}
        </Panel>
      ))}
    </div>
  );
}
