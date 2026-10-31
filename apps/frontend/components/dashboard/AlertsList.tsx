"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { useCan } from "@/lib/auth";
import { safety, type SafetyEvent } from "@/lib/safety";
import { isAbnormal, needsAttention } from "@/lib/status";
import { useSim } from "@/lib/store";
import { wms, type WmsAlert } from "@/lib/wms";

const TICKS_PER_HOUR = 600;
const clock = (tick: number) => {
  const h = (tick / TICKS_PER_HOUR) % 24;
  return `${String(Math.floor(h)).padStart(2, "0")}:${String(Math.floor((h % 1) * 60)).padStart(2, "0")}`;
};

function robotReason(r: { status: string; battery: number }, abnormal?: string): string {
  if (r.status === "FAULT") return "in fault";
  if (r.status === "PAUSED") return "paused";
  if (r.battery < 20) return `battery ${Math.round(r.battery)} %`;
  return abnormal ? `AI: ${abnormal}` : "flagged";
}

/** Everything that needs attention, in one list: robots now, warehouse alerts, safety events. */
export function AlertsList() {
  const robots = useSim((s) => s.state?.robots) ?? [];
  const health = useSim((s) => s.predictions?.robots);
  const [warehouse, setWarehouse] = useState<WmsAlert[] | null>(null);
  const [events, setEvents] = useState<SafetyEvent[]>([]);
  const seesWms = useCan("wms:view");

  useEffect(() => {
    let stop = false;
    const load = async () => {
      const [a, e] = await Promise.all([
        seesWms ? wms.alerts().catch(() => null) : Promise.resolve(null), // simple model: none
        safety.events().catch(() => []),
      ]);
      if (stop) return;
      setWarehouse(a);
      setEvents(e.filter((x) => x.severity !== "info").slice(0, 25));
    };
    void load();
    const id = setInterval(load, 5000);
    return () => {
      stop = true;
      clearInterval(id);
    };
  }, [seesWms]);

  const flagged = robots.filter((r) => needsAttention(r) || isAbnormal(r.robot_id, health));
  return (
    <div className="min-h-0 flex-1 space-y-4 overflow-auto pr-1 text-sm">
      <Group title={`Robots now (${flagged.length})`} more={{ href: "/fleet", label: "Fleet" }}>
        {flagged.map((r) => (
          <Row
            key={r.robot_id}
            tone={r.status === "FAULT" ? "critical" : "warning"}
            left={<span className="font-mono font-semibold">{r.robot_id}</span>}
            text={robotReason(r, health?.[r.robot_id]?.reason ?? undefined)}
          />
        ))}
        {!flagged.length && <Empty text="Every robot is working normally." />}
      </Group>
      {warehouse && (
        <Group title="Warehouse" more={{ href: "/inventory", label: "Inventory" }}>
          {warehouse.slice(0, 25).map((a, i) => (
            <Row
              key={`${a.tick}-${i}`}
              tone={a.level === "warning" ? "warning" : "info"}
              left={<span className="tabular text-muted">{clock(a.tick)}</span>}
              text={a.text}
            />
          ))}
          {!warehouse.length && <Empty text="No warehouse alerts." />}
        </Group>
      )}
      <Group title="Safety" more={{ href: "/safety", label: "Safety log" }}>
        {events.map((e, i) => (
          <Row
            key={`${e.tick}-${i}`}
            tone={e.severity === "critical" ? "critical" : "warning"}
            left={<span className="tabular text-muted">{clock(e.tick)}</span>}
            text={e.text}
          />
        ))}
        {!events.length && <Empty text="No safety events." />}
      </Group>
    </div>
  );
}

function Group({
  title,
  more,
  children,
}: {
  title: string;
  more: { href: string; label: string };
  children: React.ReactNode;
}) {
  return (
    <section>
      <div className="mb-1 flex items-center justify-between text-xs">
        <span className="font-semibold uppercase tracking-wide text-muted">{title}</span>
        <Link href={more.href} className="text-accent hover:underline">
          {more.label} →
        </Link>
      </div>
      <ul className="divide-y divide-border/70">{children}</ul>
    </section>
  );
}

function Row({ tone, left, text }: { tone: "critical" | "warning" | "info"; left: React.ReactNode; text: string }) {
  const dot = tone === "critical" ? "bg-danger" : tone === "warning" ? "bg-warning" : "bg-muted";
  return (
    <li className="flex items-start gap-2 py-1.5 text-xs">
      <span className={`mt-1 h-2 w-2 shrink-0 rounded-full ${dot}`} />
      <span className="w-12 shrink-0">{left}</span>
      <span className="min-w-0 flex-1">{text}</span>
    </li>
  );
}

function Empty({ text }: { text: string }) {
  return <li className="py-1.5 text-xs text-muted">{text}</li>;
}
