import { Offline, Panel, Stat, StatusBadge } from "@/components/ui";
import { api } from "@/lib/api";
import { getT } from "@/lib/locale";

export const dynamic = "force-dynamic";

/**
 * What this deployment is connected to, and the rulebooks it can be judged by.
 *
 * Deliberately not a catalogue of firms to choose from. The obvious version of
 * this page is a list of brokers with their MetaTrader server strings, and a
 * wrong server string is the worst thing it could publish: it produces a
 * connection that never establishes, and the hunt for the reason goes
 * everywhere except the list that looked authoritative. A server name arrives
 * with the account, from the provider, in writing.
 *
 * MetaTrader gets three separate booleans rather than one status, because
 * "installed", "reachable" and "logged in" fail independently and a single
 * green dot would hide which one is missing.
 *
 * Every rulebook row carries the date it was read and an unconfirmed flag. A
 * prop firm's published page and one account's contract are not guaranteed to
 * be the same document, and only the account holder can close that gap.
 */
export default async function BrokersPage() {
  const { t } = await getT();
  const [brokers, books] = await Promise.all([api.brokers(), api.rulebooks()]);
  if (!brokers.ok) return <Offline error={brokers.error} />;

  const b = brokers.data;
  const pct = (v: number | string) =>
    typeof v === "number" ? `${(v * 100).toFixed(0)}%` : t("brokers.notImposed");

  return (
    <div className="space-y-4">
      <header>
        <h1 className="text-xl font-bold">{t("brokers.title")}</h1>
        <p className="text-xs ink-3 mt-0.5 max-w-2xl">{t("brokers.subtitle")}</p>
      </header>

      <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
        <Stat
          label={t("brokers.marketData")}
          value={b.market_data.name}
          tone="good"
          hint={t("brokers.marketDataHint")}
        />
        <Stat
          label={t("brokers.executionBroker")}
          value={b.execution.name}
          tone={b.execution.simulated ? "good" : "warning"}
          hint={b.execution.simulated ? t("brokers.simulated") : t("brokers.live")}
        />
        <Stat
          label={t("brokers.metatrader")}
          value={
            b.metatrader.reachable_from_application
              ? t("brokers.reachable")
              : t("brokers.notReachable")
          }
          tone="neutral"
          hint={t("brokers.metatraderHint")}
        />
        <Stat
          label={t("brokers.providers")}
          value={String(b.challenge_providers.length)}
          hint={b.challenge_providers.join(", ") || "—"}
        />
      </div>

      <Panel title={t("brokers.connections")} subtitle={t("brokers.connectionsSubtitle")}>
        <div className="scroll-x">
          <table className="data">
            <thead>
              <tr>
                <th>{t("brokers.what")}</th>
                <th>{t("brokers.name")}</th>
                <th>{t("brokers.role")}</th>
              </tr>
            </thead>
            <tbody>
              <tr>
                <td className="font-semibold">{t("brokers.marketData")}</td>
                <td className="num">{b.market_data.name}</td>
                <td className="ink-3 text-xs">{b.market_data.note}</td>
              </tr>
              <tr>
                <td className="font-semibold">{t("brokers.executionBroker")}</td>
                <td className="num">{b.execution.name}</td>
                <td className="ink-3 text-xs">{b.execution.note}</td>
              </tr>
            </tbody>
          </table>
        </div>
      </Panel>

      <Panel title={b.metatrader.name} subtitle={b.metatrader.role}>
        <div className="scroll-x">
          <table className="data">
            <tbody>
              <tr>
                <td className="font-semibold">{t("brokers.installed")}</td>
                <td>
                  <StatusBadge
                    status={b.metatrader.installed_on_host ? "good" : "warning"}
                    label={b.metatrader.installed_on_host ? t("brokers.yes") : t("brokers.no")}
                  />
                </td>
              </tr>
              <tr>
                <td className="font-semibold">{t("brokers.reachableRow")}</td>
                <td>
                  <StatusBadge
                    status={b.metatrader.reachable_from_application ? "good" : "warning"}
                    label={
                      b.metatrader.reachable_from_application
                        ? t("brokers.yes")
                        : t("brokers.no")
                    }
                  />
                </td>
              </tr>
            </tbody>
          </table>
        </div>
        <ul className="p-4 space-y-1.5 text-xs ink-3 leading-relaxed">
          {b.metatrader.blocked_by.map((reason) => (
            <li key={reason}>— {reason}</li>
          ))}
        </ul>
      </Panel>

      {books.ok && (
        <Panel
          title={t("brokers.rulebooks")}
          subtitle={`${books.data.rulebooks.length} · ${t("brokers.noneConfirmed")}`}
        >
          <div className="scroll-x">
            <table className="data">
              <thead>
                <tr>
                  <th>{t("brokers.program")}</th>
                  <th>{t("brokers.target")}</th>
                  <th>{t("brokers.daily")}</th>
                  <th>{t("brokers.total")}</th>
                  <th>{t("brokers.floor")}</th>
                  <th>{t("brokers.days")}</th>
                  <th>{t("brokers.read")}</th>
                </tr>
              </thead>
              <tbody>
                {books.data.rulebooks.map((book) => (
                  <tr key={book.key}>
                    <td className="font-semibold num">
                      {book.program} · {book.phase}
                    </td>
                    <td className="num ink-2">{pct(book.profit_target_pct)}</td>
                    <td className="num ink-2">{pct(book.max_daily_drawdown_pct)}</td>
                    <td className="num ink-2">{pct(book.max_total_drawdown_pct)}</td>
                    <td>
                      <StatusBadge
                        status={book.total_drawdown_trailing ? "warning" : "good"}
                        label={
                          book.total_drawdown_trailing
                            ? t("brokers.trailing")
                            : t("brokers.static")
                        }
                      />
                    </td>
                    <td className="num ink-3">
                      {typeof book.min_trading_days === "number"
                        ? book.min_trading_days
                        : "—"}
                    </td>
                    <td className="num ink-3">{book.retrieved}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <p className="p-4 text-xs ink-3 leading-relaxed">{books.data.note}</p>
        </Panel>
      )}

      <Panel title={t("brokers.whyNoList")}>
        <p className="p-4 text-xs ink-3 leading-relaxed">{b.why}</p>
      </Panel>
    </div>
  );
}
