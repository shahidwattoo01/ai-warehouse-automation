import type {
  CopilotHistoryItem,
  CopilotReply,
  CopilotStatus,
  DetectionResult,
  DocType,
  ExperimentResults,
  InventoryItem,
  KnowledgeAnswer,
  KnowledgeDocument,
  KnowledgeSource,
  KnowledgeStatus,
  Priority,
  StrategyPresets,
  VisionStatus,
} from "./types";

import { API_URL, authFetch } from "./auth";

export { API_URL };

/** JSON request with the access token (refreshed and retried once on 401). */
export async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await authFetch(`${API_URL}${path}`, {
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
    start: () => request<{ running: boolean }>("/simulation/start", { method: "POST" }),
    pause: () => request<{ running: boolean }>("/simulation/pause", { method: "POST" }),
    reset: () => request("/simulation/reset", { method: "POST" }),
    speed: (multiplier: number) =>
      request("/simulation/speed", { method: "PUT", body: JSON.stringify({ multiplier }) }),
    setAssignmentMode: (mode: "auto" | "manual") =>
      request("/simulation/assignment-mode", { method: "PUT", body: JSON.stringify({ mode }) }),
    strategy: () => request<StrategyPresets>("/simulation/strategy"),
    setPreset: (preset: string) => request("/simulation/strategy", { method: "PUT", body: JSON.stringify({ preset }) }),
  },
  analytics: {
    experiments: () => request<ExperimentResults>("/analytics/experiments"),
  },
  copilot: {
    status: () => request<CopilotStatus>("/copilot/status"),
    chat: (text: string) => request<CopilotReply>("/copilot/chat", { method: "POST", body: JSON.stringify({ text }) }),
    approve: (id: string) =>
      request<{ ok: boolean; answer: string }>(`/copilot/actions/${id}/approve`, { method: "POST" }),
    reject: (id: string) =>
      request<{ ok: boolean; answer: string }>(`/copilot/actions/${id}/reject`, { method: "POST" }),
    history: () => request<CopilotHistoryItem[]>("/copilot/history"),
  },
  rag: {
    status: () => request<KnowledgeStatus>("/rag/status"),
    query: (question: string, docType?: DocType | null) =>
      request<KnowledgeAnswer>("/rag/query", {
        method: "POST",
        body: JSON.stringify({ question, doc_type: docType ?? null }),
      }),
    documents: () => request<KnowledgeDocument[]>("/rag/documents"),
    section: (sectionId: string) => request<KnowledgeSource>(`/rag/sections/${encodeURIComponent(sectionId)}`),
  },
  vision: {
    status: () => request<VisionStatus>("/vision/status"),
    detect: (image: string) =>
      request<DetectionResult>("/vision/detect", { method: "POST", body: JSON.stringify({ image }) }),
  },
  orders: {
    create: (body: {
      priority: Priority;
      items: { product_id: string; quantity: number }[];
      robot_id?: string | null;
    }) =>
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
