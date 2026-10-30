"use client";

import { useSim } from "@/lib/store";
import { isAbnormal, isActive, needsAttention } from "@/lib/status";

const pad = (n: number) => String(n).padStart(2, "0");

/** Live status bar shown on every screen (UI/UX brief §5). */
export function StatusBar() {
  const state = useSim((s) => s.state);
  const connected = useSim((s) => s.connected);
  const robots = state?.robots ?? [];
  const pending = state?.orders.filter((o) => o.status === "PENDING").length ?? 0;
  const health = useSim((s) => s.predictions?.robots);
  const alerts = robots.filter((r) => needsAttention(r) || isAbnormal(r.robot_id, health)).length;
  const clock = state?.clock;

  return (
    <div className="flex h-8 items-center gap-6 border-b border-border bg-surface/60 px-6 text-xs text-muted">
      {!connected && <span className="text-warning">Reconnecting…</span>}
      <span>
        Robots{" "}
        <b className="tabular text-ink">
          {robots.filter(isActive).length}/{robots.length}
        </b>{" "}
        active
      </span>
      <span>
        Orders <b className="tabular text-ink">{pending}</b> pending
      </span>
      <span
        className={alerts ? "text-danger" : ""}
        title="Faulted, paused, below 20% battery, or flagged abnormal by the anomaly model"
      >
        Alerts <b className="tabular">{alerts}</b>
      </span>
      <span className="ml-auto font-mono">
        {clock && (
          <span className="mr-4 text-ink" title="Simulated time">
            Day {clock.day} · {pad(clock.hour)}:{pad(clock.minute)}
          </span>
        )}
        tick {state?.time ?? 0}
      </span>
    </div>
  );
}
