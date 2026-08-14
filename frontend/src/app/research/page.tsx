import { Offline, Panel, Stat, StatusBadge } from "@/components/ui";
import { api } from "@/lib/api";
import { getT } from "@/lib/locale";

export const dynamic = "force-dynamic";

/**
 * The one page whose job is to say "nothing yet", clearly.
 *
 * Every other page reports what the system knows. This one reports what it has
 * failed to establish — which is the more useful fact when somebody is deciding
 * whether to trust it with money, and the fact a dashboard is most tempted to
 * leave out.
 *
 * The rejected claim is shown with its numbers rather than hidden. "We tried
 * nothing" and "we tried this and it did not clear the bar" are different
 * facts, and hiding the second invites the same rule being proposed again next
 * month as a new idea.
 */
export default async function ResearchPage() {
  const { t } = await getT();
  const research = await api.research();
  if (!research.ok) return <Offline error={research.error} />;

  const { live_trading_allowed, reason, proven, rejected, requirements, sample_needed, note } =
    research.data;

  return (
    <div className="space-y-4">
      <header>
        <h1 className="text-xl font-bold">{t("research.title")}</h1>
        <p className="text-xs ink-3 mt-0.5 max-w-3xl">{t("research.subtitle")}</p>
      </header>

      <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
        <Stat
          label={t("research.provenEdges")}
          value={String(proven.length)}
          tone={proven.length ? "good" : "warning"}
          hint={t("research.provenHint")}
        />
        <Stat label={t("research.rejected")} value={String(rejected.length)} />
        <Stat
          label={t("research.forTwoPoints")}
          value={String(sample_needed.for_a_2pp_edge)}
          hint={t("research.perArm")}
        />
        <Stat
          label={t("research.forHalfPoint")}
          value={String(sample_needed.for_a_half_pp_edge)}
          hint={t("research.perArm")}
        />
      </div>

      <Panel title={t("research.verdict")}>
        <div className="p-4 space-y-2">
          <StatusBadge
            status={live_trading_allowed ? "good" : "warning"}
            label={live_trading_allowed ? t("research.allowed") : t("research.notAllowed")}
          />
          <p className="text-xs ink-3 leading-relaxed">{reason}</p>
        </div>
      </Panel>

      <Panel title={t("research.bar")} subtitle={t("research.barSubtitle")}>
        <ol className="p-4 space-y-2 text-xs ink-3 leading-relaxed">
          {requirements.map((requirement, index) => (
            <li key={requirement}>
              <span className="num me-1.5">{index + 1}.</span>
              {requirement}
            </li>
          ))}
        </ol>
      </Panel>

      {rejected.map((claim) => (
        <Panel key={claim.key} title={`${t("research.testedRejected")}: ${claim.key}`}>
          <div className="p-4 space-y-3">
            <p className="text-xs ink-3 leading-relaxed">{claim.description}</p>

            <div className="scroll-x">
              <table className="data">
                <tbody>
                  {Object.entries(claim.evidence).map(([field, value]) => (
                    <tr key={field}>
                      <td className="ink-3">{field}</td>
                      <td className="num">{String(value)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>

            <div className="text-xs leading-relaxed">
              <p className="font-medium">{t("research.whyItFailed")}</p>
              <ul className="mt-1 space-y-1 ink-3">
                {claim.verdict.failures.map((failure) => (
                  <li key={failure}>— {failure}</li>
                ))}
              </ul>
            </div>
          </div>
        </Panel>
      ))}

      <p className="text-xs ink-3 leading-relaxed">{note}</p>
    </div>
  );
}
