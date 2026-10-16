"use client";

import { useEffect, useRef, useState } from "react";
import { api } from "@/lib/api";
import { robotOptions } from "@/lib/orders";
import { useSim } from "@/lib/store";
import type { Order, Robot } from "@/lib/types";

const NO_ROBOTS: Robot[] = [];

/** "Assign" button for a waiting order: lists robots, free and nearest to the first rack first. */
export function AssignMenu({ order, onResult }: { order: Order; onResult: (msg: { ok: boolean; text: string }) => void }) {
  const robots = useSim((s) => s.state?.robots ?? NO_ROBOTS);
  const [open, setOpen] = useState(false);
  const [sending, setSending] = useState<string | null>(null);
  const box = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) return;
    const close = (e: MouseEvent) => !box.current?.contains(e.target as Node) && setOpen(false);
    const esc = (e: KeyboardEvent) => e.key === "Escape" && setOpen(false);
    document.addEventListener("mousedown", close);
    document.addEventListener("keydown", esc);
    return () => {
      document.removeEventListener("mousedown", close);
      document.removeEventListener("keydown", esc);
    };
  }, [open]);

  const options = open ? robotOptions(robots, order) : [];
  const freeCount = options.filter((o) => !o.reason).length;

  const assign = async (robotId: string) => {
    setSending(robotId);
    try {
      await api.orders.assign(order.order_id, robotId);
      onResult({ ok: true, text: `${order.order_id} assigned to ${robotId}` });
      setOpen(false);
    } catch (e) {
      onResult({ ok: false, text: (e as Error).message });
    } finally {
      setSending(null);
    }
  };

  return (
    <div ref={box} className="relative inline-block">
      <button
        onClick={() => setOpen((v) => !v)}
        aria-expanded={open}
        className="rounded-control border border-accent bg-accent/15 px-2 py-0.5 text-xs font-semibold hover:bg-accent/25"
      >
        Assign
      </button>
      {open && (
        <div className="absolute right-0 top-7 z-20 w-64 rounded-card border border-border bg-surface shadow-xl">
          <div className="border-b border-border px-3 py-2 text-xs text-muted">
            {freeCount} free robot{freeCount === 1 ? "" : "s"} · nearest to the first rack first
          </div>
          <ul className="max-h-64 overflow-auto py-1 text-xs">
            {options.map(({ robot, distance, reason }) => (
              <li key={robot.robot_id}>
                <button
                  disabled={!!reason || sending !== null}
                  onClick={() => assign(robot.robot_id)}
                  className="flex w-full items-center justify-between gap-2 px-3 py-1.5 text-left enabled:hover:bg-border/50 disabled:opacity-45"
                >
                  <span className="font-mono font-semibold">{robot.robot_id}</span>
                  <span className="flex-1 text-muted">
                    {reason ?? (distance !== null ? `${distance} m away` : "free")}
                  </span>
                  <span className="tabular">{Math.round(robot.battery)}%</span>
                  {sending === robot.robot_id && <span className="text-muted">…</span>}
                </button>
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}
