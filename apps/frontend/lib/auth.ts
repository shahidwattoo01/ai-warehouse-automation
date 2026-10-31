"use client";

import { create } from "zustand";

// Session handling for the browser (backend: apps/backend/app/core/auth.py).
//
// * The access token (JWT, 15 min) is kept in memory only, never in localStorage, so a malicious
//   script cannot read it from storage.
// * The refresh token is an httpOnly cookie that this code never sees; POST /auth/refresh turns
//   it into a new access token. That happens on page load, a minute before expiry, and when a
//   request comes back 401.

export const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000/api/v1";

export interface AuthUser {
  user_id: string;
  username: string;
  full_name: string;
  role: string;
  role_label: string;
  home: string;
  permissions: string[];
}

interface AuthState {
  status: "unknown" | "anonymous" | "authenticated";
  user: AuthUser | null;
  token: string | null;
}

export const useAuth = create<AuthState>(() => ({ status: "unknown", user: null, token: null }));

interface Session {
  access_token: string;
  expires_in: number;
  user: AuthUser;
}

let timer: ReturnType<typeof setTimeout> | undefined;
let refreshing: Promise<boolean> | null = null;

function start(session: Session) {
  useAuth.setState({ status: "authenticated", user: session.user, token: session.access_token });
  clearTimeout(timer);
  timer = setTimeout(() => void refreshSession(), Math.max(10, session.expires_in - 60) * 1000);
}

function end() {
  clearTimeout(timer);
  useAuth.setState({ status: "anonymous", user: null, token: null });
}

async function message(res: Response, fallback: string): Promise<string> {
  const body = await res.json().catch(() => ({}));
  return body?.detail?.message ?? (typeof body?.detail === "string" ? body.detail : fallback);
}

/** Exchange the refresh cookie for a new access token. One request at a time. */
export function refreshSession(): Promise<boolean> {
  refreshing ??= fetch(`${API_URL}/auth/refresh`, { method: "POST", credentials: "include" })
    .then(async (res) => {
      if (!res.ok) {
        end();
        return false;
      }
      start((await res.json()) as Session);
      return true;
    })
    .catch(() => {
      end();
      return false;
    })
    .finally(() => {
      refreshing = null;
    });
  return refreshing;
}

export async function login(username: string, password: string): Promise<AuthUser> {
  const res = await fetch(`${API_URL}/auth/login`, {
    method: "POST",
    credentials: "include",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ username, password }),
  });
  if (!res.ok) throw new Error(await message(res, "Login failed"));
  const session = (await res.json()) as Session;
  start(session);
  return session.user;
}

export async function logout(): Promise<void> {
  try {
    await fetch(`${API_URL}/auth/logout`, { method: "POST", credentials: "include" });
  } finally {
    end();
  }
}

/** fetch with the access token; on 401 refresh once and retry. */
export async function authFetch(url: string, init: RequestInit = {}): Promise<Response> {
  const withToken = () => {
    const token = useAuth.getState().token;
    const headers = new Headers(init.headers);
    if (token) headers.set("Authorization", `Bearer ${token}`);
    return fetch(url, { ...init, headers });
  };
  let res = await withToken();
  if (res.status === 401 && (await refreshSession())) res = await withToken();
  return res;
}

/** Object URL of a protected file (barcode SVG, label PDF): <img> and links cannot send tokens. */
export async function protectedObjectUrl(url: string): Promise<string> {
  const res = await authFetch(url);
  if (!res.ok) throw new Error(await message(res, `${res.status} ${res.statusText}`));
  return URL.createObjectURL(await res.blob());
}

/** Open a protected PDF (labels) in a new tab. */
export async function openProtected(url: string): Promise<void> {
  const tab = window.open("", "_blank"); // opened now, so pop-up blockers allow it
  try {
    const objectUrl = await protectedObjectUrl(url);
    if (tab) tab.location.href = objectUrl;
    else window.location.href = objectUrl;
  } catch (e) {
    tab?.close();
    alert((e as Error).message);
  }
}

/** Download a protected file (CSV, ZPL, PDF) under the given name. */
export async function downloadProtected(url: string, filename: string): Promise<void> {
  try {
    const objectUrl = await protectedObjectUrl(url);
    const a = document.createElement("a");
    a.href = objectUrl;
    a.download = filename;
    document.body.appendChild(a);
    a.click();
    a.remove();
    setTimeout(() => URL.revokeObjectURL(objectUrl), 10_000);
  } catch (e) {
    alert((e as Error).message);
  }
}

/** Does the logged-in user hold this permission? (The backend checks it again.) */
export function useCan(permission: string): boolean {
  return useAuth((s) => s.user?.permissions.includes(permission) ?? false);
}

/** Pages and the permission each needs (the backend refuses the data anyway). */
export const PAGE_PERMISSION: [string, string][] = [
  ["/admin", "users:manage"],
  ["/inventory", "wms:view"],
  ["/analytics", "analytics:view"],
  ["/copilot", "copilot:use"],
  ["/knowledge", "copilot:use"],
  ["/vision", "dashboard:view"],
  ["/dashboard", "dashboard:view"],
  ["/simulation", "dashboard:view"],
  ["/fleet", "dashboard:view"],
  ["/orders", "dashboard:view"],
  ["/safety", "dashboard:view"],
  ["/alerts", "dashboard:view"],
];

export function pagePermission(path: string): string | null {
  return PAGE_PERMISSION.find(([prefix]) => path.startsWith(prefix))?.[1] ?? null;
}

/** First run: no account exists yet. */
export async function needsSetup(): Promise<boolean> {
  try {
    const res = await fetch(`${API_URL}/auth/setup`);
    return res.ok ? Boolean((await res.json()).needs_setup) : false;
  } catch {
    return false;
  }
}

/** Create the first administrator (only accepted while there are no accounts) and log in. */
export async function setupFirstAdmin(username: string, full_name: string, password: string): Promise<AuthUser> {
  const res = await fetch(`${API_URL}/auth/setup`, {
    method: "POST",
    credentials: "include",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ username, full_name, password }),
  });
  if (!res.ok) throw new Error(await message(res, "Setup failed"));
  const session = (await res.json()) as Session;
  start(session);
  return session.user;
}
