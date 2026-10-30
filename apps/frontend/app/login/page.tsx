"use client";

import { Lock, ShieldCheck, Warehouse } from "lucide-react";
import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, useEffect, useState } from "react";
import { login, needsSetup, setupFirstAdmin, useAuth } from "@/lib/auth";

const field = "mt-1 w-full rounded-control border border-border bg-canvas px-3 py-2 outline-none focus:border-accent";

function LoginForm() {
  const router = useRouter();
  const params = useSearchParams();
  const status = useAuth((s) => s.status);
  const user = useAuth((s) => s.user);
  const [setup, setSetup] = useState<boolean | null>(null);
  const [fullName, setFullName] = useState("");
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [repeat, setRepeat] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Only go back to a page of this app (never an outside address passed in ?next=).
  const next = params.get("next");
  const target = (home: string) => (next && next.startsWith("/") && !next.startsWith("//") ? next : home);

  useEffect(() => {
    void needsSetup().then(setSetup);
  }, []);

  useEffect(() => {
    if (status === "authenticated" && user) router.replace(target(user.home));
    // eslint-disable-next-line react-hooks/exhaustive-deps -- run when the session appears
  }, [status, user]);

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (setup && password !== repeat) {
      setError("The passwords differ.");
      return;
    }
    setBusy(true);
    setError(null);
    try {
      const u = setup
        ? await setupFirstAdmin(username.trim(), fullName.trim(), password)
        : await login(username.trim(), password);
      router.replace(setup ? "/admin/users" : target(u.home));
    } catch (err) {
      setError((err as Error).message);
      setPassword("");
      setRepeat("");
    } finally {
      setBusy(false);
    }
  };

  if (setup === null) return null;
  return (
    <div className="flex min-h-screen items-center justify-center bg-canvas p-4">
      <form onSubmit={submit} className="w-full max-w-sm rounded-card border border-border bg-surface p-6 shadow-sm">
        <div className="mb-6 flex items-center gap-2">
          <Warehouse size={22} className="text-accent" />
          <div>
            <div className="text-lg font-semibold">Warehouse AI</div>
            <div className="text-xs text-muted">Control Center · {setup ? "first-time setup" : "sign in"}</div>
          </div>
        </div>

        {setup && (
          <div className="mb-4 rounded-control border border-accent/40 bg-accent/5 p-3 text-xs">
            <b>Welcome.</b> There are no accounts yet. Create the first <b>administrator</b>; you will then create the
            other users (supervisors, operators, inventory clerks, viewers) under <i>Users &amp; roles</i>.
          </div>
        )}
        {setup && (
          <label className="mb-3 block text-sm">
            Full name
            <input
              value={fullName}
              onChange={(e) => setFullName(e.target.value)}
              required
              autoFocus
              className={field}
            />
          </label>
        )}
        <label className="mb-3 block text-sm">
          Username
          <input
            value={username}
            onChange={(e) => setUsername(e.target.value)}
            autoComplete="username"
            autoFocus={!setup}
            required
            className={field}
          />
        </label>
        <label className="mb-3 block text-sm">
          Password
          <input
            type="password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            autoComplete={setup ? "new-password" : "current-password"}
            required
            className={field}
          />
        </label>
        {setup && (
          <label className="mb-3 block text-sm">
            Repeat password
            <input
              type="password"
              value={repeat}
              onChange={(e) => setRepeat(e.target.value)}
              autoComplete="new-password"
              required
              className={field}
            />
          </label>
        )}
        {setup && (
          <p className="mb-3 text-[11px] text-muted">
            At least 10 characters, letters mixed with digits or symbols, not containing the username.
          </p>
        )}
        {error && (
          <div role="alert" className="mb-3 rounded-control border border-danger/50 bg-danger/10 p-2 text-sm">
            {error}
          </div>
        )}
        <button
          type="submit"
          disabled={busy || !username || !password || (setup && !fullName)}
          className="flex w-full items-center justify-center gap-2 rounded-control bg-accent py-2 text-sm font-semibold text-white disabled:opacity-50"
        >
          {setup ? <ShieldCheck size={14} /> : <Lock size={14} />}{" "}
          {busy ? "Please wait…" : setup ? "Create administrator" : "Sign in"}
        </button>

        {!setup && (
          <div className="mt-5 space-y-2 border-t border-border pt-4 text-xs text-muted">
            <p>
              <b className="text-ink">No account yet?</b> There is no self sign-up: your administrator creates accounts
              and gives you a username, a starting password and a role. You can change the password under{" "}
              <i>My account</i> after signing in.
            </p>
            <p>
              <b className="text-ink">Forgot your password or locked out?</b> Ask an administrator to reset or unlock
              it. After 5 wrong passwords an account is locked for 15 minutes.
            </p>
            <p>
              <b className="text-ink">Administrators</b> manage everyone under <i>Users &amp; roles</i>.
            </p>
          </div>
        )}
      </form>
    </div>
  );
}

export default function LoginPage() {
  return (
    <Suspense>
      <LoginForm />
    </Suspense>
  );
}
