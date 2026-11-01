"use client";

import { useCallback, useEffect, useState } from "react";
import { ErrorNote, Panel, td, th } from "@/components/wms/shared";
import { request } from "@/lib/api";

interface Person {
  associate: string;
  crew: string;
  pace: number;
  tasks: number;
  earned_hours: number;
  worked_hours: number;
  performance_percent: number | null;
  utilisation_percent: number | null;
  productivity_percent: number | null;
  top_tasks: Record<string, number>;
  busy_now: boolean;
}

interface Crew {
  crew: string;
  people: number;
  tasks: number;
  performance_percent: number | null;
  utilisation_percent: number | null;
}

interface Report {
  shift: number;
  current_shift: number;
  shift_hours: number;
  hours_elapsed: number;
  people: Person[];
  crews: Crew[];
  handover: { open_tasks: Record<string, number>; below_85_percent: string[]; in_progress: number };
  standards: { task: string; standard_minutes: number; note: string }[];
}

const CREW: Record<string, string> = { inbound: "Inbound", pack: "Packing", dock: "Dock" };

function Pct({ v, warnBelow }: { v: number | null; warnBelow?: number }) {
  if (v == null) return <span className="text-muted">—</span>;
  const tone = warnBelow != null && v < warnBelow ? "text-warning" : "";
  return <span className={`tabular-nums ${tone}`}>{v}%</span>;
}

/** Labour management: engineered standards, performance and utilisation per person and shift. */
export function Labour() {
  const [shift, setShift] = useState<number | null>(null);
  const [r, setR] = useState<Report | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [showStd, setShowStd] = useState(false);

  const load = useCallback(async () => {
    try {
      setR(await request<Report>(`/wms/labour${shift == null ? "" : `?shift=${shift}`}`));
      setError(null);
    } catch (e) {
      setError((e as Error).message);
    }
  }, [shift]);

  useEffect(() => {
    void load();
    const id = setInterval(load, 5000);
    return () => clearInterval(id);
  }, [load]);

  if (!r) return <ErrorNote text={error} />;
  const earlier = Array.from({ length: r.current_shift }, (_, i) => r.current_shift - 1 - i);
  const live = r.shift === r.current_shift;
  return (
    <div className="space-y-4">
      <ErrorNote text={error} />
      <Panel
        title={`Shift ${r.shift + 1} · ${live ? `${r.hours_elapsed} of ${r.shift_hours} h` : "complete"}`}
        actions={
          <div className="flex gap-1">
            <select
              value={shift ?? ""}
              onChange={(e) => setShift(e.target.value === "" ? null : Number(e.target.value))}
              className="rounded-control border border-border bg-canvas px-2 py-0.5 text-xs"
            >
              <option value="">current shift</option>
              {earlier.map((s) => (
                <option key={s} value={s}>
                  shift {s + 1}
                </option>
              ))}
            </select>
            <button
              onClick={() => setShowStd(!showStd)}
              className="rounded-control border border-border px-2 py-0.5 text-xs hover:border-accent"
            >
              {showStd ? "Hide standards" : "Standards"}
            </button>
          </div>
        }
      >
        <p className="mb-2 text-xs text-muted">
          Performance = earned standard time ÷ time spent on tasks (100 % = on standard). Utilisation = time on tasks ÷
          time in the shift. Each associate has a personal pace; the standard is what a trained person needs at a normal
          pace.
        </p>
        {showStd && (
          <table className="mb-3 w-full text-xs">
            <tbody>
              {r.standards.map((s) => (
                <tr key={s.task} className="border-t border-border">
                  <td className={`${td} font-mono`}>{s.task}</td>
                  <td className={`${td} tabular-nums`}>{s.standard_minutes} min</td>
                  <td className={`${td} text-muted`}>{s.note}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
        <div className="mb-3 grid gap-2 md:grid-cols-3">
          {r.crews.map((c) => (
            <div key={c.crew} className="rounded-card border border-border px-3 py-2 text-xs">
              <div className="font-semibold">
                {CREW[c.crew] ?? c.crew} · {c.people} people · {c.tasks} tasks
              </div>
              <div className="text-muted">
                performance <Pct v={c.performance_percent} warnBelow={85} /> · utilisation{" "}
                <Pct v={c.utilisation_percent} />
              </div>
            </div>
          ))}
        </div>
        <div className="overflow-x-auto">
          <table className="w-full whitespace-nowrap text-xs">
            <thead>
              <tr>
                <th className={th}>Associate</th>
                <th className={th}>Crew</th>
                <th className={th}>Tasks</th>
                <th className={th}>Earned h</th>
                <th className={th}>Worked h</th>
                <th className={th}>Performance</th>
                <th className={th}>Utilisation</th>
                <th className={th}>Productivity</th>
                <th className={th}>Mostly</th>
              </tr>
            </thead>
            <tbody>
              {r.people.map((p) => (
                <tr key={p.associate} className="border-t border-border">
                  <td className={`${td} font-mono font-semibold`}>
                    {p.associate}
                    {p.busy_now && <span className="ml-1 text-accent">●</span>}
                  </td>
                  <td className={td}>{CREW[p.crew] ?? p.crew}</td>
                  <td className={`${td} tabular-nums`}>{p.tasks}</td>
                  <td className={`${td} tabular-nums`}>{p.earned_hours}</td>
                  <td className={`${td} tabular-nums`}>{p.worked_hours}</td>
                  <td className={td}>
                    <Pct v={p.performance_percent} warnBelow={85} />
                  </td>
                  <td className={td}>
                    <Pct v={p.utilisation_percent} />
                  </td>
                  <td className={td}>
                    <Pct v={p.productivity_percent} />
                  </td>
                  <td className={`${td} text-muted`}>
                    {Object.entries(p.top_tasks)
                      .map(([t, n]) => `${t.toLowerCase()} ${n}`)
                      .join(", ")}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Panel>
      <Panel title="Shift handover">
        <div className="grid gap-3 text-xs md:grid-cols-3">
          <div>
            <div className="mb-1 text-muted">Open work for the next shift</div>
            {Object.keys(r.handover.open_tasks).length ? (
              Object.entries(r.handover.open_tasks).map(([t, n]) => (
                <div key={t}>
                  <span className="font-mono">{t.toLowerCase()}</span> {n}
                </div>
              ))
            ) : (
              <div>none</div>
            )}
          </div>
          <div>
            <div className="mb-1 text-muted">Below 85 % of standard (5+ tasks)</div>
            <div>{r.handover.below_85_percent.join(", ") || "nobody"}</div>
          </div>
          <div>
            <div className="mb-1 text-muted">Tasks in progress now</div>
            <div>{r.handover.in_progress}</div>
          </div>
        </div>
      </Panel>
    </div>
  );
}
