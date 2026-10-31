"use client";

import dynamic from "next/dynamic";
import { useSearchParams } from "next/navigation";
import { Suspense, useEffect, useState } from "react";
import { AlertsList } from "@/components/dashboard/AlertsList";
import { useSafety } from "@/components/layout/EStop";
import { FleetTable } from "@/components/fleet/FleetTable";
import { Screen } from "@/components/layout/Screen";
import { YourWork } from "@/components/layout/YourWork";
import { AiPanel } from "@/components/predictions/AiPanel";
import { KpiCard } from "@/components/ui/KpiCard";
import { useCan } from "@/lib/auth";
import { simDuration } from "@/lib/orders";
import { isAbnormal, isActive, needsAttention } from "@/lib/status";
import { useSim } from "@/lib/store";
import { wms, type WmsKpis } from "@/lib/wms";

const WarehouseScene = dynamic(() => import("@/components/three/WarehouseScene").then((m) => m.WarehouseScene), {
  ssr: false,
});

const PANELS = [
  ["fleet", "Fleet"],
  ["alerts", "Alerts"],
  ["ai", "AI predictions"],
] as const;
type Panel = (typeof PANELS)[number][0];

/** Warehouse KPIs from the WMS (null with the simple inventory model or without wms:view). */
function useWmsKpis(): WmsKpis | null | "off" {
  const seesWms = useCan("wms:view");
  const [kpis, setKpis] = useState<WmsKpis | null | "off">(null);
  useEffect(() => {
    if (!seesWms) return;
    let stop = false;
    const load = () =>
      wms
        .kpis()
        .then((k) => !stop && setKpis(k))
        // "off" only for the simple inventory model; a slow or failed request keeps the last figures
        .catch((e) => !stop && (e as Error).message.includes("INVENTORY_MODEL") && setKpis("off"));
    void load();
    const id = setInterval(load, 5000);
    return () => {
      stop = true;
      clearInterval(id);
    };
  }, [seesWms]);
  return kpis;
}

/**
 * The control room on one screen: what needs attention, eight KPIs across the whole warehouse
 * (robots, orders, stock, shipping, safety), the live 3D view, and one panel with the fleet, the
 * alerts and the AI predictions. Details live on their own pages.
 */
function Dashboard() {
  const state = useSim((s) => s.state);
  const health = useSim((s) => s.predictions?.robots);
  const params = useSearchParams();
  const [panel, setPanel] = useState<Panel>("fleet");
  const wk = useWmsKpis();
  const w = wk === "off" ? null : wk;
  const off = wk === "off" ? "WMS off" : "loading…";
  const s = useSafety();

  useEffect(() => {
    const wanted = params.get("panel");
    if (wanted === "alerts" || wanted === "ai" || wanted === "fleet") setPanel(wanted);
  }, [params]);

  const robots = state?.robots ?? [];
  const kpis = state?.kpis;
  const secondsPerTick = state?.clock?.seconds_per_tick ?? 1;
  const avgBattery = robots.length ? Math.round(robots.reduce((a, r) => a + r.battery, 0) / robots.length) : 0;
  const pending = state?.orders.filter((o) => o.status === "PENDING").length ?? 0;
  const active = robots.filter(isActive).length;
  const faults = robots.filter((r) => r.status === "FAULT").length;
  const centre = useSim((st) => st.alerts);
  const alerts = centre
    ? centre.open + centre.acknowledged
    : robots.filter((r) => needsAttention(r) || isAbnormal(r.robot_id, health)).length;
  const late = kpis?.late_percent ?? 0;
  const out = w?.outbound;
  const onTime = out?.on_time_ship_rate;
  const truck = out?.next_truck;

  return (
    <div className="flex h-full min-h-[640px] flex-col gap-3">
      <YourWork />
      <div className="grid grid-cols-4 gap-3 xl:grid-cols-8">
        <KpiCard
          compact
          label="Robots active"
          value={`${active}/${robots.length}`}
          hint={faults ? `${faults} in fault` : kpis ? `${kpis.utilisation_percent}% utilisation` : undefined}
          tone={faults ? "critical" : "normal"}
          title="Robots on an order or driving to a charger"
        />
        <KpiCard
          compact
          label="Orders waiting"
          value={pending}
          hint="for a robot"
          tone={pending >= 60 ? "critical" : pending >= 20 ? "warning" : "normal"}
          title="Released orders no robot has taken yet (warning from 20)"
        />
        <KpiCard
          compact
          label="Late orders"
          value={`${late}%`}
          hint="target below 5%"
          tone={late > 10 ? "critical" : late > 5 ? "warning" : "normal"}
          title="Share of delivered orders that missed their robot deadline; target below 5 %"
        />
        <KpiCard
          compact
          label="Throughput"
          value={kpis ? Math.round(kpis.throughput_per_hour) : "—"}
          hint="orders per hour"
          title={
            kpis?.avg_completion_ticks != null
              ? `Orders delivered to packing in the last simulated hour; ${kpis.orders_completed} done, ${simDuration(kpis.avg_completion_ticks, secondsPerTick)} per order on average`
              : "Orders delivered to packing in the last simulated hour"
          }
        />
        <KpiCard
          compact
          label="Battery"
          value={`${avgBattery}%`}
          hint="fleet average"
          tone={avgBattery < 20 ? "critical" : avgBattery < 50 ? "warning" : "normal"}
        />
        <KpiCard
          compact
          label="Waiting for stock"
          value={w ? w.orders_waiting_stock : "—"}
          hint={w ? `${w.stockouts} ${w.stockouts === 1 ? "item" : "items"} out of stock` : off}
          tone={w && w.orders_waiting_stock >= 10 ? "warning" : "normal"}
          title="Orders waiting for stock to be replenished, and items with nothing left to promise"
        />
        <KpiCard
          compact
          label="Shipping on time"
          value={onTime == null ? "—" : `${Math.round(onTime * 100)}%`}
          hint={truck ? `next truck ${truck.departs_at.slice(-5)}` : w ? "no truck planned" : off}
          tone={onTime != null && onTime < 0.9 ? "critical" : onTime != null && onTime < 0.95 ? "warning" : "normal"}
          title={
            truck
              ? `Orders shipped on their promised truck. Next: ${truck.carrier} ${truck.departs_at} (${truck.cartons_loaded} cartons loaded)`
              : "Orders shipped on their promised truck"
          }
        />
        <KpiCard
          compact
          label="Safety"
          value={!s || s.state === "NORMAL" ? "Normal" : s.state === "ESTOP" ? "STOPPED" : "Reset?"}
          hint={`${s?.near_misses ?? 0} near misses`}
          tone={s?.state === "ESTOP" ? "critical" : s?.state === "RELEASED" ? "warning" : "normal"}
          title="Emergency stop state and near misses this run (Safety page)"
        />
      </div>

      <div className="grid min-h-0 flex-1 grid-cols-12 gap-3">
        <div className="col-span-12 min-h-[380px] rounded-card border border-border bg-surface p-1 lg:col-span-7">
          <WarehouseScene compact />
        </div>
        <div className="col-span-12 flex min-h-[380px] flex-col rounded-card border border-border bg-surface p-3 lg:col-span-5">
          <nav className="mb-3 flex gap-1 border-b border-border pb-2" role="tablist" aria-label="Dashboard panel">
            {PANELS.map(([id, label]) => (
              <button
                key={id}
                role="tab"
                aria-selected={panel === id}
                onClick={() => setPanel(id)}
                className={`rounded-control px-3 py-1 text-sm ${panel === id ? "bg-accent/15 font-semibold text-ink" : "text-muted hover:text-ink"}`}
              >
                {label}
                {id === "alerts" && alerts > 0 && (
                  <span className="ml-1 rounded-full bg-danger px-1.5 text-[10px] text-white">{alerts}</span>
                )}
              </button>
            ))}
          </nav>
          <div className="flex min-h-0 flex-1 flex-col">
            {panel === "fleet" && <FleetTable compact />}
            {panel === "alerts" && <AlertsList />}
            {panel === "ai" && (
              <div className="min-h-0 flex-1 overflow-auto pr-1">
                <AiPanel compact />
              </div>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}

export default function DashboardPage() {
  return (
    <Screen title="Dashboard">
      <Suspense>
        <Dashboard />
      </Suspense>
    </Screen>
  );
}
