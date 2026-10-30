"use client";

import { simDuration } from "@/lib/orders";
import { useSim } from "@/lib/store";
import type { Predictions } from "@/lib/types";

const pct = (v: number | null | undefined) => (v == null ? "—" : `${Math.round(v * 100)}%`);

function Card({ title, children, foot }: { title: string; children: React.ReactNode; foot?: React.ReactNode }) {
  return (
    <div className="flex flex-col rounded-card border border-border bg-surface p-4">
      <div className="text-xs text-muted">{title}</div>
      <div className="mt-1 flex-1">{children}</div>
      {foot && <div className="mt-2 border-t border-border/60 pt-2 text-[11px] text-muted">{foot}</div>}
    </div>
  );
}

/** Forecast vs actual orders for the last simulated hours (bars = actual, line marks = forecast). */
function DemandChart({ history }: { history: Predictions["demand"]["history"] }) {
  if (!history.length)
    return <div className="mt-3 text-xs text-muted">The chart fills in as simulated hours pass.</div>;
  const max = Math.max(1, ...history.flatMap((h) => [h.actual, h.forecast ?? 0]));
  const w = 100 / history.length;
  return (
    <svg
      viewBox="0 0 100 40"
      className="mt-2 h-16 w-full"
      preserveAspectRatio="none"
      role="img"
      aria-label="Forecast versus actual orders per hour"
    >
      {history.map((h, i) => {
        const ah = (h.actual / max) * 38;
        const fy = 40 - ((h.forecast ?? 0) / max) * 38;
        return (
          <g key={h.hour}>
            <rect x={i * w + w * 0.15} y={40 - ah} width={w * 0.7} height={ah} className="fill-accent/40" />
            {h.forecast != null && (
              <rect x={i * w + w * 0.05} y={fy - 0.6} width={w * 0.9} height={1.2} className="fill-ink" />
            )}
          </g>
        );
      })}
    </svg>
  );
}

/** Forecast for this hour per zone (order lines) and per priority (orders), with arrivals so far. */
function Breakdown({ demand }: { demand: Predictions["demand"] }) {
  const groups = [
    { title: "Order lines per zone", rows: demand.zones ?? {}, label: (k: string) => k.replace("ZONE_", "Zone ") },
    { title: "Orders per priority", rows: demand.priorities ?? {}, label: (k: string) => k },
  ];
  if (!Object.keys(groups[0].rows).length) return null;
  return (
    <div className="mt-4 grid grid-cols-2 gap-4 rounded-card border border-border bg-surface p-4">
      {groups.map((g) => {
        const max = Math.max(1, ...Object.values(g.rows).map((r) => r.forecast ?? 0));
        return (
          <div key={g.title}>
            <div className="mb-2 text-xs text-muted">
              {g.title} · forecast for this hour <span className="ml-1">(bar = forecast, number = arrived so far)</span>
            </div>
            <div className="space-y-1.5">
              {Object.entries(g.rows).map(([key, r]) => (
                <div key={key} className="flex items-center gap-2 text-xs">
                  <span className="w-16 shrink-0">{g.label(key)}</span>
                  <span className="h-3 flex-1 overflow-hidden rounded bg-border/60">
                    <span
                      className={`block h-full ${key === "HIGH" ? "bg-danger/70" : "bg-accent/60"}`}
                      style={{ width: `${Math.min(100, ((r.forecast ?? 0) / max) * 100)}%` }}
                    />
                  </span>
                  <span className="tabular w-24 shrink-0 text-right">
                    <b>{r.forecast != null ? Math.round(r.forecast) : "—"}</b>
                    <span className="text-muted"> · {r.so_far} so far</span>
                  </span>
                </div>
              ))}
            </div>
          </div>
        );
      })}
    </div>
  );
}

/**
 * Phase 3 on the dashboard: the four trained models running on the live simulation, with how
 * accurate each one is on this run (the simulator knows the truth) next to its offline test score.
 */
export function AiPanel() {
  const p = useSim((s) => s.predictions);
  const time = useSim((s) => s.state?.time ?? 0);
  const orders = useSim((s) => s.state?.orders);
  const secondsPerTick = useSim((s) => s.state?.clock?.seconds_per_tick ?? 1);

  if (!p || !p.models?.length) {
    return (
      <div className="rounded-card border border-border bg-surface p-4 text-sm text-muted">
        AI predictions are off: train the models with notebooks/01-04 (they are saved in models/).
      </div>
    );
  }
  const live = p.live_accuracy;
  const test = p.test_scores;
  const atRisk = Object.entries(p.orders)
    .filter(([, o]) => o.late_flag)
    .sort((a, b) => (b[1].late_risk ?? 0) - (a[1].late_risk ?? 0));
  const abnormal = Object.entries(p.robots).filter(([, h]) => h.abnormal);
  const nextEta = Object.entries(p.orders)
    .filter(([, o]) => o.eta_tick != null)
    .sort((a, b) => (a[1].eta_tick ?? 0) - (b[1].eta_tick ?? 0))
    .slice(0, 3);
  const pad = (n: number) => String(n).padStart(2, "0");
  const hourLabel = (h: number) => `${pad(h % 24)}:00`;
  const priority = (id: string) => orders?.find((o) => o.order_id === id)?.priority;

  return (
    <section>
      <div className="mb-2 flex items-baseline justify-between">
        <h2 className="text-base font-semibold">AI predictions · live models</h2>
        <span className="text-xs text-muted">Live accuracy is measured on this run against what really happens</span>
      </div>
      <div className="grid grid-cols-4 gap-4">
        <Card
          title={`Demand forecast · ${hourLabel(p.demand.hour)}–${hourLabel(p.demand.hour + 1)}`}
          foot={
            <>
              Live error {live.demand_mae ?? "—"} orders/h · test {test.demand_mae?.toFixed(1) ?? "—"}
              <span className="ml-1">(bars = actual, marks = forecast)</span>
            </>
          }
        >
          <div className="tabular text-[28px] font-semibold leading-none">
            {p.demand.forecast != null ? Math.round(p.demand.forecast) : "—"}
            <span className="ml-1 text-sm font-normal text-muted">orders expected</span>
          </div>
          <div className="mt-1 text-xs text-muted">{p.demand.so_far} arrived so far this hour</div>
          <DemandChart history={p.demand.history} />
        </Card>

        <Card
          title="Delivery time (ETA)"
          foot={
            <>
              Live error {live.eta_mae != null ? `${live.eta_mae} ticks` : "—"} over {live.eta_n} deliveries · test{" "}
              {test.eta_mae?.toFixed(1) ?? "—"}
            </>
          }
        >
          <div className="tabular text-[28px] font-semibold leading-none">
            {Object.keys(p.orders).length}
            <span className="ml-1 text-sm font-normal text-muted">orders with an ETA</span>
          </div>
          <ul className="mt-2 space-y-0.5 text-xs">
            {nextEta.map(([id, o]) => (
              <li key={id} className="flex justify-between">
                <span className="font-mono">{id}</span>
                <span className="tabular text-muted">
                  {(o.eta_tick ?? 0) - time > 0
                    ? `in ${simDuration((o.eta_tick ?? 0) - time, secondsPerTick)}`
                    : "any moment"}
                </span>
              </li>
            ))}
            {!nextEta.length && <li className="text-muted">No orders on the way.</li>}
          </ul>
        </Card>

        <Card
          title="Late-order risk"
          foot={
            <>
              Live precision {pct(live.late.precision)} · recall {pct(live.late.recall)} · test F1{" "}
              {test.late?.F1?.toFixed(2) ?? "—"}
            </>
          }
        >
          <div className={`tabular text-[28px] font-semibold leading-none ${atRisk.length ? "text-danger" : ""}`}>
            {atRisk.length}
            <span className="ml-1 text-sm font-normal text-muted">orders likely late</span>
          </div>
          <ul className="mt-2 space-y-0.5 text-xs">
            {atRisk.slice(0, 3).map(([id, o]) => (
              <li key={id} className="flex justify-between">
                <span className="font-mono">
                  {id} <span className="font-sans text-muted">{priority(id)}</span>
                </span>
                <span className="tabular text-danger">{pct(o.late_risk)}</span>
              </li>
            ))}
            {!atRisk.length && <li className="text-muted">No order at risk right now.</li>}
          </ul>
        </Card>

        <Card
          title="Robot health (anomaly detection)"
          foot={
            <>
              Live precision {pct(live.anomaly.precision)} · recall {pct(live.anomaly.recall)} · test F1{" "}
              {test.anomaly?.F1?.toFixed(2) ?? "—"}
            </>
          }
        >
          <div className={`tabular text-[28px] font-semibold leading-none ${abnormal.length ? "text-warning" : ""}`}>
            {abnormal.length}
            <span className="ml-1 text-sm font-normal text-muted">robots abnormal</span>
          </div>
          <ul className="mt-2 space-y-0.5 text-xs">
            {abnormal.slice(0, 3).map(([id, h]) => (
              <li key={id} className="flex justify-between gap-2">
                <span className="font-mono">{id}</span>
                <span className="truncate text-warning">{h.reason}</span>
              </li>
            ))}
            {!abnormal.length && <li className="text-muted">All robots look normal.</li>}
          </ul>
        </Card>
      </div>
      <Breakdown demand={p.demand} />
      {p.algorithms && (
        <p className="mt-2 text-[11px] text-muted">
          Models:{" "}
          {Object.entries(p.algorithms)
            .map(([k, a]) => `${k.replace("_", " ")} = ${a ?? "?"}`)
            .join(" · ")}
        </p>
      )}
    </section>
  );
}
