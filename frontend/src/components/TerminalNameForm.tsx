"use client";

import { useState } from "react";

/**
 * Give a terminal a name a person recognises.
 *
 * The fleet is `term-b` through `term-h`. Those names are unique, correct,
 * and say nothing: which one holds the five hundred dollars, which one is
 * the cent account, which one exists to be broken. Answering that meant
 * opening each page and reading a login, and the logins differ by one digit
 * in the middle - which is exactly the shape of mistake that ends with an
 * order on the wrong account.
 *
 * **The name is decoration and the key is the identity.** Nothing routes on
 * what is typed here. That is why the key stays on the page next to it: a
 * reader who only ever sees "cent 500" has nothing to search the logs, the
 * directories or any other page for.
 *
 * Clearing the field is how a name is removed. A separate delete button
 * would be a second way to reach one state.
 */

export type TerminalNameLabels = {
  field: string;
  hint: string;
  placeholder: string;
  save: string;
  saving: string;
  saved: string;
  failed: string;
};

export function TerminalNameForm({
  terminal,
  initial,
  labels,
}: {
  terminal: string;
  initial: string | null;
  labels: TerminalNameLabels;
}) {
  const [name, setName] = useState<string>(initial ?? "");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function save() {
    setBusy(true);
    setError(null);
    try {
      const response = await fetch(
        `/api/v1/brokers/terminals/${encodeURIComponent(terminal)}/name`,
        {
          method: "PUT",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ label: name }),
        },
      );
      if (!response.ok) {
        const payload = await response.json().catch(() => ({}));
        // The server's own words. Both refusals it can give - the name is
        // another terminal's key, or another terminal already has it - are
        // about two rows reading the same, and paraphrasing them into
        // "failed" would hide the one thing worth knowing.
        setError(payload?.message ?? payload?.detail ?? labels.failed);
        return;
      }
      // Re-read rather than trust the field: the server trims and collapses
      // whitespace, so what is stored is not always what was typed.
      window.location.reload();
    } catch (problem) {
      setError(String(problem));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="space-y-3">
      <label className="block space-y-1">
        <span className="text-xs font-semibold">{labels.field}</span>
        <input
          type="text"
          value={name}
          maxLength={60}
          onChange={(event) => setName(event.target.value)}
          placeholder={labels.placeholder}
          className="field"
        />
        <span className="block text-xs ink-3">{labels.hint}</span>
      </label>
      <div className="flex items-center gap-3">
        <button type="button" onClick={save} disabled={busy} className="btn">
          {busy ? labels.saving : labels.save}
        </button>
        {error && (
          <span className="text-xs" style={{ color: "var(--bad)" }}>
            {error}
          </span>
        )}
      </div>
    </div>
  );
}
