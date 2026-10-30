"use client";

import { useCan } from "@/lib/auth";
import { Bot, ChevronRight, Inbox, ListOrdered, PackageCheck, ShoppingCart, UserRound } from "lucide-react";
import { useState } from "react";
import { api } from "@/lib/api";
import { useSim } from "@/lib/store";

const STEPS = [
  {
    icon: ShoppingCart,
    title: "Order arrives",
    text: "Customer demand from the order generator, or an operator order from this page.",
  },
  { icon: ListOrdered, title: "Waiting queue", text: "High priority first, then oldest first." },
  { icon: Bot, title: "Assignment", text: "" }, // depends on mode
  {
    icon: Inbox,
    title: "Pick at racks",
    text: "The robot drives to each rack location and waits while the item is picked into its tote.",
  },
  {
    icon: PackageCheck,
    title: "Packing",
    text: "It drops the totes at the least busy packing bay, then parks or charges.",
  },
];

/** How orders flow through the warehouse, with the Auto / Manual assignment switch. */
export function OrderFlow() {
  const canAssign = useCan("orders:assign");
  const mode = useSim((s) => s.state?.assignment_mode ?? "auto");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const setMode = async (next: "auto" | "manual") => {
    if (next === mode) return;
    setBusy(true);
    setError(null);
    try {
      await api.simulation.setAssignmentMode(next);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  };

  const assignText =
    mode === "auto"
      ? "Dispatcher gives each order to the nearest free robot with 20%+ battery, within one tick."
      : "Orders wait here until you pick a robot with Assign.";

  return (
    <section className="rounded-card border border-border bg-surface p-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h2 className="text-base font-semibold">How orders flow</h2>
        <div className="flex items-center gap-2 text-xs">
          <span className="text-muted">Assignment</span>
          <div
            className="flex rounded-control border border-border p-0.5"
            role="radiogroup"
            aria-label="Assignment mode"
          >
            {(["auto", "manual"] as const).map((m) => (
              <button
                key={m}
                role="radio"
                aria-checked={mode === m}
                disabled={busy || !canAssign}
                title={canAssign ? undefined : "Your role cannot change the assignment mode"}
                onClick={() => setMode(m)}
                className={`flex items-center gap-1.5 rounded-[4px] px-2.5 py-1 ${
                  mode === m ? "bg-accent/20 text-ink" : "text-muted hover:text-ink"
                }`}
              >
                {m === "auto" ? <Bot size={14} /> : <UserRound size={14} />}
                {m === "auto" ? "Auto" : "Manual"}
              </button>
            ))}
          </div>
        </div>
      </div>
      {error && <p className="mt-2 text-xs text-danger">{error}</p>}
      <ol className="mt-3 grid grid-cols-5 gap-2">
        {STEPS.map((s, i) => (
          <li key={s.title} className="relative flex gap-2 rounded-control border border-border/70 p-2.5">
            <s.icon size={18} className={i === 2 ? "mt-0.5 shrink-0 text-accent" : "mt-0.5 shrink-0 text-muted"} />
            <div>
              <div className="text-xs font-semibold">
                {i === 2 ? (mode === "auto" ? "Auto assignment" : "You assign") : s.title}
              </div>
              <p className="mt-0.5 text-xs leading-snug text-muted">{i === 2 ? assignText : s.text}</p>
            </div>
            {i < STEPS.length - 1 && (
              <ChevronRight
                size={14}
                className="absolute -right-2.5 top-1/2 z-10 -translate-y-1/2 rounded-full bg-surface text-muted"
              />
            )}
          </li>
        ))}
      </ol>
    </section>
  );
}
