"use client";

import { useEffect, useState } from "react";

import { proofFor } from "@/lib/humanCheck";

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
  register: string;
  signOut: string;
  email: string;
  password: string;
  submit: string;
  cancel: string;
  working: string;
  failed: string;
  /** Shown while the proof of work is being solved. */
  verifying: string;
  /** Shown when the server is refusing attempts for a while. */
  tooMany: string;
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
  const [solving, setSolving] = useState(false);
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
      // Asked for before the attempt, not after a refusal. The server counts a
      // missing proof as a failed attempt, so retrying after being told one was
      // needed would spend two attempts per sign-in and reach the cooldown
      // twice as fast. When no proof is being asked for this is one cheap GET
      // and an empty object.
      setSolving(true);
      const proof = await proofFor(email);
      setSolving(false);

      const response = await fetch("/api/v1/session/sign-in", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ email, password, ...proof }),
      });
      if (!response.ok) {
        // 429 is not a wrong password and must not be reported as one - the
        // person retyping a password they know is right needs to be told the
        // server is asking them to wait, or they will assume the account is
        // broken and try harder, which is the one thing that makes it worse.
        setError(response.status === 429 ? labels.tooMany : labels.failed);
        return;
      }
      // Dropped the moment it has been sent; nothing here keeps it.
      setPassword("");
      setOpen(false);
      await refresh();
    } catch {
      setError(labels.failed);
    } finally {
      setSolving(false);
      setBusy(false);
    }
  }

  async function signOut() {
    const response = await fetch("/api/v1/session/sign-out", { method: "POST" });

    // Navigated, not merely re-rendered. Re-reading the session turned this
    // header back into a "sign in" button and left the person standing on the
    // dashboard it belongs to - a page that was server-rendered while they
    // still had a session, so its contents stay on screen. Nothing bounces
    // them, because the gate runs on navigation and there was no navigation.
    // Signing out looked exactly like not having signed out.
    //
    // A whole page load rather than a router push, because that is the only
    // thing that also discards the state the signed-in session left in memory.
    if (response.ok) {
      window.location.href = "/";
      return;
    }

    // The request failed, so the session may well still exist. Re-reading is
    // right here: it makes the header agree with whatever is actually true
    // rather than asserting a sign-out that did not happen.
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

  // Signing out stays here: it is one button and it needs no page. Signing in
  // does not - the real flow is four steps, and this popover could hold one.
  //
  // Both doors, side by side. Registration existed already and lived inside
  // `/access`, a page somebody has to know about to find; the two things a
  // visitor arrives wanting to do should not be one link and one rumour.
  return (
    <span className="flex items-center gap-1.5">
      <a href="/register" className="pill" style={{ color: "var(--ink-2)" }}>
        {labels.register}
      </a>
      <a
        href="/login"
        className="pill pill-accent"
        title={labels.anonymousHint}
      >
        {labels.signIn}
      </a>
    </span>
  );
}
