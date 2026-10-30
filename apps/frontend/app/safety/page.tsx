"use client";

import { OctagonX } from "lucide-react";
import { useCallback, useEffect, useState } from "react";
import { Screen } from "@/components/layout/Screen";
import { ErrorNote, Panel, button, input, td, th } from "@/components/wms/shared";
import { useCan } from "@/lib/auth";
import { safety, type SafetyEvent, type SafetyStatus } from "@/lib/safety";
import { useSim } from "@/lib/store";

const KINDS = [
  "ESTOP",
  "ESTOP_RELEASED",
  "ESTOP_RESET",
  "NEAR_MISS",
  "FLOOR_HAZARD",
  "AISLE_CLOSED",
  "ROBOT_FAULT",
  "SETTINGS",
];
const TONE = {
  critical: "bg-red-600/15 text-red-600",
  warning: "bg-warning/15 text-warning",
  info: "bg-border/70 text-muted",
};
const TICKS_PER_HOUR = 600;

function clock(tick: number): string {
  const h = tick / TICKS_PER_HOUR;
  return `Day ${Math.floor(h / 24) + 1} ${String(Math.floor(h % 24)).padStart(2, "0")}:${String(
    Math.floor((h % 1) * 60),
  ).padStart(2, "0")}`;
}

/** Fleet safety: emergency and zone stops, slow zones near people, and the safety event log. */
export default function SafetyPage() {
  const [status, setStatus] = useState<SafetyStatus | null>(null);
  const [events, setEvents] = useState<SafetyEvent[]>([]);
  const [kind, setKind] = useState("");
  const [zone, setZone] = useState("");
  const [reason, setReason] = useState("");
  const [error, setError] = useState<string | null>(null);
  const canReset = useCan("safety:reset");
  const live = useSim((s) => s.state?.safety?.state);

  const load = useCallback(async () => {
    try {
      const [s, e] = await Promise.all([safety.status(), safety.events(kind || undefined)]);
      setStatus(s);
      setEvents(e);
      setError(null);
    } catch (err) {
      setError((err as Error).message);
    }
  }, [kind]);

  useEffect(() => {
    void load();
    const id = setInterval(load, 3000);
    return () => clearInterval(id);
  }, [load, live]);

  const run = async (call: () => Promise<unknown>) => {
    try {
      await call();
      await load();
    } catch (err) {
      setError((err as Error).message);
    }
  };

  return (
    <Screen title="Safety">
      <ErrorNote text={error} />
      {status && (
        <div className="space-y-4">
          <div className="grid grid-cols-2 gap-2 md:grid-cols-5">
            <Stat
              label="Fleet"
              value={status.state === "NORMAL" ? "Running" : status.state === "ESTOP" ? "STOPPED" : "Awaiting reset"}
              alert={status.state !== "NORMAL"}
            />
            <Stat label="Emergency stops" value={status.metrics.estops ?? 0} />
            <Stat
              label="Near misses"
              value={status.metrics.near_misses ?? 0}
              alert={(status.metrics.near_misses ?? 0) > 0}
            />
            <Stat label="Robots slowed now" value={status.robots_slowed.length} />
            <Stat label="Floor hazards" value={status.metrics.FLOOR_HAZARD ?? 0} />
          </div>

          <div className="grid items-start gap-4 lg:grid-cols-2">
            <Panel title="Stop one zone">
              <p className="mb-2 text-xs text-muted">
                For work inside one zone (racking repair, a spill): robots in the zone hold, the others keep working but
                do not drive in. The red E-STOP button at the top stops the whole fleet. Release and reset work the same
                way for both.
              </p>
              <form
                className="flex flex-wrap gap-2"
                onSubmit={(e) => {
                  e.preventDefault();
                  void run(() => safety.estop(reason || "Zone stop", zone));
                }}
              >
                <select value={zone} onChange={(e) => setZone(e.target.value)} className={input} required>
                  <option value="">Zone…</option>
                  {status.zones.map((z) => (
                    <option key={z} value={z}>
                      {z.replace("ZONE_", "Zone ")}
                    </option>
                  ))}
                </select>
                <input
                  value={reason}
                  onChange={(e) => setReason(e.target.value)}
                  placeholder="Reason"
                  className={`${input} flex-1`}
                />
                <button className={`${button} flex items-center gap-1 bg-red-600`} disabled={!zone}>
                  <OctagonX size={14} /> Stop zone
                </button>
              </form>
              {status.state === "RELEASED" && status.blockers.length > 0 && (
                <p className="mt-2 text-xs text-warning">
                  Reset waits: a person is next to {status.blockers.join(", ")}.
                </p>
              )}
            </Panel>

            <Panel title="Slow zones near people">
              <p className="mb-2 text-xs text-muted">
                A robot within {status.slow_radius} m of a person drives at half speed. A moving robot within{" "}
                {status.near_miss_radius} m of a person is logged as a near miss.
              </p>
              <div className="flex flex-wrap items-center gap-3 text-sm">
                <label className="flex items-center gap-2">
                  <input
                    type="checkbox"
                    checked={status.slow_zones}
                    disabled={!canReset}
                    onChange={(e) => void run(() => safety.settings({ slow_zones: e.target.checked }))}
                  />
                  Slow zones on
                </label>
                <label className="flex items-center gap-2">
                  Radius
                  <select
                    value={status.slow_radius}
                    disabled={!canReset}
                    onChange={(e) => void run(() => safety.settings({ slow_radius: Number(e.target.value) }))}
                    className={input}
                  >
                    {[1, 2, 3, 4, 5].map((r) => (
                      <option key={r} value={r}>
                        {r} m
                      </option>
                    ))}
                  </select>
                </label>
              </div>
            </Panel>
          </div>

          <Panel
            title="Safety log"
            actions={
              <select value={kind} onChange={(e) => setKind(e.target.value)} className={input}>
                <option value="">All events</option>
                {KINDS.map((k) => (
                  <option key={k} value={k}>
                    {k.replaceAll("_", " ").toLowerCase()}
                  </option>
                ))}
              </select>
            }
          >
            <div className="max-h-[55vh] overflow-auto">
              <table className="w-full text-sm">
                <thead className="sticky top-0 bg-surface">
                  <tr>
                    <th className={th}>Time</th>
                    <th className={th}>Event</th>
                    <th className={th}>What happened</th>
                    <th className={th}>Robot</th>
                    <th className={th}>Where</th>
                    <th className={th}>By</th>
                  </tr>
                </thead>
                <tbody>
                  {events.map((e, i) => (
                    <tr key={`${e.tick}-${i}`} className="border-t border-border">
                      <td className={`${td} whitespace-nowrap text-xs`}>{clock(e.tick)}</td>
                      <td className={td}>
                        <span className={`rounded px-1.5 py-0.5 text-[11px] font-medium ${TONE[e.severity]}`}>
                          {e.kind.replaceAll("_", " ")}
                        </span>
                      </td>
                      <td className={td}>{e.text}</td>
                      <td className={`${td} font-mono text-xs`}>{e.robot_id ?? ""}</td>
                      <td className={`${td} text-xs`}>
                        {e.zone?.replace("ZONE_", "Zone ") ?? ""}
                        {e.x !== null && (
                          <span className="text-muted">
                            {" "}
                            ({e.x}, {e.y})
                          </span>
                        )}
                      </td>
                      <td className={`${td} text-xs`}>{e.user}</td>
                    </tr>
                  ))}
                  {!events.length && (
                    <tr>
                      <td colSpan={6} className={`${td} text-muted`}>
                        Nothing logged yet.
                      </td>
                    </tr>
                  )}
                </tbody>
              </table>
            </div>
          </Panel>

          <p className="text-xs text-muted">
            This is the supervisory (software) layer. Certified safety, the safety-rated stop circuits, personnel
            detection scanners and speed limits required by ISO 3691-4 and ANSI/RIA R15.08, lives in each robot and its
            controller and is not replaced by this page. See docs/safety.md.
          </p>
        </div>
      )}
    </Screen>
  );
}

function Stat({ label, value, alert = false }: { label: string; value: React.ReactNode; alert?: boolean }) {
  return (
    <div className="rounded-card border border-border bg-surface px-3 py-2">
      <div className="text-[11px] text-muted">{label}</div>
      <div className={`text-lg font-semibold ${alert ? "text-red-600" : ""}`}>{value}</div>
    </div>
  );
}
