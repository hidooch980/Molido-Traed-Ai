"use client";

import { useState } from "react";

import type { TerminalRow } from "@/lib/api";

/**
 * Registering the MetaTrader terminals that publish into this platform.
 *
 * Bridge directories used to come from an environment variable. That is the
 * right shape for the one terminal this platform was built around and the
 * wrong shape for eleven: every new account meant an edit, a rebuild, and
 * somebody with a shell - so the person who owns the accounts could not add
 * one, and the person who could had no way to know which account was which.
 *
 * **No credentials on this form, and that is the point of it.** A terminal is
 * a name and a key here. The broker login and password go into MetaTrader's
 * own configuration on the machine running the terminal and never travel to
 * this platform, which has no use for them - and a field that could carry one
 * is a field somebody will eventually put one in.
 *
 * **The key is refused rather than tidied.** It becomes a directory name, so
 * it is lowercase letters, digits, hyphen and underscore only. Silently
 * rewriting `My Account` into `my-account` would produce a terminal whose key
 * is not the one typed into the expert, and the symptom of that is a terminal
 * publishing perfectly into a folder nobody reads.
 *
 * **Registered and publishing are shown as separate columns.** They answer
 * different questions - one is configuration, one is evidence - and a page
 * that showed only the first would list eleven healthy-looking rows for
 * eleven terminals that were all switched off.
 */

export interface TerminalLabels {
  key: string;
  keyHint: string;
  label: string;
  labelHint: string;
  broker: string;
  kind: string;
  kindHint: string;
  add: string;
  adding: string;
  added: string;
  failed: string;
  noTerminals: string;
  refused: string;
  colKey: string;
  colLabel: string;
  colBroker: string;
  colState: string;
  publishing: string;
  silent: string;
  off: string;
  disable: string;
  enable: string;
  neverPublished: string;
  secondsAgo: string;
  nextSteps: string;
}

export function TerminalAdmin({
  labels,
  terminals,
  refused,
  publishUrl,
}: {
  labels: TerminalLabels;
  terminals: TerminalRow[];
  refused: boolean;
  /** The absolute URL an expert posts to. Shown after a terminal is added,
   *  because that is the moment somebody is about to type it. */
  publishUrl: string;
}) {
  const [key, setKey] = useState("");
  const [label, setLabel] = useState("");
  const [broker, setBroker] = useState("");
  const [kind, setKind] = useState("");
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState<{ ok: boolean; text: string } | null>(null);

  async function add(event: React.FormEvent) {
    event.preventDefault();
    setBusy(true);
    setMessage(null);
    try {
      const response = await fetch("/api/v1/terminals", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ key, label, broker, kind }),
      });
      const payload = await response.json().catch(() => ({}));
      if (!response.ok) {
        // The server's own sentence. It knows which rule the key broke and
        // says so; a generic failure would leave somebody guessing at a
        // pattern nobody showed them.
        setMessage({ ok: false, text: payload?.message ?? labels.failed });
        return;
      }
      setMessage({ ok: true, text: labels.added });
      setKey("");
      setLabel("");
      setBroker("");
      window.location.reload();
    } catch {
      setMessage({ ok: false, text: labels.failed });
    } finally {
      setBusy(false);
    }
  }

  async function setActive(id: string, active: boolean) {
    await fetch(`/api/v1/terminals/${id}/active`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ active }),
    });
    window.location.reload();
  }

  if (refused) return <p className="text-sm ink-3">{labels.refused}</p>;

  return (
    <div className="space-y-5">
      <form onSubmit={add} className="user-form">
        <label className="auth-field">
          <span className="auth-label">{labels.key}</span>
          <input
            className="auth-input"
            value={key}
            onChange={(e) => setKey(e.target.value)}
            required
            maxLength={64}
            dir="ltr"
            placeholder="fundednext-60k"
            /* Mirrors the server's rule so the refusal happens before the
               round trip. The server still enforces it - a pattern in a
               browser is a convenience, never a control. */
            pattern="[a-z0-9][a-z0-9_\-]{0,62}[a-z0-9]"
          />
          <span className="auth-hint">{labels.keyHint}</span>
        </label>

        <label className="auth-field">
          <span className="auth-label">{labels.label}</span>
          <input
            className="auth-input"
            value={label}
            onChange={(e) => setLabel(e.target.value)}
            maxLength={120}
            placeholder="FundedNext 60k · phase 1"
          />
          <span className="auth-hint">{labels.labelHint}</span>
        </label>

        <label className="auth-field">
          <span className="auth-label">{labels.broker}</span>
          <input
            className="auth-input"
            value={broker}
            onChange={(e) => setBroker(e.target.value)}
            maxLength={120}
            placeholder="RoboForex"
          />
        </label>

        <label className="auth-field">
          <span className="auth-label">{labels.kind}</span>
          <input
            className="auth-input"
            value={kind}
            onChange={(e) => setKind(e.target.value)}
            maxLength={32}
            placeholder="funded"
          />
          <span className="auth-hint">{labels.kindHint}</span>
        </label>

        <button type="submit" className="auth-button user-form-submit" disabled={busy}>
          {busy ? labels.adding : labels.add}
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

      {terminals.length === 0 ? (
        <p className="text-sm ink-3">{labels.noTerminals}</p>
      ) : (
        <div className="scroll-x">
          <table className="data">
            <thead>
              <tr>
                <th>{labels.colKey}</th>
                <th>{labels.colLabel}</th>
                <th>{labels.colBroker}</th>
                <th>{labels.colState}</th>
                <th />
              </tr>
            </thead>
            <tbody>
              {terminals.map((terminal) => (
                <tr key={terminal.id}>
                  <td className="font-semibold" dir="ltr">
                    {terminal.key}
                  </td>
                  <td className="ink-2">{terminal.label || "—"}</td>
                  <td className="ink-3">
                    {[terminal.broker, terminal.kind].filter(Boolean).join(" · ") || "—"}
                  </td>
                  <td>
                    {/* Three states, not two. Switched off is a decision;
                        silent is a fault; publishing is health - and
                        collapsing the first two would hide a terminal
                        somebody turned off on purpose among the broken ones. */}
                    {!terminal.is_active ? (
                      <span className="pill" style={{ color: "var(--ink-3)" }}>
                        {labels.off}
                      </span>
                    ) : terminal.publishing ? (
                      <span className="pill" style={{ color: "var(--good)" }}>
                        {labels.publishing}
                        {terminal.age_seconds != null && (
                          <span className="ink-3">
                            {" "}
                            · {labels.secondsAgo.replace(
                              "{n}",
                              String(Math.round(terminal.age_seconds)),
                            )}
                          </span>
                        )}
                      </span>
                    ) : (
                      <span
                        className="pill"
                        style={{ color: "var(--warning)", borderColor: "var(--warning)" }}
                        title={terminal.reason ?? undefined}
                      >
                        {labels.silent}
                      </span>
                    )}
                  </td>
                  <td>
                    <button
                      type="button"
                      className="pill"
                      onClick={() => void setActive(terminal.id, !terminal.is_active)}
                      style={{ color: "var(--ink-2)", cursor: "pointer" }}
                    >
                      {terminal.is_active ? labels.disable : labels.enable}
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      <div className="panel p-4 space-y-2">
        <p className="text-xs ink-2">{labels.nextSteps}</p>
        <pre
          className="text-xs ink-3"
          dir="ltr"
          style={{ whiteSpace: "pre-wrap", wordBreak: "break-all" }}
        >
{`PublishUrl        ${publishUrl}
PublishApiKey     (create one under Security)
PublishAccountKey (the key from the table above)`}
        </pre>
      </div>
    </div>
  );
}
