import { InstrumentLinks } from "@/components/InstrumentLinks";
import { Empty, Offline, Panel, Pill, Stat, StatusBadge } from "@/components/ui";
import { api } from "@/lib/api";
import { getT } from "@/lib/locale";

export const dynamic = "force-dynamic";

/**
 * What the brain currently thinks, and every block it thought it with.
 *
 * `/brain/think` and `/world-state` have answered over the API since phase 14
 * and were unreachable from the site, so the reasoning was only visible to
 * somebody willing to curl it. This page shows the chain rather than a verdict:
 * the decision on its own is the least interesting part, and a screen that
 * showed only "BUY, conviction 0.62" would be asking to be trusted.
 *
 * The world-state panel deliberately renders unavailable blocks rather than
 * hiding them. A missing block is a fact about what the system could not see,
 * and hiding it would make a partial picture look complete.
 */
export default async function BrainPage({
  searchParams,
}: {
  searchParams: Promise<{ instrument?: string }>;
}) {
  const { t } = await getT();
  const params = await searchParams;
  const instruments = await api.instruments();
  if (!instruments.ok) return <Offline error={instruments.error} />;
  if (instruments.data.length === 0) {
    return (
      <Panel title={t("brain.title")}>
        <Empty>{t("markets.empty")}</Empty>
      </Panel>
    );
  }

  const selectedId = params.instrument ?? instruments.data[0].id;
  const selectedSymbol = instruments.data.find((x) => x.id === selectedId)?.symbol;
  const [proposal, state] = await Promise.all([
    api.proposal(selectedId),
    api.worldState(selectedId),
  ]);

  const decisionTone = (decision: string) =>
    decision === "wait" ? "neutral" : ("good" as const);

  return (
    <div className="space-y-6">
      <header className="flex items-end justify-between gap-4 flex-wrap">
        <div>
          <h1 className="display">{t("brain.title")}</h1>
          <p className="page-lede">{t("brain.subtitle")}</p>
        </div>
        <div className="flex flex-wrap gap-1.5">
          {instruments.data.slice(0, 12).map((x) => (
            <a
              key={x.id}
              href={`/brain?instrument=${x.id}`}
              className="pill"
              style={{
                color: x.id === selectedId ? "var(--accent)" : "var(--ink-3)",
                borderColor: x.id === selectedId ? "var(--accent)" : "var(--border-strong)",
              }}
            >
              {x.symbol}
            </a>
          ))}
        </div>
      </header>

      <InstrumentLinks
        instrumentId={selectedId}
        symbol={selectedSymbol}
        current="/brain"
        t={t}
      />

      {!proposal.ok ? (
        <Offline error={proposal.error} />
      ) : (
        <>
          <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
            <Stat
              label={t("brain.decision")}
              value={proposal.data.decision}
              tone={decisionTone(proposal.data.decision)}
            />
            <Stat
              label={t("brain.conviction")}
              value={proposal.data.conviction.toFixed(3)}
              hint={t("brain.convictionHint")}
            />
            <Stat
              label={t("brain.regime")}
              value={String(proposal.data.regime?.regime ?? "—")}
            />
            <Stat
              label={t("brain.authorises")}
              value={t("brain.no")}
              tone="neutral"
              hint={t("brain.authorisesHint")}
            />
          </div>

          {proposal.data.wait_reasons.length > 0 && (
            <Panel title={t("brain.whyWait")} subtitle={t("brain.whyWaitSubtitle")}>
              <ul className="p-4 space-y-2 text-xs ink-2">
                {proposal.data.wait_reasons.map((reason) => (
                  <li key={reason} className="flex gap-2.5">
                    <span style={{ color: "var(--ink-3)" }} aria-hidden="true">
                      ●
                    </span>
                    <span>{reason}</span>
                  </li>
                ))}
              </ul>
            </Panel>
          )}

          <Panel title={t("brain.council")} subtitle={t("brain.councilSubtitle")}>
            {proposal.data.council.length === 0 ? (
              <Empty>{t("brain.noOpinions")}</Empty>
            ) : (
              <div className="scroll-x">
                <table className="data">
                  <thead>
                    <tr>
                      <th>{t("brain.analyst")}</th>
                      <th>{t("brain.decision")}</th>
                      <th>{t("brain.conviction")}</th>
                      <th>{t("brain.reason")}</th>
                    </tr>
                  </thead>
                  <tbody>
                    {proposal.data.council.map((opinion) => (
                      <tr key={opinion.analyst}>
                        <td className="font-semibold num">{opinion.analyst}</td>
                        <td>
                          <StatusBadge
                            status={opinion.decision === "wait" ? "info" : "good"}
                            label={opinion.decision}
                          />
                        </td>
                        <td className="num ink-2">{opinion.conviction?.toFixed(3) ?? "—"}</td>
                        <td className="ink-3">{opinion.reason}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </Panel>

          {proposal.data.invalidation && (
            <Panel title={t("brain.invalidation")} subtitle={t("brain.invalidationSubtitle")}>
              <p className="p-4 text-xs ink-2">{proposal.data.invalidation}</p>
            </Panel>
          )}

          <Panel title={t("brain.stages")} subtitle={t("brain.stagesSubtitle")}>
            <div className="p-4 flex flex-wrap gap-1.5">
              {proposal.data.stages.map((stage) => (
                <Pill key={stage}>{stage}</Pill>
              ))}
            </div>
          </Panel>
        </>
      )}

      {state.ok && (
        <Panel title={t("brain.worldState")} subtitle={t("brain.worldStateSubtitle")}>
          <div className="scroll-x">
            <table className="data">
              <thead>
                <tr>
                  <th>{t("brain.block")}</th>
                  <th>{t("brain.available")}</th>
                  <th>{t("brain.detail")}</th>
                </tr>
              </thead>
              <tbody>
                {(
                  ["price", "session", "freshness", "features", "memory", "dna", "quality"] as const
                ).map((name) => {
                  const block = state.data[name];
                  return (
                    <tr key={name}>
                      <td className="font-semibold num">{name}</td>
                      <td>
                        <StatusBadge
                          status={block?.available ? "good" : "warning"}
                          label={block?.available ? t("brain.yes") : t("brain.no")}
                        />
                      </td>
                      <td className="ink-3">
                        {block?.available ? t("brain.measured") : (block?.reason ?? "—")}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        </Panel>
      )}
    </div>
  );
}
