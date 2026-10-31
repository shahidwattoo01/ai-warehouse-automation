// Alert centre (backend: apps/backend/app/api/v1/alerts.py, app/services/alerts.py).

import { request } from "./api";

export type Severity = "critical" | "warning" | "info";
export type Channel = "screen" | "email" | "webhook";

export interface Incident {
  alert_id: string;
  rule: string;
  name: string;
  subject: string;
  severity: Severity;
  title: string;
  detail: string;
  status: "OPEN" | "ACKNOWLEDGED" | "RESOLVED";
  escalated: boolean;
  opened_time: string;
  resolved_time: string | null;
  minutes_open: number;
  acknowledged_by: string | null;
  resolved_by: string | null;
  history: { at: string; tick: number; event: string; user: string; note: string | null }[];
}

export interface AlertSummary {
  open: number;
  acknowledged: number;
  critical: number;
  escalated: number;
}

export interface AlertRule {
  name: string;
  severity: Severity;
  threshold: number | null;
  unit: string | null;
  escalate_after_min: number;
  notify: Channel[];
  escalate_to: Channel[];
  enabled: boolean;
}

export interface Notification {
  at: string | null;
  alert_id: string;
  channel: string;
  why: string;
  status: "PENDING" | "SHOWN" | "SENT" | "FAILED" | "NOT_CONFIGURED";
  detail: string | null;
}

const post = (body: unknown = {}): RequestInit => ({ method: "POST", body: JSON.stringify(body) });

export const alerts = {
  list: (status = "active") => request<{ incidents: Incident[]; summary: AlertSummary }>(`/alerts?status=${status}`),
  acknowledge: (id: string, note?: string) => request<Incident>(`/alerts/${id}/acknowledge`, post({ note })),
  resolve: (id: string, note?: string) => request<Incident>(`/alerts/${id}/resolve`, post({ note })),
  rules: () => request<{ rules: Record<string, AlertRule>; channels: Channel[] }>("/alerts/rules"),
  updateRule: (id: string, change: Partial<AlertRule>) =>
    request<AlertRule>(`/alerts/rules/${id}`, { method: "PUT", body: JSON.stringify(change) }),
  notifications: () => request<Notification[]>("/alerts/notifications"),
  test: (channel: "email" | "webhook") => request<Notification>("/alerts/test-notification", post({ channel })),
};

export const SEVERITY_DOT: Record<Severity, string> = {
  critical: "bg-danger",
  warning: "bg-warning",
  info: "bg-muted",
};
