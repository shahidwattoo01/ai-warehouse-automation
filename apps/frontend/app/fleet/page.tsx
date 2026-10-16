"use client";

import dynamic from "next/dynamic";
import { FleetTable } from "@/components/fleet/FleetTable";
import { Screen } from "@/components/layout/Screen";

const WarehouseScene = dynamic(() => import("@/components/three/WarehouseScene").then((m) => m.WarehouseScene), {
  ssr: false,
});

/** Every robot with position, battery, task, status, speed and pause/resume (project map §22). */
export default function FleetPage() {
  return (
    <Screen title="Fleet">
      <div className="grid h-full min-h-[560px] grid-cols-12 gap-4">
        <section className="col-span-7 flex min-h-0 flex-col rounded-card border border-border bg-surface p-4">
          <FleetTable detailed />
        </section>
        <section className="col-span-5 min-h-[420px] rounded-card border border-border bg-surface p-1">
          <WarehouseScene compact />
        </section>
      </div>
    </Screen>
  );
}
