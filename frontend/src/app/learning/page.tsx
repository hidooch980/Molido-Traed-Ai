import { Empty, Offline, Panel, Stat } from "@/components/ui";
import { api } from "@/lib/api";
import { getT } from "@/lib/locale";

export const dynamic = "force-dynamic";

/**
 * The lines this system judges evidence against, and why each one sits there.
 *
 * The numbers matter less than the fact that they are fixed in advance. A
 * promotion threshold chosen after seeing the result is not a threshold, and
 * the reason every row here carries a `why` is that a bar without a stated
 * reason gets quietly lowered the first time something interesting fails it.
 *
 * The registry is empty and says so. An empty champion slot rendered as a
 * blank panel would read as "no problems"; it means nothing has ever cleared
 * the bar, which is a different and much more important statement.
 */
export default async function LearningPage() {
  const { t } = await getT();
  const [thresholds, drift, registry] = await Promise.all([
    api.learningThresholds(),
    api.drift(),
    api.modelRegistry(),
  ]);
  if (!thresholds.ok) return <Offline error={thresholds.error} />;

  const { scorecard, registry: promo, drift: driftRules } = thresholds.data;

  return (
    <div className="space-y-6">
      <header className="page-header">
        <div className="min-w-0">
          <h1 className="display">{t("learning.title")}</h1>
          <p className="page-lede">{t("learning.subtitle")}</p>
        </div>
      </header>

      <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
        <Stat
          label={t("learning.minTrials")}
          value={String(scorecard.min_trials)}
          hint={t("learning.minTrialsHint")}
        />
        <Stat label={t("learning.confidence")} value={`z = ${scorecard.confidence_z}`} />
        <Stat
          label={t("learning.promotionSigma")}
          value={`${promo.promotion_sigma}σ`}
          hint={t("learning.promotionSigmaHint")}
        />
        <Stat
          label={t("learning.champion")}
          value={registry.ok && registry.data.champion ? "1" : "—"}
          tone="neutral"
          hint={t("learning.noChampionHint")}
        />
      </div>

      <Panel title={t("learning.scorecardRules")} subtitle={scorecard.why}>
        <div className="scroll-x">
          <table className="data">
            <thead>
              <tr>
                <th>{t("learning.rule")}</th>
                <th>{t("learning.value")}</th>
              </tr>
            </thead>
            <tbody>
              <tr>
                <td className="font-semibold num">min_trials</td>
                <td className="num ink-2">{scorecard.min_trials}</td>
              </tr>
              <tr>
                <td className="font-semibold num">confidence_z</td>
                <td className="num ink-2">{scorecard.confidence_z}</td>
              </tr>
            </tbody>
          </table>
        </div>
      </Panel>

      <Panel title={t("learning.promotion")} subtitle={promo.why}>
        <div className="scroll-x">
          <table className="data">
            <thead>
              <tr>
                <th>{t("learning.rule")}</th>
                <th>{t("learning.value")}</th>
              </tr>
            </thead>
            <tbody>
              <tr>
                <td className="font-semibold num">min_evaluation_sample</td>
                <td className="num ink-2">{promo.min_evaluation_sample}</td>
              </tr>
              <tr>
                <td className="font-semibold num">min_overlap</td>
                <td className="num ink-2">{promo.min_overlap}</td>
              </tr>
              <tr>
                <td className="font-semibold num">promotion_sigma</td>
                <td className="num ink-2">{promo.promotion_sigma}</td>
              </tr>
            </tbody>
          </table>
        </div>
      </Panel>

      <Panel title={t("learning.drift")} subtitle={driftRules.why}>
        <div className="scroll-x">
          <table className="data">
            <thead>
              <tr>
                <th>{t("learning.rule")}</th>
                <th>{t("learning.value")}</th>
              </tr>
            </thead>
            <tbody>
              <tr>
                <td className="font-semibold num">psi_shifted</td>
                <td className="num ink-2">{driftRules.psi_shifted}</td>
              </tr>
              <tr>
                <td className="font-semibold num">psi_broken</td>
                <td className="num ink-2">{driftRules.psi_broken}</td>
              </tr>
              <tr>
                <td className="font-semibold num">min_sample</td>
                <td className="num ink-2">{driftRules.min_sample}</td>
              </tr>
            </tbody>
          </table>
        </div>
        {drift.ok && (
          <p className="p-4 text-xs ink-3 leading-relaxed">
            {drift.data.feature_drift.reason ?? drift.data.note}
          </p>
        )}
      </Panel>

      <Panel title={t("learning.registry")} subtitle={t("learning.registrySubtitle")}>
        {!registry.ok || registry.data.versions.length === 0 ? (
          <div className="p-4 space-y-2">
            <Empty>{t("learning.noVersions")}</Empty>
            {registry.ok && <p className="text-xs ink-3 leading-relaxed">{registry.data.reason}</p>}
          </div>
        ) : (
          <div className="p-4 text-xs ink-2">{registry.data.versions.length}</div>
        )}
      </Panel>

      <Panel title={t("learning.whyFixed")}>
        <p className="p-4 text-xs ink-3 leading-relaxed">{t("learning.whyFixedBody")}</p>
      </Panel>
    </div>
  );
}
