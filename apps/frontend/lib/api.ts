import type { ExperimentResults, InventoryItem, Priority, StrategyPresets } from "./types";

const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000/api/v1";

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${API_URL}${path}`, {
    ...init,
    headers: { "Content-Type": "application/json", ...(init?.headers ?? {}) },
  });
  if (!res.ok) {
    const body = await res.json().catch(() => ({}));
    throw new Error(body?.detail?.message ?? `${res.status} ${res.statusText}`);
  }
  return res.json() as Promise<T>;
}

export const api = {
  simulation: {
    start: () => request("/simulation/start", { method: "POST" }),
    pause: () => request("/simulation/pause", { method: "POST" }),
    reset: () => request("/simulation/reset", { method: "POST" }),
    speed: (multiplier: number) =>
      request("/simulation/speed", { method: "PUT", body: JSON.stringify({ multiplier }) }),
    setAssignmentMode: (mode: "auto" | "manual") =>
      request("/simulation/assignment-mode", { method: "PUT", body: JSON.stringify({ mode }) }),
    strategy: () => request<StrategyPresets>("/simulation/strategy"),
    setPreset: (preset: string) =>
      request("/simulation/strategy", { method: "PUT", body: JSON.stringify({ preset }) }),
  },
  analytics: {
    experiments: () => request<ExperimentResults>("/analytics/experiments"),
  },
  orders: {
    create: (body: { priority: Priority; items: { product_id: string; quantity: number }[]; robot_id?: string | null }) =>
      request<{ order_id: string; robot_id: string | null }>("/orders", { method: "POST", body: JSON.stringify(body) }),
    assign: (orderId: string, robotId: string) =>
      request(`/orders/${orderId}/assign`, { method: "POST", body: JSON.stringify({ robot_id: robotId }) }),
  },
  inventory: {
    list: () => request<InventoryItem[]>("/inventory"),
  },
  robots: {
    pause: (id: string) => request(`/robots/${id}/pause`, { method: "POST" }),
    resume: (id: string) => request(`/robots/${id}/resume`, { method: "POST" }),
  },
};
