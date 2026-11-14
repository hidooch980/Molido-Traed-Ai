import Link from "next/link";
import type { ReactNode } from "react";

import PriceChart from "@/components/PriceChart";
import { Empty, Offline, Panel, Pill } from "@/components/ui";
import { api, type SymbolView } from "@/lib/api";
import { getT } from "@/lib/locale";

export const dynamic = "force-dynamic";

const TIMEFRAMES = ["M5", "M15", "H1", "H4", "D1"];
type Tone = "good" | "warning" | "critical" | "muted" | "neutral";

function decisionTone(d: string | undefined): Tone {
  const v = (d ?? "").toUpperCase();
  if (v === "BUY" || v === "LONG" || v === "APPROVE") return "good";
  if (v === "SELL" || v === "SHORT") return "critical";
  if (v === "REDUCE") return "warning";
  if (v === "BLOCK") return "critical";
  return "muted";
}

function Big({ label, value, tone, hint }: { label: string; value: string; tone: Tone; hint?: string }) {
  const color =
    tone === "good" ? "var(--good)" : tone === "critical" ? "var(--critical)"
      : tone === "warning" ? "var(--warning)" : "var(--ink-2)";
  return (
    <div
      className="rounded-xl p-3"
      style={{ background: "linear-gradient(145deg, var(--panel-raised), var(--panel))" }}
    >
      <div className="text-[0.6875rem] ink-3">{label}</div>
      <div className="text-xl font-semibold mt-0.5" style={{ color }}>
        {value}
      </div>
      {hint && <div className="text-[0.6875rem] ink-3 mt-0.5">{hint}</div>}
    </div>
  );
}

function VoteBar({ votes }: { votes: Record<string, number> }) {
  const buy = votes.BUY ?? 0;
  const sell = votes.SELL ?? 0;
  const wait = (votes.WAIT ?? 0) + (votes.ABSTAIN ?? 0);
  const total = Math.max(1, buy + sell + wait);
  const seg = (n: number, color: string) => (
    <div style={{ width: `${(n / total) * 100}%`, background: color }} className="h-full" />
  );
  return (
    <div>
      <div className="flex h-2 rounded-full overflow-hidden" style={{ background: "var(--panel-raised)" }}>
        {seg(buy, "var(--good)")}
        {seg(wait, "var(--ink-3, #666)")}
        {seg(sell, "var(--critical)")}
      </div>
      <div className="flex justify-between text-[0.6875rem] ink-3 mt-1 num">
        <span>BUY {buy}</span>
        <span>WAIT {wait}</span>
        <span>SELL {sell}</span>
      </div>
    </div>
  );
}

function Row({ children }: { children: ReactNode }) {
  return <div className="flex flex-wrap gap-x-3 gap-y-1 items-center text-xs py-1 border-t border-white/5">{children}</div>;
}

export default async function SymbolPage({
  params,
  searchParams,
}: {
  params: Promise<{ symbol: string }>;
  searchParams: Promise<{ tf?: string }>;
}) {
  const { t } = await getT();
  const symbol = decodeURIComponent((await params).symbol).toUpperCase();
  const tfParam = (await searchParams).tf ?? "H1";
  const tf = TIMEFRAMES.includes(tfParam) ? tfParam : "H1";

  const [view, instruments, positions] = await Promise.all([
    api.symbolView(symbol, tf),
    api.instruments(),
    api.positions(),
  ]);
  if (!view.ok) return <Offline error={view.error} />;
  const v: SymbolView = view.data;
  const inst = instruments.ok ? instruments.data.find((i) => i.symbol === symbol) : undefined;
  if (v.status === "unknown_symbol" || !inst) {
    return (
      <Panel title={symbol}>
        <Empty>{t("symbol.unknown")}</Empty>
      </Panel>
    );
  }
  const newsTag = symbol.startsWith("XAU") ? "XAU" : symbol.slice(0, 3) === "EUR" ? "EUR" : "USD";
  const [bars, proposal, news] = await Promise.all([
    api.bars(inst.id, tf, 300),
    api.proposal(inst.id, tf),
    api.headlines(newsTag, 8),
  ]);
  const points = bars.ok ? bars.data.bars.map((b) => ({ t: b.event_time, c: b.close })) : [];
  const last = points.length ? points[points.length - 1].c : null;
  const first = points.length ? points[0].c : null;
  const change = last !== null && first ? ((last - first) / first) * 100 : null;
  const digits = symbol.startsWith("XAU") || symbol.endsWith("JPY") ? 2 : 5;
  const ex = v.explain;
  const symPositions = positions.ok
    ? positions.data.positions.filter((p) => String(p.symbol ?? "").toUpperCase().startsWith(symbol))
    : [];
  const headlines = news.ok ? news.data.headlines ?? news.data.items ?? [] : [];
  const healthRows = Object.entries(v.health?.agents ?? {});

  return (
    <div className="space-y-5">
      <header className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <Link href="/symbols" className="text-xs ink-3">← {t("symbols.title")}</Link>
          <h1 className="display font-mono">{symbol}</h1>
          <p className="text-xs ink-3">{inst.name} · {t("symbol.shadow")}</p>
        </div>
        <nav className="flex gap-1 rounded-xl p-1" style={{ background: "var(--panel-raised)" }}>
          {TIMEFRAMES.map((x) => (
            <Link
              key={x}
              href={`/symbol/${encodeURIComponent(symbol)}?tf=${x}`}
              className="px-3 py-1 rounded-lg text-xs font-mono"
              style={x === tf ? { background: "var(--accent)", color: "var(--accent-ink)" } : {}}
            >
              {x}
            </Link>
          ))}
        </nav>
      </header>

      <div className="grid gap-3 grid-cols-2 md:grid-cols-4">
        <Big label={t("symbol.price")} value={last === null ? "—" : last.toFixed(digits)} tone="neutral"
          hint={change === null ? undefined : `${change >= 0 ? "+" : ""}${change.toFixed(2)}% · ${points.length} ${tf}`} />
        <Big label={t("symbol.agents")} value={v.ensemble?.decision ?? "WAIT"} tone={decisionTone(v.ensemble?.decision)}
          hint={`${t("symbol.weights")} v${v.ensemble?.weights_version ?? 0} · ${v.ensemble?.directional_votes ?? 0} ${t("symbol.directional")}`} />
        <Big label={t("symbol.brain")} value={proposal.ok ? proposal.data.decision : "—"}
          tone={decisionTone(proposal.ok ? proposal.data.decision : undefined)}
          hint={proposal.ok ? `${t("symbol.conviction")} ${(proposal.data.conviction * 100).toFixed(0)}%` : proposal.error} />
        <Big label={t("symbol.rocket")} value={v.rocket?.signals[0]?.rocket_rank ?? "—"}
          tone={v.rocket?.signals.length ? decisionTone(v.rocket.signals[0].risk_review?.verdict) : "muted"}
          hint={v.rocket?.signals[0] ? `${v.rocket.signals[0].direction} · ${v.rocket.signals[0].risk_review?.verdict ?? ""}` : t("symbol.noRocket")} />
      </div>

      <Panel title={t("symbol.chart")} subtitle={tf}>
        {points.length < 2 ? <Empty>{t("symbol.noBars")}</Empty> : <PriceChart points={points} digits={digits} label={symbol} />}
      </Panel>

      <div className="grid gap-4 lg:grid-cols-2">
        <Panel title={t("symbol.votes")} subtitle={ex ? `${t("symbol.lean")}: ${ex.lean}` : undefined}>
          {!ex ? <Empty>{t("symbol.noRun")}</Empty> : (
            <div className="space-y-3">
              <VoteBar votes={ex.votes} />
              {ex.dissent.length > 0 && <p className="text-xs ink-3">{t("symbol.dissent")}: {ex.dissent.join(", ")}</p>}
              {ex.missing_inputs.length > 0 && <p className="text-xs ink-3">{t("symbol.missing")}: {ex.missing_inputs.join(", ")}</p>}
              <div className="max-h-96 overflow-auto">
                {ex.trace.map((r) => (
                  <Row key={r.agent}>
                    <span className="font-mono w-14">{r.agent}</span>
                    <Pill tone={decisionTone(r.says)}>{r.says}</Pill>
                    <span className="num ink-3">{(r.confidence * 100).toFixed(0)}%</span>
                    <span className="ink-2 flex-1 min-w-40">{r.because}</span>
                    {r.evidence[0] && <span className="ink-3 w-full">{r.evidence.slice(0, 2).join(" · ")}</span>}
                  </Row>
                ))}
              </div>
              <p className="text-[0.6875rem] ink-3">{ex.decision}</p>
            </div>
          )}
        </Panel>

        <Panel title={t("symbol.council")} subtitle={proposal.ok ? `v${proposal.data.brain_version}` : undefined}>
          {!proposal.ok ? <Empty>{proposal.error}</Empty> : (
            <div className="space-y-2">
              {proposal.data.council.map((o) => (
                <Row key={o.analyst}>
                  <span className="w-28 ink-2">{o.analyst}</span>
                  <Pill tone={decisionTone(o.abstained ? "WAIT" : o.decision)}>{o.abstained ? "—" : o.decision}</Pill>
                  <span className="num ink-3">{(o.conviction * 100).toFixed(0)}%</span>
                  <span className="ink-3 flex-1 min-w-40">{o.reason}</span>
                </Row>
              ))}
              {proposal.data.wait_reasons.length > 0 && (
                <p className="text-xs ink-3">{t("symbol.waitReasons")}: {proposal.data.wait_reasons.join(" · ")}</p>
              )}
              {proposal.data.invalidation && <p className="text-xs ink-3">{t("symbol.invalidation")}: {proposal.data.invalidation}</p>}
            </div>
          )}
        </Panel>
      </div>

      <div className="grid gap-4 lg:grid-cols-3">
        <Panel title={t("symbol.rocketTitle")}>
          {!v.rocket?.signals.length ? <Empty>{t("symbol.noRocket")}</Empty> : v.rocket.signals.map((s, i) => (
            <div key={i} className="text-xs space-y-1">
              <div className="flex gap-2"><Pill tone="neutral">{s.rocket_rank}</Pill><Pill tone={decisionTone(s.direction)}>{s.direction}</Pill></div>
              <div className="num ink-2">SL {s.stop_loss ?? "—"} · TP {s.take_profit ?? "—"}</div>
            </div>
          ))}
        </Panel>
        <Panel title={t("symbol.risk")}>
          {!v.risk ? <Empty>—</Empty> : (
            <div className="text-xs space-y-1">
              <div className="flex gap-2 items-center">
                <Pill tone={decisionTone(v.rocket?.signals[0]?.risk_review?.verdict ?? "WAIT")}>
                  {v.rocket?.signals[0]?.risk_review?.verdict ?? t("symbol.noSignal")}
                </Pill>
                {v.risk.kill_switch && <Pill tone="critical">kill switch</Pill>}
              </div>
              {(v.rocket?.signals[0]?.risk_review?.reasons ?? []).map((r) => <div key={r} className="ink-3">• {r}</div>)}
              <div className="ink-3">{v.risk.source}</div>
              <div className="num">{t("symbol.daily")}: {v.risk.daily_pnl_pct === null ? "—" : `${v.risk.daily_pnl_pct.toFixed(2)}%`}</div>
            </div>
          )}
        </Panel>
        <Panel title={t("symbol.learning")}>
          <div className="text-xs space-y-1">
            <div>{t("symbol.weights")}: v{v.learning?.version ?? 0}</div>
            <div className="ink-3">{t("symbol.quarantined")}: {v.learning?.quarantined.join(", ") || "—"}</div>
            <div className="ink-3">{t("symbol.lastRun")}: {v.health?.last_run_at ?? "—"}</div>
          </div>
        </Panel>
      </div>

      <div className="grid gap-4 lg:grid-cols-2">
        <Panel title={t("symbol.positions")} subtitle={t("symbol.positionsHint")}>
          {symPositions.length === 0 && !(v.paper_trades ?? []).length ? <Empty>{t("symbol.noPositions")}</Empty> : (
            <div>
              {symPositions.map((p, i) => (
                <Row key={`p${i}`}>
                  <Pill tone="neutral">{t("symbol.live")}</Pill>
                  <span>{String(p.side ?? p.type ?? "")}</span>
                  <span className="num">{String(p.volume ?? "")}</span>
                  <span className="num ink-3">{String(p.price_open ?? p.open_price ?? "")}</span>
                  <span className="num" style={{ color: Number(p.profit ?? 0) >= 0 ? "var(--good)" : "var(--critical)" }}>{String(p.profit ?? "")}</span>
                </Row>
              ))}
              {(v.paper_trades ?? []).map((p, i) => (
                <Row key={`t${i}`}>
                  <Pill tone="muted">paper</Pill>
                  <span>{String(p.direction ?? "")}</span>
                  <span className="ink-3">{String(p.account ?? "")}</span>
                  <span>{String(p.status ?? "")}</span>
                  <span className="num">{p.r === null || p.r === undefined ? "" : `${String(p.r)}R`}</span>
                </Row>
              ))}
            </div>
          )}
        </Panel>
        <Panel title={t("symbol.health")}>
          {healthRows.length === 0 ? <Empty>{t("symbol.noRun")}</Empty> : (
            <div className="flex flex-wrap gap-1">
              {healthRows.map(([id, h]) => (
                <span key={id} title={h.error ?? ""} className="px-2 py-0.5 rounded-md text-[0.6875rem] font-mono"
                  style={{ background: "var(--panel-raised)", color: h.skipped ? "var(--warning)" : h.ok === false ? "var(--critical)" : "var(--good)" }}>
                  {id} {typeof h.ms === "number" ? `${h.ms.toFixed(0)}ms` : ""}
                </span>
              ))}
            </div>
          )}
        </Panel>
      </div>

      <div className="grid gap-4 lg:grid-cols-2">
        <Panel title={t("symbol.news")} subtitle={newsTag}>
          {headlines.length === 0 ? <Empty>{news.ok ? t("symbol.noNews") : news.error}</Empty> : headlines.map((h, i) => (
            <Row key={i}>
              <span className="ink-3 num">{String(h.published_tehran ?? "")}</span>
              <span className="flex-1">{String(h.title_fa ?? h.title ?? "")}</span>
              <span className="ink-3">{String(h.source_fa ?? h.source_name ?? "")}</span>
            </Row>
          ))}
        </Panel>
        <Panel title={t("symbol.calendar")}>
          {v.calendar === null || v.calendar === undefined ? <Empty>{t("symbol.calendarOff")}</Empty>
            : v.calendar.length === 0 ? <Empty>{t("symbol.noEvents")}</Empty>
            : v.calendar.map((e, i) => (
              <Row key={i}><span className="num ink-3">{e.time.slice(0, 16).replace("T", " ")} UTC</span><Pill tone="warning">{e.currency}</Pill><span>{e.title}</span></Row>
            ))}
        </Panel>
      </div>
    </div>
  );
}
