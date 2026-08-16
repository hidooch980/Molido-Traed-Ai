import { Offline, Panel, Stat, StatusBadge } from "@/components/ui";
import { api } from "@/lib/api";
import { getT } from "@/lib/locale";

export const dynamic = "force-dynamic";

/**
 * This week's scheduled releases, and the clocks they land on.
 *
 * Every time on this page is UTC and says so. The feed publishes no timezone
 * field, and the common assumption that it is US Eastern is wrong by four
 * hours — the real one was derived from two New Zealand releases whose local
 * publication times are fixed. A calendar that is wrong by a constant is worse
 * than no calendar, because nothing about it looks wrong.
 *
 * It decides nothing. No trade is gated, sized or suppressed by what is on
 * this page: that would be a rule, and rules here clear the edge registry
 * first.
 */
const IMPACT_TONE: Record<string, "good" | "warning" | "info"> = {
  High: "warning",
  Medium: "info",
  Low: "info",
  Holiday: "info",
};

export default async function CalendarPage() {
  const { t } = await getT();
  const [calendar, clocks] = await Promise.all([api.calendar(), api.timezones()]);
  if (!calendar.ok) return <Offline error={calendar.error} />;

  const { releases, next, hours_to_next, clock_warning, note, count } = calendar.data;

  return (
    <div className="space-y-4">
      <header>
        <h1 className="text-xl font-bold">{t("calendar.title")}</h1>
        <p className="text-xs ink-3 mt-0.5 max-w-3xl">{t("calendar.subtitle")}</p>
      </header>

      {/* Published rather than logged. A feed whose clock moved would show
          every time wrong by a constant and look entirely normal doing it. */}
      {clock_warning && (
        <Panel title="⚠">
          <p className="p-4 text-xs ink-2 leading-relaxed">{clock_warning}</p>
        </Panel>
      )}

      <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-3">
        <Stat
          label={t("calendar.next")}
          value={next ? next.title : t("calendar.none")}
          hint={next ? `${next.currency} · ${next.impact}` : ""}
        />
        <Stat
          label={t("calendar.hours")}
          value={hours_to_next != null ? String(hours_to_next) : "—"}
          tone={hours_to_next != null && hours_to_next < 2 ? "warning" : undefined}
        />
        <Stat label={t("calendar.event")} value={String(count)} hint="UTC" />
      </div>

      {clocks.ok && (
        <Panel title={t("calendar.clocks")}>
          <div className="p-4">
            <div className="grid gap-2 sm:grid-cols-3 xl:grid-cols-5">
              {clocks.data.places.map((place) => (
                <div key={place.name} className="text-xs">
                  <div className="ink-3">{place.name}</div>
                  <div className="font-medium tabular-nums">{place.local}</div>
                </div>
              ))}
            </div>
            {!clocks.data.broker_offset_known && (
              <p className="text-xs ink-3 leading-relaxed mt-3">
                {t("calendar.brokerUnknown")}
              </p>
            )}
          </div>
        </Panel>
      )}

      <Panel title={t("calendar.title")}>
        <div className="scroll-x">
          <table className="data">
            <thead>
              <tr>
                <th>{t("calendar.when")}</th>
                <th>{t("calendar.ccy")}</th>
                <th>{t("calendar.event")}</th>
                <th>{t("calendar.impact")}</th>
                <th>{t("calendar.forecast")}</th>
                <th>{t("calendar.previous")}</th>
              </tr>
            </thead>
            <tbody>
              {releases.map((release, index) => (
                <tr key={`${release.title}-${release.at ?? index}`}>
                  <td className="tabular-nums ink-2">
                    {/* An all-day entry has no clock. Showing midnight would
                        put a bank holiday at the top of the day looking like
                        something to trade around. */}
                    {release.all_day
                      ? t("calendar.allDay")
                      : release.at!.slice(5, 16).replace("T", " ")}
                  </td>
                  <td className="font-medium">{release.currency}</td>
                  <td>{release.title}</td>
                  <td>
                    <StatusBadge
                      status={IMPACT_TONE[release.impact] ?? "info"}
                      label={release.impact}
                    />
                  </td>
                  <td className="num ink-2">{release.forecast ?? "—"}</td>
                  <td className="num ink-3">{release.previous ?? "—"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Panel>

      <p className="text-xs ink-3 leading-relaxed">{note}</p>
    </div>
  );
}
