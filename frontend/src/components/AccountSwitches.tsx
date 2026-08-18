"use client";

import { useState } from "react";

/**
 * Pause and resume buttons, one row per account.
 *
 * The control is deliberately unglamorous: two buttons, the current state
 * spelled out beside them, and a name required before either does anything.
 *
 * **A name is required, not optional.** The record of who paused an account
 * and who resumed it is the thing anybody reads later, and a control that
 * writes "somebody" is a control whose history cannot be used. It is asked
 * for once and remembered for the session, so it is a question rather than a
 * chore.
 *
 * **The button says what it will do, not what is true now.** A toggle labelled
 * with the current state is read as the action about half the time, and here
 * the two readings are opposite.
 *
 * **Nothing is optimistic.** The row shows what the server said, after it
 * said it. An account that appears to resume and did not is exactly the
 * failure this page exists to make visible.
 */

type Row = { account: string; active: boolean; reason: string };

export function AccountSwitches({ initial }: { initial: Row[] }) {
  const [rows, setRows] = useState<Row[]>(initial);
  const [by, setBy] = useState("");
  const [busy, setBusy] = useState<string | null>(null);
  const [failed, setFailed] = useState<string | null>(null);

  async function change(account: string, active: boolean) {
    if (!by.trim()) {
      setFailed("نام لازم است — بدون آن ثبت نمی‌شود");
      return;
    }
    setBusy(account);
    setFailed(null);
    try {
      const answer = await fetch("/fleet/state", {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ account, active, by }),
      });
      const body = await answer.json();
      if (!answer.ok) throw new Error(body?.error ?? body?.message ?? `HTTP ${answer.status}`);
      // Taken from the answer rather than assumed. An account that appears to
      // resume and did not is the failure this page exists to show.
      setRows((current) =>
        current.map((row) =>
          row.account === account
            ? { account, active: body.active, reason: body.reason ?? "" }
            : row,
        ),
      );
    } catch (problem) {
      setFailed(problem instanceof Error ? problem.message : "ناموفق");
    } finally {
      setBusy(null);
    }
  }

  return (
    <div className="space-y-3">
      <label className="block text-xs ink-3">
        نام شما — روی هر تغییر ثبت می‌شود
        <input
          value={by}
          onChange={(event) => setBy(event.target.value)}
          placeholder="aziz"
          className="mt-1 block w-48 rounded border border-slate-700 bg-transparent px-2 py-1 text-sm"
        />
      </label>

      {failed ? <p className="text-xs text-rose-400">{failed}</p> : null}

      {rows.length === 0 ? (
        <p className="text-sm ink-3">هیچ حسابی پیکربندی نشده.</p>
      ) : (
        <table className="w-full text-sm">
          <tbody>
            {rows.map((row) => (
              <tr key={row.account} className="border-t border-slate-800">
                <td className="p-2 font-medium">{row.account}</td>
                <td className="p-2">
                  <span
                    className={row.active ? "text-emerald-400" : "text-amber-400"}
                  >
                    {row.active ? "فعال" : "غیرفعال"}
                  </span>
                  {row.reason ? (
                    <div className="text-xs ink-3">{row.reason}</div>
                  ) : null}
                </td>
                <td className="p-2 text-end">
                  <button
                    type="button"
                    disabled={busy === row.account}
                    onClick={() => change(row.account, !row.active)}
                    className="rounded border border-slate-700 px-3 py-1 text-xs disabled:opacity-50"
                  >
                    {/* What it will do, not what is true. */}
                    {busy === row.account
                      ? "..."
                      : row.active
                        ? "غیرفعال کن"
                        : "فعال کن"}
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}

      <p className="text-xs ink-3">
        این کلید سراسری نیست. تا وقتی کلید توقف بالا روشن است، هیچ حسابی سفارش
        نمی‌فرستد — هرچقدر هم که اینجا فعال باشد.
      </p>
    </div>
  );
}
