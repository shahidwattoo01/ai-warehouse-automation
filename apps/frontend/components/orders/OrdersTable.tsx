"use client";

import { useMemo, useState } from "react";
import { PRIORITY_STYLE, rackLabel, simDuration } from "@/lib/orders";
import { useSim } from "@/lib/store";
import type { Order } from "@/lib/types";
import { AssignMenu } from "./AssignMenu";

const NO_ORDERS: Order[] = [];

type Tab = "waiting" | "active" | "done";
const TABS: { id: Tab; label: string; statuses: Order["status"][] }[] = [
  { id: "waiting", label: "Waiting", statuses: ["PENDING"] },
  { id: "active", label: "In progress", statuses: ["ASSIGNED", "IN_PROGRESS"] },
  { id: "done", label: "Done", statuses: ["DELIVERED", "LATE", "CANCELLED"] },
];

const STATUS_TEXT: Record<Order["status"], string> = {
  PENDING: "Waiting",
  ASSIGNED: "Robot on the way",
  IN_PROGRESS: "Picking",
  DELIVERED: "Delivered",
  LATE: "Delivered late",
  CANCELLED: "Cancelled",
};

/** Live order list from the simulator stream, with manual assignment for waiting orders. */
export function OrdersTable({ onResult }: { onResult: (msg: { ok: boolean; text: string }) => void }) {
  const orders = useSim((s) => s.state?.orders ?? NO_ORDERS);
  const now = useSim((s) => s.state?.time ?? 0);
  const mode = useSim((s) => s.state?.assignment_mode ?? "auto");
  const secondsPerTick = useSim((s) => s.state?.clock?.seconds_per_tick ?? 1);
  const selectRobot = useSim((s) => s.selectRobot);
  const predictions = useSim((s) => s.predictions?.orders);
  const [tab, setTab] = useState<Tab>("waiting");

  const byTab = useMemo(() => {
    const out = { waiting: [] as Order[], active: [] as Order[], done: [] as Order[] };
    for (const o of orders) {
      const t = TABS.find((x) => x.statuses.includes(o.status));
      if (t) out[t.id].push(o);
    }
    const rank = { HIGH: 0, MEDIUM: 1, LOW: 2 };
    out.waiting.sort((a, b) => rank[a.priority] - rank[b.priority] || a.order_time - b.order_time); // dispatcher order
    out.active.sort((a, b) => a.order_time - b.order_time);
    out.done.sort((a, b) => b.order_time - a.order_time);
    return out;
  }, [orders]);

  const rows = byTab[tab];

  return (
    <section className="flex min-h-0 flex-col rounded-card border border-border bg-surface p-4">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h2 className="text-base font-semibold">Orders — live</h2>
        <div className="flex gap-1" role="tablist" aria-label="Order status">
          {TABS.map((t) => (
            <button
              key={t.id}
              role="tab"
              aria-selected={tab === t.id}
              onClick={() => setTab(t.id)}
              className={`rounded-control border px-2 py-0.5 text-xs ${
                tab === t.id ? "border-accent bg-accent/15 text-ink" : "border-border text-muted hover:text-ink"
              }`}
            >
              {t.label} <span className="tabular">{byTab[t.id].length}</span>
            </button>
          ))}
        </div>
      </div>
      {tab === "waiting" && mode === "auto" && (
        <p className="mt-2 text-xs text-muted">
          Auto assignment is on, so waiting orders are usually taken within a tick. Switch to <b className="text-ink">Manual</b>{" "}
          above to choose robots yourself.
        </p>
      )}

      <div className="mt-3 min-h-0 flex-1 overflow-auto">
        <table className="w-full whitespace-nowrap text-left text-xs">
          <thead className="sticky top-0 z-10 bg-surface text-muted">
            <tr>
              <th className="py-1.5 pr-2 font-medium">Order</th>
              <th className="py-1.5 pr-2 font-medium">Priority</th>
              <th className="py-1.5 pr-2 font-medium">Pick at</th>
              <th className="py-1.5 pr-2 font-medium">Pack at</th>
              <th className="py-1.5 pr-2 font-medium">Status</th>
              <th className="py-1.5 pr-2 font-medium">{tab === "done" ? "" : "Deadline"}</th>
              {tab === "active" && (
                <th className="py-1.5 pr-2 font-medium" title="Predicted by the ETA model when the robot was assigned">
                  AI ETA
                </th>
              )}
              {tab === "active" && (
                <th className="py-1.5 pr-2 font-medium" title="Probability of missing the deadline (late-risk model)">
                  Late risk
                </th>
              )}
              <th className="py-1.5 pr-3 text-right font-medium">Robot</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((o) => {
              const left = o.deadline - now;
              const pred = predictions?.[o.order_id];
              const etaLeft = pred?.eta_tick != null ? pred.eta_tick - now : null;
              return (
                <tr key={o.order_id} className="border-t border-border/60 align-middle">
                  <td className="py-1.5 pr-2">
                    <div className="font-mono font-semibold">{o.order_id}</div>
                    <div className="text-[10px] text-muted">{o.source === "MANUAL" ? "Operator" : "Customer"}</div>
                  </td>
                  <td className="py-1.5 pr-2">
                    <span className={`rounded border px-1.5 py-px text-[10px] font-semibold ${PRIORITY_STYLE[o.priority]}`}>{o.priority}</span>
                  </td>
                  <td className="max-w-[190px] whitespace-normal py-1.5 pr-2">
                    {o.items.map((i) => (
                      <span key={i.product_id} className="mr-2 inline-block whitespace-nowrap">
                        Rack {rackLabel(i.product_id)} <span className="text-muted">×{i.quantity}</span>
                      </span>
                    ))}
                  </td>
                  <td className="py-1.5 pr-2 text-muted">{o.status === "PENDING" ? "—" : o.destination ?? "—"}</td>
                  <td className={`py-1.5 pr-2 ${o.status === "LATE" ? "text-danger" : ""}`}>{STATUS_TEXT[o.status]}</td>
                  <td className={`tabular py-1.5 pr-2 ${tab !== "done" && left < 60 ? "text-danger" : "text-muted"}`}>
                    {tab === "done" ? "—" : left > 0 ? `in ${simDuration(left, secondsPerTick)}` : `overdue ${simDuration(-left, secondsPerTick)}`}
                  </td>
                  {tab === "active" && (
                    <td className="tabular py-1.5 pr-2">
                      {etaLeft == null ? (
                        <span className="text-muted">—</span>
                      ) : etaLeft > 0 ? (
                        <span className={pred?.eta_tick != null && pred.eta_tick > o.deadline ? "text-danger" : ""}>
                          in {simDuration(etaLeft, secondsPerTick)}
                        </span>
                      ) : (
                        <span className="text-muted">due now</span>
                      )}
                    </td>
                  )}
                  {tab === "active" && (
                    <td className="py-1.5 pr-2">
                      {pred?.late_risk == null ? (
                        <span className="text-muted">—</span>
                      ) : (
                        <span
                          className={`tabular rounded border px-1.5 py-px text-[10px] font-semibold ${
                            pred.late_flag ? "border-danger/60 text-danger" : "border-border text-muted"
                          }`}
                        >
                          {Math.round(pred.late_risk * 100)}%
                        </span>
                      )}
                    </td>
                  )}
                  <td className="py-1.5 pr-3 text-right">
                    {o.assigned_robot ? (
                      <button
                        onClick={() => selectRobot(o.assigned_robot)}
                        className="font-mono font-semibold hover:text-accent"
                        title="Show this robot in the 3D view"
                      >
                        {o.assigned_robot}
                        {o.manual_assignment && <span className="ml-1 font-sans font-normal text-muted">(you)</span>}
                      </button>
                    ) : (
                      <AssignMenu order={o} onResult={onResult} />
                    )}
                  </td>
                </tr>
              );
            })}
            {rows.length === 0 && (
              <tr>
                <td colSpan={tab === "active" ? 9 : 7} className="py-8 text-center text-muted">
                  {tab === "waiting" ? "No orders waiting." : tab === "active" ? "No orders in progress." : "No finished orders yet."}
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
    </section>
  );
}
