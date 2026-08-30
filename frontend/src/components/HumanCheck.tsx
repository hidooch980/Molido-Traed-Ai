"use client";

import { useCallback, useEffect, useRef, useState } from "react";

import { solve, type Challenge } from "@/lib/humanCheck";

/**
 * The "I am not a robot" box, made visible.
 *
 * The proof of work has been running since it was built: the server issues a
 * challenge, the browser burns processor time finding a nonce, and a guessing
 * loop pays that cost on every attempt. It worked, and nobody could tell. It
 * ran silently at submit time, and the only evidence it existed was a pause.
 *
 * A security control the person cannot see is one they do not believe in, and
 * this was asked for repeatedly by somebody who already had it. That is the
 * whole reason this component exists - not to add protection, but to show the
 * protection that was there.
 *
 * **It also solves earlier.** The proof used to be found when the form was
 * submitted, which put its cost between pressing the button and being signed
 * in - the one moment somebody is watching. It now starts as soon as there is
 * an address to bind it to, and runs while they type their password. Same
 * work, spent where nobody is waiting on it.
 *
 * **A solved proof expires.** The server spends a challenge once and discards
 * it after five minutes, so a form left open on a desk has a stale proof. This
 * reports that state rather than hiding it, and `refresh()` lets the caller
 * ask for another after a rejection.
 */

export type CheckState = "idle" | "solving" | "ready" | "stale" | "failed" | "not-needed";

export interface HumanCheckLabels {
  idle: string;
  solving: string;
  ready: string;
  stale: string;
  failed: string;
  notNeeded: string;
  explain: string;
}

export interface Proof {
  challenge_id?: string;
  nonce?: number;
}

export function useHumanCheck(
  email: string,
  // "claim" is its own purpose rather than a flavour of "register", because
  // the server binds a solved proof to the form it was issued for. A proof
  // minted for registration is refused at the claim endpoint, which is the
  // point: the cheaper door must not become the mint for the expensive one.
  purpose: "sign-in" | "register" | "claim",
) {
  const [state, setState] = useState<CheckState>("idle");
  const [attempts, setAttempts] = useState(0);
  const proof = useRef<Proof>({});
  // Bumped to force a fresh challenge after one has been spent or refused.
  const [round, setRound] = useState(0);

  const refresh = useCallback(() => {
    proof.current = {};
    setRound((r) => r + 1);
  }, []);

  useEffect(() => {
    // Bound to the address, so the difficulty the server picks reflects this
    // account's recent failures rather than a stranger's.
    if (!email.includes("@")) {
      setState("idle");
      return;
    }

    let cancelled = false;
    // Debounced: solving on every keystroke of an email address would start
    // and abandon a dozen searches before the person finished typing.
    const timer = window.setTimeout(async () => {
      try {
        const response = await fetch(
          `/api/v1/session/challenge?email=${encodeURIComponent(email)}&purpose=${purpose}`,
          { cache: "no-store" },
        );
        if (!response.ok) {
          if (!cancelled) setState("failed");
          return;
        }
        const challenge = (await response.json()) as Challenge;
        if (cancelled) return;

        if (!challenge.required) {
          // Honest rather than reassuring: the server is not asking for one
          // yet, and saying "verified" here would be theatre.
          proof.current = {};
          setState("not-needed");
          return;
        }

        setState("solving");
        setAttempts(0);
        const nonce = await solve(challenge.salt, challenge.difficulty, {
          onProgress: (n) => {
            if (!cancelled) setAttempts(n);
          },
        });
        if (cancelled) return;

        proof.current = { challenge_id: challenge.challenge_id, nonce };
        setState("ready");

        // The server discards it after five minutes. Saying so beats a form
        // that silently stops working while somebody reads their email.
        window.setTimeout(() => {
          if (!cancelled) setState((s) => (s === "ready" ? "stale" : s));
        }, 4 * 60 * 1000);
      } catch {
        if (!cancelled) setState("failed");
      }
    }, 400);

    return () => {
      cancelled = true;
      window.clearTimeout(timer);
    };
  }, [email, purpose, round]);

  return { state, attempts, proof, refresh };
}

export function HumanCheckBox({
  labels,
  state,
  attempts,
}: {
  labels: HumanCheckLabels;
  state: CheckState;
  attempts: number;
}) {
  const text = {
    idle: labels.idle,
    solving: labels.solving.replace("{n}", attempts.toLocaleString("fa-IR")),
    ready: labels.ready,
    stale: labels.stale,
    failed: labels.failed,
    "not-needed": labels.notNeeded,
  }[state];

  return (
    <div className="human-check" data-state={state}>
      <span className="human-check-mark" aria-hidden="true">
        {state === "ready" ? "✓" : state === "failed" ? "!" : ""}
      </span>
      <div className="min-w-0">
        <div className="human-check-text">{text}</div>
        <div className="human-check-explain">{labels.explain}</div>
      </div>
    </div>
  );
}
