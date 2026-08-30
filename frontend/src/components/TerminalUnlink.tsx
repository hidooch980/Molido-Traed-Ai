"use client";

import { useState } from "react";

/**
 * The log-out control beside each connected terminal.
 *
 * **It asks once, inline, before doing anything.** Logging a terminal out
 * mid-trade is as much an act on the account as logging it in was, and a
 * one-tap disconnect next to every row is an accident that will eventually
 * happen on a phone. The confirmation names the terminal so the accident has
 * to be made twice in the same place.
 *
 * The row reloads rather than updating in place: whether a terminal is
 * connected is the server's fact, read from what the terminal itself
 * publishes, and this component holds none of it.
 */
export function TerminalUnlink({
  terminal,
  labels,
}: {
  terminal: string;
  labels: { unlink: string; confirm: string; cancel: string; working: string; failed: string };
}) {
  const [asking, setAsking] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function unlink() {
    setBusy(true);
    setError(null);
    try {
      const response = await fetch("/api/v1/brokers/unlink", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        credentials: "same-origin",
        body: JSON.stringify({ terminal }),
      });
      if (!response.ok) {
        const body = await response.json().catch(() => ({}));
        setError(body?.message ?? labels.failed);
        return;
      }
      // The agent restarts the terminal; a short pause keeps the reload from
      // reading the state from just before the restart and looking like the
      // button did nothing.
      await new Promise((resolve) => setTimeout(resolve, 4000));
      window.location.reload();
    } catch {
      setError(labels.failed);
    } finally {
      setBusy(false);
    }
  }

  if (!asking) {
    return (
      <button type="button" className="phase-move-open" onClick={() => setAsking(true)}>
        {labels.unlink}
      </button>
    );
  }

  return (
    <span className="phase-move-actions">
      <button type="button" className="phase-move-go" onClick={unlink} disabled={busy}>
        {busy ? labels.working : `${labels.confirm} (${terminal})`}
      </button>
      <button
        type="button"
        className="phase-move-cancel"
        onClick={() => setAsking(false)}
        disabled={busy}
      >
        {labels.cancel}
      </button>
      {error && (
        <span className="switch-error" role="status">
          {error}
        </span>
      )}
    </span>
  );
}
