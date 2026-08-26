"use client";

import { useState } from "react";

import type { RulebookEntry } from "@/lib/api";

/**
 * Recording a prop account, and the rules it is measured against.
 *
 * The API to do this has existed since challenge tracking was built and there
 * was no way to reach it from a browser. An endpoint nobody can call is a
 * feature nobody has, which is why the question "where do I enter my account"
 * had no answer.
 *
 * **The confirmation box is not pre-ticked, and that is the load-bearing
 * decision here.** Every rulebook in the catalogue was transcribed from a
 * provider's public page on a stated date, and a marketing page is not the
 * contract somebody signed. Until the holder has compared the two, the
 * platform measures the account against nothing and says so - a confident
 * verdict drawn from the wrong document is worse than no verdict, because it
 * looks exactly like a right one. A form that ticks the box on their behalf
 * collects an agreement nobody gave.
 *
 * **An account is recorded before it is confirmed, not after.** Somebody
 * halfway through setup has a real account with rules nobody has checked, and
 * refusing the row would mean the only accounts the system knows about are the
 * ones whose paperwork is already finished.
 */

export interface AccountFormLabels {
  title: string;
  subtitle: string;
  label: string;
  labelHint: string;
  program: string;
  programHint: string;
  balance: string;
  balanceHint: string;
  currency: string;
  perR: string;
  perRHint: string;
  notes: string;
  confirm: string;
  confirmHint: string;
  submit: string;
  submitting: string;
  created: string;
  failed: string;
  choose: string;
}

/**
 * **No callback prop, deliberately.** A function cannot cross the boundary
 * from a server component, and the page that renders this is one - it would
 * compile, build, and fail at request time with "Functions cannot be passed
 * directly to Client Components", which this application has already done once
 * in production. The list above this form is server-rendered anyway, so a
 * reload is what actually refreshes it.
 */
export function ChallengeAccountForm({
  labels,
  rulebooks,
}: {
  labels: AccountFormLabels;
  rulebooks: RulebookEntry[];
}) {
  const [label, setLabel] = useState("");
  const [rulebookKey, setRulebookKey] = useState("");
  const [balance, setBalance] = useState("");
  const [currency, setCurrency] = useState("USD");
  const [perR, setPerR] = useState("");
  const [notes, setNotes] = useState("");
  const [confirmed, setConfirmed] = useState(false);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState<{ ok: boolean; text: string } | null>(null);

  async function submit(event: React.FormEvent) {
    event.preventDefault();
    setBusy(true);
    setMessage(null);
    try {
      const response = await fetch("/api/v1/risk/challenge-accounts", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          label,
          rulebook_key: rulebookKey,
          starting_balance: balance,
          currency,
          // Empty means "not decided yet" rather than zero. What one R is
          // worth in currency is a sizing choice, and a zero there would make
          // every position size zero without saying why.
          currency_per_r: perR === "" ? null : perR,
          rules_confirmed: confirmed,
          notes,
        }),
      });
      const payload = await response.json().catch(() => ({}));
      if (!response.ok) {
        // The server's own sentence where it wrote one - it knows which field
        // was refused and why, and a generic failure throws that away.
        setMessage({ ok: false, text: payload?.message ?? labels.failed });
        return;
      }
      setMessage({ ok: true, text: labels.created });
      setLabel("");
      setBalance("");
      setPerR("");
      setNotes("");
      setConfirmed(false);
      window.location.reload();
    } catch {
      setMessage({ ok: false, text: labels.failed });
    } finally {
      setBusy(false);
    }
  }

  return (
    <form onSubmit={submit} className="user-form">
      <label className="auth-field">
        <span className="auth-label">{labels.label}</span>
        <input
          className="auth-input"
          value={label}
          onChange={(e) => setLabel(e.target.value)}
          required
          maxLength={120}
          placeholder="FundedNext 60k"
        />
        <span className="auth-hint">{labels.labelHint}</span>
      </label>

      <label className="auth-field">
        <span className="auth-label">{labels.program}</span>
        <select
          className="auth-input"
          value={rulebookKey}
          onChange={(e) => setRulebookKey(e.target.value)}
          required
        >
          <option value="">{labels.choose}</option>
          {/* The catalogue as the server holds it. A hardcoded list here
              would keep offering a program the API had stopped knowing, and
              the failure arrives as a rejected form nobody can explain. */}
          {rulebooks.map((book) => (
            <option key={book.key} value={book.key}>
              {book.provider} · {book.program} · {book.phase}
            </option>
          ))}
        </select>
        <span className="auth-hint">{labels.programHint}</span>
      </label>

      <label className="auth-field">
        <span className="auth-label">{labels.balance}</span>
        <input
          className="auth-input"
          type="number"
          inputMode="decimal"
          min="1"
          step="any"
          value={balance}
          onChange={(e) => setBalance(e.target.value)}
          required
          dir="ltr"
          placeholder="60000"
        />
        <span className="auth-hint">{labels.balanceHint}</span>
      </label>

      <label className="auth-field">
        <span className="auth-label">{labels.currency}</span>
        <input
          className="auth-input"
          value={currency}
          onChange={(e) => setCurrency(e.target.value.toUpperCase())}
          maxLength={8}
          dir="ltr"
        />
      </label>

      <label className="auth-field">
        <span className="auth-label">{labels.perR}</span>
        <input
          className="auth-input"
          type="number"
          inputMode="decimal"
          min="0"
          step="any"
          value={perR}
          onChange={(e) => setPerR(e.target.value)}
          dir="ltr"
          placeholder="600"
        />
        <span className="auth-hint">{labels.perRHint}</span>
      </label>

      <label className="auth-field" style={{ gridColumn: "1 / -1" }}>
        <span className="auth-label">{labels.notes}</span>
        <input
          className="auth-input"
          value={notes}
          onChange={(e) => setNotes(e.target.value)}
          maxLength={2000}
        />
      </label>

      {/* Deliberately last, deliberately unticked, and deliberately explained
          rather than labelled. Somebody scanning a form ticks boxes; somebody
          reading a sentence about which document they are agreeing to does
          not tick it by accident. */}
      <label
        className="auth-field"
        style={{ gridColumn: "1 / -1", flexDirection: "row", alignItems: "flex-start", gap: "0.6rem" }}
      >
        <input
          type="checkbox"
          checked={confirmed}
          onChange={(e) => setConfirmed(e.target.checked)}
          style={{ marginTop: "0.25rem" }}
        />
        <span className="min-w-0">
          <span className="auth-label">{labels.confirm}</span>
          <span className="auth-hint">{labels.confirmHint}</span>
        </span>
      </label>

      <button type="submit" className="auth-button user-form-submit" disabled={busy}>
        {busy ? labels.submitting : labels.submit}
      </button>

      {message && (
        <p
          className="text-xs"
          style={{
            gridColumn: "1 / -1",
            color: message.ok ? "var(--good)" : "var(--critical)",
          }}
          role="status"
        >
          {message.text}
        </p>
      )}
    </form>
  );
}
