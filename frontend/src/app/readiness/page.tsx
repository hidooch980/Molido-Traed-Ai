import { Offline, Panel, Stat, StatusBadge } from "@/components/ui";
import { api } from "@/lib/api";
import { getT } from "@/lib/locale";

export const dynamic = "force-dynamic";

/**
 * When the forward measurement will be able to answer the question.
 *
 * The question people actually ask is "when can I connect a real account", and
 * the honest form of it is not a countdown to yes - it is when there will be
 * enough evidence to answer at all. So this page leads with what is still
 * unmet and says plainly what the date means, rather than putting a number in
 * a big box and letting the reader supply the optimism.
 *
 * Progress is counted in instants. The decision count is eight times larger and
 * appears as a hint rather than as the figure: a bar drawn from it would show
 * eight times the evidence that exists, which is exactly the error the
 * historical measurement had to correct for.
 */
const SOURCES = ["yfinance", "metatrader"] as const;

export default async function ReadinessPage() {
  const { t } = await getT();
  const view = await api.evidence();
  if (!view.ok) return <Offline error={view.error} />;

  const label = (source: string) =>
    source === "metatrader" ? t("journal.broker") : t("journal.public");

  return (
    <div className="space-y-6">
      <header className="page-header">
        <div className="min-w-0">
          <h1 className="display">{t("readiness.title")}</h1>
        <p className="text-xs ink-3 mt-0.5 max-w-3xl">{t("readiness.subtitle")}</p>
      </div>
      </header>

      {SOURCES.map((source) => {
        const r = view.data.by_source[source];
        if (!r) return null;
        return (
          <Panel key={source} title={label(source)}>
            <div className="p-4 space-y-4">
              <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
                <Stat
                  label={t("readiness.instants")}
                  value={String(r.instants_resolved)}
                  hint={`${r.decisions_resolved} ${t("readiness.decisions")} · ${t(
                    "readiness.instantsHint",
                  )}`}
                />
                <Stat
                  label={t("readiness.needed")}
                  value={r.instants_needed != null ? String(r.instants_needed) : "—"}
                />
                <Stat
                  label={t("readiness.rate")}
                  value={
                    r.instants_per_week != null ? String(r.instants_per_week) : "—"
                  }
                  hint={t("readiness.rateHint")}
                />
                <Stat
                  label={t("readiness.date")}
                  value={r.answerable_on ?? t("readiness.noDate")}
                  tone="warning"
                  hint={`${
                    r.spread_is_measured
                      ? t("readiness.spreadMeasured")
                      : t("readiness.spreadAssumed")
                  } · ${t("readiness.spread")} ${r.spread_r} R`}
                />
              </div>

              {/* Drawn from instants. From decisions it would show eight times
                  the progress that exists. */}
              {r.fraction != null && (
                <div className="h-1.5 w-full rounded bg-[var(--line)] overflow-hidden">
                  <div
                    className="h-full bg-[var(--accent)]"
                    style={{ width: `${Math.max(0.5, r.fraction * 100)}%` }}
                  />
                </div>
              )}

              <p className="text-xs ink-3 leading-relaxed">{r.what_the_date_means}</p>
              <p className="text-xs ink-3 leading-relaxed">{r.the_assumption}</p>

              {r.open_requirements.length > 0 && (
                <div className="space-y-1">
                  <StatusBadge status="warning" label={t("readiness.stillOpen")} />
                  <ul className="text-xs ink-3 leading-relaxed list-disc ps-5 space-y-1">
                    {r.open_requirements.map((note: string) => (
                      <li key={note}>{note}</li>
                    ))}
                  </ul>
                </div>
              )}

              {r.met_requirements.length > 0 && (
                <div className="space-y-1">
                  <StatusBadge status="good" label={t("readiness.alreadyMet")} />
                  <ul className="text-xs ink-3 leading-relaxed list-disc ps-5 space-y-1">
                    {r.met_requirements.map((note: string) => (
                      <li key={note}>{note}</li>
                    ))}
                  </ul>
                </div>
              )}
            </div>
          </Panel>
        );
      })}

      <Panel title={t("readiness.andThen")}>
        <p className="p-4 text-xs ink-3 leading-relaxed">{view.data.and_then_what}</p>
      </Panel>
    </div>
  );
}
