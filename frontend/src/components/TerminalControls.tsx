"use client";

import { useState } from "react";

/**
 * Connect, disconnect and delete, beside each terminal.
 *
 * There was one control and it did the destructive thing: log out and forget
 * the account. So parking a terminal for an afternoon cost the password on
 * the way back, and a system that makes people re-type passwords is a system
 * that teaches them to keep passwords somewhere convenient.
 *
 * The three are genuinely different acts:
 *
 * - **Connect** starts a terminal that still holds a login. No credential,
 *   because the account is already in MetaTrader's own config. Idempotent and
 *   harmless, so it asks nothing.
 * - **Disconnect** stops the terminal and leaves the login alone. Coming back
 *   is a Connect, not a re-registration.
 * - **Delete** forgets the account. Coming back means typing the password
 *   again, which is exactly why it is not the same button as Disconnect.
 *
 * **Both of the last two ask once, inline.** Acting on a live account from a
 * one-tap button beside every row is an accident that eventually happens on a
 * phone, and the confirmation names the terminal so the accident has to be
 * made twice in the same place. Connect does not ask, because starting a
 * terminal that is already started changes nothing.
 *
 * The row reloads rather than updating in place: whether a terminal is
 * connected is the server's fact, read from what the terminal itself
 * publishes, and this component holds none of it.
 */
export type ControlLabels = {
  connect: string;
  disconnect: string;
  remove: string;
  confirm: string;
  cancel: string;
  working: string;
  failed: string;
  removeWarning: string;
};

type Action = "connect" | "disconnect" | "remove";

//: Which endpoint each control posts to. `remove` is the old `/unlink`, kept
//: under that name on the server because it is the same act it always was -
//: only the label beside it changed, once there was something else to tell it
//: apart from.
const ENDPOINT: Record<Action, string> = {
  connect: "/api/v1/brokers/connect",
  disconnect: "/api/v1/brokers/disconnect",
  remove: "/api/v1/brokers/unlink",
};

//: Connect changes nothing when the terminal is already up, so it goes
//: straight through. The other two act on an account.
const ASKS_FIRST: Record<Action, boolean> = {
  connect: false,
  disconnect: true,
  remove: true,
};

export function TerminalControls({
  terminal,
  labels,
}: {
  terminal: string;
  labels: ControlLabels;
}) {
  const [asking, setAsking] = useState<Action | null>(null);
  const [busy, setBusy] = useState<Action | null>(null);
  const [error, setError] = useState<string | null>(null);

  async function run(action: Action) {
    setBusy(action);
    setError(null);
    try {
      const response = await fetch(ENDPOINT[action], {
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
      // The agent stops or starts the terminal; a short pause keeps the
      // reload from reading the state from just before it moved and looking
      // like the button did nothing.
      await new Promise((resolve) => setTimeout(resolve, 4000));
      window.location.reload();
    } catch {
      setError(labels.failed);
    } finally {
      setBusy(null);
      setAsking(null);
    }
  }

  function press(action: Action) {
    if (ASKS_FIRST[action]) setAsking(action);
    else void run(action);
  }

  if (asking) {
    return (
      <span className="phase-move-actions">
        <button
          type="button"
          className="phase-move-go"
          onClick={() => void run(asking)}
          disabled={busy !== null}
        >
          {busy ? labels.working : `${labels.confirm} (${terminal})`}
        </button>
        <button
          type="button"
          className="phase-move-cancel"
          onClick={() => setAsking(null)}
          disabled={busy !== null}
        >
          {labels.cancel}
        </button>
        {/* Only the irreversible one carries a warning. Putting one on both
            would make the word mean nothing on the row where it matters. */}
        {asking === "remove" && (
          <span className="text-xs ink-3 block">{labels.removeWarning}</span>
        )}
        {error && (
          <span className="switch-error" role="status">
            {error}
          </span>
        )}
      </span>
    );
  }

  return (
    <span className="phase-move-actions">
      <button
        type="button"
        className="phase-move-open"
        onClick={() => press("connect")}
        disabled={busy !== null}
      >
        {busy === "connect" ? labels.working : labels.connect}
      </button>
      <button
        type="button"
        className="phase-move-open"
        onClick={() => press("disconnect")}
        disabled={busy !== null}
      >
        {labels.disconnect}
      </button>
      <button
        type="button"
        className="phase-move-open"
        onClick={() => press("remove")}
        disabled={busy !== null}
        style={{ color: "var(--bad, #b4413c)" }}
      >
        {labels.remove}
      </button>
      {error && (
        <span className="switch-error" role="status">
          {error}
        </span>
      )}
    </span>
  );
}
