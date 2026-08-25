import { Offline, Panel, Stat } from "@/components/ui";
import { api } from "@/lib/api";
import { getT } from "@/lib/locale";

export const dynamic = "force-dynamic";

/**
 * What the deployment is configured to do. Reading, not configuring:
 * configuration is changed in the environment on the server by a person, and
 * this page renders the redacted view the API publishes. If a credential ever
 * appeared here, the bug would be in the API's redaction, which is what the
 * backend contract tests grep for.
 */
export default async function SettingsPage() {
  const { t } = await getT();
  const settings = await api.systemSettings();
  if (!settings.ok) return <Offline error={settings.error} />;

  const { app, collector, ingestion, execution, retention } = settings.data;

  return (
    <div className="space-y-6">
      <header className="page-header">
        <div className="min-w-0">
          <h1 className="display">{t("settings.title")}</h1>
          <p className="page-lede">{t("settings.subtitle")}</p>
        </div>
      </header>

      <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
        <Stat label={t("settings.environment")} value={String(app.env)} />
        <Stat
          label={t("settings.execution")}
          value={execution.enabled ? t("posture.on") : t("posture.off")}
          tone={execution.enabled ? "warning" : "good"}
        />
        <Stat
          label={t("settings.dryRun")}
          value={execution.dry_run ? t("posture.on") : t("posture.off")}
          tone={execution.dry_run ? "good" : "warning"}
        />
        <Stat
          label={t("settings.collectorInterval")}
          value={`${collector.interval_seconds}s`}
          hint={`${collector.watchlist_size} ${t("settings.watchlistEntries")}`}
        />
      </div>

      <Panel title={t("settings.connections")} subtitle={t("settings.connectionsSubtitle")}>
        <div className="p-4 grid gap-3 sm:grid-cols-2 text-xs">
          <div>
            <div className="eyebrow mb-1">{t("settings.database")}</div>
            <div className="num ink-2">{String(app.database)}</div>
          </div>
          <div>
            <div className="eyebrow mb-1">Redis</div>
            <div className="num ink-2">{String(app.redis)}</div>
          </div>
        </div>
      </Panel>

      <Panel title={t("settings.watchedSymbols")} subtitle={collector.provider}>
        <div className="p-4 flex flex-wrap gap-1.5">
          {collector.symbols.map((symbol) => (
            <span key={symbol} className="pill num">
              {symbol}
            </span>
          ))}
        </div>
      </Panel>

      <Panel title={t("settings.ingestion")} subtitle={t("settings.ingestionSubtitle")}>
        <div className="p-4 grid gap-3 sm:grid-cols-2 xl:grid-cols-4 text-xs">
          <div>
            <div className="eyebrow mb-1">{t("settings.maxRetries")}</div>
            <div className="num ink-2">{ingestion.max_retries}</div>
          </div>
          <div>
            <div className="eyebrow mb-1">{t("settings.backoff")}</div>
            <div className="num ink-2">{ingestion.backoff_base_seconds}s</div>
          </div>
          <div>
            <div className="eyebrow mb-1">{t("settings.chunkDays")}</div>
            <div className="num ink-2">{ingestion.chunk_days}</div>
          </div>
          <div>
            <div className="eyebrow mb-1">{t("settings.minQuality")}</div>
            <div className="num ink-2">{ingestion.min_quality_score}</div>
          </div>
        </div>
      </Panel>

      <Panel title={t("settings.retention")} subtitle={t("settings.retentionSubtitle")}>
        <div className="scroll-x">
          <table className="data">
            <thead>
              <tr>
                <th>{t("settings.table")}</th>
                <th>{t("settings.keepDays")}</th>
                <th>{t("settings.why")}</th>
                <th>{t("settings.neverDeletes")}</th>
              </tr>
            </thead>
            <tbody>
              {retention.map((policy) => (
                <tr key={policy.table}>
                  <td className="font-semibold num">{policy.table}</td>
                  <td className="num ink-2">{policy.keep_days}</td>
                  <td className="ink-3">{policy.reason}</td>
                  <td className="ink-3">{policy.protect_reason ?? "—"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Panel>

      <Panel title={t("settings.readOnly")}>
        <p className="p-4 text-xs ink-3 leading-relaxed">{t("settings.readOnlyBody")}</p>
      </Panel>
    </div>
  );
}
