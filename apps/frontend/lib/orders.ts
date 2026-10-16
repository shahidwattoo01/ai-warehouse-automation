import type { Order, Robot } from "./types";

/** Rack cell of a product: "P-A-05-12" is zone A, row y=5, bay x=12. */
export function rackCell(productId: string): [number, number] | null {
  const m = /^P-[A-Z]-(\d+)-(\d+)$/.exec(productId);
  return m ? [Number(m[2]), Number(m[1])] : null;
}

/** Rack location label used across the UI, e.g. "A-05-12". */
export function rackLabel(productId: string): string {
  return productId.replace(/^P-/, "");
}

export const LOW_BATTERY = 20; // configs/simulation.yaml battery.low_threshold

/** Mirrors engine.can_take_order: why a robot cannot take an order now (null = it can). */
export function unavailableReason(r: Robot): string | null {
  if (r.status === "PAUSED" || r.status === "FAULT") return r.status.toLowerCase();
  if (r.current_task) return `on ${r.current_task}`;
  if (r.destination_type === "CHARGER") return "charging";
  if (r.battery < LOW_BATTERY) return "battery low";
  return null;
}

export interface RobotOption {
  robot: Robot;
  distance: number | null; // metres to the first pick (Manhattan, 1 cell = 1 m)
  reason: string | null;
}

/** All robots for an assignment menu: free ones first, nearest to the order's first rack first. */
export function robotOptions(robots: Robot[], order?: Pick<Order, "items"> | null): RobotOption[] {
  const target = order?.items[0] ? rackCell(order.items[0].product_id) : null;
  return robots
    .map((robot) => ({
      robot,
      reason: unavailableReason(robot),
      distance: target ? Math.abs(robot.position[0] - target[0]) + Math.abs(robot.position[1] - target[1]) : null,
    }))
    .sort((a, b) => Number(!!a.reason) - Number(!!b.reason) || (a.distance ?? 0) - (b.distance ?? 0));
}

export const PRIORITY_STYLE: Record<string, string> = {
  HIGH: "border-danger/50 bg-danger/15 text-danger",
  MEDIUM: "border-warning/50 bg-warning/15 text-warning",
  LOW: "border-border bg-border/40 text-muted",
};

/** Simulated time for a tick count; secondsPerTick comes from state.clock (1 by default). */
export function simDuration(ticks: number, secondsPerTick = 1): string {
  const s = Math.max(0, Math.round(ticks * secondsPerTick));
  return s >= 60 ? `${Math.floor(s / 60)}m ${String(s % 60).padStart(2, "0")}s` : `${s}s`;
}
