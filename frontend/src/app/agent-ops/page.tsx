import { Empty, Offline, Panel, Pill } from "@/components/ui";
import { api } from "@/lib/api";
import { getT } from "@/lib/locale";

export const dynamic = "force-dynamic";

type Tone = "good" | "warning" | "critical" | "muted" | "neutral";
const tone = (v: string | null | undefined): Tone =>
  v === "PASS" || v === "PROPOSED" ? "good" : v === "FAIL" ? "critical"
    : v === "INSUFFICIENT" || v === "PENDING" ? "warning" : "muted";
const pct = (x: number | null | undefined) => (x === null || x === undefined ? "—" : `${(x * 100).toFixed(1)}%`);

export default async function AgentOps() {
  const { t } = await getT();
  const [shadow, ops] = await Promise.all([api.brainShadow(), api.agentOps()]);
  if (!ops.ok) return <Offline error={ops.error} />;
  const o = ops.data;
  const v = shadow.ok ? shadow.data.latest_verdict : null;
  const gate = o.backtest_gate.current;

  return (
    <div className="space-y-5">
      <header>
        <h1 className="display">{t("ops.title")}</h1>
        <p className="text-xs ink-3 mt-0.5 max-w-2xl">{t("ops.subtitle")}</p>
      </header>

      <div className="grid gap-4 lg:grid-cols-2">
        <Panel title={t("ops.shadow")} subtitle={t("ops.shadowHint")}>
          {!v ? <Empty>{t("ops.noShadow")}</Empty> : (
            <div className="space-y-2 text-xs">
              <div className="flex gap-2 items-center">
                <Pill tone={tone(v.status)}>{v.status}</Pill>
                <span className="ink-3">{v.rows} {t("ops.rows")} · {v.pending} {t("ops.pending")}</span>
              </div>
              <div className="grid grid-cols-2 gap-2">
                <div className="rounded-lg p-2" style={{ background: "var(--panel-raised)" }}>
                  <div className="ink-3">{t("ops.production")}</div>
                  <div className="num text-lg">{pct(v.production.hit_rate)}</div>
                  <div className="ink-3 num">n={v.production.n}</div>
                </div>
                <div className="rounded-lg p-2" style={{ background: "var(--panel-raised)" }}>
                  <div className="ink-3">{t("ops.withAgents")}</div>
                  <div className="num text-lg">{pct(v.with_agents.hit_rate)}</div>
                  <div className="ink-3 num">n={v.with_agents.n}</div>
                </div>
              </div>
              <p className="ink-2">{v.decision.reason}</p>
              <p className="ink-3">{t("ops.liveEffect")}</p>
            </div>
          )}
        </Panel>

        <Panel title={t("ops.gate")} subtitle={`${t("ops.version")} ${o.backtest_gate.strategy_version}`}>
          {!gate ? <Empty>{t("ops.noGate")}</Empty> : (
            <div className="space-y-2 text-xs">
              <div className="flex gap-2 items-center">
                <Pill tone={tone(gate.verdict)}>{gate.verdict}</Pill>
                <span className="num ink-3">{gate.trades ?? 0} trades · avg {gate.avg_r ?? "—"}R</span>
                {!o.backtest_gate.enabled && <Pill tone="muted">{t("ops.gateOff")}</Pill>}
              </div>
              {(gate.symbols ?? []).map((s) => (
                <div key={s.symbol} className="flex gap-3 num border-t border-white/5 py-1">
                  <span className="font-mono w-20">{s.symbol}</span>
                  <span>n={s.n}</span><span>{s.avg_r ?? "—"}R</span>
                  {s.error && <span className="ink-3">{s.error}</span>}
                </div>
              ))}
              {o.backtest_gate.history.filter((h) => h.kind === "ea").slice(0, 3).map((h) => (
                <div key={h.version} className="flex gap-2"><Pill tone={tone(h.verdict)}>EA {h.version}</Pill><span>{h.verdict}</span></div>
              ))}
            </div>
          )}
        </Panel>
      </div>

      <div className="grid gap-4 lg:grid-cols-3">
        <Panel title={t("ops.reports")} className="lg:col-span-2">
          {o.reports.length === 0 ? <Empty>{t("ops.noReports")}</Empty> : o.reports.slice(0, 7).map((r) => (
            <details key={r.date} className="border-t border-white/5 py-2 text-xs" open={r === o.reports[0]}>
              <summary className="cursor-pointer flex flex-wrap gap-3 items-center">
                <span className="font-mono">{r.date}</span>
                <span className="num" style={{ color: r.paper.total_r >= 0 ? "var(--good)" : "var(--critical)" }}>
                  {r.paper.total_r}R
                </span>
                <span className="ink-3">{r.paper.closed} {t("ops.closed")} · {r.paper.open} {t("ops.open")}</span>
                {r.delivered && <Pill tone="good">Telegram</Pill>}
              </summary>
              <div className="grid sm:grid-cols-3 gap-3 mt-2">
                <div>
                  <div className="ink-3 mb-1">{t("ops.accounts")}</div>
                  {Object.entries(r.paper.accounts).map(([a, x]) => (
                    <div key={a} className="num">{a}: {x.total_r}R ({x.closed})</div>
                  ))}
                </div>
                <div>
                  <div className="ink-3 mb-1">{t("ops.topAgents")}</div>
                  {r.agents.top.map((a) => <div key={a.id} className="num">{a.id} {pct(a.hit_rate)} · {a.calls}</div>)}
                </div>
                <div>
                  <div className="ink-3 mb-1">{t("ops.learning")}</div>
                  <div>v{r.learning.weights ?? 0} · {r.learning.changes_today.length} {t("ops.changes")}</div>
                  <div className="ink-3">{r.learning.quarantined.join(", ") || "—"}</div>
                  {r.learning.brain_shadow && <div>{r.learning.brain_shadow.status}</div>}
                </div>
              </div>
            </details>
          ))}
        </Panel>
        <Panel title={t("ops.telegram")}>
          <div className="text-xs space-y-1">
            <Pill tone={o.notify.configured ? "good" : "muted"}>
              {o.notify.configured ? t("ops.tgOn") : t("ops.tgOff")}
            </Pill>
            {o.notify.recent.length === 0 ? <Empty>{t("ops.noAlerts")}</Empty> : o.notify.recent.map((a, i) => (
              <div key={i} className="border-t border-white/5 py-1">
                <span className="ink-3 num">{a.at.slice(0, 16).replace("T", " ")} UTC</span> {a.text}
              </div>
            ))}
          </div>
        </Panel>
      </div>
    </div>
  );
}
