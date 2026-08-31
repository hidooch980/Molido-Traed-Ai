"use client";

import { useEffect, useState } from "react";

/**
 * Open positions and floating P&L, refreshed while the page is open.
 *
 * The page under this is server-rendered and correct at the moment it was
 * requested. On a page about open risk that is not enough: a floating loss
 * that was -$12 when the tab was opened an hour ago is still on screen looking
 * like the answer.
 *
 * **A stalled poll must look stalled.** The failure this is designed against
 * is not the fetch that errors - it is the one that quietly stops while the
 * last numbers stay on screen looking current. A floating loss that stopped
 * moving is indistinguishable from one that stopped growing, and only one of
 * those is good news. So the age of the data is rendered beside it, always,
 * and it turns into a warning before it turns into a lie.
 *
 * Poll rather than a socket. The data changes once per bridge cycle, a socket
 * would hold a connection per reader against a four-core box, and a dropped
 * socket looks exactly like a quiet market until someone checks.
 */

const POLL_MS = 5_000;

/** Older than this and the reading stops being presented as current. */
const STALE_AFTER_MS = 20_000;

type Position = {
  ticket?: number;
  symbol?: string;
  side?: string;
  volume?: number;
  price_open?: number;
  stop?: number;
  target?: number;
  profit?: number;
};

type Live = {
  stamped_at: string;
  positions: { positions?: Position[]; floating?: number } | null;
  realised: { net?: number | null; available?: boolean } | null;
  unreachable: string[];
};

function money(value: number | null | undefined): string {
  if (value === null || value === undefined || Number.isNaN(value)) return "—";
  const sign = value > 0 ? "+" : "";
  return `${sign}${value.toFixed(2)}`;
}

function tone(value: number | null | undefined): string {
  if (value === null || value === undefined || value === 0) return "text-slate-400";
  return value > 0 ? "text-emerald-400" : "text-rose-400";
}

export function LiveTrading({ initial }: { initial?: Live }) {
  const [data, setData] = useState<Live | null>(initial ?? null);
  const [failed, setFailed] = useState<string | null>(null);
  const [now, setNow] = useState<number>(() => Date.now());

  useEffect(() => {
    let alive = true;

    async function pull() {
      try {
        const answer = await fetch("/live-feed", { cache: "no-store" });
        if (!answer.ok) throw new Error(`HTTP ${answer.status}`);
        const body = (await answer.json()) as Live;
        if (!alive) return;
        setData(body);
        setFailed(null);
      } catch (problem) {
        if (!alive) return;
        // The last good numbers stay on screen, because a blank table is a
        // worse answer than an old one - but the age below them keeps
        // counting, so nobody reads them as current.
        setFailed(problem instanceof Error ? problem.message : "unreachable");
      }
    }

    pull();
    const poll = setInterval(pull, POLL_MS);
    // Ticks independently of the poll so the age keeps climbing when the poll
    // is the thing that stopped.
    const clock = setInterval(() => setNow(Date.now()), 1_000);
    return () => {
      alive = false;
      clearInterval(poll);
      clearInterval(clock);
    };
  }, []);

  const positions = data?.positions?.positions ?? [];
  const floating =
    data?.positions?.floating ??
    positions.reduce((total, row) => total + (row.profit ?? 0), 0);
  const ageMs = data ? now - new Date(data.stamped_at).getTime() : null;
  const stale = ageMs !== null && ageMs > STALE_AFTER_MS;

  return (
    <section className="space-y-3">
      <header className="flex flex-wrap items-baseline justify-between gap-2">
        <h2 className="text-lg font-semibold">معاملات لحظه‌ای</h2>
        <span
          className={`text-xs tabular-nums ${
            stale || failed ? "text-amber-400" : "text-slate-400"
          }`}
        >
          {ageMs === null
            ? "در انتظار نخستین خواندن"
            : stale || failed
              ? `داده ${Math.round(ageMs / 1000)} ثانیه پیش — به‌روزرسانی متوقف شده`
              : `${Math.round(ageMs / 1000)} ثانیه پیش`}
        </span>
      </header>

      <div className="grid grid-cols-2 gap-3 sm:grid-cols-3">
        <div className="rounded-lg border border-slate-800 p-3">
          <div className="text-xs text-slate-400">شناور</div>
          <div className={`text-2xl font-semibold tabular-nums ${tone(floating)}`}>
            {money(floating)}
          </div>
        </div>
        <div className="rounded-lg border border-slate-800 p-3">
          <div className="text-xs text-slate-400">پوزیشن باز</div>
          <div className="text-2xl font-semibold tabular-nums">{positions.length}</div>
        </div>
        <div className="rounded-lg border border-slate-800 p-3">
          <div className="text-xs text-slate-400">محقق‌شده امروز</div>
          <div
            className={`text-2xl font-semibold tabular-nums ${tone(
              data?.realised?.net ?? null,
            )}`}
          >
            {data?.realised?.available === false ? "منتشر نشده" : money(data?.realised?.net)}
          </div>
        </div>
      </div>

      {data?.unreachable?.length ? (
        <p className="text-xs text-amber-400">
          خوانده نشد: {data.unreachable.join("، ")} — این با «چیزی باز نیست» یکی نیست
        </p>
      ) : null}

      {positions.length === 0 ? (
        <p className="text-sm text-slate-400">هیچ پوزیشن بازی نیست.</p>
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead className="text-xs text-slate-400">
              <tr>
                <th className="p-2 text-start">نماد</th>
                <th className="p-2 text-start">جهت</th>
                <th className="p-2 text-end">حجم</th>
                <th className="p-2 text-end">ورود</th>
                <th className="p-2 text-end">حد ضرر</th>
                <th className="p-2 text-end">شناور</th>
              </tr>
            </thead>
            <tbody>
              {positions.map((row) => (
                <tr key={row.ticket ?? `${row.symbol}-${row.price_open}`}
                    className="border-t border-slate-800">
                  <td className="p-2 font-medium">{row.symbol ?? "—"}</td>
                  <td className="p-2">{row.side === "buy" ? "خرید" : "فروش"}</td>
                  <td className="p-2 text-end tabular-nums">{row.volume ?? "—"}</td>
                  <td className="p-2 text-end tabular-nums">{row.price_open ?? "—"}</td>
                  <td className="p-2 text-end tabular-nums">
                    {/* Named rather than blank. A position with no stop is not
                        one risking nothing; it is one whose risk has no
                        ceiling, and that has to be visible at a glance. */}
                    {row.stop ? row.stop : <span className="text-rose-400">بدون حد</span>}
                  </td>
                  <td className={`p-2 text-end tabular-nums ${tone(row.profit)}`}>
                    {money(row.profit)}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
}
