import { AccountSwitches } from "@/components/AccountSwitches";
import { LiveTrading } from "@/components/LiveTrading";
import { Offline, Panel, Stat, StatusBadge } from "@/components/ui";
import { api } from "@/lib/api";
import { getT } from "@/lib/locale";

export const dynamic = "force-dynamic";

/**
 * Every account on one page, and each one separately.
 *
 * A single total across a fleet hides the case that matters: one account
 * quietly down while the others carry it. So the aggregate is shown because
 * it is what somebody wants first, and every account is shown beside it
 * because the aggregate is not what they should act on.
 *
 * An account that is paused, unreachable or failing its challenge is named
 * rather than shown as a row of zeros. Those three look identical in a total
 * and want opposite responses.
 */
export default async function FleetPage() {
  const { t } = await getT();
  const [accounts, positions, realised, states] = await Promise.all([
    api.accounts(),
    api.positions(),
    api.realised(30),
    api.accountStates(),
  ]);

  if (!accounts.ok) return <Offline error={accounts.error} />;

  const book = accounts.data as {
    global_kill_switch?: { engaged?: boolean; reason?: string };
    accounts?: Array<{
      account_id?: string;
      label?: string;
      broker?: string;
      enabled?: boolean;
      dry_run?: boolean;
      kill_switch?: { engaged?: boolean; reason?: string };
      allowed_symbols?: string[];
    }>;
  };

  const rows = book.accounts ?? [];
  const halted = book.global_kill_switch?.engaged === true;

  const firstReading = {
    stamped_at: new Date().toISOString(),
    positions: positions.ok ? positions.data : null,
    realised: realised.ok ? realised.data : null,
    unreachable: [
      positions.ok ? null : "positions",
      realised.ok ? null : "realised",
    ].filter(Boolean) as string[],
  };

  return (
    <div className="space-y-4">
      <header>
        <h1 className="text-xl font-bold">ناوگان حساب‌ها</h1>
        <p className="text-xs ink-3 mt-0.5 max-w-3xl">
          هر حساب جدا. یک جمع کل، حالتی را پنهان می‌کند که مهم است — یک حساب
          خاموش که بقیه رویش سرپوش می‌گذارند.
        </p>
      </header>

      {/* The fleet-wide halt, first and unmissable. Everything below it is
          about accounts that cannot trade while this is engaged. */}
      <Panel title="کلید توقف سراسری">
        <div className="flex flex-wrap items-center gap-3">
          <StatusBadge
            status={halted ? "critical" : "good"}
            label={halted ? "متوقف" : "آزاد"}
          />
          <span className="text-xs ink-3">
            {book.global_kill_switch?.reason ?? "—"}
          </span>
        </div>
        {halted ? (
          <p className="text-xs ink-3 mt-2">
            تا وقتی این روشن است هیچ حسابی سفارش نمی‌فرستد، هرچقدر هم که خودش
            فعال باشد.
          </p>
        ) : null}
      </Panel>

      <LiveTrading initial={firstReading as never} />

      <Panel title="فعال و غیرفعال کردن حساب">
        {states.ok ? (
          <AccountSwitches initial={states.data.accounts} />
        ) : (
          /* Not an empty control. A registry that cannot be read and a fleet
             with nothing in it look identical in a blank panel. */
          <Offline error={states.error} />
        )}
      </Panel>

      <Panel title={`حساب‌ها (${rows.length})`}>
        {rows.length === 0 ? (
          /* Not an empty table. "No accounts configured" and "we cannot read
             the registry" look the same in a blank list. */
          <p className="text-sm ink-3">
            هیچ حسابی پیکربندی نشده — این با «خوانده نشد» یکی نیست.
          </p>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead className="text-xs ink-3">
                <tr>
                  <th className="p-2 text-start">حساب</th>
                  <th className="p-2 text-start">بروکر</th>
                  <th className="p-2 text-start">وضعیت</th>
                  <th className="p-2 text-start">کلید حساب</th>
                  <th className="p-2 text-start">نمادهای مجاز</th>
                </tr>
              </thead>
              <tbody>
                {rows.map((row) => {
                  const stopped = row.kill_switch?.engaged === true;
                  const off = row.enabled === false;
                  return (
                    <tr
                      key={row.account_id ?? row.label}
                      className="border-t border-slate-800"
                    >
                      <td className="p-2">
                        <div className="font-medium">{row.label ?? "—"}</div>
                        <div className="text-xs ink-3">{row.account_id ?? "—"}</div>
                      </td>
                      <td className="p-2">{row.broker ?? "—"}</td>
                      <td className="p-2">
                        <StatusBadge
                          status={off ? "warning" : "good"}
                          label={off ? "غیرفعال" : "فعال"}
                        />
                        {row.dry_run ? (
                          <span className="ms-2 text-xs ink-3">آزمایشی</span>
                        ) : null}
                      </td>
                      <td className="p-2">
                        <StatusBadge
                          status={stopped ? "critical" : "good"}
                          label={stopped ? "متوقف" : "آزاد"}
                        />
                        <div className="text-xs ink-3 max-w-xs truncate">
                          {row.kill_switch?.reason ?? ""}
                        </div>
                      </td>
                      <td className="p-2 text-xs ink-3">
                        {/* Empty means every symbol, which is the opposite of
                            what a blank cell suggests. */}
                        {row.allowed_symbols?.length
                          ? row.allowed_symbols.join("، ")
                          : "همه"}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
      </Panel>

      <Panel title="سود محقق‌شده">
        {!realised.ok ? (
          <Offline error={realised.error} />
        ) : (realised.data as { available?: boolean }).available === false ? (
          <p className="text-sm ink-3">
            {(realised.data as { reason?: string }).reason ?? "منتشر نشده"}
          </p>
        ) : (
          <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
            <Stat
              label="خالص"
              value={String((realised.data as { net?: number }).net ?? "—")}
            />
            <Stat
              label="ناخالص"
              value={String((realised.data as { gross?: number }).gross ?? "—")}
            />
            <Stat
              label="سواپ"
              value={String((realised.data as { swap?: number }).swap ?? "—")}
            />
            <Stat
              label="کمیسیون"
              value={String(
                (realised.data as { commission?: number }).commission ?? "—",
              )}
            />
          </div>
        )}
      </Panel>
    </div>
  );
}
