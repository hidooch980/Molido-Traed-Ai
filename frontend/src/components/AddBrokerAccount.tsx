"use client";

import { useState } from "react";

/**
 * The form that connects a broker account, and the one place in this
 * application a secret is typed.
 *
 * Three deliberate choices.
 *
 * The password field is never put into component state that outlives the
 * submit, never logged, and never echoed back by the endpoint. It goes from
 * the input to the request body and is dropped.
 *
 * No key is asked for. The route carries a permission above READ, which the
 * API refuses for an anonymous caller, and the browser proves who it is with
 * the session cookie set at sign-in. Asking an operator to fetch a key from a
 * terminal is asking for a step that does not get taken.
 *
 * The result is polled rather than assumed. The API hands the request to a
 * host agent it cannot see, so "queued" and "applied" are different facts and
 * the second one takes a few seconds to arrive. Reporting the first as though
 * it were the second is how a login that silently failed looks like a success.
 */
/** Every label this form needs, resolved on the server and handed over as
 *  plain strings. A `t` function cannot cross that boundary - React refuses to
 *  serialise it, and the page 500s with "Functions cannot be passed directly to
 *  Client Components", which is a runtime error no type check or build catches.
 */
export interface BrokerFormLabels {
  add: string;
  login: string;
  server: string;
  password: string;
  passwordHint: string;
  connect: string;
  cancel: string;
  submitting: string;
  queued: string;
  applied: string;
  failed: string;
  refused: string;
  signInFirst: string;
  stillWaiting: string;
  connected: string;
  terminal: string;
  terminalAuto: string;
  terminalHint: string;
}

export function AddBrokerAccount({
  labels,
  terminals = [],
}: {
  labels: BrokerFormLabels;
  /** Terminal keys from the live map, for the optional selector. Empty keeps
   *  the selector hidden and the agent picking the first free terminal. */
  terminals?: string[];
}) {
  const [open, setOpen] = useState(false);
  const [login, setLogin] = useState("");
  const [server, setServer] = useState("");
  const [password, setPassword] = useState("");
  const [terminal, setTerminal] = useState("");
  const [busy, setBusy] = useState(false);
  const [status, setStatus] = useState<string | null>(null);
  const [tone, setTone] = useState<"good" | "warning" | "critical">("warning");

  async function submit(event: React.FormEvent) {
    event.preventDefault();
    setBusy(true);
    setStatus(labels.submitting);
    setTone("warning");

    try {
      const response = await fetch("/api/v1/brokers/link", {
        method: "POST",
        // No key. The browser carries a session cookie, and an operator
        // hunting for a key in a terminal is a step that does not get taken.
        headers: { "Content-Type": "application/json" },
        credentials: "same-origin",
        // Blank terminal is sent as absent: the agent reads a missing key as
        // "first terminal that has never held an account", and an empty
        // string would be a name lookup that fails.
        body: JSON.stringify({
          login,
          server,
          password,
          terminal: terminal || null,
        }),
      });
      const body = await response.json();

      if (!response.ok) {
        setTone("critical");
        // `message` first, because that is the field this API uses. Domain
        // errors are serialised as {error, message, context} by the handler in
        // main.py - not FastAPI's {detail} - so reading `detail` first threw
        // away every real reason and showed the generic fallback instead. That
        // fallback says "check the account number and server", which sent
        // somebody hunting through a login that was perfectly correct while
        // the actual answer, "you are not signed in", sat unread in the body.
        //
        // 401 is special-cased because no message about the account number is
        // the right thing to show a person who simply has no session.
        setStatus(
          response.status === 401
            ? labels.signInFirst
            : (body?.message ?? body?.detail?.message ?? body?.detail ?? labels.refused),
        );
        return;
      }

      // Dropped the moment it has been sent. Nothing in this component keeps
      // it, and nothing in the application stores it.
      setPassword("");

      const id: string = body.request_id;
      setStatus(labels.queued);

      // The agent restarts the terminal and then waits for it to report a
      // live account, so a real answer takes up to a minute and a half.
      // Forty-five tries at two seconds covers that; past it, saying "still
      // waiting" is more honest than spinning forever.
      for (let attempt = 0; attempt < 45; attempt++) {
        await new Promise((resolve) => setTimeout(resolve, 2000));
        const check = await fetch(`/api/v1/brokers/link/${id}`);
        const result = await check.json();
        if (result.known) {
          // Applied and connected are different facts. A wrong server name
          // applies perfectly and connects to nothing, and calling that a
          // success sends the reader looking for a bug in the form.
          const ok = result.applied && result.connected;
          setTone(ok ? "good" : "critical");
          setStatus(ok ? labels.connected : `${labels.failed}: ${result.reason ?? ""}`);
          return;
        }
      }
      setTone("warning");
      setStatus(labels.stillWaiting);
    } catch (error) {
      setTone("critical");
      setStatus(`${labels.failed}: ${String(error)}`);
    } finally {
      setBusy(false);
    }
  }

  if (!open) {
    return (
      <button
        type="button"
        onClick={() => setOpen(true)}
        className="pill"
        style={{ color: "var(--accent)", borderColor: "var(--accent)", cursor: "pointer" }}
      >
        + {labels.add}
      </button>
    );
  }

  const field = {
    background: "var(--panel-raised)",
    border: "1px solid var(--border-strong)",
    borderRadius: "3px",
    padding: "0.35rem 0.5rem",
    color: "var(--ink)",
    fontSize: "0.8125rem",
    width: "100%",
  } as const;

  return (
    <form onSubmit={submit} className="p-4 space-y-3" style={{ maxWidth: "34rem" }}>
      <div className="grid gap-3 sm:grid-cols-2">
        <label className="space-y-1 block">
          <span className="eyebrow">{labels.login}</span>
          <input
            value={login}
            onChange={(e) => setLogin(e.target.value)}
            inputMode="numeric"
            required
            style={field}
            placeholder="12345678"
          />
        </label>
        <label className="space-y-1 block">
          <span className="eyebrow">{labels.server}</span>
          <input
            value={server}
            onChange={(e) => setServer(e.target.value)}
            required
            style={field}
            placeholder="MetaQuotes-Demo"
          />
        </label>
      </div>

      {terminals.length > 0 && (
        <label className="space-y-1 block">
          <span className="eyebrow">{labels.terminal}</span>
          <select
            value={terminal}
            onChange={(e) => setTerminal(e.target.value)}
            style={field}
          >
            <option value="">{labels.terminalAuto}</option>
            {terminals.map((key) => (
              <option key={key} value={key}>
                {key}
              </option>
            ))}
          </select>
          <span className="text-xs ink-3 block">{labels.terminalHint}</span>
        </label>
      )}

      <label className="space-y-1 block">
        <span className="eyebrow">{labels.password}</span>
        <input
          type="password"
          value={password}
          onChange={(e) => setPassword(e.target.value)}
          required
          autoComplete="off"
          style={field}
        />
        <span className="text-xs ink-3 block">{labels.passwordHint}</span>
      </label>


      <div className="flex items-center gap-2 flex-wrap">
        <button
          type="submit"
          disabled={busy}
          className="pill"
          style={{
            color: "var(--accent)",
            borderColor: "var(--accent)",
            cursor: busy ? "wait" : "pointer",
          }}
        >
          {busy ? labels.submitting : labels.connect}
        </button>
        <button
          type="button"
          onClick={() => setOpen(false)}
          className="pill"
          style={{ color: "var(--ink-3)", cursor: "pointer" }}
        >
          {labels.cancel}
        </button>
      </div>

      {status && (
        <p
          className="text-xs leading-relaxed"
          style={{
            color:
              tone === "good"
                ? "var(--good)"
                : tone === "critical"
                  ? "var(--critical)"
                  : "var(--warning)",
          }}
        >
          {status}
        </p>
      )}
    </form>
  );
}
