"use client";

import { useState } from "react";
import { Screen } from "@/components/layout/Screen";
import { admin } from "@/lib/admin";
import { useAuth } from "@/lib/auth";

const input =
  "w-full rounded-control border border-border bg-canvas px-3 py-2 text-sm outline-none focus:border-accent";

/** My account: who I am, what my role allows, and changing my password (every role). */
export default function AccountPage() {
  const user = useAuth((s) => s.user);
  const [current, setCurrent] = useState("");
  const [next, setNext] = useState("");
  const [repeat, setRepeat] = useState("");
  const [message, setMessage] = useState<{ ok: boolean; text: string } | null>(null);

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (next !== repeat) {
      setMessage({ ok: false, text: "The new passwords differ." });
      return;
    }
    try {
      await admin.changeOwnPassword(current, next);
      setMessage({ ok: true, text: "Password changed. Your other sessions were logged out." });
      setCurrent("");
      setNext("");
      setRepeat("");
    } catch (err) {
      setMessage({ ok: false, text: (err as Error).message });
    }
  };

  if (!user) return null;
  return (
    <Screen title="My account">
      <div className="grid max-w-4xl gap-4 md:grid-cols-2">
        <section className="rounded-card border border-border bg-surface p-4 text-sm">
          <div className="text-lg font-semibold">{user.full_name}</div>
          <div className="font-mono text-xs text-muted">{user.username}</div>
          <div className="mt-2">{user.role_label}</div>
          <h3 className="mb-1 mt-4 text-xs font-semibold uppercase tracking-wide text-muted">You may</h3>
          <ul className="space-y-0.5 font-mono text-xs">
            {user.permissions.map((p) => (
              <li key={p}>{p}</li>
            ))}
          </ul>
        </section>
        <form onSubmit={submit} className="space-y-2 rounded-card border border-border bg-surface p-4 text-sm">
          <h2 className="font-semibold">Change password</h2>
          <input
            className={input}
            type="password"
            placeholder="Current password"
            autoComplete="current-password"
            value={current}
            onChange={(e) => setCurrent(e.target.value)}
            required
          />
          <input
            className={input}
            type="password"
            placeholder="New password"
            autoComplete="new-password"
            value={next}
            onChange={(e) => setNext(e.target.value)}
            required
          />
          <input
            className={input}
            type="password"
            placeholder="Repeat new password"
            autoComplete="new-password"
            value={repeat}
            onChange={(e) => setRepeat(e.target.value)}
            required
          />
          <p className="text-[11px] text-muted">At least 10 characters, letters mixed with digits or symbols.</p>
          {message && (
            <div
              className={`rounded-control border p-2 ${message.ok ? "border-success/50 bg-success/10" : "border-danger/50 bg-danger/10"}`}
            >
              {message.text}
            </div>
          )}
          <button className="rounded-control bg-accent px-3 py-1.5 font-medium text-white">Change password</button>
        </form>
      </div>
    </Screen>
  );
}
