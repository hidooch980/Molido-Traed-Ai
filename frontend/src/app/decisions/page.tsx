import Link from "next/link";

import { InstrumentLinks } from "@/components/InstrumentLinks";
import { Empty, Offline, Panel, Stat, StatusBadge } from "@/components/ui";
import { api } from "@/lib/api";
import { getT } from "@/lib/locale";

export const dynamic = "force-dynamic";

/**
 * The whole chain, gate by gate, and the one that closed.
 *
 * Every other page in this app answers a piece of the question. This one runs
 * all eighteen modules in order and reports where the answer stopped, which
 * turns "no trade" from a shrug into a specific, checkable statement: not
 * "nothing today" but "the expected-value gate refused, because nothing has
 * been calibrated against a resolved outcome yet".
 *
 * The stages after the stopping point are shown greyed rather than hidden.
 * Hiding them would make a chain that stopped at stage 3 look like a chain
 * with three stages, and the reader would have no way to tell a gate that
 * passed from a gate that was never reached.
 *
 * `reached_intent` is not permission. The chain ends at an intent; whether
 * that intent is ever sent is `app.execution.safety`'s question, and it asks
 * its own — which is why the response carries `authorises_execution: false`
 * and this page repeats it rather than rendering a tradeable-looking badge.
 */
export default async function DecisionsPage({
  searchParams,
}: {
  searchParams: Promise<{ instrument?: string }>;
}) {
  const { t } = await getT();
  const params = await searchParams;
  const instruments = await api.instruments();
  if (!instruments.ok) return <Offline error={instruments.error} />;

  const rows = instruments.data;
  if (rows.length === 0) return <Empty>{t("markets.empty")}</Empty>;

  const selectedId = params.instrument ?? rows[0].id;
  const selectedSymbol = rows.find((x) => x.id === selectedId)?.symbol;
  const trace = await api.decisionChain(selectedId);

  return (
    <div className="space-y-6">
      <header className="flex items-end justify-between gap-4 flex-wrap">
        <div>
          <h1 className="display">{t("decisions.title")}</h1>
          <p className="text-xs ink-3 mt-0.5 max-w-2xl">{t("decisions.subtitle")}</p>
        </div>
        {rows.length > 1 && (
          <div className="flex gap-1.5 flex-wrap max-w-lg justify-end">
            {rows.slice(0, 12).map((x) => (
              <Link
                key={x.id}
                href={`/decisions?instrument=${x.id}`}
                className="pill"
                style={{
                  color: x.id === selectedId ? "var(--accent)" : "var(--ink-3)",
                  borderColor: x.id === selectedId ? "var(--accent)" : "var(--border-strong)",
                }}
              >
                {x.symbol}
              </Link>
            ))}
          </div>
        )}
      </header>

      <InstrumentLinks
        instrumentId={selectedId}
        symbol={selectedSymbol}
        current="/decisions"
        t={t}
      />

      {!trace.ok ? (
        <Offline error={trace.error} />
      ) : (
        <>
          <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
            <Stat
              label={t("decisions.stoppedAt")}
              value={trace.data.stopped_at ?? t("decisions.completed")}
              tone={trace.data.stopped_at ? "neutral" : "good"}
              hint={t("decisions.stoppedAtHint")}
            />
            <Stat
              label={t("decisions.reachedIntent")}
              value={trace.data.reached_intent ? t("decisions.yes") : t("decisions.no")}
              tone="neutral"
              hint={t("decisions.reachedIntentHint")}
            />
            <Stat
              label={t("decisions.permittedRisk")}
              value={
                trace.data.permitted_risk_r !== null
                  ? `${trace.data.permitted_risk_r.toFixed(2)} R`
                  : "—"
              }
              hint={t("decisions.permittedRiskHint")}
            />
            <Stat
              label={t("decisions.geometry")}
              value={`${trace.data.policy.stop_atr_multiple}× ATR · ${trace.data.policy.target_reward_risk}R`}
              hint={t("decisions.geometryHint")}
            />
          </div>

          <Panel
            title={t("decisions.chain")}
            subtitle={`${trace.data.symbol} · ${trace.data.timeframe} · ${trace.data.as_of.slice(0, 16).replace("T", " ")}`}
          >
            <div className="scroll-x">
              <table className="data">
                <thead>
                  <tr>
                    <th>#</th>
                    <th>{t("decisions.stage")}</th>
                    <th>{t("decisions.verdict")}</th>
                    <th>{t("decisions.detail")}</th>
                  </tr>
                </thead>
                <tbody>
                  {trace.data.stages.map((stage, index) => (
                    <tr key={stage.stage}>
                      <td className="num ink-3">{index + 1}</td>
                      <td className="font-semibold num">{stage.stage}</td>
                      <td>
                        <StatusBadge
                          status={stage.passed ? "good" : "warning"}
                          label={stage.passed ? t("decisions.passed") : t("decisions.stopped")}
                        />
                      </td>
                      <td className="ink-2 text-xs">{stage.detail}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <p className="p-4 text-xs ink-3 leading-relaxed">
              {t("decisions.notPermission")}
            </p>
          </Panel>

          <Panel title={t("decisions.whyItStops")}>
            <p className="p-4 text-xs ink-3 leading-relaxed">{t("decisions.whyItStopsBody")}</p>
          </Panel>
        </>
      )}
    </div>
  );
}
