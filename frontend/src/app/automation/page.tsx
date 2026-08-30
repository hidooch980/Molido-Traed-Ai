import { Offline, Panel, Stat, StatusBadge } from "@/components/ui";
import { api } from "@/lib/api";
import { getT } from "@/lib/locale";

export const dynamic = "force-dynamic";

/**
 * What can reach this system from outside, and what it is allowed to ask for.
 *
 * Both panels describe refusals, and the refusals are the design. An unset
 * webhook secret means "not configured to receive webhooks" and never "accept
 * everything" — those two readings of the same empty string are the difference
 * between a closed door and an open one, and a system that conflates them
 * fails open at the worst possible moment.
 *
 * The chat allowlist is short because a chat transport authenticates a channel
 * rather than a person. Anyone holding the bot token is indistinguishable from
 * the owner, so the channel answers questions and does nothing else.
 */
export default async function AutomationPage() {
  const { t } = await getT();
  const [hooks, commands] = await Promise.all([api.webhooks(), api.commands()]);
  if (!hooks.ok) return <Offline error={hooks.error} />;

  const h = hooks.data;

  return (
    <div className="space-y-6">
      <header className="page-header">
        <div className="min-w-0">
          <h1 className="display">{t("automation.title")}</h1>
        <p className="text-xs ink-3 mt-0.5 max-w-3xl">{t("automation.subtitle")}</p>
      </div>
      </header>

      <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
        <Stat
          label={t("automation.secret")}
          value={h.secret_configured ? t("automation.configured") : t("automation.notConfigured")}
          tone={h.secret_configured ? "good" : "neutral"}
          hint={t("automation.secretHint")}
        />
        <Stat
          label={t("automation.maxAge")}
          value={`${h.max_age_seconds}s`}
          hint={t("automation.maxAgeHint")}
        />
        <Stat
          label={t("automation.allowed")}
          value={String(h.verified_webhooks_may.length)}
          hint={t("automation.allowedHint")}
        />
        <Stat
          label={t("automation.canTrade")}
          value={t("automation.no")}
          tone="good"
          hint={t("automation.canTradeHint")}
        />
      </div>

      <Panel title={t("automation.signing")} subtitle={h.signature}>
        <div className="scroll-x">
          <table className="data">
            <tbody>
              <tr>
                <td className="font-semibold">{t("automation.whyConstantTime")}</td>
                <td className="ink-2 text-xs">{h.why_constant_time}</td>
              </tr>
              <tr>
                <td className="font-semibold">{t("automation.whyMaxAge")}</td>
                <td className="ink-2 text-xs">{h.why_max_age}</td>
              </tr>
              <tr>
                <td className="font-semibold">{t("automation.unsetMeans")}</td>
                <td className="ink-2 text-xs">{h.unset_secret_means}</td>
              </tr>
            </tbody>
          </table>
        </div>
      </Panel>

      <Panel title={t("automation.whatAVerifiedCallMayAsk")} subtitle={t("automation.allowlist")}>
        <div className="p-4 flex flex-wrap gap-2">
          {h.verified_webhooks_may.map((command) => (
            <span key={command} className="pill">
              {command}
            </span>
          ))}
        </div>
        {commands.ok && (
          <p className="px-4 pb-4 text-xs ink-3 leading-relaxed">{commands.data.why}</p>
        )}
      </Panel>

      <Panel title={t("automation.whatItCannotDo")}>
        <div className="scroll-x">
          <table className="data">
            <tbody>
              <tr>
                <td className="font-semibold">{t("automation.placeOrder")}</td>
                <td>
                  <StatusBadge status="good" label={t("automation.no")} />
                </td>
              </tr>
              <tr>
                <td className="font-semibold">{t("automation.changeLimits")}</td>
                <td>
                  <StatusBadge status="good" label={t("automation.no")} />
                </td>
              </tr>
              <tr>
                <td className="font-semibold">{t("automation.readState")}</td>
                <td>
                  <StatusBadge status="neutral" label={t("automation.yes")} />
                </td>
              </tr>
            </tbody>
          </table>
        </div>
        <p className="p-4 text-xs ink-3 leading-relaxed">{t("automation.whyReadOnlyBody")}</p>
      </Panel>
    </div>
  );
}
