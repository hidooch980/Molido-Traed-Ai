import { Offline, Panel, Stat, StatusBadge } from "@/components/ui";
import { api } from "@/lib/api";
import { getT } from "@/lib/locale";

export const dynamic = "force-dynamic";

/**
 * How a result is judged here, shown by judging one.
 *
 * The scorecard is run against the real out-of-sample result this deployment
 * measured — 30% hit rate on a 2:1 target — rather than an invented example.
 * It needs 33.3% to break even, and the interval straddles that line, so the
 * verdict is "insufficient": not shown to work, not shown to fail. That is the
 * honest reading of the only evidence this system has, and it belongs on the
 * page rather than in a commit message.
 *
 * The walk-forward panel shows what leak-free costs. Each fold gives up
 * training samples to purging (outcomes that had not resolved when the fold
 * ended) and to the embargo (samples close enough to leak through serial
 * correlation). The number is larger than people expect, which is exactly why
 * it is drawn rather than described.
 */
export default async function LabPage() {
  const { t } = await getT();

  const [thresholds, walk, measured, breakeven] = await Promise.all([
    api.learningThresholds(),
    api.walkForward({ samples: 400, folds: 3, embargo_hours: 6, maturity_hours: 4 }),
    // The real number, not a demonstration: 12,755 out-of-sample trades at
    // 30.0%, which is what the 49-instrument scan actually returned.
    api.scorecard({ wins: 3827, losses: 8928, reward_risk: 2.0 }),
    api.breakeven(2.0),
  ]);

  if (!thresholds.ok) return <Offline error={thresholds.error} />;

  const card = measured.ok ? measured.data : null;
  const verdictTone = (verdict: string) =>
    verdict === "edge" ? "good" : verdict === "negative" ? "critical" : "warning";

  return (
    <div className="space-y-6">
      <header className="page-header">
        <div className="min-w-0">
          <h1 className="display">{t("lab.title")}</h1>
        <p className="text-xs ink-3 mt-0.5 max-w-3xl">{t("lab.subtitle")}</p>
      </div>
      </header>

      <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
        <Stat
          label={t("lab.trials")}
          value={card ? card.trials.toLocaleString("en-US") : "—"}
          hint={t("lab.trialsHint")}
        />
        <Stat
          label={t("lab.hitRate")}
          value={card?.hit_rate !== null && card ? `${(card.hit_rate * 100).toFixed(1)}%` : "—"}
          hint={
            card && card.hit_rate_95ci
              ? `95% CI ${(card.hit_rate_95ci[0] * 100).toFixed(1)}–${(card.hit_rate_95ci[1] * 100).toFixed(1)}%`
              : undefined
          }
        />
        <Stat
          label={t("lab.needed")}
          value={card ? `${(card.required_hit_rate * 100).toFixed(1)}%` : "—"}
          hint={t("lab.neededHint")}
        />
        <Stat
          label={t("lab.expectancy")}
          value={card ? `${card.expectancy_r >= 0 ? "+" : ""}${card.expectancy_r.toFixed(3)} R` : "—"}
          tone={card && card.expectancy_r > 0 ? "good" : "critical"}
          hint={t("lab.expectancyHint")}
        />
      </div>

      <Panel title={t("lab.measured")} subtitle={t("lab.measuredSubtitle")}>
        {card ? (
          <>
            <div className="p-4 flex items-center gap-3 flex-wrap">
              <StatusBadge status={verdictTone(card.verdict)} label={card.verdict} />
              <span className="text-xs ink-2">{card.reason}</span>
            </div>
            <div className="scroll-x">
              <table className="data">
                <tbody>
                  <tr>
                    <td className="font-semibold">{t("lab.realisedRR")}</td>
                    <td className="num ink-2">{card.realised_reward_risk.toFixed(2)}</td>
                  </tr>
                  <tr>
                    <td className="font-semibold">{t("lab.comparisons")}</td>
                    <td className="num ink-2">{card.comparisons}</td>
                  </tr>
                  <tr>
                    <td className="font-semibold">{t("lab.breakeven")}</td>
                    <td className="num ink-2">
                      {breakeven.ok
                        ? `${(breakeven.data.required_hit_rate * 100).toFixed(1)}%`
                        : "—"}
                    </td>
                  </tr>
                </tbody>
              </table>
            </div>
            <p className="p-4 text-xs ink-3 leading-relaxed">{t("lab.measuredBody")}</p>
          </>
        ) : (
          <p className="p-4 text-xs ink-3">{t("lab.noResult")}</p>
        )}
      </Panel>

      <Panel title={t("lab.walkForward")} subtitle={t("lab.walkForwardSubtitle")}>
        {walk.ok && walk.data.available ? (
          <>
            <div className="scroll-x">
              <table className="data">
                <thead>
                  <tr>
                    <th>{t("lab.fold")}</th>
                    <th>{t("lab.train")}</th>
                    <th>{t("lab.test")}</th>
                    <th>{t("lab.purged")}</th>
                    <th>{t("lab.embargoed")}</th>
                    <th>{t("lab.lost")}</th>
                  </tr>
                </thead>
                <tbody>
                  {walk.data.folds.map((fold) => (
                    <tr key={fold.index}>
                      <td className="num font-semibold">{fold.index + 1}</td>
                      <td className="num ink-2">{fold.train_size}</td>
                      <td className="num ink-2">{fold.test_size}</td>
                      <td className="num ink-3">{fold.purged}</td>
                      <td className="num ink-3">{fold.embargoed}</td>
                      <td className="num" style={{ color: "var(--warning)" }}>
                        {fold.purged + fold.embargoed}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <p className="p-4 text-xs ink-3 leading-relaxed">{t("lab.walkForwardBody")}</p>
          </>
        ) : (
          <p className="p-4 text-xs ink-3">
            {walk.ok ? walk.data.reason : t("lab.noResult")}
          </p>
        )}
      </Panel>

      <Panel title={t("lab.thresholds")} subtitle={thresholds.data.scorecard.why}>
        <div className="scroll-x">
          <table className="data">
            <tbody>
              <tr>
                <td className="font-semibold num">min_trials</td>
                <td className="num ink-2">{thresholds.data.scorecard.min_trials}</td>
              </tr>
              <tr>
                <td className="font-semibold num">confidence_z</td>
                <td className="num ink-2">{thresholds.data.scorecard.confidence_z}</td>
              </tr>
            </tbody>
          </table>
        </div>
      </Panel>

      <Panel title={t("lab.whyCorrected")}>
        <p className="p-4 text-xs ink-3 leading-relaxed">{t("lab.whyCorrectedBody")}</p>
      </Panel>
    </div>
  );
}
