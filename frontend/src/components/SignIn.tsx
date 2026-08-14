"use client";

import { useEffect, useState } from "react";

/**
 * Sign in, and show whether this browser is signed in at all.
 *
 * It lives in the shell rather than on a page of its own, because the question
 * it answers — "can I press the buttons?" — is asked from every page, and a
 * separate login screen would mean discovering the answer only after being
 * refused somewhere else.
 *
 * The state comes from the server on mount. Trusting a flag in local storage
 * would show an operator a signed-in header over a session that expired hours
 * ago, and the first they would learn of it is a button that silently fails.
 */
export interface SignInLabels {
  signIn: string;
  signOut: string;
  email: string;
  password: string;
  submit: string;
  cancel: string;
  working: string;
  failed: string;
  signedInAs: string;
  anonymous: string;
  anonymousHint: string;
}

interface Me {
  authenticated: boolean;
  role: string | null;
  can_change_state: boolean;
}

export function SignIn({ labels }: { labels: SignInLabels }) {
  const [me, setMe] = useState<Me | null>(null);
  const [open, setOpen] = useState(false);
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function refresh() {
    try {
      const response = await fetch("/api/v1/session/me", { cache: "no-store" });
      setMe(await response.json());
    } catch {
      setMe(null);
    }
  }

  useEffect(() => {
    void refresh();
  }, []);

  async function submit(event: React.FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const response = await fetch("/api/v1/session/sign-in", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ email, password }),
      });
      if (!response.ok) {
        setError(labels.failed);
        return;
      }
      // Dropped the moment it has been sent; nothing here keeps it.
      setPassword("");
      setOpen(false);
      await refresh();
    } catch {
      setError(labels.failed);
    } finally {
      setBusy(false);
    }
  }

  async function signOut() {
    await fetch("/api/v1/session/sign-out", { method: "POST" });
    await refresh();
  }

  const field = {
    background: "var(--panel-raised)",
    border: "1px solid var(--border-strong)",
    borderRadius: "3px",
    padding: "0.3rem 0.5rem",
    color: "var(--ink)",
    fontSize: "0.8125rem",
    width: "100%",
  } as const;

  if (me?.authenticated) {
    return (
      <span className="flex items-center gap-2">
        <span className="text-xs ink-3">
          {labels.signedInAs} {me.role}
        </span>
        <button
          type="button"
          onClick={signOut}
          className="pill"
          style={{ color: "var(--ink-3)", cursor: "pointer" }}
        >
          {labels.signOut}
        </button>
      </span>
    );
  }

  if (!open) {
    return (
      <button
        type="button"
        onClick={() => setOpen(true)}
        className="pill"
        style={{ color: "var(--accent)", borderColor: "var(--accent)", cursor: "pointer" }}
        title={labels.anonymousHint}
      >
        {labels.signIn}
      </button>
    );
  }

  return (
    <form
      onSubmit={submit}
      className="panel p-3 space-y-2"
      style={{ position: "absolute", insetInlineEnd: "1rem", top: "3rem", zIndex: 20, width: "18rem" }}
    >
      <label className="space-y-1 block">
        <span className="eyebrow">{labels.email}</span>
        <input
          type="email"
          value={email}
          onChange={(e) => setEmail(e.target.value)}
          required
          autoComplete="username"
          style={field}
        />
      </label>
      <label className="space-y-1 block">
        <span className="eyebrow">{labels.password}</span>
        <input
          type="password"
          value={password}
          onChange={(e) => setPassword(e.target.value)}
          required
          autoComplete="current-password"
          style={field}
        />
      </label>
      <div className="flex gap-2">
        <button
          type="submit"
          disabled={busy}
          className="pill"
          style={{ color: "var(--accent)", borderColor: "var(--accent)", cursor: "pointer" }}
        >
          {busy ? labels.working : labels.submit}
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
      {error && (
        <p className="text-xs" style={{ color: "var(--critical)" }}>
          {error}
        </p>
      )}
    </form>
  );
}
