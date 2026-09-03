"use client";

import { useState } from "react";

/**
 * What this account trades and how much it risks, changed from here.
 *
 * Both settings lived in an environment variable, so changing either was an
 * SSH session and a container recreate - and the recreate killed whatever
 * cycle was in flight. Twice in one day an operator had to ask an engineer
 * to change a number. A setting nobody can reach is a setting nobody tunes.
 *
 * **Stored and in force are shown separately**, because they are different
 * facts and the difference is the one that confuses people. An account with
 * nothing stored here is not an account with no settings - it is running on
 * the deployment's own figures, and a form that showed only the stored row
 * would render blank for an account that is very much trading.
 */

export type PolicyLabels = {
  title: string;
  subtitle: string;
  risk: string;
  riskHint: string;
  brains: string;
  brainsHint: string;
  inForce: string;
  usingFleetDefault: string;
  save: string;
  saving: string;
  saved: string;
  failed: string;
  cap: string;
};

export type PolicyState = {
  stored: { risk_percent: number | null; strategies: string[] } | null;
  in_force: { risk_percent: number | null; strategies: string[]; refused: string | null };
  available_strategies: string[];
  max_risk_percent: number;
};

export function AccountPolicyForm({
  login,
  initial,
  labels,
}: {
  login: string;
  initial: PolicyState;
  labels: PolicyLabels;
}) {
  const [risk, setRisk] = useState<string>(
    initial.stored?.risk_percent != null ? String(initial.stored.risk_percent) : "",
  );
  const [chosen, setChosen] = useState<string[]>(initial.stored?.strategies ?? []);
  const [busy, setBusy] = useState(false);
  const [note, setNote] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  function toggle(name: string) {
    setChosen((current) =>
      current.includes(name)
        ? current.filter((n) => n !== name)
        : [...current, name],
    );
  }

  async function save() {
    setBusy(true);
    setError(null);
    setNote(null);
    try {
      const trimmed = risk.trim();
      const response = await fetch(
        `/api/v1/execution/accounts/${encodeURIComponent(login)}/policy`,
        {
          method: "PUT",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            strategies: chosen,
            // Blank means "not set here", which is not the same as zero -
            // zero would make R undefined and stop the account by a route
            // that is not the kill switch.
            risk_percent: trimmed === "" ? null : Number(trimmed),
          }),
        },
      );
      if (!response.ok) {
        const payload = await response.json().catch(() => ({}));
        setError(payload?.message ?? labels.failed);
        return;
      }
      setNote(labels.saved);
      // Re-read rather than trust the form: what is in force is decided by
      // the server, and showing the value we just typed would hide a cap or
      // a fallback that changed it.
      window.location.reload();
    } catch (problem) {
      setError(String(problem));
    } finally {
      setBusy(false);
    }
  }

  const forceRisk = initial.in_force.risk_percent;
  const forceBrains = initial.in_force.strategies;

  return (
    <div className="space-y-4">
      <div className="text-xs ink-3">
        {labels.inForce}:{" "}
        <span className="num" dir="ltr">
          {forceRisk === null ? "—" : `${forceRisk}%`}
        </span>
        {" · "}
        <span dir="ltr">{forceBrains.length ? forceBrains.join(", ") : "—"}</span>
        {initial.stored === null && <> · {labels.usingFleetDefault}</>}
      </div>

      <label className="block space-y-1">
        <span className="text-xs font-semibold">{labels.risk}</span>
        <input
          type="number"
          step="0.05"
          min="0"
          max={initial.max_risk_percent}
          value={risk}
          onChange={(event) => setRisk(event.target.value)}
          dir="ltr"
          className="field"
          placeholder="—"
        />
        <span className="block text-xs ink-3">
          {labels.riskHint} · {labels.cap.replace("{max}", String(initial.max_risk_percent))}
        </span>
      </label>

      <div className="space-y-1">
        <span className="text-xs font-semibold">{labels.brains}</span>
        <div className="flex flex-wrap gap-2">
          {initial.available_strategies.map((name) => (
            <label
              key={name}
              className="inline-flex items-center gap-1.5 text-xs border rounded px-2 py-1"
              style={{ borderColor: "var(--line)" }}
              dir="ltr"
            >
              <input
                type="checkbox"
                checked={chosen.includes(name)}
                onChange={() => toggle(name)}
              />
              {name}
            </label>
          ))}
        </div>
        <span className="block text-xs ink-3">{labels.brainsHint}</span>
      </div>

      <div className="flex items-center gap-3">
        <button type="button" onClick={save} disabled={busy} className="btn">
          {busy ? labels.saving : labels.save}
        </button>
        {note && <span className="text-xs" style={{ color: "var(--good)" }}>{note}</span>}
        {error && <span className="text-xs" style={{ color: "var(--bad)" }}>{error}</span>}
      </div>
    </div>
  );
}
