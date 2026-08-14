"use client";

import { useState } from "react";

/**
 * The way in. Three forms behind one page, and which one you get is decided by
 * the deployment rather than by a tab the visitor picks.
 *
 * An unclaimed deployment shows "claim" and nothing else: there is nobody to
 * sign in as, and offering a sign-in form to a person who cannot possibly have
 * an account is how somebody concludes the site is broken. A claimed one shows
 * sign-in, with registration as the secondary path.
 *
 * The password goes from the input into the request body and is dropped. It is
 * never put into state that outlives the submit, never logged, never echoed by
 * the endpoint, and never placed in a URL - a query string reaches the server
 * log, the browser history and the referrer header.
 *
 * The minimum length is enforced by the server and shown here before the
 * submit, so a rejection arrives while the person is still typing rather than
 * after a round trip that looks like a failure.
 */
export interface AccessLabels {
  claimTitle: string;
  claimBody: string;
  signInTitle: string;
  registerTitle: string;
  registerBody: string;
  email: string;
  password: string;
  displayName: string;
  claim: string;
  signIn: string;
  register: string;
  working: string;
  tooShort: string;
  switchToRegister: string;
  switchToSignIn: string;
  viewerNote: string;
}

type Mode = "claim" | "sign-in" | "register";

export function AccessForm({
  claimed,
  minLength,
  labels,
}: {
  claimed: boolean;
  minLength: number;
  labels: AccessLabels;
}) {
  // An unclaimed deployment has exactly one thing you can do, so there is no
  // choice to offer and no tab to get lost in.
  const [mode, setMode] = useState<Mode>(claimed ? "sign-in" : "claim");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [displayName, setDisplayName] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const needsLength = mode !== "sign-in";
  const tooShort = needsLength && password.length > 0 && password.length < minLength;

  async function submit(event: React.FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError(null);

    const endpoint =
      mode === "sign-in"
        ? "/api/v1/session/sign-in"
        : mode === "claim"
          ? "/api/v1/users/claim"
          : "/api/v1/users/register";

    const body =
      mode === "sign-in"
        ? { email, password }
        : { email, password, display_name: displayName };

    try {
      const response = await fetch(endpoint, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        // The session cookie is set by the sign-in response and must be kept.
        credentials: "same-origin",
        body: JSON.stringify(body),
      });
      const payload = await response.json().catch(() => null);

      if (!response.ok) {
        // The API's own message. It is written to be read by the person who
        // hit the problem - "that email already has an account" is actionable
        // in a way that "400" is not.
        setError(
          payload?.message ?? payload?.detail?.message ?? payload?.detail ?? `HTTP ${response.status}`,
        );
        setBusy(false);
        return;
      }

      if (mode === "sign-in") {
        // A full load rather than a client-side push: every page reads the
        // session on the server, and they all need to see the new cookie.
        window.location.assign("/");
        return;
      }

      // Claiming or registering creates the account but does not sign you in.
      // Signing in with the password just chosen proves it works now, rather
      // than at the next visit when the person no longer remembers what they
      // typed.
      const followUp = await fetch("/api/v1/session/sign-in", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        credentials: "same-origin",
        body: JSON.stringify({ email, password }),
      });
      if (followUp.ok) {
        window.location.assign("/");
        return;
      }
      setMode("sign-in");
      setPassword("");
      setBusy(false);
    } catch (problem) {
      setError(problem instanceof Error ? problem.message : String(problem));
      setBusy(false);
    }
  }

  const title =
    mode === "claim"
      ? labels.claimTitle
      : mode === "sign-in"
        ? labels.signInTitle
        : labels.registerTitle;

  const blurb =
    mode === "claim" ? labels.claimBody : mode === "register" ? labels.registerBody : null;

  const action =
    mode === "claim" ? labels.claim : mode === "sign-in" ? labels.signIn : labels.register;

  return (
    <form onSubmit={submit} className="space-y-3">
      <div>
        <h2 className="text-sm font-semibold">{title}</h2>
        {blurb && <p className="text-xs ink-3 mt-1 leading-relaxed">{blurb}</p>}
      </div>

      <label className="block">
        <span className="text-xs ink-3">{labels.email}</span>
        <input
          type="email"
          required
          autoComplete="email"
          value={email}
          onChange={(event) => setEmail(event.target.value)}
          className="mt-1 w-full rounded border border-white/10 bg-black/20 px-2 py-1.5 text-sm"
        />
      </label>

      {mode !== "sign-in" && (
        <label className="block">
          <span className="text-xs ink-3">{labels.displayName}</span>
          <input
            type="text"
            value={displayName}
            onChange={(event) => setDisplayName(event.target.value)}
            className="mt-1 w-full rounded border border-white/10 bg-black/20 px-2 py-1.5 text-sm"
          />
        </label>
      )}

      <label className="block">
        <span className="text-xs ink-3">{labels.password}</span>
        <input
          type="password"
          required
          minLength={needsLength ? minLength : undefined}
          autoComplete={mode === "sign-in" ? "current-password" : "new-password"}
          value={password}
          onChange={(event) => setPassword(event.target.value)}
          className="mt-1 w-full rounded border border-white/10 bg-black/20 px-2 py-1.5 text-sm"
        />
        {tooShort && (
          <span className="mt-1 block text-xs text-amber-400">
            {labels.tooShort.replace("{n}", String(minLength))}
          </span>
        )}
      </label>

      {error && (
        <p className="rounded border border-red-500/30 bg-red-500/10 px-2 py-1.5 text-xs text-red-300">
          {error}
        </p>
      )}

      <button
        type="submit"
        disabled={busy || tooShort}
        className="w-full rounded bg-white/10 px-3 py-2 text-sm font-medium hover:bg-white/15 disabled:opacity-40"
      >
        {busy ? labels.working : action}
      </button>

      {claimed && (
        <div className="pt-1 text-center">
          <button
            type="button"
            onClick={() => {
              setMode(mode === "sign-in" ? "register" : "sign-in");
              setError(null);
            }}
            className="text-xs ink-3 underline underline-offset-2 hover:text-white"
          >
            {mode === "sign-in" ? labels.switchToRegister : labels.switchToSignIn}
          </button>
          {mode === "register" && (
            <p className="mt-2 text-xs ink-3 leading-relaxed">{labels.viewerNote}</p>
          )}
        </div>
      )}
    </form>
  );
}
