"use client";

import { Check, KeyRound, Lock, UserPlus, X } from "lucide-react";
import { useCallback, useEffect, useState } from "react";
import { Screen } from "@/components/layout/Screen";
import { admin, type LoginEvent, type RolesTable, type UserRow } from "@/lib/admin";
import { useAuth } from "@/lib/auth";

const input = "rounded-control border border-border bg-canvas px-2 py-1.5 text-sm outline-none focus:border-accent";
const th = "px-2 py-1.5 text-left text-[11px] font-semibold uppercase tracking-wide text-muted";
const td = "px-2 py-1.5";

/** User administration (permission users:manage): accounts, roles, passwords, the login audit
 *  and the role/permission table. Accounts are only created here, never by sign-up. */
export default function UsersPage() {
  const me = useAuth((s) => s.user);
  const [users, setUsers] = useState<UserRow[]>([]);
  const [roles, setRoles] = useState<RolesTable | null>(null);
  const [events, setEvents] = useState<LoginEvent[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [note, setNote] = useState<string | null>(null);
  const [form, setForm] = useState({ username: "", full_name: "", role: "operator", password: "" });
  const [resetFor, setResetFor] = useState<string | null>(null);
  const [newPassword, setNewPassword] = useState("");

  const load = useCallback(() => {
    admin
      .users()
      .then(setUsers)
      .catch((e: Error) => setError(e.message));
    admin
      .loginEvents()
      .then(setEvents)
      .catch(() => undefined);
  }, []);
  useEffect(() => {
    load();
    admin
      .roles()
      .then(setRoles)
      .catch(() => undefined);
  }, [load]);

  const run = async (fn: () => Promise<unknown>, done: string) => {
    try {
      await fn();
      setError(null);
      setNote(done);
      load();
    } catch (e) {
      setNote(null);
      setError((e as Error).message);
    }
  };

  const roleNames = roles ? Object.entries(roles.roles) : [];
  return (
    <Screen title="Users & roles">
      {error && <div className="mb-3 rounded-control border border-danger/50 bg-danger/10 p-2 text-sm">{error}</div>}
      {note && <div className="mb-3 rounded-control border border-success/50 bg-success/10 p-2 text-sm">{note}</div>}
      <div className="grid items-start gap-4 xl:grid-cols-[minmax(0,1fr)_360px]">
        <section className="rounded-card border border-border bg-surface p-4">
          <h2 className="mb-3 text-sm font-semibold">Accounts ({users.length})</h2>
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr>
                  <th className={th}>User</th>
                  <th className={th}>Role</th>
                  <th className={th}>Status</th>
                  <th className={th}>Last login</th>
                  <th className={th} />
                </tr>
              </thead>
              <tbody>
                {users.map((u) => (
                  <tr key={u.user_id} className="border-t border-border align-top">
                    <td className={td}>
                      <div className="font-medium">{u.full_name}</div>
                      <div className="font-mono text-xs text-muted">{u.username}</div>
                    </td>
                    <td className={td}>
                      <select
                        className={`${input} py-1`}
                        value={u.role}
                        aria-label={`Role of ${u.username}`}
                        onChange={(e) =>
                          run(
                            () => admin.change(u.user_id, { role: e.target.value }),
                            `${u.username} is now ${e.target.value}`,
                          )
                        }
                      >
                        {roleNames.map(([k, r]) => (
                          <option key={k} value={k}>
                            {r.label}
                          </option>
                        ))}
                      </select>
                    </td>
                    <td className={td}>
                      {u.locked ? (
                        <span className="text-danger">locked</span>
                      ) : u.active ? (
                        <span className="text-success">active</span>
                      ) : (
                        <span className="text-muted">disabled</span>
                      )}
                    </td>
                    <td className={`${td} text-xs text-muted`}>
                      {u.last_login ? new Date(u.last_login).toLocaleString() : "never"}
                    </td>
                    <td className={`${td} whitespace-nowrap text-xs`}>
                      <div className="flex flex-wrap gap-1">
                        {u.user_id !== me?.user_id && (
                          <button
                            className="rounded-control border border-border px-2 py-1 hover:border-accent"
                            onClick={() =>
                              run(
                                () => admin.change(u.user_id, { active: !u.active }),
                                `${u.username} ${u.active ? "disabled" : "enabled"}`,
                              )
                            }
                          >
                            {u.active ? "Disable" : "Enable"}
                          </button>
                        )}
                        {u.locked && (
                          <button
                            className="flex items-center gap-1 rounded-control border border-border px-2 py-1 hover:border-accent"
                            onClick={() => run(() => admin.unlock(u.user_id), `${u.username} unlocked`)}
                          >
                            <Lock size={12} /> Unlock
                          </button>
                        )}
                        <button
                          className="flex items-center gap-1 rounded-control border border-border px-2 py-1 hover:border-accent"
                          onClick={() => {
                            setResetFor(resetFor === u.user_id ? null : u.user_id);
                            setNewPassword("");
                          }}
                        >
                          <KeyRound size={12} /> Reset password
                        </button>
                      </div>
                      {resetFor === u.user_id && (
                        <form
                          className="mt-2 flex gap-1"
                          onSubmit={(e) => {
                            e.preventDefault();
                            void run(
                              () => admin.resetPassword(u.user_id, newPassword),
                              `New password set for ${u.username}`,
                            );
                            setResetFor(null);
                          }}
                        >
                          <input
                            type="password"
                            autoComplete="new-password"
                            className={`${input} w-40 py-1`}
                            placeholder="new password"
                            value={newPassword}
                            onChange={(e) => setNewPassword(e.target.value)}
                          />
                          <button className="rounded-control bg-accent px-2 text-white" aria-label="Save password">
                            <Check size={14} />
                          </button>
                          <button
                            type="button"
                            className="rounded-control border border-border px-2"
                            onClick={() => setResetFor(null)}
                            aria-label="Cancel"
                          >
                            <X size={14} />
                          </button>
                        </form>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>

        <section className="rounded-card border border-border bg-surface p-4">
          <h2 className="mb-3 flex items-center gap-2 text-sm font-semibold">
            <UserPlus size={16} /> New account
          </h2>
          <form
            className="space-y-2"
            onSubmit={(e) => {
              e.preventDefault();
              void run(async () => {
                await admin.create(form);
                setForm({ username: "", full_name: "", role: form.role, password: "" });
              }, `Account ${form.username} created`);
            }}
          >
            <input
              className={`${input} w-full`}
              placeholder="Username (letters, digits, . _ -)"
              value={form.username}
              onChange={(e) => setForm({ ...form, username: e.target.value })}
              autoComplete="off"
              required
            />
            <input
              className={`${input} w-full`}
              placeholder="Full name"
              value={form.full_name}
              onChange={(e) => setForm({ ...form, full_name: e.target.value })}
              required
            />
            <select
              className={`${input} w-full`}
              value={form.role}
              onChange={(e) => setForm({ ...form, role: e.target.value })}
              aria-label="Role"
            >
              {roleNames.map(([k, r]) => (
                <option key={k} value={k}>
                  {r.label}
                </option>
              ))}
            </select>
            <input
              className={`${input} w-full`}
              type="password"
              placeholder="Initial password"
              value={form.password}
              onChange={(e) => setForm({ ...form, password: e.target.value })}
              autoComplete="new-password"
              required
            />
            <p className="text-[11px] text-muted">
              At least 10 characters, letters mixed with digits or symbols, not containing the username. Give it to the
              person privately; they can change it under My account.
            </p>
            <button className="w-full rounded-control bg-accent py-1.5 text-sm font-medium text-white">
              Create account
            </button>
          </form>
        </section>
      </div>

      {roles && (
        <section className="mt-4 rounded-card border border-border bg-surface p-4">
          <h2 className="mb-3 text-sm font-semibold">What each role may do</h2>
          <div className="overflow-x-auto">
            <table className="w-full text-xs">
              <thead>
                <tr>
                  <th className={th}>Permission</th>
                  {roleNames.map(([k, r]) => (
                    <th key={k} className={`${th} text-center`}>
                      {r.label}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {Object.entries(roles.permissions).map(([perm, text]) => (
                  <tr key={perm} className="border-t border-border">
                    <td className={td}>
                      <span className="font-mono">{perm}</span>
                      <div className="text-muted">{text}</div>
                    </td>
                    {roleNames.map(([k, r]) => (
                      <td key={k} className={`${td} text-center`}>
                        {r.permissions.includes(perm) ? <Check size={14} className="inline text-success" /> : ""}
                      </td>
                    ))}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>
      )}

      <section className="mt-4 rounded-card border border-border bg-surface p-4">
        <h2 className="mb-3 text-sm font-semibold">Recent logins</h2>
        <div className="max-h-72 overflow-auto">
          <table className="w-full text-xs">
            <tbody>
              {events.map((e, i) => (
                <tr key={i} className="border-t border-border">
                  <td className={`${td} text-muted`}>{new Date(e.created_at).toLocaleString()}</td>
                  <td className={`${td} font-mono`}>{e.username}</td>
                  <td className={`${td} ${e.outcome === "success" ? "text-success" : "text-danger"}`}>
                    {e.outcome.replaceAll("_", " ")}
                  </td>
                  <td className={`${td} text-muted`}>{e.client}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>
    </Screen>
  );
}
