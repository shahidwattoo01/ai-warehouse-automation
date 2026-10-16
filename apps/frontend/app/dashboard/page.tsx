"use client";

import dynamic from "next/dynamic";
import { FleetTable } from "@/components/fleet/FleetTable";
import { Screen } from "@/components/layout/Screen";
import { AiPanel } from "@/components/predictions/AiPanel";
import { KpiCard } from "@/components/ui/KpiCard";
import { simDuration } from "@/lib/orders";
import { isActive } from "@/lib/status";
import { useSim } from "@/lib/store";

const WarehouseScene = dynamic(() => import("@/components/three/WarehouseScene").then((m) => m.WarehouseScene), {
  ssr: false,
});

export default function DashboardPage() {
  const state = useSim((s) => s.state);
  const robots = state?.robots ?? [];
  const kpis = state?.kpis;
  const secondsPerTick = state?.clock?.seconds_per_tick ?? 1;
  const avgBattery = robots.length ? Math.round(robots.reduce((a, r) => a + r.battery, 0) / robots.length) : 0;
  const pending = state?.orders.filter((o) => o.status === "PENDING").length ?? 0;
  const active = robots.filter(isActive).length;

  return (
    <Screen title="Dashboard">
      <div className="grid grid-cols-6 gap-4">
        <KpiCard label="Active robots" value={`${active}/${robots.length}`} hint={kpis ? `${kpis.utilisation_percent}% utilisation` : undefined} />
        <KpiCard label="Pending orders" value={pending} tone={pending >= 20 ? "warning" : "normal"} />
        <KpiCard label="Completed" value={kpis?.orders_completed ?? 0} hint={kpis ? `${kpis.late_percent}% late` : undefined} />
        <KpiCard
          label="Avg completion"
          value={kpis?.avg_completion_ticks != null ? simDuration(kpis.avg_completion_ticks, secondsPerTick) : "—"}
          hint="order placed → packed"
        />
        <KpiCard label="Throughput" value={kpis ? Math.round(kpis.throughput_per_hour) : "—"} hint="orders per sim hour" />
        <KpiCard
          label="Battery"
          value={`${avgBattery}%`}
          hint="fleet average"
          tone={avgBattery < 20 ? "critical" : avgBattery < 50 ? "warning" : "normal"}
        />
      </div>
      <div className="mt-6">
        <AiPanel />
      </div>
      <div className="mt-6 grid grid-cols-12 gap-4">
        <div className="col-span-7 h-[460px] rounded-card border border-border bg-surface p-1">
          <WarehouseScene compact />
        </div>
        <div className="col-span-5 h-[460px] rounded-card border border-border bg-surface p-4">
          <FleetTable />
        </div>
      </div>
    </Screen>
  );
}
