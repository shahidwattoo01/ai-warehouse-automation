// User administration and account API (backend: apps/backend/app/api/v1/auth.py).

import { request } from "./api";

export interface UserRow {
  user_id: string;
  username: string;
  full_name: string;
  role: string;
  role_label: string;
  active: boolean;
  locked: boolean;
  last_login: string | null;
  created_at: string | null;
}

export interface RolesTable {
  permissions: Record<string, string>;
  roles: Record<string, { label: string; home: string; permissions: string[] }>;
}

export interface LoginEvent {
  username: string;
  user_id: string | null;
  outcome: string;
  client: string | null;
  created_at: string;
}

const json = (method: string, body: unknown): RequestInit => ({ method, body: JSON.stringify(body) });

export const admin = {
  users: () => request<UserRow[]>("/users"),
  create: (b: { username: string; full_name: string; role: string; password: string }) =>
    request<UserRow>("/users", json("POST", b)),
  change: (id: string, b: { full_name?: string; role?: string; active?: boolean }) =>
    request<UserRow>(`/users/${id}`, json("PUT", b)),
  resetPassword: (id: string, password: string) =>
    request<{ ok: boolean }>(`/users/${id}/password`, json("POST", { password })),
  unlock: (id: string) => request<{ ok: boolean }>(`/users/${id}/unlock`, { method: "POST" }),
  loginEvents: () => request<LoginEvent[]>("/users/login-events?limit=100"),
  roles: () => request<RolesTable>("/auth/roles"),
  changeOwnPassword: (current: string, next: string) =>
    request<{ ok: boolean }>("/auth/password", json("PUT", { current, new: next })),
};
