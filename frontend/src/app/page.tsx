import Link from "next/link";

import { Empty, Offline, Panel, Sparkline, Stat, StatusBadge } from "@/components/ui";
import { api } from "@/lib/api";
import { getT } from "@/lib/locale";

export const dynamic = "force-dynamic";

export default async function HomePage() {
  const { t } = await getT();
  const [health, instruments] = await Promise.all([api.health(), api.instruments()]);

  const primary = instruments.ok ? instruments.data[0] : undefined;
  const [quality, session, bars] = await Promise.all([
    primary ? api.dataQuality(primary.id) : Promise.resolve(null),
    primary ? api.sessionStatus(primary.id) : Promise.resolve(null),
    primary ? api.bars(primary.id, "H1", 120) : Promise.resolve(null),
  ]);

  const dataset = quality?.ok ? quality.data.datasets[0] : undefined;
  const findings = quality?.ok ? quality.data.findings : [];
  const blocking = findings.filter(
    (f) => f.severity === "error" || f.severity === "critical",
  ).length;
  const closes = bars?.ok ? bars.data.bars.map((b) => b.close) : [];

  const liveItems: [string, string][] = [
    [t("live.ingestion"), t("live.ingestionBody")],
    [t("live.quality"), t("live.qualityBody")],
    [t("live.pit"), t("live.pitBody")],
    [t("live.calendar"), t("live.calendarBody")],
    [t("live.features"), t("live.featuresBody")],
    [t("live.dna"), t("live.dnaBody")],
    [t("live.memory"), t("live.memoryBody")],
    [t("live.episodes"), t("live.episodesBody")],
    [t("live.similarity"), t("live.similarityBody")],
  ];

  return (
    <div className="space-y-4">
      <header className="flex items-end justify-between gap-4 flex-wrap">
        <div>
          <h1 className="text-xl font-bold">{t("home.title")}</h1>
          <p className="text-xs ink-3 mt-0.5">{t("home.subtitle")}</p>
        </div>
        {session?.ok && (
          <div className="flex items-center gap-2">
            <StatusBadge
              status={session.data.is_open ? "good" : "info"}
              label={session.data.is_open ? t("home.marketOpen") : t("home.marketClosed")}
            />
            {session.data.active_sessions
              .filter((s) => s !== "off")
              .map((s) => (
                <span key={s} className="pill" style={{ color: "var(--ink-2)" }}>
                  {t(`session.${s}`)}
                </span>
              ))}
          </div>
        )}
      </header>

      {!health.ok && <Offline error={health.error} />}

      <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
        <Stat
          label={t("home.backend")}
          value={health.ok ? health.data.status : t("health.down")}
          tone={health.ok && health.data.status === "ok" ? "good" : "critical"}
          hint={health.ok ? `v${health.data.version} · ${health.data.environment}` : undefined}
        />
        <Stat
          label={t("home.quality")}
          value={dataset ? `${(dataset.score * 100).toFixed(1)}%` : "—"}
          tone={!dataset ? "neutral" : dataset.is_training_eligible ? "good" : "warning"}
          hint={
            dataset
              ? dataset.is_training_eligible
                ? t("home.eligible")
                : `${t("home.blocked")} (${blocking})`
              : t("home.notEvaluated")
          }
        />
        <Stat
          label={t("home.barsStored")}
          value={dataset ? dataset.actual_bars.toLocaleString() : "—"}
          hint={dataset ? `${dataset.open_findings} ${t("quality.findings")}` : undefined}
        />
        <Stat
          label={t("home.safeMode")}
          value={health.ok && health.data.safe_mode ? t("home.engaged") : t("home.clear")}
          tone={health.ok && health.data.safe_mode ? "warning" : "good"}
          hint={
            health.ok && health.data.safe_mode
              ? health.data.safe_mode_reasons.join(", ")
              : t("home.safeClear")
          }
        />
      </div>

      <div className="grid gap-4 lg:grid-cols-3">
        <Panel
          className="lg:col-span-2"
          title={primary ? `${primary.symbol} · H1 ${t("home.priceTitle")}` : t("home.priceTitle")}
          subtitle={t("home.priceSubtitle")}
          actions={
            primary && (
              <Link
                href={`/markets/${primary.id}`}
                className="text-xs"
                style={{ color: "var(--accent)" }}
              >
                {t("home.openInstrument")} ←
              </Link>
            )
          }
        >
          {closes.length > 1 ? (
            <div className="p-4 pt-3">
              <div className="flex items-baseline gap-3 mb-2">
                <span className="text-2xl font-semibold num">
                  {closes[closes.length - 1].toFixed(5)}
                </span>
                <span className="text-xs ink-3">
                  {closes.length} {t("common.bars")}
                </span>
              </div>
              <Sparkline values={closes} width={640} height={90} />
            </div>
          ) : (
            <Empty>{t("markets.empty")}</Empty>
          )}
        </Panel>

        <Panel title={t("home.findings")} subtitle={t("home.findingsSubtitle")}>
          {findings.length === 0 ? (
            <Empty>{t("common.empty")}</Empty>
          ) : (
            <ul className="divide-y" style={{ borderColor: "var(--border)" }}>
              {findings.slice(0, 6).map((f) => (
                <li key={f.id} className="px-4 py-2.5 flex items-start gap-2.5">
                  <StatusBadge status={f.severity} label={t(`severity.${f.severity}`)} />
                  <div className="min-w-0">
                    <div className="text-xs font-medium">{t(`issue.${f.issue}`)}</div>
                    <div className="text-[0.6875rem] ink-3 num">
                      {f.window_start.slice(0, 16).replace("T", " ")} · {f.affected_rows}{" "}
                      {t("quality.rows")}
                    </div>
                  </div>
                </li>
              ))}
            </ul>
          )}
        </Panel>
      </div>

      <div className="grid gap-4 lg:grid-cols-2">
        <Panel title={t("home.live")} subtitle={t("app.phase")}>
          <ul className="p-4 space-y-2 text-xs ink-2">
            {liveItems.map(([name, detail]) => (
              <li key={name} className="flex gap-2.5">
                <span style={{ color: "var(--good)" }} aria-hidden="true">
                  ●
                </span>
                <span>
                  <strong className="font-semibold" style={{ color: "var(--ink)" }}>
                    {name}
                  </strong>
                  <span className="ink-3"> — {detail}</span>
                </span>
              </li>
            ))}
          </ul>
        </Panel>

        <Panel title={t("home.notBuilt")} subtitle={t("home.notBuiltSubtitle")}>
          <p className="p-4 text-xs ink-3 leading-relaxed">{t("home.notBuiltBody")}</p>
        </Panel>
      </div>
    </div>
  );
}
