import { Offline, Panel, Stat } from "@/components/ui";
import { TerminalAdmin } from "@/components/TerminalAdmin";
import { api } from "@/lib/api";
import { getT } from "@/lib/locale";

export const dynamic = "force-dynamic";

/**
 * The terminals that feed this platform, and which of them are awake.
 *
 * Two questions live here and they are not the same question. "Which accounts
 * have I told the platform about" is configuration. "Which of them sent
 * anything in the last minute" is evidence. A page answering only the first
 * would show eleven healthy-looking rows for eleven terminals that were all
 * switched off, which is the failure this whole screen exists to prevent.
 *
 * So the headline figures are registered *and* publishing, side by side, and
 * the gap between them is the number worth looking at.
 */
export default async function TerminalsPage() {
  const { t } = await getT();
  const terminals = await api.terminals();

  if (!terminals.ok) return <Offline error={terminals.error} />;

  const { terminals: rows, total, publishing } = terminals.data;
  const active = rows.filter((r) => r.is_active).length;
  // Only active terminals can be silent. One switched off on purpose is not a
  // fault, and counting it as one would make the number cry wolf.
  const silent = rows.filter((r) => r.is_active && !r.publishing).length;

  return (
    <div className="space-y-6">
      <header className="page-header">
        <div className="min-w-0">
          <h1 className="display">{t("terminals.title")}</h1>
          <p className="page-lede">{t("terminals.subtitle")}</p>
        </div>
      </header>

      <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
        <Stat label={t("terminals.registered")} value={String(total)} />
        <Stat label={t("terminals.active")} value={String(active)} />
        <Stat
          label={t("terminals.publishingNow")}
          value={String(publishing)}
          tone={publishing > 0 ? "good" : "neutral"}
          hint={t("terminals.publishingHint")}
        />
        <Stat
          label={t("terminals.silent")}
          value={String(silent)}
          tone={silent > 0 ? "warning" : "good"}
          hint={t("terminals.silentHint")}
        />
      </div>

      <Panel title={t("terminals.yours")} subtitle={t("terminals.yoursSubtitle")}>
        <div className="p-4">
          <TerminalAdmin
            labels={{
              key: t("terminals.key"),
              keyHint: t("terminals.keyHint"),
              label: t("terminals.label"),
              labelHint: t("terminals.labelHint"),
              broker: t("terminals.broker"),
              kind: t("terminals.kind"),
              kindHint: t("terminals.kindHint"),
              add: t("terminals.add"),
              adding: t("terminals.adding"),
              added: t("terminals.added"),
              failed: t("terminals.failed"),
              noTerminals: t("terminals.none"),
              refused: t("terminals.refused"),
              colKey: t("terminals.key"),
              colLabel: t("terminals.label"),
              colBroker: t("terminals.broker"),
              colState: t("terminals.state"),
              publishing: t("terminals.statePublishing"),
              silent: t("terminals.stateSilent"),
              off: t("terminals.stateOff"),
              disable: t("terminals.disable"),
              enable: t("terminals.enable"),
              neverPublished: t("terminals.neverPublished"),
              secondsAgo: t("terminals.secondsAgo"),
              nextSteps: t("terminals.nextSteps"),
            }}
            terminals={rows}
            refused={false}
            publishUrl="https://trade.molido.shop/api/v1/bridge/publish"
          />
        </div>
      </Panel>

      <Panel title={t("terminals.noCredentials")}>
        <p className="p-4 text-xs ink-3 leading-relaxed">
          {t("terminals.noCredentialsBody")}
        </p>
      </Panel>
    </div>
  );
}
