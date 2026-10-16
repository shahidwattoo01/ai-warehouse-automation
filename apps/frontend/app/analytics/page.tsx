"use client";

import { useEffect, useState } from "react";
import { Screen } from "@/components/layout/Screen";
import { api } from "@/lib/api";
import type { ExperimentResults } from "@/lib/types";

// KPI -> label and whether lower is better (matches scripts/run_experiments.py)
const KPIS: { key: string; label: string; lower: boolean; unit?: string }[] = [
  { key: "avg_completion_ticks", label: "Avg completion", lower: true, unit: "ticks" },
  { key: "p90_completion_ticks", label: "90th pct completion", lower: true, unit: "ticks" },
  { key: "late_percent", label: "Late orders", lower: true, unit: "%" },
  { key: "throughput_per_hour", label: "Throughput", lower: false, unit: "orders/h" },
  { key: "avg_queue_ticks", label: "Wait for a robot", lower: true, unit: "ticks" },
  { key: "distance_per_order_m", label: "Distance per order", lower: true, unit: "m" },
  { key: "blocked_events", label: "Standoffs", lower: true },
];

function Bars({ data, kpi, baseline }: { data: ExperimentResults; kpi: (typeof KPIS)[number]; baseline: string }) {
  const ids = Object.keys(data.results);
  const values = ids.map((id) => data.results[id][kpi.key]?.mean ?? 0);
  const max = Math.max(1e-9, ...values);
  const best = kpi.lower ? Math.min(...values) : Math.max(...values);
  return (
    <div className="rounded-card border border-border bg-surface p-4">
      <div className="mb-2 text-xs text-muted">
        {kpi.label} {kpi.unit && <span>({kpi.unit})</span>} · {kpi.lower ? "lower is better" : "higher is better"}
      </div>
      <div className="space-y-1.5">
        {ids.map((id, i) => (
          <div key={id} className="flex items-center gap-2 text-xs">
            <span className="w-9 shrink-0 font-mono">{id}</span>
            <span className="h-3 flex-1 overflow-hidden rounded bg-border/60">
              <span
                className={`block h-full ${id === baseline ? "bg-muted/60" : values[i] === best ? "bg-success/70" : "bg-accent/60"}`}
                style={{ width: `${(values[i] / max) * 100}%` }}
              />
            </span>
            <span className="tabular w-24 shrink-0 text-right">
              {values[i].toFixed(1)}
              <span className="text-muted"> ± {(data.results[id][kpi.key]?.std ?? 0).toFixed(1)}</span>
            </span>
          </div>
        ))}
      </div>
    </div>
  );
}

/** Phase 4 optimisation experiments: every strategy on the same orders, faults and hazards. */
export default function AnalyticsPage() {
  const [data, setData] = useState<ExperimentResults | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api.analytics.experiments().then(setData).catch((e) => setError(String(e.message ?? e)));
  }, []);

  return (
    <Screen title="Analytics · Optimisation experiments">
      {error && (
        <div className="rounded-card border border-border bg-surface p-4 text-sm text-muted">
          {error}. Run <code className="font-mono">python scripts/run_experiments.py</code> to create the results.
        </div>
      )}
      {data && (
        <div className="space-y-4">
          <p className="text-sm text-muted">
            {Object.keys(data.results).length} experiments × {data.manifest.seeds} seeds × {data.manifest.hours} simulated hours.
            Every experiment received exactly the same orders, faults and hazards, so differences come from the strategies.
            Baseline: <b className="text-ink">{data.manifest.baseline}</b> (today&apos;s rules). Green = best.
          </p>
          <div className="overflow-auto rounded-card border border-border bg-surface p-4">
            <table className="w-full whitespace-nowrap text-left text-xs">
              <thead className="text-muted">
                <tr>
                  <th className="py-1.5 pr-3 font-medium">Experiment</th>
                  {KPIS.map((k) => (
                    <th key={k.key} className="py-1.5 pr-3 text-right font-medium">
                      {k.label}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {Object.keys(data.results).map((id) => (
                  <tr key={id} className="border-t border-border/60">
                    <td className="py-1.5 pr-3">
                      <span className="font-mono font-semibold">{id}</span>{" "}
                      <span className="text-muted">{data.manifest.experiments[id]?.name}</span>
                    </td>
                    {KPIS.map((k) => {
                      const row = data.vs_baseline.find((r) => r.experiment === id && r.kpi === k.key);
                      const pct = row?.change_percent;
                      const good = pct != null && (k.lower ? pct < 0 : pct > 0);
                      return (
                        <td key={k.key} className="tabular py-1.5 pr-3 text-right">
                          {data.results[id][k.key]?.mean.toFixed(1)}
                          {pct != null && Math.abs(pct) >= 0.05 && (
                            <span className={`ml-1 ${good ? "text-success" : "text-danger"}`}>
                              {pct > 0 ? "+" : ""}
                              {pct.toFixed(1)}%
                            </span>
                          )}
                        </td>
                      );
                    })}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <div className="grid grid-cols-2 gap-4 xl:grid-cols-3">
            {KPIS.map((k) => (
              <Bars key={k.key} data={data} kpi={k} baseline={data.manifest.baseline} />
            ))}
          </div>
        </div>
      )}
    </Screen>
  );
}
