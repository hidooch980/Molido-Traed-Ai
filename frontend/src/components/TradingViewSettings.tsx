"use client";

import { useEffect, useState } from "react";

export interface TradingViewLabels {
  webhookUrl: string;
  secret: string;
  noSecret: string;
  activeSecret: string;
  make: string;
  remake: string;
  making: string;
  shownOnce: string;
  message: string;
  messageHint: string;
  signInFirst: string;
  failed: string;
}

export function TradingViewSettings({
  configured,
  hint,
  path,
  labels,
}: {
  configured: boolean;
  hint: string;
  path: string;
  labels: TradingViewLabels;
}) {
  const [origin, setOrigin] = useState("");
  const [secret, setSecret] = useState<string | null>(null);
  const [active, setActive] = useState(configured ? hint : "");
  const [busy, setBusy] = useState(false);
  const [note, setNote] = useState<string | null>(null);

  useEffect(() => setOrigin(window.location.origin), []);

  async function make() {
    setBusy(true);
    setNote(null);
    try {
      const response = await fetch("/api/v1/tradingview/secret", {
        method: "POST",
        credentials: "include",
      });
      const payload = await response.json().catch(() => ({}));
      if (response.status === 401 || response.status === 403) {
        setNote(labels.signInFirst);
      } else if (!response.ok) {
        setNote(payload.message ?? payload.detail ?? labels.failed);
      } else {
        setSecret(payload.secret);
        setActive(payload.secret_hint);
      }
    } catch (problem) {
      setNote(problem instanceof Error ? problem.message : labels.failed);
    } finally {
      setBusy(false);
    }
  }

  const template = JSON.stringify(
    {
      secret: secret ?? "…",
      symbol: "{{ticker}}",
      action: "{{strategy.order.action}}",
      price: "{{close}}",
      timeframe: "{{interval}}",
      message: "…",
    },
    null,
    2,
  );

  return (
    <div className="space-y-4 p-4">
      <div>
        <p className="text-xs ink-3">{labels.webhookUrl}</p>
        <code dir="ltr" className="block mt-1 break-all text-sm">
          {origin}
          {path}
        </code>
      </div>

      <div className="flex flex-wrap items-center gap-3">
        <span className="text-sm">
          {labels.secret}:{" "}
          {active ? (
            <span dir="ltr">
              {labels.activeSecret} {active}…
            </span>
          ) : (
            labels.noSecret
          )}
        </span>
        <button id="tv-make-secret" className="btn" onClick={make} disabled={busy}>
          {busy ? labels.making : active ? labels.remake : labels.make}
        </button>
      </div>

      {secret && (
        <div className="text-sm" role="status">
          <p style={{ color: "var(--warning)" }}>{labels.shownOnce}</p>
          <code dir="ltr" className="block mt-1 break-all">
            {secret}
          </code>
        </div>
      )}
      {note && (
        <p className="text-sm" style={{ color: "var(--critical)" }} role="alert">
          {note}
        </p>
      )}

      <div>
        <p className="text-xs ink-3">{labels.message}</p>
        <pre dir="ltr" className="mt-1 text-xs overflow-x-auto p-3 rounded" style={{ background: "var(--panel-raised)" }}>
          {template}
        </pre>
        <p className="text-xs ink-3 mt-1">{labels.messageHint}</p>
      </div>
    </div>
  );
}
