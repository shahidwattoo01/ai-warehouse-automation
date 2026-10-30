// WMS (inventory_model: wms): types and API client for /api/v1/wms (apps/backend/app/api/v1/wms.py).

import { API_URL, request } from "./api";
import { openProtected } from "./auth";

export interface WmsKpis {
  skus: number;
  locations: number;
  units_on_hand: number;
  inventory_value: number;
  stockouts: number;
  orders_waiting_stock: number;
  fill_rate: number;
  units_short: number;
  inventory_record_accuracy: number | null;
  counts_done: number;
  counts_pending_approval: number;
  open_purchase_orders: number;
  trucks_at_dock: number;
  dock_to_stock_ticks: number | null;
  open_tasks: Record<string, number>;
  on_hold_units: number;
  date: string;
  tick: number;
}

export interface WmsAlert {
  tick: number;
  level: "info" | "warning";
  text: string;
  ref: string | null;
}

export interface WmsItemRow {
  sku: string;
  name: string;
  category: string;
  gtin: string;
  abc: "A" | "B" | "C";
  home: string;
  unit_cost: number;
  pick_min: number;
  pick_max: number;
  on_order: number;
  expiry_controlled: boolean;
  serial_controlled: boolean;
  on_hand: number;
  available: number;
  allocated: number;
  atp: number;
  pick_face: number;
  reserve: number;
  on_hold: number;
}

export interface WmsStockRow {
  sku: string;
  location: string;
  lot: string;
  expiry: string | null;
  status: string;
  lpn: string | null;
  qty: number;
  allocated: number;
}

export interface WmsTxn {
  txn_id: number;
  tick: number;
  type: string;
  sku: string;
  qty: number;
  from_loc: string | null;
  to_loc: string | null;
  lot: string | null;
  lpn: string | null;
  status: string | null;
  reason: string | null;
  ref: string | null;
  user: string;
  serials: string[];
}

export interface WmsItemDetail extends WmsItemRow {
  item: {
    case_gtin: string;
    case_qty: number;
    pallet_cases: number;
    weight_kg: number;
    shelf_life_days: number | null;
    supplier_id: string;
  };
  supplier: { supplier_id: string; name: string; lead_time_hours: number[] };
  demand_per_hour: number;
  reorder_point: number;
  order_up_to: number;
  stock: WmsStockRow[];
  allocations: { order_id: string; location: string; lot: string; qty: number; picked: number }[];
  purchase_orders: { po_id: string; status: string; eta: number; qty: number; received: number }[];
  serials_in_stock: number;
  serial_sample: string[];
  transactions: WmsTxn[];
}

export interface WmsLocation {
  code: string;
  type: string;
  zone: string | null;
  level: number;
  capacity: number | null;
  sku: string | null;
  blocked: boolean;
  check: string;
  units?: number;
  stock?: WmsStockRow[];
}

export interface WmsPlate {
  sscc: string;
  sku: string;
  qty: number;
  lot: string;
  expiry: string | null;
  received: boolean;
}

export interface WmsPurchaseOrder {
  po_id: string;
  supplier_id: string;
  supplier: string;
  created: number;
  eta: number;
  status: string;
  dock: string | null;
  arrived: number | null;
  lines: { sku: string; qty: number; received: number; damaged: number }[];
  asn: WmsPlate[];
  plates_received: number;
}

export interface WmsCount {
  count_id: string;
  location: string;
  sku: string;
  reason: string;
  created: number;
  status: string;
  expected: number | null;
  counted: number | null;
  variance: number | null;
  counter: string | null;
  recount_of: string | null;
  value: number | null;
  decided_by: string | null;
}

export interface WmsTask {
  task_id: string;
  type: string;
  created: number;
  data: Record<string, unknown>;
  status: string;
  assignee: string | null;
  result: string | null;
  priority: number;
}

export interface WmsScanResult {
  scan: {
    raw: string;
    kind: string;
    gtin?: string;
    sscc?: string;
    lot?: string;
    expiry?: string;
    serial?: string;
    quantity?: number;
    code?: string;
    errors?: string[];
  };
  item?: WmsItemRow | null;
  unit?: string;
  location?: WmsLocation | null;
  plate?: {
    sscc: string;
    stock: WmsStockRow[];
    asn: (WmsPlate & { po_id: string; dock: string | null; status: string }) | null;
  };
  putaway_suggestion?: [string, number][];
}

type Params = Record<string, string | number | boolean | null | undefined>;

const post = (body: unknown): RequestInit => ({ method: "POST", body: JSON.stringify(body) });

function query(params: Params): string {
  const q = new URLSearchParams();
  for (const [k, v] of Object.entries(params)) if (v !== null && v !== undefined && v !== "") q.set(k, String(v));
  const s = q.toString();
  return s ? `?${s}` : "";
}

export const wms = {
  kpis: () => request<WmsKpis>("/wms/kpis"),
  alerts: () => request<WmsAlert[]>("/wms/alerts"),
  reasons: () => request<Record<string, string>>("/wms/reasons"),
  items: (p: Params) => request<{ total: number; items: WmsItemRow[] }>(`/wms/items${query(p)}`),
  item: (sku: string) => request<WmsItemDetail>(`/wms/items/${encodeURIComponent(sku)}`),
  locations: (p: Params) => request<{ total: number; locations: WmsLocation[] }>(`/wms/locations${query(p)}`),
  location: (code: string) => request<WmsLocation>(`/wms/locations/${encodeURIComponent(code)}`),
  transactions: (p: Params) => request<WmsTxn[]>(`/wms/transactions${query(p)}`),
  scan: (code: string) => request<WmsScanResult>("/wms/scan", post({ code })),
  purchaseOrders: (status?: string) => request<WmsPurchaseOrder[]>(`/wms/purchase-orders${query({ status })}`),
  receive: (b: {
    po_id: string;
    sscc: string;
    qty?: number | null;
    damaged?: number;
    lot?: string | null;
    expiry?: string | null;
    user: string;
  }) => request<{ result: string; putaway_suggestion: [string, number][] }>("/wms/receive", post(b)),
  putaway: (b: { sscc: string; location: string; user: string }) =>
    request<{ moved: number; to: string; left_on_plate: number }>("/wms/putaway", post(b)),
  move: (b: { sku: string; qty: number; from_location: string; to_location: string; lot: string; user: string }) =>
    request<WmsTxn>("/wms/moves", post(b)),
  adjust: (b: { sku: string; location: string; lot: string; delta: number; reason: string; user: string }) =>
    request<WmsTxn>("/wms/adjustments", post(b)),
  hold: (b: { sku: string; lot?: string | null; reason: string; release: boolean; user: string }) =>
    request<{ units: number; action: string }>("/wms/holds", post(b)),
  counts: (status?: string) => request<WmsCount[]>(`/wms/counts${query({ status })}`),
  createCount: (location: string) => request<WmsCount>("/wms/counts", post({ location })),
  submitCount: (id: string, counted: number, user: string) =>
    request<WmsCount>(`/wms/counts/${id}/submit`, post({ counted, user })),
  decideCount: (id: string, approve: boolean, user: string) =>
    request<WmsCount>(`/wms/counts/${id}/decide`, post({ approve, user })),
  tasks: () =>
    request<{ tasks: WmsTask[]; associates: { name: string; task: string | null; until: number }[] }>("/wms/tasks"),
  settings: () => request<{ auto_tasks: Record<string, boolean> }>("/wms/settings"),
  setAutoTasks: (auto_tasks: Record<string, boolean>) =>
    request<{ auto_tasks: Record<string, boolean> }>("/wms/settings", {
      method: "PUT",
      body: JSON.stringify({ auto_tasks }),
    }),
  barcodeUrl: (kind: "ean13" | "code128" | "gs1-128", value: string) =>
    `${API_URL}/wms/barcode.svg${query({ kind, value })}`,
  labelUrl: (path: string) => `${API_URL}/wms/labels/${path}`,
  /** Labels are protected: fetched with the token and opened as a PDF in a new tab. */
  openLabel: (path: string) => openProtected(`${API_URL}/wms/labels/${path}`),
};
