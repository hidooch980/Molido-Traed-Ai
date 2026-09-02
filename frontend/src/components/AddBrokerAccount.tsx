"use client";

import { useEffect, useState } from "react";

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
  serverHint: string;
  connect: string;
  cancel: string;
  submitting: string;
  queued: string;
  stageConfig: string;
  stageRestarted: string;
  stageWaiting: string;
  stageSeen: string;
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

//: Where the half-filled form lives between visits.
//:
//: Setting up an account means reading a number off a broker's email, a
//: server name off a different page, and finding the password somewhere
//: else. Doing that in one sitting is the exception, and a form that empties
//: itself on every reload turns three interruptions into three restarts.
const DRAFT_KEY = "molido.broker.draft";

//: Server names with a successful authorization on this deployment.
//:
//: This page refuses to publish a directory of brokers and is right to: a
//: guessed server name produces a connection that never establishes and a
//: search that goes everywhere except the list that looked authoritative.
//: These are not guesses. Each was read out of a terminal's own journal,
//: from a line saying the broker accepted a login against it:
//:
//:     MetaQuotes-Demo       124 successful authorizations
//:     RoboForex-Pro          88
//:     FundedNext-Server 3     4
//:
//: The third is the entire argument for having this at all. Its real name
//: carries a space, `FundedNext-Server3` was typed instead, and the result
//: was days spent hunting a connection that had never reached a broker.
//:
//: They are merged with whatever is connected right now, and typing stays
//: free - the first suggestion sourced only from live terminals was empty
//: exactly when somebody had none connected, which is when the list is for.
const PROVEN_SERVERS = [
  "MetaQuotes-Demo",
  "RoboForex-Pro",
  "FundedNext-Server 3",
];

//: The password is deliberately absent from what is saved. Everything else
//: here is on the page already - the login shows in the terminals table the
//: moment it connects - but a password in browser storage is a password on a
//: shared laptop, in a backup, and in whatever else reads that origin. The
//: one field worth protecting is the one field not kept.
type Draft = { login: string; server: string; terminal: string };

function readDraft(): Draft | null {
  try {
    const raw = window.localStorage.getItem(DRAFT_KEY);
    return raw ? (JSON.parse(raw) as Draft) : null;
  } catch {
    // Private windows, cleared site data and browsers set to refuse storage
    // all land here. A form that cannot remember still has to work.
    return null;
  }
}

export function AddBrokerAccount({
  labels,
  terminals = [],
  knownServers = [],
}: {
  labels: BrokerFormLabels;
  /** Terminal keys from the live map, for the optional selector. Empty keeps
   *  the selector hidden and the agent picking the first free terminal. */
  terminals?: string[];
  /** Server names with a proven authorization on this host. Suggestions, not
   *  a catalogue - see the field itself for why that distinction matters. */
  knownServers?: string[];
}) {
  const [open, setOpen] = useState(false);
  const [login, setLogin] = useState("");
  const [server, setServer] = useState("");
  const [password, setPassword] = useState("");
  const [terminal, setTerminal] = useState("");
  const [restored, setRestored] = useState(false);

  // Restored when the form opens rather than on mount: reading storage for a
  // panel nobody has opened is work for nothing, and the effect would run on
  // every page view.
  useEffect(() => {
    if (!open || restored) return;
    const draft = readDraft();
    if (draft) {
      if (draft.login) setLogin(draft.login);
      if (draft.server) setServer(draft.server);
      if (draft.terminal) setTerminal(draft.terminal);
    }
    setRestored(true);
  }, [open, restored]);

  useEffect(() => {
    if (!open) return;
    try {
      window.localStorage.setItem(
        DRAFT_KEY,
        JSON.stringify({ login, server, terminal }),
      );
    } catch {
      // Saving is a convenience. Losing it must not stop the registration.
    }
  }, [open, login, server, terminal]);
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

      // The agent restarts the terminal and waits for it to publish a live
      // account. Ninety seconds was the old budget on both sides and it was
      // wrong here: a real registration published ten minutes after it was
      // applied, on a host running eight terminals under Wine. This has to
      // outlast the agent's own wait or the page reports "still waiting" for
      // an account that connects perfectly a few minutes later.
      const tries = 400; // 400 x 2s = ~13 min, just past the agent's 12
      for (let attempt = 0; attempt < tries; attempt++) {
        await new Promise((resolve) => setTimeout(resolve, 2000));
        const check = await fetch(`/api/v1/brokers/link/${id}`);
        const result = await check.json();
        // Seven minutes between "queued" and "done" on this host, and the
        // page used to show the first word for all of them - so a login that
        // was working looked stuck at exactly the moment it was working. The
        // agent names its stage now, and the stage is what is shown.
        if (!result.known && result.progress?.stage) {
          const stage = String(result.progress.stage);
          const secs = Number(result.progress.elapsed_seconds ?? 0);
          const text =
            stage === "config_written" ? labels.stageConfig
            : stage === "terminal_restarted" ? labels.stageRestarted
            : stage === "waiting_for_account" ? labels.stageWaiting.replace("{s}", String(secs))
            : stage === "account_visible" ? labels.stageSeen
            : labels.queued;
          setStatus(text);
        }
        if (result.known) {
          // Applied and connected are different facts. A wrong server name
          // applies perfectly and connects to nothing, and calling that a
          // success sends the reader looking for a bug in the form.
          const ok = result.applied && result.connected;
          setTone(ok ? "good" : "critical");
          setStatus(ok ? labels.connected : `${labels.failed}: ${result.reason ?? ""}`);
          if (ok) {
            // The draft has served its purpose. Left behind, the next
            // registration opens pre-filled with the account just connected,
            // which is the one account it cannot be for.
            try {
              window.localStorage.removeItem(DRAFT_KEY);
            } catch {
              // Nothing to clean up if nothing could be stored.
            }
          }
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
          {/* A suggestion list, not a catalogue.
              This page refuses to publish a directory of brokers, and it is
              right to: a guessed server name produces a connection that never
              establishes and a search that goes everywhere except the list
              that looked authoritative. `FundedNext-Server3` cost days here,
              because the real name has a space in it.
              What is offered below is the opposite of a guess - every entry
              is a name that has successfully authorized on this host, taken
              from the terminals' own journals. Typing is still free, so a
              broker nobody here has used yet is not blocked by a list that
              has never heard of it. */}
          <input
            value={server}
            onChange={(e) => setServer(e.target.value)}
            required
            style={field}
            placeholder="MetaQuotes-Demo"
            list="known-servers"
            autoComplete="off"
            spellCheck={false}
          />
          <datalist id="known-servers">
            {Array.from(new Set([...PROVEN_SERVERS, ...knownServers]))
              .sort()
              .map((name) => (
                <option key={name} value={name} />
              ))}
          </datalist>
          <span className="text-xs ink-3 block">{labels.serverHint}</span>
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
