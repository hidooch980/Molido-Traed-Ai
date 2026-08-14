"use client";

import { useEffect, useState } from "react";

/**
 * Spends a verification token, once, on arrival.
 *
 * The link in the email points here. It was pointing at a 404 for a while,
 * which is worth remembering: the token system was built, tested and shipped,
 * and the one thing a person actually touches did not exist. Backend coverage
 * says nothing about whether the path a human walks is complete.
 *
 * The token is read from the URL and never put anywhere else — not into state
 * that outlives the request, not into a fetch that could be retried, and not
 * back into the address bar. It is single-use, so a second attempt fails by
 * design and the page says so rather than looking broken.
 */
export interface VerifyLabels {
  working: string;
  success: string;
  successNote: string;
  alreadyDone: string;
  failed: string;
  noToken: string;
  pointsAwarded: string;
  referrerAwarded: string;
  goHome: string;
}

type State =
  | { kind: "working" }
  | { kind: "done"; already: boolean; points: number; referrer: number }
  | { kind: "failed"; reason: string };

export function VerifyToken({ labels }: { labels: VerifyLabels }) {
  const [state, setState] = useState<State>({ kind: "working" });

  useEffect(() => {
    const token = new URLSearchParams(window.location.search).get("token");
    if (!token) {
      setState({ kind: "failed", reason: labels.noToken });
      return;
    }

    let cancelled = false;
    (async () => {
      try {
        const response = await fetch("/api/v1/users/verify", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          credentials: "same-origin",
          body: JSON.stringify({ token }),
        });
        const payload = await response.json().catch(() => null);
        if (cancelled) return;

        if (!response.ok) {
          // The API's own wording. It deliberately does not say whether the
          // link expired or was already spent - telling the holder which
          // describes the state of an account they may not own.
          setState({
            kind: "failed",
            reason: payload?.message ?? payload?.detail ?? labels.failed,
          });
          return;
        }

        setState({
          kind: "done",
          already: Boolean(payload?.already_verified),
          points: Number(payload?.points_awarded ?? 0),
          referrer: Number(payload?.referrer_awarded ?? 0),
        });
      } catch (problem) {
        if (!cancelled) {
          setState({
            kind: "failed",
            reason: problem instanceof Error ? problem.message : String(problem),
          });
        }
      }
    })();

    // Guards against the double-invoke React does in development. Without it
    // the first call spends the token and the second reports it as already
    // used, which is correct behaviour that looks exactly like a bug.
    return () => {
      cancelled = true;
    };
  }, [labels.failed, labels.noToken]);

  if (state.kind === "working") {
    return <p className="text-sm ink-3">{labels.working}</p>;
  }

  if (state.kind === "failed") {
    return (
      <div className="space-y-2">
        <p className="rounded border border-red-500/30 bg-red-500/10 px-3 py-2 text-sm text-red-300">
          {state.reason}
        </p>
        <a href="/" className="text-xs underline underline-offset-2 ink-3">
          {labels.goHome}
        </a>
      </div>
    );
  }

  return (
    <div className="space-y-2">
      <p className="text-sm font-semibold">
        {state.already ? labels.alreadyDone : labels.success}
      </p>
      {!state.already && <p className="text-xs ink-3">{labels.successNote}</p>}
      {state.points > 0 && (
        <p className="text-xs ink-3">
          {labels.pointsAwarded.replace("{n}", String(state.points))}
        </p>
      )}
      {state.referrer > 0 && (
        <p className="text-xs ink-3">
          {labels.referrerAwarded.replace("{n}", String(state.referrer))}
        </p>
      )}
      <a href="/" className="text-xs underline underline-offset-2 ink-3">
        {labels.goHome}
      </a>
    </div>
  );
}
