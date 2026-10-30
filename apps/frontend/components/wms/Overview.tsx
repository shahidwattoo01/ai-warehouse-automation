"use client";

import { AlertTriangle, Info } from "lucide-react";
import { KpiCard } from "@/components/ui/KpiCard";
import type { WmsAlert, WmsKpis } from "@/lib/wms";
import { clock, minutes, Panel } from "./shared";

const TASK_NAMES: Record<string, string> = {
  REPLENISH_URGENT: "Urgent replenishment",
  RECEIVE: "Receiving",
  PUTAWAY: "Putaway",
  REPLENISH: "Replenishment",
  RETURN: "Returns inspection",
  QUARANTINE: "Quarantine / scrap",
  COUNT: "Cycle counts",
};

export function Overview({ kpis, alerts }: { kpis: WmsKpis; alerts: WmsAlert[] }) {
  const pct = (v: number | null) => (v === null ? "–" : `${(v * 100).toFixed(1)}%`);
  const openTasks = Object.entries(kpis.open_tasks);
  return (
    <div className="space-y-4">
      <div className="grid grid-cols-2 gap-3 md:grid-cols-4 2xl:grid-cols-6">
        <KpiCard
          label="Units on hand"
          value={kpis.units_on_hand.toLocaleString()}
          hint={`${kpis.skus.toLocaleString()} SKUs`}
        />
        <KpiCard
          label="Inventory value"
          value={`$${Math.round(kpis.inventory_value).toLocaleString()}`}
          hint="at purchase cost"
        />
        <KpiCard
          label="Fill rate"
          value={pct(kpis.fill_rate)}
          hint={`${kpis.units_short} units short-picked`}
          tone={kpis.fill_rate < 0.98 ? "warning" : "normal"}
        />
        <KpiCard
          label="Inventory record accuracy"
          value={pct(kpis.inventory_record_accuracy)}
          hint={`${kpis.counts_done} counts`}
          tone={(kpis.inventory_record_accuracy ?? 1) < 0.95 ? "warning" : "normal"}
        />
        <KpiCard
          label="Stockouts"
          value={kpis.stockouts}
          hint={`${kpis.orders_waiting_stock} orders waiting for stock`}
          tone={kpis.stockouts > 0 ? "warning" : "normal"}
        />
        <KpiCard
          label="Inbound"
          value={kpis.open_purchase_orders}
          hint={`open POs · ${kpis.trucks_at_dock} trucks at the docks · dock-to-stock ${minutes(kpis.dock_to_stock_ticks)}`}
        />
      </div>
      <div className="grid gap-4 xl:grid-cols-[1fr_360px]">
        <Panel title="Alerts">
          {alerts.length === 0 ? (
            <p className="text-sm text-muted">Nothing needs attention.</p>
          ) : (
            <ul className="max-h-[420px] space-y-1.5 overflow-auto text-sm">
              {alerts.map((a, i) => (
                <li key={i} className="flex items-start gap-2">
                  {a.level === "warning" ? (
                    <AlertTriangle size={15} className="mt-0.5 shrink-0 text-warning" />
                  ) : (
                    <Info size={15} className="mt-0.5 shrink-0 text-accent" />
                  )}
                  <span className="flex-1">{a.text}</span>
                  <span className="shrink-0 font-mono text-xs text-muted">{clock(a.tick)}</span>
                </li>
              ))}
            </ul>
          )}
        </Panel>
        <div className="space-y-4">
          <Panel title="Open work">
            {openTasks.length === 0 ? (
              <p className="text-sm text-muted">All tasks done.</p>
            ) : (
              <ul className="space-y-1 text-sm">
                {openTasks.map(([type, n]) => (
                  <li key={type} className="flex justify-between">
                    <span>{TASK_NAMES[type] ?? type}</span>
                    <b className="tabular">{n}</b>
                  </li>
                ))}
              </ul>
            )}
          </Panel>
          <Panel title="Control">
            <ul className="space-y-1 text-sm">
              <li className="flex justify-between">
                <span>Counts waiting for a supervisor</span>
                <b className={kpis.counts_pending_approval ? "text-danger" : ""}>{kpis.counts_pending_approval}</b>
              </li>
              <li className="flex justify-between">
                <span>Units on hold / damaged / expired</span>
                <b>{kpis.on_hold_units}</b>
              </li>
              <li className="flex justify-between">
                <span>Locations</span>
                <b>{kpis.locations.toLocaleString()}</b>
              </li>
              <li className="flex justify-between text-muted">
                <span>Warehouse date</span>
                <span>
                  {kpis.date} · {clock(kpis.tick)}
                </span>
              </li>
            </ul>
          </Panel>
        </div>
      </div>
    </div>
  );
}
