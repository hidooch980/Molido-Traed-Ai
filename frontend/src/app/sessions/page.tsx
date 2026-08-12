import { Empty, Offline, Panel, Pill, StatusBadge } from "@/components/ui";
import { api } from "@/lib/api";
import { getT } from "@/lib/locale";

export const dynamic = "force-dynamic";

const SESSION_ORDER = ["sydney", "tokyo", "london", "new_york"] as const;

export default async function SessionsPage() {
  const instruments = await api.instruments();
  const { t } = await getT();
  if (!instruments.ok) return <Offline error={instruments.error} />;

  const primary = instruments.data[0];
  const [status, holidays] = await Promise.all([
    primary ? api.sessionStatus(primary.id) : Promise.resolve(null),
    api.holidays(),
  ]);

  const active = status?.ok ? new Set(status.data.active_sessions) : new Set<string>();

  return (
    <div className="space-y-4">
      <header>
        <h1 className="text-xl font-bold">{t("sessions.title")}</h1>
        <p className="text-xs ink-3 mt-0.5">
{t("sessions.subtitle")}
        </p>
      </header>

      <Panel
        title={t("sessions.liquidity")}
        subtitle={t("sessions.overlap")}
      >
        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4 p-4">
          {SESSION_ORDER.map((key) => {
            const on = active.has(key);
            return (
              <div
                key={key}
                className="p-3 rounded-lg"
                style={{
                  background: on ? "var(--accent-soft)" : "var(--panel-raised)",
                  border: "1px solid var(--border)",
                }}
              >
                <div className="flex items-center justify-between">
                  <span className="font-semibold text-sm">{t(`session.${key}`)}</span>
                  <span
                    className="dot"
                    style={{ background: on ? "var(--good)" : "var(--ink-3)" }}
                    aria-hidden="true"
                  />
                </div>
                <div className="text-xs ink-3 mt-1">{on ? t("sessions.openNow") : t("common.closed")}</div>
              </div>
            );
          })}
        </div>
      </Panel>

      {status?.ok && (
        <Panel title={`${status.data.symbol} · ${t("sessions.state")}`}>
          <dl className="grid gap-x-6 gap-y-2.5 p-4 text-sm sm:grid-cols-2 lg:grid-cols-4">
            {[
              [t("sessions.status"), status.data.is_open ? t("common.open") : t("common.closed")],
              [t("sessions.calendar"), status.data.market_code],
              [t("sessions.timezone"), status.data.timezone],
              [t("sessions.holiday"), status.data.holiday ?? t("common.none")],
              [
                t("sessions.nextOpen"),
                status.data.next_open
                  ? status.data.next_open.slice(0, 16).replace("T", " ")
                  : "—",
              ],
              [
                t("sessions.nextClose"),
                status.data.next_close
                  ? status.data.next_close.slice(0, 16).replace("T", " ")
                  : t("sessions.never"),
              ],
            ].map(([label, value]) => (
              <div key={label}>
                <dt className="eyebrow">{label}</dt>
                <dd className="num mt-0.5">{value}</dd>
              </div>
            ))}
          </dl>
          <p className="px-4 pb-3 text-xs ink-3">
{t("sessions.nullNote")}
          </p>
        </Panel>
      )}

      <Panel
        title={t("sessions.holidays")}
        subtitle={t("sessions.holidaysSubtitle")}
      >
        {!holidays.ok || holidays.data.length === 0 ? (
          <Empty>
            {t("sessions.noHolidays")}
          </Empty>
        ) : (
          <div className="scroll-x scroll-y" style={{ maxHeight: 380 }}>
            <table className="data">
              <thead>
                <tr>
                  <th>{t("sessions.date")}</th>
                  <th>{t("markets.marketCode")}</th>
                  <th>{t("markets.name")}</th>
                  <th>{t("sessions.kind")}</th>
                  <th>{t("sessions.closes")}</th>
                </tr>
              </thead>
              <tbody>
                {holidays.data.map((h) => (
                  <tr key={`${h.market_code}-${h.holiday_date}`}>
                    <td className="num">{h.holiday_date}</td>
                    <td className="ink-3">{h.market_code}</td>
                    <td>{h.name}</td>
                    <td>
                      {h.kind === "closed" ? (
                        <StatusBadge status="critical" label={t("common.closed")} />
                      ) : (
                        <Pill tone="muted">{h.kind.replace("_", " ")}</Pill>
                      )}
                    </td>
                    <td className="num ink-3">{h.closes_at ?? "—"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Panel>
    </div>
  );
}
