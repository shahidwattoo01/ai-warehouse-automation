// Fleet safety: emergency stop, release, reset, zone stops, slow zones, the safety log
// (backend: apps/backend/app/api/v1/safety.py).

import { request } from "./api";
import type { SafetyState } from "./types";

export interface SafetyStatus extends SafetyState {
  near_miss_radius: number;
  zones: string[];
  metrics: Record<string, number>;
  blockers: string[];
}

export interface SafetyEvent {
  tick: number;
  kind: string;
  severity: "info" | "warning" | "critical";
  text: string;
  robot_id: string | null;
  zone: string | null;
  x: number | null;
  y: number | null;
  user: string;
  detail: Record<string, unknown>;
}

const post = (body: unknown = {}): RequestInit => ({ method: "POST", body: JSON.stringify(body) });

export const safety = {
  status: () => request<SafetyStatus>("/safety/status"),
  estop: (reason = "Emergency stop button", zone: string | null = null) =>
    request<SafetyState>("/safety/estop", post({ reason, zone })),
  release: (note?: string) => request<SafetyState>("/safety/release", post({ note })),
  reset: (area_checked = false) => request<SafetyState>("/safety/reset", post({ area_checked })),
  settings: (s: { slow_zones?: boolean; slow_radius?: number }) =>
    request<SafetyState>("/safety/settings", { method: "PUT", body: JSON.stringify(s) }),
  events: (kind?: string) => request<SafetyEvent[]>(`/safety/events${kind ? `?kind=${kind}` : ""}`),
};
