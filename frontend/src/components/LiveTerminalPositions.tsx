"use client";

import { useEffect, useState } from "react";

/**
 * One account's open positions, kept current while the page is open.
 *
 * The page under this is server-rendered and was correct when it was
 * requested. On a page somebody opens to ask "what is my account doing right
 * now" that is not enough: a floating loss that was -$12 when the tab was
 * opened an hour ago is still on screen, looking like the answer.
 *
 * **A stalled poll must look stalled.** The failure worth designing against
 * is not the fetch that errors - it is the one that quietly stops while the
 * last numbers stay on screen looking current. A floating loss that stopped
 * moving is indistinguishable from one that stopped growing, and only one of
 * those is good news. So the age of the reading is rendered beside it,
 * always, and it turns into a warning before it turns into a lie.
 *
 * It asks `/live-feed?terminal=…`, which reads that terminal's own bridge.
 * Reading the fleet's positions and filtering them here would attribute a
 * position to whichever terminal the reader happened to be looking at, which
 * is the one mistake this whole page exists to make impossible.
 */

const POLL_MS = 5_000;

/** Older than this and the reading stops being presented as current. */
const STALE_AFTER_MS = 20_000;

export type TerminalPosition = {
  ticket: number | string;
  symbol: string;
  side: string;
  volume: number;
  price_open: number;
  stop: number | null;
  target: number | null;
  profit: number;
};

export type PositionLabels = {
  symbol: string;
  side: string;
  volume: string;
  entry: string;
  stop: string;
  target: string;
  reward: string;
  floating: string;
  buy: string;
  sell: string;
  empty: string;
  /** "updated {age}s ago" - the age is substituted by the caller's translator. */
  age: string;
  stale: string;
  unreachable: string;
};

type Feed = {
  stamped_at: string;
  detail: { positions?: TerminalPosition[] } | null;
  unreachable?: string[];
};

function money(value: number | null | undefined, digits = 2) {
  return value === null || value === undefined
    ? "—"
    : Number(value).toLocaleString("en-US", {
        minimumFractionDigits: digits,
        maximumFractionDigits: digits,
      });
}

export function LiveTerminalPositions({
  terminal,
  initial,
  labels,
}: {
  terminal: string;
  initial: TerminalPosition[];
  labels: PositionLabels;
}) {
  const [positions, setPositions] = useState<TerminalPosition[]>(initial);
  const [stampedAt, setStampedAt] = useState<number>(() => Date.now());
  const [failed, setFailed] = useState<string | null>(null);
  const [now, setNow] = useState<number>(() => Date.now());

  useEffect(() => {
    let alive = true;

    async function pull() {
      try {
        const answer = await fetch(
          `/live-feed?terminal=${encodeURIComponent(terminal)}`,
          { cache: "no-store" },
        );
        if (!answer.ok) throw new Error(`HTTP ${answer.status}`);
        const body = (await answer.json()) as Feed;
        if (!alive) return;
        if (body.detail) {
          setPositions(body.detail.positions ?? []);
          setStampedAt(Date.parse(body.stamped_at) || Date.now());
          setFailed(null);
        } else {
          // A reachable route that could not reach the terminal is not an
          // account with nothing open, and must not render as one.
          setFailed(labels.unreachable);
        }
      } catch (problem) {
        if (alive) setFailed(String(problem));
      }
    }

    pull();
    const poll = setInterval(pull, POLL_MS);
    // A separate, faster tick so the age keeps counting up even when the
    // fetch itself has stopped returning - which is the case the age exists
    // to make visible.
    const clock = setInterval(() => alive && setNow(Date.now()), 1_000);
    return () => {
      alive = false;
      clearInterval(poll);
      clearInterval(clock);
    };
  }, [terminal, labels.unreachable]);

  const age = Math.max(0, Math.round((now - stampedAt) / 1000));
  const stale = now - stampedAt > STALE_AFTER_MS || failed !== null;
  const floating = positions.reduce((total, p) => total + Number(p.profit ?? 0), 0);

  return (
    <div className="space-y-2">
      <div
        className="text-xs"
        style={{ color: stale ? "var(--bad)" : "var(--ink-3)" }}
      >
        {failed
          ? `${labels.stale} — ${failed}`
          : stale
            ? `${labels.stale} — ${labels.age.replace("{age}", String(age))}`
            : labels.age.replace("{age}", String(age))}
      </div>

      {positions.length === 0 ? (
        <p className="ink-3 text-sm">{labels.empty}</p>
      ) : (
        <div className="scroll-x">
          <table className="data">
            <thead>
              <tr>
                <th>{labels.symbol}</th>
                <th>{labels.side}</th>
                <th className="num">{labels.volume}</th>
                <th className="num">{labels.entry}</th>
                <th className="num">{labels.stop}</th>
                <th className="num">{labels.target}</th>
                <th className="num">{labels.reward}</th>
                <th className="num">{labels.floating}</th>
              </tr>
            </thead>
            <tbody>
              {positions.map((p) => {
                const entry = Number(p.price_open);
                const stopDistance = Math.abs(entry - Number(p.stop));
                const targetDistance = Math.abs(Number(p.target) - entry);
                const reward =
                  stopDistance > 0 ? (targetDistance / stopDistance).toFixed(2) : "—";
                return (
                  <tr key={String(p.ticket)}>
                    <td className="font-semibold" dir="ltr">
                      {p.symbol}
                    </td>
                    <td>{p.side === "buy" ? labels.buy : labels.sell}</td>
                    <td className="num">{p.volume}</td>
                    <td className="num">{p.price_open}</td>
                    <td className="num">{p.stop || "—"}</td>
                    <td className="num">{p.target || "—"}</td>
                    <td className="num">{reward}</td>
                    <td
                      className="num"
                      style={{
                        color: Number(p.profit) < 0 ? "var(--bad)" : "var(--good)",
                      }}
                    >
                      {Number(p.profit) >= 0 ? "+" : ""}
                      {money(p.profit)}
                    </td>
                  </tr>
                );
              })}
              <tr>
                <td colSpan={7} className="ink-3">
                  {labels.floating}
                </td>
                <td
                  className="num font-semibold"
                  style={{ color: floating < 0 ? "var(--bad)" : "var(--good)" }}
                >
                  {floating >= 0 ? "+" : ""}
                  {money(floating)}
                </td>
              </tr>
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
