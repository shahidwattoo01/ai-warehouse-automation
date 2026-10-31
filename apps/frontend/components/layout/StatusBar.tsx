"use client";

import Link from "next/link";
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
  const centre = useSim((s) => s.alerts);
  // The alert centre's active incidents; before its first summary, the robots needing attention.
  const alerts = centre
    ? centre.open + centre.acknowledged
    : robots.filter((r) => needsAttention(r) || isAbnormal(r.robot_id, health)).length;
  const urgent = centre ? centre.critical > 0 || centre.escalated > 0 : alerts > 0;
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
      <Link
        href="/alerts"
        className={`hover:underline ${urgent ? "text-danger" : alerts ? "text-warning" : ""}`}
        title={
          centre
            ? `${centre.open} open, ${centre.acknowledged} acknowledged, ${centre.critical} critical, ${centre.escalated} escalated`
            : "Robots needing attention"
        }
      >
        Alerts <b className="tabular">{alerts}</b>
        {centre?.escalated ? <span className="ml-1">({centre.escalated} escalated)</span> : null}
      </Link>
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
