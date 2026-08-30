"use client";

import { useState } from "react";

import type { UserRow } from "@/lib/api";

/**
 * Creating and switching off the accounts that can sign in.
 *
 * **The password is typed here and travels no further.** It goes straight to
 * `POST /users`, which hashes it before anything is written; this component
 * never stores it, never logs it, and clears the field the moment the request
 * returns. That is also why this exists rather than an account somebody sets
 * up on the owner's behalf: a password that reaches a second person is a
 * password two people know.
 *
 * **Roles are the server's list, not a copy.** `assignable_roles` comes back
 * with the listing, so a role added or removed in the permission table shows
 * up here without an edit. A hardcoded dropdown would keep offering a role the
 * API had stopped accepting, and the failure arrives as a rejected form nobody
 * can explain.
 *
 * **`owner` is not in that list, deliberately.** The first owner is made by
 * claiming an unclaimed deployment and there is exactly one of them; a screen
 * that could mint a second would make "the account holder" a role rather than
 * a person.
 *
 * **Nothing is deleted.** Accounts are switched off, and the row stays, because
 * the audit trail refers to them - a user id in a security log that resolves to
 * nothing is a record of something happening to nobody.
 */

export interface UserAdminLabels {
  title: string;
  subtitle: string;
  name: string;
  email: string;
  password: string;
  role: string;
  create: string;
  creating: string;
  created: string;
  failed: string;
  minLength: string;
  activate: string;
  deactivate: string;
  active: string;
  inactive: string;
  neverSignedIn: string;
  lastSeen: string;
  refused: string;
  roleNames: Record<string, string>;
}

export function UserAdmin({
  labels,
  users,
  assignableRoles,
  refused,
  passwordMinLength,
}: {
  labels: UserAdminLabels;
  users: UserRow[];
  assignableRoles: string[];
  /** True when the API refused the listing. Distinct from an empty list: one
   *  means "you may not see this", the other means "there is nobody". */
  refused: boolean;
  passwordMinLength: number;
}) {
  const [name, setName] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [role, setRole] = useState(assignableRoles[0] ?? "viewer");
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState<{ ok: boolean; text: string } | null>(null);

  async function create(event: React.FormEvent) {
    event.preventDefault();
    setBusy(true);
    setMessage(null);
    try {
      const response = await fetch("/api/v1/users", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ email, password, role, display_name: name }),
      });
      const payload = await response.json().catch(() => ({}));
      if (!response.ok) {
        // The server's own sentence where it wrote one - it knows which of
        // several rules was broken, and a generic failure throws that away.
        setMessage({ ok: false, text: payload?.message ?? labels.failed });
        return;
      }
      // Dropped the instant it has been sent. Nothing here keeps it.
      setPassword("");
      setEmail("");
      setName("");
      setMessage({ ok: true, text: labels.created });
      window.location.reload();
    } catch {
      setMessage({ ok: false, text: labels.failed });
    } finally {
      setBusy(false);
    }
  }

  async function setActive(id: string, active: boolean) {
    await fetch(`/api/v1/users/${id}/active`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ active }),
    });
    window.location.reload();
  }

  if (refused) {
    return <p className="text-sm ink-3">{labels.refused}</p>;
  }

  return (
    <div className="space-y-5">
      <form onSubmit={create} className="user-form">
        <label className="auth-field">
          <span className="auth-label">{labels.name}</span>
          <input
            className="auth-input"
            value={name}
            onChange={(e) => setName(e.target.value)}
            autoComplete="off"
          />
        </label>
        <label className="auth-field">
          <span className="auth-label">{labels.email}</span>
          <input
            className="auth-input"
            type="email"
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            required
            autoComplete="off"
            dir="ltr"
          />
        </label>
        <label className="auth-field">
          <span className="auth-label">{labels.password}</span>
          <input
            className="auth-input"
            type="password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            required
            minLength={passwordMinLength}
            autoComplete="new-password"
            dir="ltr"
          />
          <span className="auth-hint">
            {labels.minLength.replace("{n}", String(passwordMinLength))}
          </span>
        </label>
        <label className="auth-field">
          <span className="auth-label">{labels.role}</span>
          <select
            className="auth-input"
            value={role}
            onChange={(e) => setRole(e.target.value)}
          >
            {assignableRoles.map((r) => (
              <option key={r} value={r}>
                {labels.roleNames[r] ?? r}
              </option>
            ))}
          </select>
        </label>

        <button type="submit" className="auth-button user-form-submit" disabled={busy}>
          {busy ? labels.creating : labels.create}
        </button>
      </form>

      {message && (
        <p
          className="text-xs"
          style={{ color: message.ok ? "var(--good)" : "var(--critical)" }}
          role="status"
        >
          {message.text}
        </p>
      )}

      <div className="scroll-x">
        <table className="data">
          <thead>
            <tr>
              <th>{labels.email}</th>
              <th>{labels.role}</th>
              <th>{labels.lastSeen}</th>
              <th />
            </tr>
          </thead>
          <tbody>
            {users.map((user) => (
              <tr key={user.id}>
                <td dir="ltr">
                  {user.email}
                  {user.display_name && (
                    <span className="ink-3"> · {user.display_name}</span>
                  )}
                </td>
                <td>
                  <span className="pill">{labels.roleNames[user.role] ?? user.role}</span>
                </td>
                <td className="num ink-3">
                  {user.last_login_at
                    ? new Date(user.last_login_at).toLocaleString()
                    : labels.neverSignedIn}
                </td>
                <td>
                  {/* An owner cannot be switched off here. The deployment
                      refuses to remove its last one anyway, and offering a
                      button that the server will refuse is a button that
                      teaches people to distrust the screen. */}
                  {user.role !== "owner" && (
                    <button
                      type="button"
                      className="pill"
                      onClick={() => void setActive(user.id, !user.is_active)}
                      style={{
                        color: user.is_active ? "var(--ink-2)" : "var(--accent)",
                        cursor: "pointer",
                      }}
                    >
                      {user.is_active ? labels.deactivate : labels.activate}
                    </button>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
