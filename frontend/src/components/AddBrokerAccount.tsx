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
 * The API key is asked for in the form rather than stored in the page. This
 * route is the first in the application that changes state, so it carries a
 * permission above READ — which the API refuses for an anonymous caller
 * whether or not authentication is switched on. Keeping the key in a field the
 * operator pastes each time means the browser is not holding a credential that
 * can place a request while nobody is looking.
 *
 * The result is polled rather than assumed. The API hands the request to a
 * host agent it cannot see, so "queued" and "applied" are different facts and
 * the second one takes a few seconds to arrive. Reporting the first as though
 * it were the second is how a login that silently failed looks like a success.
 */
export function AddBrokerAccount({
  t,
}: {
  t: (key: string) => string;
}) {
  const [open, setOpen] = useState(false);
  const [login, setLogin] = useState("");
  const [server, setServer] = useState("");
  const [password, setPassword] = useState("");
  const [apiKey, setApiKey] = useState("");
  const [busy, setBusy] = useState(false);
  const [status, setStatus] = useState<string | null>(null);
  const [tone, setTone] = useState<"good" | "warning" | "critical">("warning");

  async function submit(event: React.FormEvent) {
    event.preventDefault();
    setBusy(true);
    setStatus(t("broker.submitting"));
    setTone("warning");

    try {
      const response = await fetch("/api/v1/brokers/link", {
        method: "POST",
        headers: { "Content-Type": "application/json", "X-API-Key": apiKey },
        body: JSON.stringify({ login, server, password }),
      });
      const body = await response.json();

      if (!response.ok) {
        setTone("critical");
        setStatus(body?.detail?.message ?? body?.detail ?? t("broker.refused"));
        return;
      }

      // Dropped the moment it has been sent. Nothing in this component keeps
      // it, and nothing in the application stores it.
      setPassword("");

      const id: string = body.request_id;
      setStatus(t("broker.queued"));

      // The agent runs on the host on its own clock. Ten tries at two seconds
      // covers a terminal restart; past that, saying "still waiting" is more
      // honest than spinning forever.
      for (let attempt = 0; attempt < 10; attempt++) {
        await new Promise((resolve) => setTimeout(resolve, 2000));
        const check = await fetch(`/api/v1/brokers/link/${id}`);
        const result = await check.json();
        if (result.known) {
          setTone(result.applied ? "good" : "critical");
          setStatus(result.applied ? t("broker.applied") : `${t("broker.failed")}: ${result.reason}`);
          return;
        }
      }
      setTone("warning");
      setStatus(t("broker.stillWaiting"));
    } catch (error) {
      setTone("critical");
      setStatus(`${t("broker.failed")}: ${String(error)}`);
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
        + {t("broker.add")}
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
          <span className="eyebrow">{t("broker.login")}</span>
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
          <span className="eyebrow">{t("broker.server")}</span>
          <input
            value={server}
            onChange={(e) => setServer(e.target.value)}
            required
            style={field}
            placeholder="MetaQuotes-Demo"
          />
        </label>
      </div>

      <label className="space-y-1 block">
        <span className="eyebrow">{t("broker.password")}</span>
        <input
          type="password"
          value={password}
          onChange={(e) => setPassword(e.target.value)}
          required
          autoComplete="off"
          style={field}
        />
        <span className="text-xs ink-3 block">{t("broker.passwordHint")}</span>
      </label>

      <label className="space-y-1 block">
        <span className="eyebrow">{t("broker.apiKey")}</span>
        <input
          type="password"
          value={apiKey}
          onChange={(e) => setApiKey(e.target.value)}
          required
          autoComplete="off"
          style={field}
        />
        <span className="text-xs ink-3 block">{t("broker.apiKeyHint")}</span>
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
          {busy ? t("broker.submitting") : t("broker.connect")}
        </button>
        <button
          type="button"
          onClick={() => setOpen(false)}
          className="pill"
          style={{ color: "var(--ink-3)", cursor: "pointer" }}
        >
          {t("broker.cancel")}
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
