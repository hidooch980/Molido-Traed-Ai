"use client";

import { useState } from "react";

/**
 * The step that says a human read the rules against their own contract.
 *
 * This page listed the state and offered no way to change it. The badge said
 * "rules not confirmed", the gate correctly refused every order for that
 * reason, and the only route to the confirmation was an API call - so the
 * account holder was told to press a button that did not exist. A status this
 * page publishes and cannot act on is a dead end wearing the costume of a
 * control.
 *
 * **It asks before it confirms, in words about the contract.** The
 * confirmation is not "yes I see the numbers"; it is "I compared these to my
 * own agreement". A one-tap confirm would collect the first without ever
 * asking the second, and the difference is the whole point of the step: the
 * transcription can be right and still be the wrong firm's terms.
 *
 * The page reloads rather than flipping the badge locally, because whether an
 * account can be tracked is derived server-side from four separate facts and
 * this component knows one of them.
 */
export function AccountConfirm({
  id,
  labels,
}: {
  id: string;
  labels: {
    confirm: string;
    question: string;
    yes: string;
    cancel: string;
    working: string;
    failed: string;
    signInFirst: string;
  };
}) {
  const [asking, setAsking] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function confirm() {
    setBusy(true);
    setError(null);
    try {
      const response = await fetch(
        `/api/v1/risk/challenge-accounts/${id}/confirm`,
        {
          method: "POST",
          credentials: "include",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            notes: "confirmed against the account holder's own contract",
          }),
        },
      );
      if (response.status === 401 || response.status === 403) {
        setError(labels.signInFirst);
        return;
      }
      if (!response.ok) {
        const body = await response.json().catch(() => ({}));
        setError(body.message ?? labels.failed);
        return;
      }
      window.location.reload();
    } catch (problem) {
      setError(problem instanceof Error ? problem.message : labels.failed);
    } finally {
      setBusy(false);
    }
  }

  if (!asking) {
    return (
      <button
        className="text-xs mt-1"
        style={{ color: "var(--accent)" }}
        onClick={() => setAsking(true)}
      >
        {labels.confirm}
      </button>
    );
  }

  return (
    <div className="text-xs mt-1 space-y-1" style={{ maxWidth: "22rem" }}>
      <div style={{ color: "var(--ink-2)" }}>{labels.question}</div>
      <div className="flex items-center gap-2">
        <button
          style={{ color: "var(--good)" }}
          onClick={confirm}
          disabled={busy}
        >
          {busy ? labels.working : labels.yes}
        </button>
        <button
          style={{ color: "var(--ink-3)" }}
          onClick={() => setAsking(false)}
          disabled={busy}
        >
          {labels.cancel}
        </button>
      </div>
      {error && <div style={{ color: "var(--critical)" }}>{error}</div>}
    </div>
  );
}
