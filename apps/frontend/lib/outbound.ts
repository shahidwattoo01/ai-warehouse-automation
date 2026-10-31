// Outbound (WMS): customer orders, packing, loading and carrier departures
// (backend: wms/outbound.py, /api/v1/wms/outbound/...).

import { API_URL, request } from "./api";
import { downloadProtected, openProtected } from "./auth";

export type OrderStatus =
  | "WAITING_STOCK"
  | "READY"
  | "ON_HOLD"
  | "RELEASED"
  | "PICKING"
  | "AT_PACK"
  | "PACKED"
  | "LOADED"
  | "SHIPPED"
  | "CANCELLED";

export const PIPELINE: [OrderStatus, string][] = [
  ["WAITING_STOCK", "Waiting stock"],
  ["ON_HOLD", "On hold"],
  ["READY", "Ready (next wave)"],
  ["RELEASED", "Released"],
  ["PICKING", "Picking"],
  ["AT_PACK", "At packing"],
  ["PACKED", "Packed"],
  ["LOADED", "Loaded"],
  ["SHIPPED", "Shipped"],
  ["CANCELLED", "Cancelled"],
];

export interface CustomerOrderRow {
  order_id: string;
  status: OrderStatus;
  priority: "HIGH" | "MEDIUM" | "LOW";
  source: string;
  customer_id: string;
  customer: string;
  city: string;
  carrier: string;
  service: string;
  created_at: string;
  pick_by_at: string;
  departure: number;
  departure_at: string;
  promised_at: string;
  minutes_to_cutoff: number;
  units: number;
  lines: number;
  cartons: number;
  hold_reason: string | null;
  partial: boolean;
  backordered: number;
  missed: number;
  parent: string | null;
  wave: string | null;
  station: string | null;
  shipped_at: string | null;
  on_time: boolean | null;
}

export interface Carton {
  sscc: string;
  order_id: string;
  carrier: string;
  size: string;
  seq: number;
  of: number;
  contents: { sku: string; lot: string; qty: number }[];
  weight_kg: number;
  scale_kg: number;
  check: "PASS" | "FAIL" | "AUDITED";
  tracking: string;
  location: string;
  status: "PACKED" | "IN_LANE" | "LOADED" | "SHIPPED" | "CANCELLED";
  packed_by: string | null;
  packed_at_time: string | null;
  loaded_at_time: string | null;
  trip: string | null;
}

export interface Backorder {
  bo_id: string;
  order_id: string;
  customer_id: string;
  priority: string;
  sku: string;
  qty: number;
  created: number;
  status: "OPEN" | "RELEASED" | "CANCELLED";
  child: string | null;
}

export interface CustomerOrderDetail extends CustomerOrderRow {
  customer_detail: {
    name: string;
    kind: string;
    address: string;
    city: string;
    postal_code: string;
    allow_partial: boolean;
  };
  carrier_detail: { name: string; service: string; door: string; departures: number[] };
  order_lines: {
    line: number;
    sku: string;
    ordered: number;
    allocated: number;
    picked: number;
    short: number;
    backordered: number;
    shipped: number;
  }[];
  carton_detail: Carton[];
  backorders: Backorder[];
  cancel_reason: string | null;
  history: { tick: number; time: string; event: string; user: string; note: string | null }[];
  robot: string | null;
  robot_status: string | null;
}

export interface Trip {
  trip_id: string;
  carrier: string;
  carrier_name: string;
  service: string;
  door: string;
  departs: number;
  departs_at: string;
  cutoff_at: string;
  minutes_to_departure: number;
  status: "SCHEDULED" | "DEPARTED";
  cartons_loaded: number;
  orders_on_board: number;
  orders_late: number;
  orders_waiting: number;
  shipped_units: number;
  weight_kg: number;
}

export interface TripManifest extends Trip {
  manifest: {
    sscc: string;
    tracking: string;
    order_id: string;
    customer: string | null;
    city: string | null;
    weight_kg: number;
    units: number;
  }[];
}

export interface Wave {
  wave_id: string;
  time: string;
  orders: string[];
  units: number;
  departures: string[];
}

export interface OutboundKpis {
  next_truck: {
    trip_id: string;
    carrier: string;
    service: string;
    departs_at: string;
    minutes: number;
    cartons_loaded: number;
  } | null;
  release_mode: "continuous" | "wave";
  orders_by_status: Partial<Record<OrderStatus, number>>;
  orders_on_hold: number;
  pack_queue: number;
  cartons_in_lanes: number;
  cartons_loaded: number;
  orders_shipped: number;
  units_shipped: number;
  on_time_ship_rate: number | null;
  missed_trucks: number;
  cartons_packed: number;
  weight_check_failures: number;
  backorders_open: number;
  units_backordered: number;
  orders_cancelled: number;
  order_to_ship_minutes: number | null;
  waves: number;
}

export interface OutboundSettings {
  auto_tasks: Record<string, boolean>;
  release_mode: "continuous" | "wave";
  wave_minutes: number;
}

const post = (body?: unknown): RequestInit => ({
  method: "POST",
  body: body === undefined ? undefined : JSON.stringify(body),
});
const order = (id: string) => `/wms/outbound/orders/${encodeURIComponent(id)}`;

export const outbound = {
  kpis: () => request<{ outbound: OutboundKpis }>("/wms/kpis").then((k) => k.outbound),
  orders: (status?: string, q?: string) => {
    const p = new URLSearchParams();
    if (status) p.set("status", status);
    if (q) p.set("q", q);
    return request<{ orders: CustomerOrderRow[]; total: number; by_status: Record<string, number> }>(
      `/wms/outbound/orders?${p}`,
    );
  },
  order: (id: string) => request<CustomerOrderDetail>(order(id)),
  hold: (id: string, reason: string) => request<CustomerOrderRow>(`${order(id)}/hold`, post({ reason })),
  releaseHold: (id: string) => request<CustomerOrderRow>(`${order(id)}/release-hold`, post()),
  release: (id: string) => request<CustomerOrderRow>(`${order(id)}/release`, post()),
  shipPartial: (id: string) => request<CustomerOrderRow>(`${order(id)}/ship-partial`, post()),
  cancel: (id: string, reason: string) => request<CustomerOrderRow>(`${order(id)}/cancel`, post({ reason })),
  pack: (order_id: string) => request<{ cartons: Carton[] }>("/wms/outbound/pack", post({ order_id })),
  audit: (sscc: string) => request<Carton>("/wms/outbound/audit", post({ sscc })),
  load: (sscc: string) => request<Carton>("/wms/outbound/load", post({ sscc })),
  cartons: (status?: string) => request<Carton[]>(`/wms/outbound/cartons${status ? `?status=${status}` : ""}`),
  trips: () => request<Trip[]>("/wms/outbound/trips"),
  trip: (id: string) => request<TripManifest>(`/wms/outbound/trips/${encodeURIComponent(id)}`),
  waves: () => request<Wave[]>("/wms/outbound/waves"),
  backorders: (status = "OPEN") => request<Backorder[]>(`/wms/outbound/backorders?status=${status}`),
  settings: () => request<OutboundSettings>("/wms/settings"),
  setSettings: (s: Partial<OutboundSettings>) =>
    request<OutboundSettings>("/wms/settings", { method: "PUT", body: JSON.stringify(s) }),
  openLabel: (sscc: string) => openProtected(`${API_URL}/wms/labels/shipping/${sscc}`),
  manifestPdf: (trip: string) =>
    openProtected(`${API_URL}/wms/outbound/trips/${encodeURIComponent(trip)}/manifest.pdf`),
  manifestCsv: (trip: string) =>
    downloadProtected(`${API_URL}/wms/outbound/trips/${encodeURIComponent(trip)}/manifest.csv`, `manifest-${trip}.csv`),
};
