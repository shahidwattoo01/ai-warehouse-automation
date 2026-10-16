"use client";

import dynamic from "next/dynamic";
import { Screen } from "@/components/layout/Screen";
import { api } from "@/lib/api";
import { useSim } from "@/lib/store";

const WarehouseScene = dynamic(() => import("@/components/three/WarehouseScene").then((m) => m.WarehouseScene), { ssr: false });

export default function SimulationPage() {
  const { state, selectedRobot, selectRobot, tickInterval } = useSim();
  const robot = state?.robots.find((r) => r.robot_id === selectedRobot);

  return (
    <Screen title="Simulation">
      <div className="relative h-full min-h-[600px] rounded-card border border-border bg-surface p-1">
        <WarehouseScene />
        {robot && (
          <aside className="absolute right-4 top-4 w-72 rounded-card border border-border bg-surface/95 p-4 text-sm">
            <div className="flex items-center justify-between">
              <span className="font-mono font-semibold">{robot.robot_id}</span>
              <button onClick={() => selectRobot(null)} className="text-muted hover:text-ink" aria-label="Close">✕</button>
            </div>
            <dl className="mt-3 grid grid-cols-2 gap-y-1 text-muted">
              <dt>Status</dt><dd className="text-ink">{robot.status}</dd>
              <dt>Battery</dt><dd className="tabular text-ink">{robot.battery.toFixed(0)}%</dd>
              <dt>Position</dt><dd className="font-mono text-ink">({robot.position.join(", ")})</dd>
              <dt>Order</dt><dd className="font-mono text-ink">{robot.current_task ?? "—"}</dd>
              <dt>Destination</dt><dd className="text-ink">{robot.destination ?? "—"}</dd>
              <dt>Speed</dt>
              <dd className="tabular text-ink">
                {((robot.speed_cells_per_tick ?? 0) / Math.max(tickInterval, 0.05)).toFixed(1)} m/s
              </dd>
            </dl>
            <div className="mt-4 flex gap-2">
              <button onClick={() => api.robots.pause(robot.robot_id)} className="flex-1 rounded-control border border-border py-1.5 hover:bg-border/50">Pause</button>
              <button onClick={() => api.robots.resume(robot.robot_id)} className="flex-1 rounded-control border border-border py-1.5 hover:bg-border/50">Resume</button>
            </div>
          </aside>
        )}
      </div>
    </Screen>
  );
}
