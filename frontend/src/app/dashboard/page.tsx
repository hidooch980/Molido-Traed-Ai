import Link from "next/link";

import { AnalogClock } from "@/components/AnalogClock";
import { Empty, Offline, Panel, Pill, Sparkline, Stat, StatusBadge } from "@/components/ui";
import { api } from "@/lib/api";
import { getLocale, getT } from "@/lib/locale";

export const dynamic = "force-dynamic";

export default async function HomePage() {
  const { t } = await getT();
  const locale = await getLocale();
  const [health, instruments, clocks, accounts, equity, challenges] =
    await Promise.all([
      api.health(),
      api.instruments(),
      api.timezones(),
      api.accounts(),
      api.equity(200),
      // Prop accounts are a different kind of thing from the broker
      // connection above - one is "which terminal is signed in", the other is
      // "whose rules are we being measured against" - and a deployment can
      // easily have one without the other.
      api.challengeAccounts(),
    ]);

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

  // The faces the reader actually plans around. Tehran first for the Persian
  // reader because that is the clock they live on; London and New York because
  // those two opens move the FX book more than anything else on the page.
  //
  // Every face is anchored to `clocks.data.utc` - the server's instant - rather
  // than to the browser's. A machine four minutes fast would otherwise show a
  // different time next to session states computed on the server, and nothing
  // would say which of the two was wrong.
  const nowUtc = clocks.ok ? clocks.data.utc : null;
  const faceNames = locale === "fa"
    ? ["Tehran", "London", "New York"]
    : ["London", "New York", "Tokyo"];
  const faces = clocks.ok
    ? faceNames
        .map((name) => clocks.data.places.find((place) => place.name === name))
        .filter((place): place is NonNullable<typeof place> => Boolean(place))
    : [];

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
    <div className="space-y-6">
      {/* The one place on this application that gets display type. Every other
          heading is a label on a region; this is the sentence that says what
          the screen is, and on a page carrying forty figures it is the only
          thing that should be readable from across the room. */}
      <header className="page-header">
        <div className="min-w-0">
          <h1 className="display">{t("home.title")}</h1>
          <p className="page-lede">{t("home.subtitle")}</p>
        </div>
        {session?.ok && (
          <div className="flex items-center gap-2 shrink-0">
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

      {/* Both kinds of account, on the page that claims to show the state of
          the system.

          The empty case is the reason this renders unconditionally. Before
          this, a deployment with no broker signed in and no prop account drew
          nothing at all here - not "no accounts yet", just an absence, which
          reads as a feature that does not exist rather than as one nobody has
          used. The one question somebody opening this page has is "what am I
          trading with", and no answer is a worse answer than none. */}
      <Panel
        title={t("home.accounts")}
        subtitle={t("home.accountsSubtitle")}
        actions={
          <Link href="/accounts" className="text-xs" style={{ color: "var(--accent)" }}>
            {t("home.manageAccounts")} ←
          </Link>
        }
      >
        {!accounts.ok || !challenges.ok ? (
          <Empty>{t("home.accountsUnavailable")}</Empty>
        ) : !accounts.data.live_account.login &&
          challenges.data.accounts.length === 0 ? (
          <Empty>{t("home.noAccounts")}</Empty>
        ) : (
          <div className="scroll-x">
            <table className="data">
              <thead>
                <tr>
                  <th>{t("home.accountName")}</th>
                  <th>{t("home.accountType")}</th>
                  <th>{t("home.accountWhere")}</th>
                  <th className="num">{t("home.accountBalance")}</th>
                  <th>{t("home.accountState")}</th>
                </tr>
              </thead>
              <tbody>
                {accounts.data.live_account.login && (
                  <tr>
                    <td className="font-semibold" dir="ltr">
                      {accounts.data.live_account.login}
                    </td>
                    <td className="ink-2">
                      {accounts.data.live_account.is_demo
                        ? t("home.demo")
                        : t("home.realMoney")}
                    </td>
                    <td className="ink-3" dir="ltr">
                      {accounts.data.live_account.server ?? "—"}
                    </td>
                    <td className="num" dir="ltr">
                      {accounts.data.live_account.balance != null
                        ? `${accounts.data.live_account.balance.toLocaleString()} ${
                            accounts.data.live_account.currency ?? ""
                          }`
                        : "—"}
                    </td>
                    <td>
                      {/* Demo is the safe state, so it reads as good. Anything
                          that is not exactly trade_mode 0 is real money. */}
                      <Pill
                        tone={
                          accounts.data.live_account.is_demo ? "good" : "critical"
                        }
                      >
                        {accounts.data.live_account.is_demo
                          ? t("home.demo")
                          : t("home.realMoney")}
                      </Pill>
                    </td>
                  </tr>
                )}

                {challenges.data.accounts.map((account) => (
                  <tr key={account.id}>
                    <td className="font-semibold">{account.label}</td>
                    <td className="ink-2">
                      {[account.provider, account.program, account.phase]
                        .filter(Boolean)
                        .join(" · ") || t("home.propAccount")}
                    </td>
                    <td className="ink-3" dir="ltr">
                      {account.rulebook_key ?? "—"}
                    </td>
                    <td className="num" dir="ltr">
                      {account.starting_balance
                        ? `${account.starting_balance} ${account.currency ?? ""}`
                        : "—"}
                    </td>
                    <td>
                      {/* Confirmed is not decoration. Until the holder has
                          checked the transcribed rules against their own
                          contract, tracking stays shut - a confident verdict
                          about the wrong document is worse than no verdict. */}
                      <Pill tone={account.confirmed ? "good" : "warning"}>
                        {account.confirmed
                          ? t("home.tracked")
                          : t("home.unconfirmed")}
                      </Pill>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Panel>

      {/* The connected account, on the page people actually open.
          It lived only on /accounts, which meant the one fact that decides
          whether anything can trade - is a broker signed in, and is it a demo
          - was a click away from the dashboard that claims to show the state
          of the system. */}
      {accounts.ok && accounts.data.live_account.login && (
        <Panel title={t("home.account")} subtitle={accounts.data.reason}>
          <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4 p-4">
            <Stat
              label={t("home.accountLogin")}
              value={accounts.data.live_account.login}
              hint={accounts.data.live_account.server ?? ""}
            />
            <Stat
              label={t("home.accountKind")}
              value={
                accounts.data.live_account.is_demo
                  ? t("home.demo")
                  : t("home.realMoney")
              }
              /* Demo is the safe state here, so it reads as good. Anything
                 that is not exactly trade_mode 0 is real money and warns. */
              tone={accounts.data.live_account.is_demo ? "good" : "critical"}
              hint={`trade_mode ${accounts.data.live_account.trade_mode ?? "?"}`}
            />
            <Stat
              label={t("home.accountBalance")}
              value={
                accounts.data.live_account.balance != null
                  ? `${accounts.data.live_account.balance.toLocaleString()} ${
                      accounts.data.live_account.currency ?? ""
                    }`
                  : "—"
              }
            />
            <Stat
              label={t("home.accountEquity")}
              value={
                accounts.data.live_account.equity != null
                  ? `${accounts.data.live_account.equity.toLocaleString()} ${
                      accounts.data.live_account.currency ?? ""
                    }`
                  : "—"
              }
              /* Equity below balance is open positions carrying the entry
                 spread, not a result. Neutral on purpose. */
              hint={t("home.equityHint")}
            />
          </div>

          {/* The curve these samples describe. One has been written every
              fifteen minutes since the collector started and nothing had ever
              read them back - the data existed, so the feature looked
              present. */}
          {equity.ok && equity.data.points.length > 1 && (
            <div className="px-4 pb-4 space-y-1">
              <Sparkline
                values={equity.data.points.map((point) => point.equity)}
                width={640}
                height={56}
              />
              <div className="flex flex-wrap gap-x-4 text-[0.6875rem] ink-3">
                <span>
                  {equity.data.summary?.samples ?? 0} {t("home.samples")}
                </span>
                <span className="num">
                  {equity.data.points[0].at.slice(5, 16).replace("T", " ")}
                  {" → "}
                  {equity.data.points[equity.data.points.length - 1].at
                    .slice(5, 16)
                    .replace("T", " ")}
                </span>
                {equity.data.summary?.peak_equity != null && (
                  <span>
                    {t("home.peak")}{" "}
                    {equity.data.summary.peak_equity.toLocaleString()}
                  </span>
                )}
              </div>
            </div>
          )}
        </Panel>
      )}

      {nowUtc && faces.length > 0 && (
        <Panel title={t("home.clocks")} subtitle={t("home.clocksHint")}>
          <div className="flex flex-wrap items-start justify-center gap-6 p-4">
            {faces.map((place) => (
              <AnalogClock
                key={place.name}
                utcIso={nowUtc}
                offsetHours={place.offset}
                label={t(`clock.${place.name.replace(" ", "")}`)}
              />
            ))}
          </div>
        </Panel>
      )}

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
        <Panel title={t("home.live")}>
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
