// Mirrors the backend warehouse_state and layout snapshot (TRD 4.2, Backend Schema §11).

export type RobotStatus =
  | "IDLE" | "MOVING" | "PICKING" | "DELIVERING" | "CHARGING" | "PAUSED" | "FAULT";

export interface Robot {
  robot_id: string;
  position: [number, number];
  battery: number;
  speed: number;
  status: RobotStatus;
  current_task: string | null;
  load: number;
  route: [number, number][];
  heading: number;
  /** Live activity (engine._robot_activity). */
  destination?: string;
  destination_type?: "SHELF" | "PACKING" | "CHARGER" | "PARKING";
  order_priority?: "LOW" | "MEDIUM" | "HIGH" | null;
  items_left?: number;
  /** Average cells moved per tick over the last few ticks (1 cell = 1 m). */
  speed_cells_per_tick?: number;
}

export type Priority = "LOW" | "MEDIUM" | "HIGH";

export interface Order {
  order_id: string;
  priority: Priority;
  status: "PENDING" | "ASSIGNED" | "IN_PROGRESS" | "DELIVERED" | "LATE" | "CANCELLED";
  order_time: number;
  deadline: number;
  assigned_robot: string | null;
  items: { product_id: string; quantity: number }[];
  /** Packing station the order goes to. */
  destination: string | null;
  /** GENERATOR = simulated customer demand, MANUAL = created by an operator. */
  source: "GENERATOR" | "MANUAL";
  manual_assignment: boolean;
}

export interface InventoryItem {
  product_id: string;
  name: string;
  category: string;
  weight_kg: number;
  location: string; // rack location Zone-Row-Bay, e.g. "A-05-12"
  shelf_id: string;
  pick_face: { x: number; y: number };
  stock: number;
  restocking: boolean; // a replenishment is on its way
}

export interface Station {
  station_id: string;
  type: "PACKING" | "CHARGING";
  x: number;
  y: number;
  capacity: number;
  queue: number;
}

export interface Shelf {
  shelf_id: string;
  zone_id: string;
  x: number;
  y: number;
  levels: number;
}

export interface Zone {
  zone_id: string;
  name: string;
  bounds: [number, number, number, number];
  capacity: number;
}

export interface WarehouseState {
  time: number;
  running: boolean;
  /** auto: the dispatcher assigns waiting orders; manual: an operator does. */
  assignment_mode?: "auto" | "manual";
  robots: Robot[];
  orders: Order[];
  inventory: { product_id: string; stock: number }[];
  /** WORKER (associate), PACKAGE (dropped parcel), DEBRIS (fallen pallet). */
  obstacles: { position: [number, number]; type: string; obstacle_id?: string | null }[];
  /** Aisles closed for maintenance, a spill or an inspection (no robot enters them). */
  closures?: Closure[];
  stations: Station[];
  congestion: Record<string, number>;
  kpis?: Kpis;
  clock?: SimClock;
}

/** Live operational KPIs (simulation/environment/kpis.py). */
export interface Kpis {
  orders_created: number;
  orders_completed: number;
  late_percent: number;
  avg_completion_ticks: number | null;
  throughput_per_hour: number;
  utilisation_percent: number;
}

/** Simulated wall clock; seconds_per_tick converts tick counts to simulated time. */
export interface SimClock {
  day: number;
  hour: number;
  minute: number;
  seconds_per_tick: number;
}

export interface Closure {
  hazard_id: string;
  aisle_id: string;
  name: string;
  reason: string;
  cells: [number, number][];
  until: number;
}

export interface AisleSnapshot {
  aisle_id: string;
  name: string;
  zone_id: string | null;
  y: number;
  x_start: number;
  x_end: number;
  direction: "east" | "west";
}

export interface LayoutSnapshot {
  name: string;
  width: number;
  height: number;
  zones: Zone[];
  shelves: Shelf[];
  stations: Station[];
  blocked: [number, number][];
  /** Narrow one-way aisle segments (large layout); drawn as floor arrows. */
  one_way?: { y: number; x_start: number; x_end: number; dir: "east" | "west" }[];
  /** Dedicated robot parking areas (large layout); drawn as painted bays. */
  parking_areas?: ParkingAreaSnapshot[];
  /** Numbered picking aisles ("Aisle 7"), the same segments as one_way. */
  aisles?: AisleSnapshot[];
}

export interface ParkingAreaSnapshot {
  area_id: string; // P1 ... P8
  name: string; // e.g. "North-west"
  cells: [number, number][];
}

/** Live Phase 3 predictions (apps/backend/app/services/predictor.py). */
export interface OrderPrediction {
  eta_tick?: number; // predicted delivery tick
  eta_ticks?: number; // predicted ticks from assignment to delivery
  late_risk?: number; // probability of missing the deadline
  late_flag?: boolean; // risk above the tuned threshold
}

export interface RobotHealth {
  score: number; // anomaly probability
  abnormal: boolean;
  reason: string | null;
  since: number;
}

export interface PrecisionRecall {
  precision: number | null;
  recall: number | null;
  n: number;
}

export interface Predictions {
  models: string[];
  orders: Record<string, OrderPrediction>;
  robots: Record<string, RobotHealth>;
  demand: {
    hour: number;
    forecast: number | null;
    so_far: number;
    history: { hour: number; forecast: number | null; actual: number }[];
    /** Order lines per storage zone (ZONE_A..D) and orders per priority, this hour. */
    zones?: Record<string, { forecast: number | null; so_far: number }>;
    priorities?: Record<string, { forecast: number | null; so_far: number }>;
  };
  /** Algorithm chosen in each notebook (e.g. "XGBoost"). */
  algorithms?: Record<string, string | null>;
  live_accuracy: {
    eta_mae: number | null;
    eta_n: number;
    late: PrecisionRecall;
    demand_mae: number | null;
    anomaly: PrecisionRecall;
  };
  test_scores: {
    eta_mae?: number | null;
    late?: { precision: number; recall: number; F1: number } | null;
    demand_mae?: number | null;
    anomaly?: { precision: number; recall: number; F1: number } | null;
  };
}

/** Phase 4 decision rules in use (ai/optimization/optimizer.py). */
export interface Strategy {
  preset: string | null; // experiment preset (E1-E5) or null for a custom mix
  assignment: "nearest" | "random" | "eta" | "global";
  planner: "bfs" | "dijkstra" | "astar";
  traffic_aware: boolean;
  positioning: "balanced" | "demand";
  charging: "threshold" | "predictive";
  replanning: boolean;
}

export interface StrategyPresets {
  preset: string | null;
  strategies: Omit<Strategy, "preset">;
  presets: Record<string, { name: string; description: string }>;
}

/** Results of scripts/run_experiments.py (GET /analytics/experiments). */
export interface ExperimentResults {
  manifest: {
    created_utc: string;
    seeds: number;
    hours: number;
    baseline: string;
    experiments: Record<string, { name: string; strategies: Record<string, string | boolean> }>;
  };
  results: Record<string, Record<string, { mean: number; std: number }>>;
  vs_baseline: {
    experiment: string;
    kpi: string;
    baseline_mean: number;
    experiment_mean: number;
    change: number;
    change_percent: number | null;
    seeds_improved: string;
  }[];
}

export type StreamMessage =
  | { type: "layout"; layout: LayoutSnapshot }
  | { type: "tick"; state: WarehouseState; predictions?: Predictions; strategy?: Strategy; events: unknown[] };

/** Phase 5 object detector (apps/backend/app/api/v1/vision.py). */
export interface VisionStatus {
  available: boolean;
  loaded: boolean;
  model: string;
  algorithm: string | null;
  classes: string[] | null;
  safety_classes: string[];
  thresholds: Record<string, number>;
  image_size: number;
  test: { precision: number | null; recall: number | null; mAP50: number | null; mAP50_95: number | null };
  test_960_gpu: { precision: number; recall: number; mAP50: number; mAP50_95: number } | null;
}

export interface Detection {
  cls: string;
  conf: number;
  safety: boolean;
  box: [number, number, number, number]; // x1, y1, x2, y2 in image pixels
}

export interface DetectionResult {
  width: number;
  height: number;
  inference_ms: number;
  detections: Detection[];
  counts: Record<string, number>;
  safety_alerts: Detection[];
}

/** Operator copilot (Phase 6, apps/backend/app/api/v1/copilot.py). */
export interface CopilotEntity {
  type: string;
  text: string;
  value: string;
  start: number;
  end: number;
}

export interface ToolCall {
  name: string;
  arguments: Record<string, unknown>;
}

export interface Understanding {
  text: string;
  intent: string;
  confidence: number;
  entities: CopilotEntity[];
  tool_calls: ToolCall[];
  requires_approval: boolean;
  status: "ok" | "needs_information" | "unsure" | "out_of_scope";
  question: string | null;
}

export interface CopilotReply {
  understanding: Understanding;
  problems: string[];
  action: { id: string; summary: string; unsure: boolean } | null;
  answer: string | null;
}

export interface CopilotStatus {
  loaded: boolean;
  algorithm: string | null;
  intents: string[];
  write_actions_need_approval: boolean;
}

export interface CopilotHistoryItem {
  tick: number;
  text: string;
  tool_calls: ToolCall[];
  outcome: string;
}
