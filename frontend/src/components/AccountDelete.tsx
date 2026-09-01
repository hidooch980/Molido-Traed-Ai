"use client";

import { useState } from "react";

/**
 * Removing an account that should never have been recorded.
 *
 * **Deliberately quieter than the switch beside it.** Off is the right answer
 * for almost everything - a failed challenge, an account between funding
 * rounds, one whose holder stepped away - and each of those is real history
 * worth keeping. This is for the row that is not history: a typo, a test, a
 * program abandoned before it was traded.
 *
 * **It asks once, in place.** A confirm dialog is the cheapest guard against
 * a mis-click on a row of buttons, and doing it inline rather than through
 * `window.confirm` keeps the question in the same language as the page.
 *
 * The page reloads afterwards rather than removing the row locally: what the
 * risk layer measures is derived server-side, and a client that prunes its
 * own list is a client that can disagree with it.
 */
export function AccountDelete({
  id,
  labels,
}: {
  id: string;
  labels: {
    delete: string;
    confirm: string;
    cancel: string;
    deleting: string;
    failed: string;
    signInFirst: string;
  };
}) {
  const [asking, setAsking] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function remove() {
    setBusy(true);
    setError(null);
    try {
      const response = await fetch(`/api/v1/risk/challenge-accounts/${id}`, {
        method: "DELETE",
        credentials: "include",
      });
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
        className="text-xs"
        style={{ color: "var(--ink-3)" }}
        onClick={() => setAsking(true)}
        title={labels.delete}
      >
        {labels.delete}
      </button>
    );
  }

  return (
    <span className="inline-flex items-center gap-2 text-xs">
      <button
        style={{ color: "var(--critical)" }}
        onClick={remove}
        disabled={busy}
      >
        {busy ? labels.deleting : labels.confirm}
      </button>
      <button
        style={{ color: "var(--ink-3)" }}
        onClick={() => setAsking(false)}
        disabled={busy}
      >
        {labels.cancel}
      </button>
      {error && <span style={{ color: "var(--critical)" }}>{error}</span>}
    </span>
  );
}
