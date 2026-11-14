import { Empty, Offline, Panel, Pill } from "@/components/ui";
import { api, type FtmoMonitorRow } from "@/lib/api";
import { getT } from "@/lib/locale";

export const dynamic = "force-dynamic";

function money(v: number | undefined, ccy: string): string {
  return typeof v === "number" ? `${v.toLocaleString("en-US", { maximumFractionDigits: 2 })} ${ccy}` : "—";
}

function tone(row: FtmoMonitorRow): "good" | "warning" | "critical" | "muted" {
  if (row.status !== "monitored") return "muted";
  const v = row.verdict?.verdict;
  return v === "approve" ? "good" : v === "reduce" ? "warning" : "critical";
}

function Limit({ label, data }: { label: string; data?: Record<string, unknown> }) {
  if (!data) return null;
  const pick = ["limit", "floor", "headroom", "consumed", "breached"]
    .filter((k) => k in data)
    .map((k) => `${k}: ${String(data[k])}`);
  return (
    <div className="text-xs">
      <span className="ink-3">{label}</span> {pick.join(" · ") || "—"}
    </div>
  );
}

export default async function FtmoMonitor() {
  const { t } = await getT();
  const res = await api.ftmoMonitor();
  if (!res.ok) return <Offline error={res.error} />;
  const { accounts } = res.data;

  return (
    <div className="space-y-6">
      <header>
        <h1 className="display">{t("ftmo.title")}</h1>
        <p className="text-xs ink-3 mt-0.5 max-w-2xl">{t("ftmo.subtitle")}</p>
        <p className="text-xs ink-3 mt-1">
          {res.data.note} · bridge: {res.data.bridge_accounts.join(", ") || "—"} · {res.data.as_of}
        </p>
      </header>
      {accounts.length === 0 ? (
        <Panel title={t("ftmo.title")}>
          <Empty>{t("ftmo.empty")}</Empty>
        </Panel>
      ) : (
        accounts.map((row) => (
          <Panel
            key={row.account.id}
            title={row.account.label}
            subtitle={[row.account.program, row.account.phase].filter(Boolean).join(" · ")}
          >
            <div className="flex gap-2 flex-wrap mb-2">
              <Pill tone={tone(row)}>{row.verdict?.verdict ?? row.status}</Pill>
              {row.bridge_account_key && <Pill>{row.bridge_account_key}</Pill>}
            </div>
            {row.reason && <p className="text-xs ink-3">{row.reason}</p>}
            {row.live && (
              <dl className="grid grid-cols-2 gap-1 text-sm max-w-md">
                <dt className="ink-3">{t("ftmo.equity")}</dt>
                <dd>{money(row.live.equity, row.account.currency)}</dd>
                <dt className="ink-3">{t("ftmo.daily")}</dt>
                <dd>
                  {row.live.daily_pnl_pct === null ? "—" : `${row.live.daily_pnl_pct.toFixed(2)}%`}
                </dd>
              </dl>
            )}
            <Limit label="daily" data={row.verdict?.daily} />
            <Limit label="total" data={row.verdict?.total} />
            {(row.verdict?.warnings ?? []).concat(row.verdict?.unverified ?? []).map((w) => (
              <p key={w} className="text-xs ink-3">• {w}</p>
            ))}
          </Panel>
        ))
      )}
    </div>
  );
}
