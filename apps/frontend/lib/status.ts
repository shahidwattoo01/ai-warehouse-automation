// Robot status -> colour for light bands, beacons and table dots (UI/UX brief §7).
export const STATUS_COLOR: Record<string, string> = {
  IDLE: "#8A96A8",
  MOVING: "#3B82F6",
  PICKING: "#3B82F6",
  DELIVERING: "#3B82F6",
  CHARGING: "#22C55E",
  PAUSED: "#F59E0B",
  FAULT: "#EF4444",
};

/** One definition of "active" and "needs attention" for every screen. */
export function isActive(r: { current_task: string | null; destination_type?: string }): boolean {
  return !!r.current_task || r.destination_type === "CHARGER";
}

export function needsAttention(r: { status: string; battery: number }): boolean {
  return r.status === "FAULT" || r.status === "PAUSED" || r.battery < 20;
}

/** The anomaly model flags this robot as behaving abnormally (Phase 3). */
export function isAbnormal(robotId: string, health?: Record<string, { abnormal: boolean }> | null): boolean {
  return !!health?.[robotId]?.abnormal;
}
