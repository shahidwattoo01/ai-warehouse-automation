"use client";

import { useMemo, useState } from "react";
import { api } from "@/lib/api";
import { isAbnormal, needsAttention, STATUS_COLOR } from "@/lib/status";
import { useSim } from "@/lib/store";
import type { Robot } from "@/lib/types";

const NO_ROBOTS: Robot[] = []; // stable fallback: a fresh [] in a zustand selector re-renders forever

type Filter = "all" | "working" | "parked" | "charging" | "alerts";

type Health = Record<string, { abnormal: boolean; reason: string | null; score: number }> | undefined;

const FILTERS: { id: Filter; label: string; hint?: string; match: (r: Robot, h: Health) => boolean }[] = [
  { id: "all", label: "All", match: () => true },
  { id: "working", label: "Working", match: (r) => !!r.current_task },
  { id: "parked", label: "Parked", match: (r) => !r.current_task && r.destination_type === "PARKING" },
  {
    id: "charging",
    label: "Charging",
    hint: "Heading to or plugged into a charger",
    match: (r) => r.destination_type === "CHARGER",
  },
  {
    id: "alerts",
    label: "Alerts",
    hint: "Faulted, paused, battery below 20 % or flagged abnormal by the anomaly model",
    match: (r, h) => needsAttention(r) || isAbnormal(r.robot_id, h),
  },
];

const PRIORITY_DOT: Record<string, string> = { HIGH: "bg-danger", MEDIUM: "bg-warning", LOW: "bg-muted" };

/** "Moving" toward a charger reads as "To charger", so the Charging tab is self-explanatory. */
function statusLabel(r: Robot) {
  if (r.status === "MOVING" && r.destination_type === "CHARGER") return "To charger";
  return r.status.charAt(0) + r.status.slice(1).toLowerCase();
}

function robotNumber(id: string) {
  return Number(id.replace(/\D/g, "")) || 0;
}

/**
 * Live fleet table: every robot with its status, order, destination (rack location or station),
 * speed and battery, updated on every simulator tick. Clicking a row selects the robot, which
 * flies the 3D camera to it. `detailed` (Fleet page) adds position, load and pause/resume.
 */
export function FleetTable({ detailed = false }: { detailed?: boolean }) {
  const robots = useSim((s) => s.state?.robots ?? NO_ROBOTS);
  const tickInterval = useSim((s) => s.tickInterval);
  const selected = useSim((s) => s.selectedRobot);
  const selectRobot = useSim((s) => s.selectRobot);
  const health = useSim((s) => s.predictions?.robots);
  const [filter, setFilter] = useState<Filter>("all");
  const [busy, setBusy] = useState<string | null>(null);

  const command = async (robotId: string, action: "pause" | "resume") => {
    setBusy(robotId);
    try {
      await api.robots[action](robotId); // applied at the next tick
    } finally {
      setBusy(null);
    }
  };

  const counts = useMemo(
    () =>
      Object.fromEntries(FILTERS.map((f) => [f.id, robots.filter((r) => f.match(r, health)).length])) as Record<
        Filter,
        number
      >,
    [robots, health],
  );
  const rows = useMemo(() => {
    const match = FILTERS.find((f) => f.id === filter)!.match;
    return robots.filter((r) => match(r, health)).sort((a, b) => robotNumber(a.robot_id) - robotNumber(b.robot_id));
  }, [robots, filter, health]);

  return (
    <div className="flex h-full min-h-0 flex-col">
      <div className="flex items-center justify-between">
        <h2 className="text-base font-semibold">Fleet — live</h2>
        <span className="text-xs text-muted">{robots.length} robots</span>
      </div>

      <div className="mt-3 flex flex-wrap gap-1" role="tablist" aria-label="Filter robots">
        {FILTERS.map((f) => (
          <button
            key={f.id}
            role="tab"
            aria-selected={filter === f.id}
            onClick={() => setFilter(f.id)}
            title={f.hint}
            className={`rounded-control border px-2 py-0.5 text-xs ${
              filter === f.id ? "border-accent bg-accent/15 text-ink" : "border-border text-muted hover:text-ink"
            } ${f.id === "alerts" && counts.alerts > 0 ? "text-danger" : ""}`}
          >
            {f.label} <span className="tabular">{counts[f.id]}</span>
          </button>
        ))}
      </div>

      <div className="mt-3 min-h-0 flex-1 overflow-auto">
        <table className="w-full whitespace-nowrap text-left text-xs">
          <thead className="sticky top-0 bg-surface text-muted">
            <tr>
              <th className="py-1.5 pr-2 font-medium">Robot</th>
              <th className="py-1.5 pr-2 font-medium">Status</th>
              {detailed && <th className="py-1.5 pr-2 font-medium">Position</th>}
              <th className="py-1.5 pr-2 font-medium">Order</th>
              <th className="py-1.5 pr-2 font-medium">Destination</th>
              <th className="py-1.5 pr-2 text-right font-medium">Speed m/s</th>
              <th className="py-1.5 pr-2 font-medium">Battery</th>
              <th className="py-1.5 pr-2 font-medium" title="Anomaly model: last 20 ticks of telemetry">
                Health (AI)
              </th>
              {detailed && <th className="py-1.5 pr-2 text-right font-medium">Totes</th>}
              {detailed && <th className="py-1.5 text-right font-medium">Control</th>}
            </tr>
          </thead>
          <tbody>
            {rows.map((r) => {
              const speed = (r.speed_cells_per_tick ?? 0) / Math.max(tickInterval, 0.05); // 1 cell = 1 m
              const color = STATUS_COLOR[r.status] ?? STATUS_COLOR.IDLE;
              const battColor = r.battery > 50 ? "bg-success" : r.battery > 20 ? "bg-warning" : "bg-danger";
              return (
                <tr
                  key={r.robot_id}
                  onClick={() => selectRobot(selected === r.robot_id ? null : r.robot_id)}
                  className={`cursor-pointer border-t border-border/60 hover:bg-border/40 ${
                    selected === r.robot_id ? "bg-accent/10" : ""
                  }`}
                >
                  <td className="py-1.5 pr-2 font-mono font-semibold">{r.robot_id}</td>
                  <td className="py-1.5 pr-2">
                    <span className="inline-flex items-center gap-1.5">
                      <span className="h-2 w-2 rounded-full" style={{ background: color }} />
                      {statusLabel(r)}
                      {r.safety === "ESTOP" && (
                        <span className="rounded bg-red-600 px-1 text-[10px] font-bold text-white">E-STOP</span>
                      )}
                      {r.safety === "SLOW" && (
                        <span
                          className="rounded bg-warning/20 px-1 text-[10px] text-warning"
                          title="Half speed near a person"
                        >
                          slow
                        </span>
                      )}
                    </span>
                  </td>
                  {detailed && <td className="tabular py-1.5 pr-2 font-mono text-muted">({r.position.join(", ")})</td>}
                  <td className="py-1.5 pr-2 font-mono">
                    {r.current_task ? (
                      <span className="inline-flex items-center gap-1.5">
                        <span
                          className={`h-1.5 w-1.5 rounded-full ${PRIORITY_DOT[r.order_priority ?? "LOW"]}`}
                          title={`${r.order_priority} priority`}
                        />
                        {r.current_task}
                      </span>
                    ) : (
                      <span className="text-muted">—</span>
                    )}
                  </td>
                  <td className="py-1.5 pr-2">
                    {r.destination ?? "—"}
                    {(r.items_left ?? 0) > 1 && <span className="text-muted"> +{(r.items_left ?? 1) - 1}</span>}
                  </td>
                  <td className="tabular py-1.5 pr-2 text-right">
                    {speed > 0.05 ? speed.toFixed(1) : <span className="text-muted">0</span>}
                  </td>
                  <td className="py-1.5 pr-2">
                    <span className="inline-flex items-center gap-1.5">
                      <span className="h-1.5 w-8 overflow-hidden rounded-full bg-border">
                        <span className={`block h-full ${battColor}`} style={{ width: `${Math.max(2, r.battery)}%` }} />
                      </span>
                      <span className="tabular">{Math.round(r.battery)}%</span>
                    </span>
                  </td>
                  <td
                    className="py-1.5 pr-2"
                    title={health?.[r.robot_id] ? `anomaly score ${health[r.robot_id].score}` : undefined}
                  >
                    {!health?.[r.robot_id] ? (
                      <span className="text-muted">—</span>
                    ) : health[r.robot_id].abnormal ? (
                      <span className="text-warning">⚠ {health[r.robot_id].reason}</span>
                    ) : (
                      <span className="text-success">Normal</span>
                    )}
                  </td>
                  {detailed && <td className="tabular py-1.5 pr-2 text-right">{r.load}</td>}
                  {detailed && (
                    <td className="py-1.5 text-right">
                      <button
                        disabled={busy === r.robot_id}
                        onClick={(e) => {
                          e.stopPropagation(); // don't also select the row
                          void command(r.robot_id, r.status === "PAUSED" ? "resume" : "pause");
                        }}
                        className="rounded-control border border-border px-2 py-0.5 hover:bg-border/50 disabled:opacity-50"
                      >
                        {r.status === "PAUSED" ? "Resume" : "Pause"}
                      </button>
                    </td>
                  )}
                </tr>
              );
            })}
            {rows.length === 0 && (
              <tr>
                <td colSpan={detailed ? 10 : 7} className="py-6 text-center text-muted">
                  No robots in this view.
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
}
