"use client";

import { useState } from "react";

import type { RulebookEntry } from "@/lib/api";

/**
 * Moving an account from one phase of a programme to the next.
 *
 * A two-phase evaluation is three documents - phase one, phase two, and the
 * funded account - and to the holder it is one account passing through them.
 * Without this the only way to record passing a phase was a second account,
 * which scattered one account's history across three rows and left the
 * platform unable to say that a funded account and the challenge that earned
 * it were the same thing.
 *
 * **Collapsed until asked for.** The row it sits in is read far more often
 * than a phase is passed, and a permanently open select in every row would
 * cost more space on a phone than the whole rest of the table.
 *
 * **The warning about confirmation is shown before the move, not after.** The
 * server resets it either way; somebody who finds out afterwards has already
 * lost a tick they will have to redo, and will reasonably read it as a bug.
 */
export function AccountPhaseMove({
  id,
  rulebooks,
  labels,
}: {
  id: string;
  rulebooks: RulebookEntry[];
  labels: {
    move: string;
    choose: string;
    confirm: string;
    warning: string;
    cancel: string;
    failed: string;
    working: string;
  };
}) {
  const [open, setOpen] = useState(false);
  const [key, setKey] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function move() {
    if (!key) return;
    setBusy(true);
    setError(null);
    try {
      const chosen = rulebooks.find((book) => book.key === key);
      const response = await fetch(`/api/v1/risk/challenge-accounts/${id}/move`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          rulebook_key: key,
          // Sent only when the phase is a funded one, because that is the
          // move that changes what kind of account this is. Every other move
          // stays inside the challenge and omitting it leaves the kind alone.
          kind: chosen?.phase?.startsWith("funded") ? "funded" : null,
        }),
      });
      if (!response.ok) {
        const payload = await response.json().catch(() => ({}));
        setError(payload?.message ?? labels.failed);
        return;
      }
      window.location.reload();
    } catch {
      setError(labels.failed);
    } finally {
      setBusy(false);
    }
  }

  if (!open) {
    return (
      <button type="button" className="phase-move-open" onClick={() => setOpen(true)}>
        {labels.move}
      </button>
    );
  }

  return (
    <div className="phase-move">
      <select
        className="auth-input phase-move-select"
        value={key}
        onChange={(e) => setKey(e.target.value)}
      >
        <option value="">{labels.choose}</option>
        {rulebooks.map((book) => (
          <option key={book.key} value={book.key}>
            {book.provider} · {book.program} · {book.phase}
          </option>
        ))}
      </select>
      <p className="auth-hint phase-move-warning">{labels.warning}</p>
      <div className="phase-move-actions">
        <button type="button" onClick={move} disabled={busy || !key} className="phase-move-go">
          {busy ? labels.working : labels.confirm}
        </button>
        <button type="button" onClick={() => setOpen(false)} className="phase-move-cancel">
          {labels.cancel}
        </button>
      </div>
      {error && (
        <p className="switch-error" role="status">
          {error}
        </p>
      )}
    </div>
  );
}
