"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import QRCode from "qrcode";

import { proofFor } from "@/lib/humanCheck";

/**
 * The sign-in page.
 *
 * It replaces a popover in the corner of the header, which was a login in the
 * sense that a password went into it. What it was not was a place: there was
 * nowhere to put "this account needs a second factor", nowhere to draw a QR
 * code, nowhere to show ten recovery codes somebody has to write down, and no
 * room to say why any of it was being asked for. Every one of those is a step
 * in the real flow, and a 18rem dropdown could hold none of them.
 *
 * So this is a page with four states, and it is one component rather than four
 * routes because they are one conversation:
 *
 *   password   →  the first thing anybody sees
 *   code       →  the account has a second factor and it wants six digits
 *   enrol      →  the account must have one and does not; QR, then confirm
 *   codes      →  the recovery codes, shown once, never again
 *
 * The order matters and is set by the server, not here. The page never asks
 * for a code before a password has been accepted — doing so would tell an
 * unauthenticated caller which addresses have accounts, which is exactly what
 * the identical-failure rule on the API exists to prevent. This component only
 * ever reacts to what the server just said.
 */

export interface LoginLabels {
  title: string;
  subtitle: string;
  email: string;
  password: string;
  submit: string;
  working: string;
  verifying: string;
  failed: string;
  tooMany: string;

  codeTitle: string;
  codeSubtitle: string;
  code: string;
  codeHint: string;
  codeSubmit: string;

  enrolTitle: string;
  enrolSubtitle: string;
  scanHint: string;
  manualToggle: string;
  manualHint: string;
  enrolSubmit: string;

  codesTitle: string;
  codesSubtitle: string;
  codesWarning: string;
  codesCopy: string;
  codesCopied: string;
  codesDone: string;

  heroTitle: string;
  heroBody: string;
  statPagesLabel: string;
  statEdgeValue: string;
  statEdgeLabel: string;
  back: string;
}

interface Enrolment {
  secret: string;
  otpauth_uri: string;
  manual_entry: string;
  account: string;
}

type Stage = "password" | "code" | "enrol" | "codes";

export function LoginPanel({ labels, version }: { labels: LoginLabels; version: string }) {
  const [stage, setStage] = useState<Stage>("password");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [code, setCode] = useState("");
  const [busy, setBusy] = useState(false);
  const [solving, setSolving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const [enrolment, setEnrolment] = useState<Enrolment | null>(null);
  const [qr, setQr] = useState<string | null>(null);
  const [manual, setManual] = useState(false);
  const [recoveryCodes, setRecoveryCodes] = useState<string[] | null>(null);
  const [copied, setCopied] = useState(false);

  const codeInput = useRef<HTMLInputElement>(null);

  // Focus follows the step. Moving to a six-digit field and having to click it
  // is the kind of small friction that, on a screen somebody reaches through
  // twice a day, is the whole difference between a security feature and an
  // obstacle.
  useEffect(() => {
    if (stage === "code" || stage === "enrol") codeInput.current?.focus();
  }, [stage]);

  // Rendered locally, never fetched. The QR encodes a shared secret; sending
  // it to an image service would hand that secret to whoever runs it, which is
  // the entire thing the second factor is protecting.
  useEffect(() => {
    if (!enrolment) {
      setQr(null);
      return;
    }
    let cancelled = false;
    QRCode.toString(enrolment.otpauth_uri, {
      type: "svg",
      margin: 1,
      width: 208,
      color: { dark: "#0b1220", light: "#ffffff" },
    })
      .then((svg) => {
        if (!cancelled) setQr(svg);
      })
      .catch(() => {
        // The manual entry below is the fallback and is always rendered, so a
        // failed drawing costs a convenience rather than the enrolment.
        if (!cancelled) setQr(null);
      });
    return () => {
      cancelled = true;
    };
  }, [enrolment]);

  async function post(path: string, body: unknown) {
    const response = await fetch(path, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    const payload = await response.json().catch(() => ({}));
    return { ok: response.ok, status: response.status, payload };
  }

  function describe(status: number, payload: { error?: string; message?: string }) {
    if (status === 429) return labels.tooMany;
    // The server's own sentence when it wrote one. It knows things this page
    // does not — which of several reasons a proof of work was refused, that a
    // phone's clock is probably wrong — and replacing that with a generic
    // failure throws away the only useful part of the response.
    if (payload?.message && payload.error !== "unauthenticated") return payload.message;
    return labels.failed;
  }

  async function signIn(withCode?: string) {
    setBusy(true);
    setError(null);
    try {
      setSolving(true);
      const proof = await proofFor(email);
      setSolving(false);

      const { ok, status, payload } = await post("/api/v1/session/sign-in", {
        email,
        password,
        ...(withCode ? { code: withCode } : {}),
        ...proof,
      });

      if (!ok) {
        if (payload?.error === "two_factor_required") {
          // Not a failure. The password was right and the account wants more.
          setStage("code");
          setCode("");
          setError(null);
          return;
        }
        setError(describe(status, payload));
        return;
      }

      setPassword("");
      const factor = payload?.two_factor;
      if (factor?.blocking_sign_in) {
        await beginEnrolment();
        return;
      }
      window.location.href = "/";
    } catch {
      setError(labels.failed);
    } finally {
      setSolving(false);
      setBusy(false);
    }
  }

  async function beginEnrolment() {
    const { ok, status, payload } = await post("/api/v1/session/two-factor/begin", {});
    if (!ok) {
      setError(describe(status, payload));
      return;
    }
    setEnrolment(payload as Enrolment);
    setCode("");
    setStage("enrol");
  }

  async function confirmEnrolment() {
    setBusy(true);
    setError(null);
    try {
      const { ok, status, payload } = await post("/api/v1/session/two-factor/confirm", {
        code,
      });
      if (!ok) {
        setError(describe(status, payload));
        return;
      }
      setRecoveryCodes(payload.recovery_codes ?? []);
      setStage("codes");
    } catch {
      setError(labels.failed);
    } finally {
      setBusy(false);
    }
  }

  const buttonLabel = solving ? labels.verifying : busy ? labels.working : null;

  return (
    <div className="auth-shell">
      <section className="auth-form-side">
        <div className="auth-form">
          {stage === "password" && (
            <PasswordStep
              labels={labels}
              email={email}
              password={password}
              busy={busy}
              buttonLabel={buttonLabel}
              onEmail={setEmail}
              onPassword={setPassword}
              onSubmit={() => void signIn()}
            />
          )}

          {stage === "code" && (
            <CodeStep
              labels={labels}
              code={code}
              busy={busy}
              buttonLabel={buttonLabel}
              inputRef={codeInput}
              onCode={setCode}
              onSubmit={() => void signIn(code)}
            />
          )}

          {stage === "enrol" && enrolment && (
            <EnrolStep
              labels={labels}
              enrolment={enrolment}
              qr={qr}
              manual={manual}
              code={code}
              busy={busy}
              buttonLabel={buttonLabel}
              inputRef={codeInput}
              onManual={() => setManual((m) => !m)}
              onCode={setCode}
              onSubmit={() => void confirmEnrolment()}
            />
          )}

          {stage === "codes" && recoveryCodes && (
            <CodesStep
              labels={labels}
              codes={recoveryCodes}
              copied={copied}
              onCopy={() => {
                void navigator.clipboard?.writeText(recoveryCodes.join("\n"));
                setCopied(true);
              }}
              onDone={() => (window.location.href = "/")}
            />
          )}

          {error && (
            <p className="auth-error" role="alert">
              {error}
            </p>
          )}

          <p className="auth-version">{version}</p>
        </div>
      </section>

      <Hero labels={labels} />
    </div>
  );
}

function Field({
  label,
  ...props
}: { label: string } & React.InputHTMLAttributes<HTMLInputElement>) {
  return (
    <label className="auth-field">
      <span className="auth-label">{label}</span>
      <input className="auth-input" {...props} />
    </label>
  );
}

function PasswordStep({
  labels, email, password, busy, buttonLabel, onEmail, onPassword, onSubmit,
}: {
  labels: LoginLabels; email: string; password: string; busy: boolean;
  buttonLabel: string | null;
  onEmail: (v: string) => void; onPassword: (v: string) => void; onSubmit: () => void;
}) {
  return (
    <form
      onSubmit={(e) => {
        e.preventDefault();
        onSubmit();
      }}
    >
      <h1 className="auth-title">{labels.title}</h1>
      <p className="auth-sub">{labels.subtitle}</p>

      <Field
        label={labels.email}
        type="email"
        value={email}
        onChange={(e) => onEmail(e.target.value)}
        required
        autoComplete="username"
        dir="ltr"
      />
      <Field
        label={labels.password}
        type="password"
        value={password}
        onChange={(e) => onPassword(e.target.value)}
        required
        autoComplete="current-password"
        dir="ltr"
      />

      <button type="submit" className="auth-button" disabled={busy}>
        {buttonLabel ?? labels.submit}
      </button>
    </form>
  );
}

function CodeStep({
  labels, code, busy, buttonLabel, inputRef, onCode, onSubmit,
}: {
  labels: LoginLabels; code: string; busy: boolean; buttonLabel: string | null;
  inputRef: React.RefObject<HTMLInputElement | null>;
  onCode: (v: string) => void; onSubmit: () => void;
}) {
  return (
    <form
      onSubmit={(e) => {
        e.preventDefault();
        onSubmit();
      }}
    >
      <h1 className="auth-title">{labels.codeTitle}</h1>
      <p className="auth-sub">{labels.codeSubtitle}</p>

      <label className="auth-field">
        <span className="auth-label">{labels.code}</span>
        <input
          ref={inputRef}
          className="auth-input auth-code"
          value={code}
          onChange={(e) => onCode(e.target.value)}
          // `inputMode` rather than `type="number"`: a recovery code goes in
          // this field too, and a number input silently discards its letters.
          inputMode="numeric"
          autoComplete="one-time-code"
          required
          dir="ltr"
        />
      </label>
      <p className="auth-hint">{labels.codeHint}</p>

      <button type="submit" className="auth-button" disabled={busy}>
        {buttonLabel ?? labels.codeSubmit}
      </button>
    </form>
  );
}

function EnrolStep({
  labels, enrolment, qr, manual, code, busy, buttonLabel, inputRef,
  onManual, onCode, onSubmit,
}: {
  labels: LoginLabels; enrolment: Enrolment; qr: string | null; manual: boolean;
  code: string; busy: boolean; buttonLabel: string | null;
  inputRef: React.RefObject<HTMLInputElement | null>;
  onManual: () => void; onCode: (v: string) => void; onSubmit: () => void;
}) {
  return (
    <form
      onSubmit={(e) => {
        e.preventDefault();
        onSubmit();
      }}
    >
      <h1 className="auth-title">{labels.enrolTitle}</h1>
      <p className="auth-sub">{labels.enrolSubtitle}</p>

      <div className="auth-qr-card">
        <p className="auth-hint auth-qr-hint">{labels.scanHint}</p>
        {qr ? (
          <div className="auth-qr" dangerouslySetInnerHTML={{ __html: qr }} />
        ) : (
          <div className="auth-qr auth-qr-empty" />
        )}

        <button type="button" className="auth-link" onClick={onManual}>
          {labels.manualToggle}
        </button>

        {manual && (
          <div className="auth-manual">
            <p className="auth-hint">{labels.manualHint}</p>
            <code dir="ltr">{enrolment.manual_entry}</code>
          </div>
        )}
      </div>

      <label className="auth-field">
        <span className="auth-label">{labels.code}</span>
        <input
          ref={inputRef}
          className="auth-input auth-code"
          value={code}
          onChange={(e) => onCode(e.target.value)}
          inputMode="numeric"
          autoComplete="one-time-code"
          required
          dir="ltr"
        />
      </label>

      <button type="submit" className="auth-button" disabled={busy}>
        {buttonLabel ?? labels.enrolSubmit}
      </button>
    </form>
  );
}

function CodesStep({
  labels, codes, copied, onCopy, onDone,
}: {
  labels: LoginLabels; codes: string[]; copied: boolean;
  onCopy: () => void; onDone: () => void;
}) {
  return (
    <div>
      <h1 className="auth-title">{labels.codesTitle}</h1>
      <p className="auth-sub">{labels.codesSubtitle}</p>

      <p className="auth-warning">{labels.codesWarning}</p>

      <ul className="auth-codes" dir="ltr">
        {codes.map((c) => (
          <li key={c}>{c}</li>
        ))}
      </ul>

      <div className="auth-actions">
        <button type="button" className="auth-button auth-button-quiet" onClick={onCopy}>
          {copied ? labels.codesCopied : labels.codesCopy}
        </button>
        <button type="button" className="auth-button" onClick={onDone}>
          {labels.codesDone}
        </button>
      </div>
    </div>
  );
}

function Hero({ labels }: { labels: LoginLabels }) {
  // Two facts, and both are refusals. A sign-in page is where somebody forms
  // their idea of what this system claims about itself, and the honest claim
  // here is that it has not proven an edge and does not trade.
  const stats = useMemo(
    () => [
      { value: labels.statEdgeValue, label: labels.statEdgeLabel },
      { value: "۳۵", label: labels.statPagesLabel },
    ],
    [labels],
  );

  return (
    <section className="auth-hero" aria-hidden="true">
      <div className="auth-hero-grid" />
      <div className="auth-hero-body">
        <div className="auth-brand">
          <span className="auth-mark">◧</span>
          <span className="auth-wordmark">
            MolidoTrade<span className="auth-wordmark-ai">AI</span>
          </span>
        </div>

        <div>
          <h2 className="auth-hero-title">{labels.heroTitle}</h2>
          <p className="auth-hero-text">{labels.heroBody}</p>
        </div>

        <div className="auth-stats">
          {stats.map((s) => (
            <div key={s.label}>
              <div className="auth-stat-value">{s.value}</div>
              <div className="auth-stat-label">{s.label}</div>
            </div>
          ))}
        </div>
      </div>
    </section>
  );
}
