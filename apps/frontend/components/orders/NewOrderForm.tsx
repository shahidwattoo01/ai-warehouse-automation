"use client";

import { Plus, Shuffle, X } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { api } from "@/lib/api";
import { PRIORITY_STYLE, robotOptions } from "@/lib/orders";
import { useSim } from "@/lib/store";
import type { InventoryItem, Priority, Robot } from "@/lib/types";

const NO_ROBOTS: Robot[] = [];
const MAX_ITEMS = 4;

interface Line {
  location: string; // what the operator typed, e.g. "A-05-12"
  quantity: number;
}

/** Operator order: choose racks (or let the system pick), priority, and optionally the robot. */
export function NewOrderForm({ onResult }: { onResult: (msg: { ok: boolean; text: string }) => void }) {
  const robots = useSim((s) => s.state?.robots ?? NO_ROBOTS);
  const [inventory, setInventory] = useState<InventoryItem[]>([]);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [priority, setPriority] = useState<Priority>("MEDIUM");
  const [lines, setLines] = useState<Line[]>([{ location: "", quantity: 1 }]);
  const [robotId, setRobotId] = useState<string>("");
  const [sending, setSending] = useState(false);

  // Load rack locations; keep retrying while the backend is down or restarting.
  useEffect(() => {
    let timer: ReturnType<typeof setTimeout> | undefined;
    let cancelled = false;
    const load = () =>
      api.inventory
        .list()
        .then((items) => {
          if (cancelled) return;
          setInventory(items);
          setLoadError(null);
        })
        .catch((e: Error) => {
          if (cancelled) return;
          setLoadError(e.message);
          timer = setTimeout(load, 5000);
        });
    load();
    return () => {
      cancelled = true;
      clearTimeout(timer);
    };
  }, []);

  const byLocation = useMemo(() => new Map(inventory.map((i) => [i.location.toUpperCase(), i])), [inventory]);
  const resolved = lines.map((l) =>
    l.location.trim() ? (byLocation.get(l.location.trim().toUpperCase()) ?? null) : undefined,
  );
  const invalid = resolved.some((r, i) => r === null || (r && r.stock < lines[i].quantity));
  const chosen = resolved.filter((r): r is InventoryItem => !!r);

  // Robots sorted for the first chosen rack (or just free first when racks are random).
  const options = robotOptions(
    robots,
    chosen[0] ? { items: [{ product_id: chosen[0].product_id, quantity: 1 }] } : null,
  );

  const randomRacks = () => {
    const inStock = inventory.filter((i) => i.stock > 0);
    const pick = () => inStock[Math.floor(Math.random() * inStock.length)];
    setLines([pick(), pick()].filter(Boolean).map((i) => ({ location: i.location, quantity: 1 })));
  };

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (invalid) return;
    setSending(true);
    try {
      const res = await api.orders.create({
        priority,
        items: chosen.map((c, i) => ({
          product_id: c.product_id,
          quantity: lines.filter((l) => l.location.trim())[i]?.quantity ?? 1,
        })),
        robot_id: robotId || null,
      });
      onResult({ ok: true, text: `${res.order_id} created${res.robot_id ? ` and assigned to ${res.robot_id}` : ""}` });
      setLines([{ location: "", quantity: 1 }]);
      setRobotId("");
    } catch (err) {
      onResult({ ok: false, text: (err as Error).message });
    } finally {
      setSending(false);
    }
  };

  return (
    <form onSubmit={submit} className="rounded-card border border-border bg-surface p-4">
      <h2 className="text-base font-semibold">New order</h2>
      <p className="mt-1 text-xs text-muted">Create an order as an operator, e.g. an urgent customer request.</p>

      <fieldset className="mt-4">
        <legend className="text-xs text-muted">Priority</legend>
        <div className="mt-1 flex gap-1">
          {(["HIGH", "MEDIUM", "LOW"] as const).map((p) => (
            <button
              type="button"
              key={p}
              onClick={() => setPriority(p)}
              aria-pressed={priority === p}
              className={`flex-1 rounded-control border py-1 text-xs font-semibold ${
                priority === p ? PRIORITY_STYLE[p] : "border-border text-muted hover:text-ink"
              }`}
            >
              {p}
            </button>
          ))}
        </div>
      </fieldset>

      <fieldset className="mt-4">
        <div className="flex items-center justify-between">
          <legend className="text-xs text-muted">Pick from racks</legend>
          <button
            type="button"
            onClick={randomRacks}
            className="flex items-center gap-1 text-xs text-muted hover:text-ink"
          >
            <Shuffle size={12} /> Random
          </button>
        </div>
        <datalist id="rack-locations">
          {inventory.map((i) => (
            <option key={i.product_id} value={i.location}>{`stock ${i.stock}`}</option>
          ))}
        </datalist>
        <div className="mt-1 space-y-1.5">
          {lines.map((line, i) => {
            const r = resolved[i];
            return (
              <div key={i}>
                <div className="flex gap-1.5">
                  <input
                    list="rack-locations"
                    value={line.location}
                    onChange={(e) => setLines(lines.map((l, j) => (j === i ? { ...l, location: e.target.value } : l)))}
                    placeholder="Rack, e.g. A-05-12"
                    aria-label={`Rack location ${i + 1}`}
                    className="min-w-0 flex-1 rounded-control border border-border bg-canvas px-2 py-1 font-mono text-xs uppercase placeholder:normal-case"
                  />
                  <input
                    type="number"
                    min={1}
                    max={20}
                    value={line.quantity}
                    onChange={(e) =>
                      setLines(
                        lines.map((l, j) =>
                          j === i ? { ...l, quantity: Math.max(1, Number(e.target.value) || 1) } : l,
                        ),
                      )
                    }
                    aria-label={`Quantity ${i + 1}`}
                    className="w-14 rounded-control border border-border bg-canvas px-2 py-1 text-xs"
                  />
                  {lines.length > 1 && (
                    <button
                      type="button"
                      onClick={() => setLines(lines.filter((_, j) => j !== i))}
                      aria-label="Remove rack"
                      className="text-muted hover:text-ink"
                    >
                      <X size={14} />
                    </button>
                  )}
                </div>
                {r === null && <p className="mt-0.5 text-[11px] text-danger">No rack {line.location.toUpperCase()}</p>}
                {r && r.stock < line.quantity && (
                  <p className="mt-0.5 text-[11px] text-danger">Only {r.stock} in stock</p>
                )}
                {r && r.stock >= line.quantity && <p className="mt-0.5 text-[11px] text-muted">{r.stock} in stock</p>}
              </div>
            );
          })}
        </div>
        {lines.length < MAX_ITEMS && (
          <button
            type="button"
            onClick={() => setLines([...lines, { location: "", quantity: 1 }])}
            className="mt-1.5 flex items-center gap-1 text-xs text-muted hover:text-ink"
          >
            <Plus size={12} /> Add rack
          </button>
        )}
        {!chosen.length && (
          <p className="mt-1 text-[11px] text-muted">Leave empty to let the system pick in-stock racks.</p>
        )}
        {loadError && <p className="mt-1 text-[11px] text-danger">Could not load racks: {loadError}</p>}
      </fieldset>

      <label className="mt-4 block">
        <span className="text-xs text-muted">Robot</span>
        <select
          value={robotId}
          onChange={(e) => setRobotId(e.target.value)}
          className="mt-1 w-full rounded-control border border-border bg-canvas px-2 py-1 text-xs"
        >
          <option value="">Let the dispatcher choose</option>
          {options.map(({ robot, distance, reason }) => (
            <option key={robot.robot_id} value={robot.robot_id} disabled={!!reason}>
              {robot.robot_id} — {reason ?? (distance !== null ? `${distance} m from first rack` : "free")} ·{" "}
              {Math.round(robot.battery)}%
            </option>
          ))}
        </select>
      </label>

      <button
        type="submit"
        disabled={sending || invalid}
        className="mt-4 w-full rounded-control border border-accent bg-accent/20 py-1.5 text-sm font-semibold hover:bg-accent/30 disabled:opacity-50"
      >
        {sending ? "Creating…" : "Create order"}
      </button>
    </form>
  );
}
