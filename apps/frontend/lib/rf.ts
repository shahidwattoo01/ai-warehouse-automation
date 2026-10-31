// Handheld (RF) task-directed work (backend: wms/rf.py, /api/v1/wms/rf/...).

import { request } from "./api";

export interface RfTask {
  task_id: string;
  type: string;
  title: string;
  steps: string[];
  go_to?: string | null;
  scan: { kind: "plate" | "location"; label: string; value: string } | null;
  inputs: { name: string; label: string; default: number | null }[];
}

export interface RfSummary {
  open: Record<string, number>;
  auto: Record<string, boolean>;
  my_task: string | null;
}

const post = (body: unknown = {}): RequestInit => ({ method: "POST", body: JSON.stringify(body) });

export const rf = {
  summary: () => request<RfSummary>("/wms/rf/summary"),
  next: (types?: string[]) => request<{ task: RfTask | null }>("/wms/rf/next", post({ types })),
  confirm: (id: string, scan: string, values: Record<string, number | null>) =>
    request<{ task_id: string; result: string }>(`/wms/rf/tasks/${id}/confirm`, post({ scan, ...values })),
  release: (id: string) => request(`/wms/rf/tasks/${id}/release`, post()),
};

export const RF_LABEL: Record<string, string> = {
  RECEIVE: "Receive",
  PUTAWAY: "Put away",
  REPLENISH_URGENT: "Replenish (urgent)",
  REPLENISH: "Replenish",
  COUNT: "Count",
  LOAD: "Load trucks",
};
