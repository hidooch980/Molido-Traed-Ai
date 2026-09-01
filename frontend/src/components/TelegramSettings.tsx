"use client";

import { useState } from "react";

/**
 * The alert channel, configured from here rather than from a file on the host.
 *
 * The token used to live in the deployment's env file, which meant changing it
 * was an SSH session and a container restart - so in practice it was never set
 * and the alert path did not exist. This is the same secret with the same
 * handling as the broker password: typed once, posted, never echoed back.
 *
 * Recipients are a list because an alert that reaches one phone waits for one
 * person to wake up. Each id is validated by the API and refused by name
 * rather than dropped: an id somebody typed wrong is a person who believes
 * they are on the list and is not, and silently discarding it is how that goes
 * unnoticed until the night it matters.
 *
 * The test button sends a real message, deliberately outside the alert
 * cooldown. `getMe` proves the token; only a real send proves the recipients.
 */
export interface TelegramLabels {
  title: string;
  token: string;
  tokenHint: string;
  tokenKeep: string;
  chatIds: string;
  chatIdsHint: string;
  enabled: string;
  save: string;
  saving: string;
  test: string;
  testing: string;
  saved: string;
  testSent: string;
  testFailed: string;
  failed: string;
  signInFirst: string;
  configured: string;
  notConfigured: string;
  recipients: string;
  howTo: string;
}

export function TelegramSettings({
  labels,
  initial,
}: {
  labels: TelegramLabels;
  initial: {
    configured: boolean;
    enabled: boolean;
    masked_token: string | null;
    chat_ids: string[];
    source: string;
  };
}) {
  const [token, setToken] = useState("");
  const [chatIds, setChatIds] = useState(initial.chat_ids.join("\n"));
  const [enabled, setEnabled] = useState(initial.enabled);
  const [state, setState] = useState<"idle" | "saving" | "testing">("idle");
  const [note, setNote] = useState<string | null>(null);
  const [tone, setTone] = useState<"good" | "bad" | null>(null);
  const [masked, setMasked] = useState(initial.masked_token);
  const [saved, setSaved] = useState(initial.chat_ids.length);

  function ids(): string[] {
    return chatIds
      .split(/[\s,]+/)
      .map((line) => line.trim())
      .filter(Boolean);
  }

  async function save() {
    setState("saving");
    setNote(null);
    try {
      const body: Record<string, unknown> = { chat_ids: ids(), enabled };
      // Omitted rather than sent empty: an empty string means "clear it",
      // and a form that posts one every time would wipe a token the
      // operator cannot read back from this page.
      if (token.trim()) body.token = token.trim();

      const response = await fetch("/api/v1/integrations/telegram", {
        method: "PUT",
        headers: { "content-type": "application/json" },
        credentials: "include",
        body: JSON.stringify(body),
      });
      const payload = await response.json().catch(() => ({}));

      if (response.status === 401 || response.status === 403) {
        setTone("bad");
        setNote(labels.signInFirst);
      } else if (!response.ok) {
        setTone("bad");
        setNote(payload.message ?? payload.detail ?? labels.failed);
      } else {
        setTone("good");
        setNote(labels.saved);
        setMasked(payload.masked_token ?? masked);
        setSaved((payload.chat_ids ?? []).length);
        setToken("");
      }
    } catch (problem) {
      setTone("bad");
      setNote(problem instanceof Error ? problem.message : labels.failed);
    } finally {
      setState("idle");
    }
  }

  async function test() {
    setState("testing");
    setNote(null);
    try {
      const response = await fetch("/api/v1/integrations/telegram/test", {
        method: "POST",
        credentials: "include",
      });
      const payload = await response.json().catch(() => ({}));
      if (payload.sent) {
        setTone("good");
        setNote(`${labels.testSent} ${payload.delivered_to ?? ""}`.trim());
      } else {
        setTone("bad");
        setNote(`${labels.testFailed} ${payload.reason ?? ""}`.trim());
      }
    } catch (problem) {
      setTone("bad");
      setNote(problem instanceof Error ? problem.message : labels.failed);
    } finally {
      setState("idle");
    }
  }

  const busy = state !== "idle";

  return (
    <div className="space-y-3">
      <div className="flex items-center gap-2 text-xs">
        <span
          className="pill"
          style={{ color: initial.configured ? "var(--good)" : "var(--ink-3)" }}
        >
          {initial.configured ? labels.configured : labels.notConfigured}
        </span>
        {masked && (
          <span className="ink-3" dir="ltr">
            {masked}
          </span>
        )}
        <span className="ink-3">
          {saved} {labels.recipients}
        </span>
      </div>

      <label className="block text-sm">
        <span className="ink-2">{labels.token}</span>
        <input
          type="password"
          autoComplete="off"
          className="input w-full mt-1"
          dir="ltr"
          placeholder={initial.configured ? labels.tokenKeep : "123456789:AA..."}
          value={token}
          onChange={(event) => setToken(event.target.value)}
        />
        <span className="ink-3 text-xs">{labels.tokenHint}</span>
      </label>

      <label className="block text-sm">
        <span className="ink-2">{labels.chatIds}</span>
        <textarea
          className="input w-full mt-1"
          dir="ltr"
          rows={4}
          placeholder={"123456789\n-1001234567890"}
          value={chatIds}
          onChange={(event) => setChatIds(event.target.value)}
        />
        <span className="ink-3 text-xs">{labels.chatIdsHint}</span>
      </label>

      <label className="flex items-center gap-2 text-sm">
        <input
          type="checkbox"
          checked={enabled}
          onChange={(event) => setEnabled(event.target.checked)}
        />
        <span className="ink-2">{labels.enabled}</span>
      </label>

      <div className="flex gap-2">
        <button className="btn" onClick={save} disabled={busy}>
          {state === "saving" ? labels.saving : labels.save}
        </button>
        <button
          className="btn"
          onClick={test}
          disabled={busy || !initial.configured}
        >
          {state === "testing" ? labels.testing : labels.test}
        </button>
      </div>

      {note && (
        <p
          className="text-xs"
          style={{ color: tone === "good" ? "var(--good)" : "var(--critical)" }}
        >
          {note}
        </p>
      )}

      <p className="ink-3 text-xs">{labels.howTo}</p>
    </div>
  );
}
