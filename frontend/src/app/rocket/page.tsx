import Link from "next/link";

import { Empty, Offline, Panel, Pill } from "@/components/ui";
import { api } from "@/lib/api";
import { getT } from "@/lib/locale";

export const dynamic = "force-dynamic";

const FRAMES = ["M15", "H1", "H4", "D1"];

export default async function RocketRadar({
  searchParams,
}: {
  searchParams: Promise<{ tf?: string }>;
}) {
  const { t } = await getT();
  const params = await searchParams;
  const tf = FRAMES.includes(params.tf ?? "") ? (params.tf as string) : "H1";
  const scan = await api.rocketScan(tf);
  if (!scan.ok) return <Offline error={scan.error} />;
  const { signals, scanned } = scan.data;

  return (
    <div className="space-y-6">
      <header className="flex items-end justify-between gap-4 flex-wrap">
        <div>
          <h1 className="display">{t("rocket.title")}</h1>
          <p className="text-xs ink-3 mt-0.5 max-w-2xl">{t("rocket.subtitle")}</p>
          <p className="text-xs ink-3 mt-1">
            {scan.data.note} · {scan.data.as_of}
          </p>
        </div>
        <div className="flex gap-1.5">
          {FRAMES.map((f) => (
            <Link key={f} href={`/rocket?tf=${f}`} className="pill"
              style={{ color: f === tf ? "var(--accent)" : "var(--ink-3)" }}>
              {f}
            </Link>
          ))}
        </div>
      </header>
      <Panel title={t("rocket.signals")}>
        {signals.length === 0 ? (
          <Empty>{t("rocket.empty")}</Empty>
        ) : (
          <table className="w-full text-sm">
            <thead>
              <tr className="text-left ink-3 text-xs">
                <th>Rank</th><th>Symbol</th><th>Side</th><th>Entry</th><th>SL</th>
                <th>TP</th><th>R:R</th><th>{t("rocket.evidence")}</th><th>Status</th>
              </tr>
            </thead>
            <tbody>
              {signals.map((s) => (
                <tr key={`${s.symbol}-${s.signal_timestamp}`} className="align-top border-t"
                  title={s.invalidation}>
                  <td><Pill tone={s.rocket_rank >= "R4" ? "good" : "neutral"}>{s.rocket_rank}</Pill></td>
                  <td className="mono">{s.symbol}</td>
                  <td>{s.direction}</td>
                  <td className="mono">{s.entry_zone.map((x) => x.toFixed(5)).join("–")}</td>
                  <td className="mono">{s.stop_loss.toFixed(5)}</td>
                  <td className="mono">{s.take_profit.toFixed(5)}</td>
                  <td>{s.expected_rr.toFixed(2)}</td>
                  <td className="text-xs">
                    <div>+ {s.supporting_evidence.join("; ")}</div>
                    {s.conflicting_evidence.length > 0 && (
                      <div className="ink-3">− {s.conflicting_evidence.join("; ")}</div>
                    )}
                  </td>
                  <td className="text-xs">{s.status} / {s.risk_approval_status}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </Panel>
      <Panel title={t("rocket.scanned")}>
        {scanned.length === 0 ? (
          <Empty>{t("rocket.noInstruments")}</Empty>
        ) : (
          <ul className="text-xs space-y-1">
            {scanned.map((row) => (
              <li key={row.symbol}>
                <span className="mono">{row.symbol}</span> · {row.status}
                {row.bars !== undefined ? ` · ${row.bars} bars` : ""} · {row.reason}
              </li>
            ))}
          </ul>
        )}
      </Panel>
    </div>
  );
}
