"use client";

import { useEffect, useState } from "react";
import { Screen } from "@/components/layout/Screen";
import { api } from "@/lib/api";
import type { SlottingCell, SlottingHeatmap } from "@/lib/types";

const MAX_VEL_FLOOR = 1; // avoid all-zero scale

function Heatmap({ cells }: { cells: SlottingCell[] }) {
  if (cells.length === 0) {
    return <div className="text-sm text-muted">No pick data yet — the simulator records picks as orders are fulfilled.</div>;
  }

  const rows = cells.map((c) => c.row);
  const cols = cells.map((c) => c.col);
  const minR = Math.min(...rows);
  const maxR = Math.max(...rows);
  const minC = Math.min(...cols);
  const maxC = Math.max(...cols);
  const maxV = Math.max(MAX_VEL_FLOOR, ...cells.map((c) => c.velocity));

  const gridRows = maxR - minR + 1;
  const gridCols = maxC - minC + 1;
  const cellSize = Math.min(32, Math.floor(560 / Math.max(gridCols, 1)));

  // Build lookup: "row,col" → velocity
  const lookup = new Map<string, { velocity: number; product_id: string }>();
  for (const c of cells) {
    lookup.set(`${c.row},${c.col}`, { velocity: c.velocity, product_id: c.product_id });
  }

  function heatColor(v: number): string {
    // 0 → cool blue, max → warm red
    const t = v / maxV;
    const r = Math.round(30 + t * 215);
    const g = Math.round(80 - t * 60);
    const b = Math.round(200 - t * 180);
    return `rgb(${r},${g},${b})`;
  }

  return (
    <div className="rounded-card border border-border bg-surface p-4">
      <div className="mb-3 text-xs text-muted">
        Pick velocity per rack cell (rolling 7-day window). Blue = slow, red = fast mover.
      </div>
      <div
        className="overflow-auto"
        style={{ maxHeight: 480 }}
      >
        <div
          style={{
            display: "grid",
            gridTemplateColumns: `repeat(${gridCols}, ${cellSize}px)`,
            gap: 2,
          }}
        >
          {Array.from({ length: gridRows }, (_, ri) =>
            Array.from({ length: gridCols }, (_, ci) => {
              const r = minR + ri;
              const c = minC + ci;
              const entry = lookup.get(`${r},${c}`);
              const bg = entry ? heatColor(entry.velocity) : "var(--color-border)";
              return (
                <div
                  key={`${r},${c}`}
                  title={entry ? `${entry.product_id}: ${entry.velocity} picks` : "empty"}
                  style={{
                    width: cellSize,
                    height: cellSize,
                    backgroundColor: bg,
                    borderRadius: 3,
                    opacity: entry ? 1 : 0.2,
                    cursor: entry ? "pointer" : "default",
                  }}
                />
              );
            })
          )}
        </div>
      </div>
      <div className="mt-3 flex items-center gap-2 text-xs text-muted">
        <span>slow</span>
        <div
          style={{
            width: 100,
            height: 10,
            background: "linear-gradient(to right, rgb(30,80,200), rgb(245,20,20))",
            borderRadius: 4,
          }}
        />
        <span>fast</span>
        <span className="ml-auto">max velocity: {maxV}</span>
      </div>
    </div>
  );
}

export default function SlottingPage() {
  const [data, setData] = useState<SlottingHeatmap | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [reslotting, setReslotting] = useState(false);
  const [reslotResult, setReslotResult] = useState<number | null>(null);

  const load = () => {
    api.slotting
      .heatmap()
      .then(setData)
      .catch((e) => setError(String(e.message ?? e)));
  };

  useEffect(() => {
    load();
    const id = setInterval(load, 15_000);
    return () => clearInterval(id);
  }, []);

  const handleReslot = async () => {
    setReslotting(true);
    setReslotResult(null);
    setError(null);
    try {
      const r = await api.slotting.reslot();
      setReslotResult(r.swaps);
      load();
    } catch (e: unknown) {
      setError(String((e as Error).message ?? e));
    } finally {
      setReslotting(false);
    }
  };

  return (
    <Screen title="Slotting">
      <div className="space-y-6">
        <div className="flex items-center justify-between">
          <div>
            <h1 className="text-lg font-semibold">Slotting Optimisation</h1>
            <p className="mt-0.5 text-sm text-muted">
              Demand-driven rack slotting — fast movers near packing stations (Phase 9, PR-10)
            </p>
          </div>
          <button
            onClick={handleReslot}
            disabled={reslotting || !data?.enabled}
            className="rounded-control bg-accent px-4 py-2 text-sm font-medium text-white hover:bg-accent/90 disabled:opacity-50"
          >
            {reslotting ? "Re-slotting…" : "Re-slot now"}
          </button>
        </div>

        {error && (
          <div className="rounded-card border border-danger/40 bg-danger/10 px-4 py-3 text-sm text-danger">
            {error}
          </div>
        )}

        {reslotResult !== null && (
          <div className="rounded-card border border-success/40 bg-success/10 px-4 py-3 text-sm">
            Re-slot complete — {reslotResult} product{reslotResult !== 1 ? "s" : ""} moved to better rack faces.
          </div>
        )}

        {data && (
          <div className="grid grid-cols-2 gap-4 sm:grid-cols-3">
            {[
              { label: "Slotting enabled", value: data.enabled ? "Yes" : "No" },
              { label: "Products tracked", value: data.cells.length },
              { label: "Total swaps", value: data.total_swaps },
            ].map(({ label, value }) => (
              <div key={label} className="rounded-card border border-border bg-surface p-4">
                <div className="text-xs text-muted">{label}</div>
                <div className="mt-1 text-xl font-semibold tabular-nums">{String(value)}</div>
              </div>
            ))}
          </div>
        )}

        {data && <Heatmap cells={data.cells} />}
      </div>
    </Screen>
  );
}
