"use client";

import { usePathname, useRouter } from "next/navigation";
import { useEffect } from "react";
import { pagePermission, refreshSession, useAuth } from "@/lib/auth";
import { Sidebar } from "./Sidebar";

// Pages without a login: the login page itself, and the camera-dataset page that
// scripts/capture_frames.py drives without the API.
const PUBLIC = ["/login", "/capture"];

/**
 * Restores the session from the refresh cookie on load, sends anyone not logged in to /login,
 * and only then draws the app shell (sidebar + page). The backend checks every request again;
 * this only decides what the browser shows.
 */
export function AuthGate({ children }: { children: React.ReactNode }) {
  const path = usePathname() ?? "/";
  const router = useRouter();
  const status = useAuth((s) => s.status);
  const isPublic = PUBLIC.some((p) => path.startsWith(p));

  useEffect(() => {
    if (status === "unknown") void refreshSession();
  }, [status]);

  useEffect(() => {
    if (!isPublic && status === "anonymous") router.replace(`/login?next=${encodeURIComponent(path)}`);
  }, [isPublic, status, path, router]);

  if (isPublic) return <>{children}</>;
  if (status !== "authenticated") {
    return (
      <div className="flex h-screen items-center justify-center bg-canvas text-sm text-muted">
        Checking your session…
      </div>
    );
  }
  return (
    <div className="flex h-screen overflow-hidden">
      <Sidebar />
      <main className="flex min-w-0 flex-1 flex-col">
        <PageAccess path={path}>{children}</PageAccess>
      </main>
    </div>
  );
}

function PageAccess({ path, children }: { path: string; children: React.ReactNode }) {
  const user = useAuth((s) => s.user);
  const needed = pagePermission(path);
  if (!needed || user?.permissions.includes(needed)) return <>{children}</>;
  return (
    <div className="flex flex-1 items-center justify-center p-6">
      <div className="max-w-md rounded-card border border-border bg-surface p-6 text-center">
        <div className="text-lg font-semibold">Not available for your role</div>
        <p className="mt-2 text-sm text-muted">
          {user?.role_label} accounts cannot open this page. Ask an administrator if you need access.
        </p>
        <a
          href={user?.home ?? "/"}
          className="mt-4 inline-block rounded-control bg-accent px-3 py-1.5 text-sm text-white"
        >
          Go to my start page
        </a>
      </div>
    </div>
  );
}
