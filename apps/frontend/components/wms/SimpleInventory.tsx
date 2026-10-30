"use client";

import { Search } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { Screen } from "@/components/layout/Screen";
import { KpiCard } from "@/components/ui/KpiCard";
import { api } from "@/lib/api";
import type { InventoryItem } from "@/lib/types";

const REFRESH_MS = 5000; // stock is not on the live stream (it is large); poll it instead
const LOW_STOCK = 10; // the simulator reorders a bay below this
const PAGE_SIZE = 100;

/** Products, rack locations and live stock (project map §4 Layer 1 entities, §22 dashboard). */
export function SimpleInventory() {
  const [items, setItems] = useState<InventoryItem[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [query, setQuery] = useState("");
  const [category, setCategory] = useState("all");
  const [lowOnly, setLowOnly] = useState(false);
  const [limit, setLimit] = useState(PAGE_SIZE);

  useEffect(() => {
    let cancelled = false;
    const load = () =>
      api.inventory
        .list()
        .then((data) => {
          if (cancelled) return;
          setItems(data);
          setError(null);
        })
        .catch((e: Error) => !cancelled && setError(e.message));
    load();
    const timer = setInterval(load, REFRESH_MS);
    return () => {
      cancelled = true;
      clearInterval(timer);
    };
  }, []);

  const categories = useMemo(() => [...new Set(items.map((i) => i.category))].sort(), [items]);
  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase();
    return items.filter(
      (i) =>
        (category === "all" || i.category === category) &&
        (!lowOnly || i.stock < LOW_STOCK) &&
        (!q || i.location.toLowerCase().includes(q) || i.name.toLowerCase().includes(q)),
    );
  }, [items, query, category, lowOnly]);

  const units = items.reduce((a, i) => a + i.stock, 0);
  const low = items.filter((i) => i.stock < LOW_STOCK).length;
  const restocking = items.filter((i) => i.restocking).length;

  return (
    <Screen title="Inventory">
      <div className="grid grid-cols-4 gap-4">
        <KpiCard
          label="Products (rack bays)"
          value={items.length.toLocaleString()}
          hint={`${categories.length} categories`}
        />
        <KpiCard label="Units in stock" value={units.toLocaleString()} />
        <KpiCard
          label="Low stock"
          value={low}
          hint={`below ${LOW_STOCK} units`}
          tone={low > 0 ? "warning" : "normal"}
        />
        <KpiCard label="Replenishment on the way" value={restocking} />
      </div>

      <section className="mt-6 rounded-card border border-border bg-surface p-4">
        <div className="flex flex-wrap items-center gap-3">
          <h2 className="mr-auto text-base font-semibold">Products</h2>
          <label className="flex items-center gap-2 rounded-control border border-border bg-canvas px-2 py-1 text-xs">
            <Search size={14} className="text-muted" />
            <input
              value={query}
              onChange={(e) => {
                setQuery(e.target.value);
                setLimit(PAGE_SIZE);
              }}
              placeholder="Rack (A-05-12) or product name"
              aria-label="Search products"
              className="w-56 bg-transparent outline-none"
            />
          </label>
          <select
            value={category}
            onChange={(e) => {
              setCategory(e.target.value);
              setLimit(PAGE_SIZE);
            }}
            aria-label="Category"
            className="rounded-control border border-border bg-canvas px-2 py-1 text-xs"
          >
            <option value="all">All categories</option>
            {categories.map((c) => (
              <option key={c} value={c}>
                {c}
              </option>
            ))}
          </select>
          <label className="flex items-center gap-1.5 text-xs text-muted">
            <input type="checkbox" checked={lowOnly} onChange={(e) => setLowOnly(e.target.checked)} />
            Low stock only
          </label>
        </div>
        {error && <p className="mt-2 text-xs text-danger">Could not load inventory: {error} (retrying)</p>}

        <table className="mt-3 w-full whitespace-nowrap text-left text-xs">
          <thead className="text-muted">
            <tr>
              <th className="py-1.5 pr-3 font-medium">Rack</th>
              <th className="py-1.5 pr-3 font-medium">Product</th>
              <th className="py-1.5 pr-3 font-medium">Category</th>
              <th className="py-1.5 pr-3 text-right font-medium">Weight kg</th>
              <th className="py-1.5 pr-3 text-right font-medium">Stock</th>
              <th className="py-1.5 font-medium">Replenishment</th>
            </tr>
          </thead>
          <tbody>
            {filtered.slice(0, limit).map((i) => (
              <tr key={i.product_id} className="border-t border-border/60">
                <td className="py-1.5 pr-3 font-mono font-semibold">{i.location}</td>
                <td className="py-1.5 pr-3">{i.name}</td>
                <td className="py-1.5 pr-3 text-muted">{i.category}</td>
                <td className="tabular py-1.5 pr-3 text-right">{i.weight_kg.toFixed(2)}</td>
                <td className={`tabular py-1.5 pr-3 text-right ${i.stock < LOW_STOCK ? "text-danger" : ""}`}>
                  {i.stock}
                </td>
                <td className="py-1.5 text-muted">{i.restocking ? "On the way" : "—"}</td>
              </tr>
            ))}
            {filtered.length === 0 && (
              <tr>
                <td colSpan={6} className="py-8 text-center text-muted">
                  {items.length ? "No products match." : "Loading…"}
                </td>
              </tr>
            )}
          </tbody>
        </table>
        {filtered.length > limit && (
          <button
            onClick={() => setLimit(limit + PAGE_SIZE)}
            className="mt-3 w-full rounded-control border border-border py-1.5 text-xs text-muted hover:text-ink"
          >
            Show more ({filtered.length - limit} remaining)
          </button>
        )}
      </section>
    </Screen>
  );
}
