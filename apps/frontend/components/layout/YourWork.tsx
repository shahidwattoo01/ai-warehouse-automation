"use client";

import { AlertTriangle, CheckCircle2 } from "lucide-react";
import Link from "next/link";
import { useEffect, useState } from "react";
import { useAuth } from "@/lib/auth";
import { useSim } from "@/lib/store";
import { wms } from "@/lib/wms";

interface Item {
  text: string;
  href: string;
  urgent: boolean;
}

/**
 * The top of each role's dashboard: what needs this person's attention now. Supervisors see
 * approvals and exceptions, operators the fleet and the order queue.
 */
export function YourWork() {
  const user = useAuth((s) => s.user);
  const state = useSim((s) => s.state);
  const [pendingCounts, setPendingCounts] = useState<number | null>(null);
  const [waitingStock, setWaitingStock] = useState<number | null>(null);
  const can = (p: string) => user?.permissions.includes(p) ?? false;
  const seesWms = can("wms:view");

  useEffect(() => {
    if (!seesWms) return;
    const load = () =>
      wms
        .kpis()
        .then((k) => {
          setPendingCounts(k.counts_pending_approval);
          setWaitingStock(k.orders_waiting_stock);
        })
        .catch(() => undefined); // simple inventory model: no WMS figures
    void load();
    const id = setInterval(load, 10_000);
    return () => clearInterval(id);
  }, [seesWms]);

  if (!user) return null;
  const robots = state?.robots ?? [];
  const faults = robots.filter((r) => r.status === "FAULT").length;
  const paused = robots.filter((r) => r.status === "PAUSED").length;
  const pending = state?.orders.filter((o) => o.status === "PENDING").length ?? 0;
  const items: Item[] = [];
  if (can("wms:count_approve") && pendingCounts)
    items.push({ text: `${pendingCounts} count differences wait for your approval`, href: "/inventory", urgent: true });
  if (can("robots:command") && faults) items.push({ text: `${faults} robots in fault`, href: "/fleet", urgent: true });
  if (can("robots:command") && paused) items.push({ text: `${paused} robots paused`, href: "/fleet", urgent: false });
  if (can("orders:assign") && pending >= 20)
    items.push({ text: `${pending} orders waiting for a robot`, href: "/orders", urgent: true });
  if (seesWms && waitingStock)
    items.push({ text: `${waitingStock} orders waiting for stock`, href: "/inventory", urgent: false });

  return (
    <section className="mb-4 flex flex-wrap items-center gap-x-4 gap-y-2 rounded-card border border-border bg-surface px-4 py-3 text-sm">
      <span className="font-semibold">
        {user.full_name} · <span className="font-normal text-muted">{user.role_label}</span>
      </span>
      {items.length === 0 ? (
        <span className="flex items-center gap-1.5 text-success">
          <CheckCircle2 size={15} /> Nothing needs you right now
        </span>
      ) : (
        items.map((i) => (
          <Link
            key={i.text}
            href={i.href}
            className={`flex items-center gap-1.5 hover:underline ${i.urgent ? "text-danger" : "text-warning"}`}
          >
            <AlertTriangle size={14} /> {i.text}
          </Link>
        ))
      )}
    </section>
  );
}
