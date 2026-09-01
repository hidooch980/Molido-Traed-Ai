import { TelegramSettings } from "@/components/TelegramSettings";
import { Offline, Panel, Stat } from "@/components/ui";
import { api } from "@/lib/api";
import { getT } from "@/lib/locale";

export const dynamic = "force-dynamic";

/**
 * The alert channel: what it is configured to do, and the form that configures
 * it.
 *
 * The status above the form is read from the running configuration rather than
 * from what was last saved here - a page that reports its own last write is a
 * page that cannot show a token somebody changed on the host.
 */
export default async function TelegramPage() {
  const { t } = await getT();
  const state = await api.telegram();
  if (!state.ok) return <Offline error={state.error} />;

  const data = state.data;

  return (
    <div className="space-y-6">
      <header className="page-header">
        <div className="min-w-0">
          <h1 className="display">{t("telegram.title")}</h1>
          <p className="page-lede">{t("telegram.subtitle")}</p>
        </div>
      </header>

      <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
        <Stat
          label={t("telegram.state")}
          value={data.ready ? t("telegram.ready") : t("telegram.notReady")}
          tone={data.ready ? "good" : "warning"}
        />
        <Stat label={t("telegram.recipients")} value={String(data.recipients ?? 0)} />
        <Stat label={t("telegram.source")} value={data.source ?? "—"} />
        <Stat
          label={t("telegram.reachable")}
          value={
            data.reachable === undefined
              ? "—"
              : data.reachable
                ? t("telegram.yes")
                : t("telegram.no")
          }
          tone={data.reachable === false ? "critical" : undefined}
        />
      </div>

      <Panel title={t("telegram.configure")} subtitle={t("telegram.configureHint")}>
        <TelegramSettings
          initial={{
            configured: data.configured,
            enabled: data.enabled,
            masked_token: data.masked_token,
            chat_ids: data.chat_ids ?? [],
            source: data.source,
          }}
          labels={{
            title: t("telegram.configure"),
            token: t("telegram.token"),
            tokenHint: t("telegram.tokenHint"),
            tokenKeep: t("telegram.tokenKeep"),
            chatIds: t("telegram.chatIds"),
            chatIdsHint: t("telegram.chatIdsHint"),
            enabled: t("telegram.enabled"),
            save: t("telegram.save"),
            saving: t("telegram.saving"),
            test: t("telegram.test"),
            testing: t("telegram.testing"),
            saved: t("telegram.saved"),
            testSent: t("telegram.testSent"),
            testFailed: t("telegram.testFailed"),
            failed: t("telegram.failed"),
            signInFirst: t("telegram.signInFirst"),
            configured: t("telegram.isConfigured"),
            notConfigured: t("telegram.notConfigured"),
            recipients: t("telegram.recipientsShort"),
            howTo: t("telegram.howTo"),
          }}
        />
      </Panel>

      <Panel title={t("telegram.limits")} subtitle={t("telegram.limitsHint")}>
        <ul className="text-sm space-y-2 ink-2">
          <li>{data.why_read_only ?? t("telegram.readOnly")}</li>
          {data.allowed_commands && data.allowed_commands.length > 0 && (
            <li dir="ltr" className="ink-3">
              {data.allowed_commands.join(" · ")}
            </li>
          )}
          {data.reason && <li className="ink-3">{data.reason}</li>}
        </ul>
      </Panel>
    </div>
  );
}
