"use client";

import { useState } from "react";

/**
 * The switch that takes an account in and out of measurement.
 *
 * **Off rather than deleted, and the button says so.** A failed challenge, an
 * account between funding rounds, one the holder has stepped away from - each
 * is a real account with real history, and a delete button beside them would
 * offer to throw that away as the obvious way to stop tracking one.
 *
 * **It sends a destination, not a toggle.** A toggle retried by a slow phone
 * connection lands the account back where it started, and the second press
 * looks like it did nothing. `{active: false}` means the same thing however
 * many times it arrives.
 *
 * The row reloads rather than updating in place, because whether an account
 * can be tracked is derived server-side from four separate facts and this
 * component knows one of them. Recomputing the verdict here would be a second
 * implementation of that rule, and the two would disagree the first time
 * either changed.
 */
export function AccountSwitch({
  id,
  active,
  labels,
}: {
  id: string;
  active: boolean;
  labels: { on: string; off: string; switchOn: string; switchOff: string; failed: string };
}) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function flip() {
    setBusy(true);
    setError(null);
    try {
      const response = await fetch(`/api/v1/risk/challenge-accounts/${id}/active`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ active: !active }),
      });
      if (!response.ok) {
        const payload = await response.json().catch(() => ({}));
        // The server's own sentence where it wrote one; it knows why it
        // refused and a generic failure throws that away.
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

  return (
    <span className="account-switch">
      <button
        type="button"
        onClick={flip}
        disabled={busy}
        className={`switch-button${active ? " is-on" : ""}`}
        aria-pressed={active}
        // The label says what pressing it will do, not what the state is -
        // the pill beside it already says the state, and a button labelled
        // with its own state is read as an instruction by half the people who
        // see it.
        title={active ? labels.switchOff : labels.switchOn}
      >
        <span className="switch-track" aria-hidden="true">
          <span className="switch-knob" />
        </span>
        <span className="switch-text">{active ? labels.on : labels.off}</span>
      </button>
      {error && (
        <span className="switch-error" role="status">
          {error}
        </span>
      )}
    </span>
  );
}
