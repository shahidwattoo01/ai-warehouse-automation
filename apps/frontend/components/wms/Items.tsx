"use client";

import { Can } from "@/components/layout/Can";
import { Printer, X } from "lucide-react";
import { useCallback, useEffect, useState } from "react";
import { wms, type WmsItemDetail, type WmsItemRow } from "@/lib/wms";
import { Badge, Barcode, clock, ErrorNote, ghost, input, Panel, ScanBox, td, th } from "./shared";

const CATEGORIES = [
  "Electronics",
  "Home & Kitchen",
  "Apparel",
  "Toys & Games",
  "Books & Media",
  "Sports & Outdoors",
  "Beauty & Health",
  "Grocery",
  "Office Supplies",
  "Tools & DIY",
];
const FILTERS = [
  ["all", "All"],
  ["low", "Pick face low"],
  ["out", "Out of stock"],
  ["hold", "On hold"],
  ["expiring", "Expiring soon"],
] as const;
const PAGE = 100;

export function Items({ user, openSku }: { user: string; openSku: string | null }) {
  const [q, setQ] = useState("");
  const [category, setCategory] = useState("");
  const [abc, setAbc] = useState("");
  const [filter, setFilter] = useState("all");
  const [offset, setOffset] = useState(0);
  const [data, setData] = useState<{ total: number; items: WmsItemRow[] } | null>(null);
  const [selected, setSelected] = useState<string | null>(openSku);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => setSelected(openSku), [openSku]);

  const load = useCallback(() => {
    wms
      .items({ q, category, abc, filter, limit: PAGE, offset })
      .then((d) => {
        setData(d);
        setError(null);
      })
      .catch((e: Error) => setError(e.message));
  }, [q, category, abc, filter, offset]);

  useEffect(() => {
    load();
    const id = setInterval(load, 5000);
    return () => clearInterval(id);
  }, [load]);

  const onScan = async (code: string) => {
    try {
      const r = await wms.scan(code);
      if (r.item) setSelected(r.item.sku);
      else setQ(code);
    } catch (e) {
      setError((e as Error).message);
    }
  };

  return (
    <div className="grid items-start gap-4 lg:grid-cols-[minmax(0,1fr)_minmax(380px,42%)]">
      <Panel title={`Items${data ? ` (${data.total.toLocaleString()})` : ""}`}>
        <div className="mb-3 grid gap-2 md:grid-cols-[1fr_auto_auto]">
          <ScanBox onScan={onScan} placeholder="Scan an item barcode (EAN-13 / GS1-128)" />
          <input
            className={input}
            value={q}
            onChange={(e) => {
              setQ(e.target.value);
              setOffset(0);
            }}
            placeholder="Search SKU, name, GTIN"
            aria-label="Search items"
          />
          <div className="flex gap-2">
            <select
              className={input}
              value={category}
              onChange={(e) => setCategory(e.target.value)}
              aria-label="Category"
            >
              <option value="">All categories</option>
              {CATEGORIES.map((c) => (
                <option key={c}>{c}</option>
              ))}
            </select>
            <select className={input} value={abc} onChange={(e) => setAbc(e.target.value)} aria-label="ABC class">
              <option value="">ABC</option>
              <option>A</option>
              <option>B</option>
              <option>C</option>
            </select>
          </div>
        </div>
        <div className="mb-3 flex flex-wrap gap-1.5">
          {FILTERS.map(([value, label]) => (
            <button
              key={value}
              onClick={() => {
                setFilter(value);
                setOffset(0);
              }}
              className={`rounded-full border px-2.5 py-0.5 text-xs ${
                filter === value ? "border-accent bg-accent/15" : "border-border text-muted"
              }`}
            >
              {label}
            </button>
          ))}
        </div>
        <ErrorNote text={error} />
        <div className="max-h-[62vh] overflow-auto">
          <table className="w-full text-sm">
            <thead className="sticky top-0 bg-surface">
              <tr>
                <th className={th}>SKU</th>
                <th className={th}>Item</th>
                <th className={th}>ABC</th>
                <th className={`${th} text-right`}>On hand</th>
                <th className={`${th} text-right`}>Allocated</th>
                <th className={`${th} text-right`}>ATP</th>
                <th className={`${th} text-right`}>Pick face</th>
                <th className={`${th} text-right`}>Reserve</th>
                <th className={`${th} text-right`}>On order</th>
              </tr>
            </thead>
            <tbody>
              {data?.items.map((it) => (
                <tr
                  key={it.sku}
                  onClick={() => setSelected(it.sku)}
                  className={`cursor-pointer border-t border-border hover:bg-canvas ${selected === it.sku ? "bg-accent/10" : ""}`}
                >
                  <td className={`${td} whitespace-nowrap font-mono text-xs`}>{it.sku}</td>
                  <td className={td}>
                    {it.name}
                    <div className="text-[11px] text-muted">
                      {it.category}
                      {it.expiry_controlled && " · expiry"}
                      {it.serial_controlled && " · serials"}
                    </div>
                  </td>
                  <td className={td}>
                    <Badge value={it.abc} />
                  </td>
                  <td className={`${td} tabular text-right`}>{it.on_hand}</td>
                  <td className={`${td} tabular text-right`}>{it.allocated}</td>
                  <td className={`${td} tabular text-right font-semibold ${it.atp <= 0 ? "text-danger" : ""}`}>
                    {it.atp}
                  </td>
                  <td className={`${td} tabular text-right ${it.pick_face < it.pick_min ? "text-warning" : ""}`}>
                    {it.pick_face}/{it.pick_max}
                  </td>
                  <td className={`${td} tabular text-right`}>{it.reserve}</td>
                  <td className={`${td} tabular text-right`}>{it.on_order || ""}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        {data && data.total > PAGE && (
          <div className="mt-2 flex items-center justify-end gap-2 text-xs text-muted">
            {offset + 1}-{Math.min(offset + PAGE, data.total)} of {data.total}
            <button className={ghost} disabled={offset === 0} onClick={() => setOffset(Math.max(0, offset - PAGE))}>
              Previous
            </button>
            <button className={ghost} disabled={offset + PAGE >= data.total} onClick={() => setOffset(offset + PAGE)}>
              Next
            </button>
          </div>
        )}
      </Panel>
      {selected && (
        <div className="lg:sticky lg:top-0 lg:max-h-[calc(100vh-150px)] lg:overflow-auto">
          <ItemPanel sku={selected} user={user} onClose={() => setSelected(null)} />
        </div>
      )}
    </div>
  );
}

function ItemPanel({ sku, user, onClose }: { sku: string; user: string; onClose: () => void }) {
  const [d, setD] = useState<WmsItemDetail | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [note, setNote] = useState<string | null>(null);
  const load = useCallback(
    () =>
      wms
        .item(sku)
        .then(setD)
        .catch((e: Error) => setError(e.message)),
    [sku],
  );
  useEffect(() => {
    void load();
    const id = setInterval(load, 4000);
    return () => clearInterval(id);
  }, [load]);

  const act = async (fn: () => Promise<unknown>, done: string) => {
    try {
      await fn();
      setNote(done);
      setError(null);
      void load();
    } catch (e) {
      setError((e as Error).message);
    }
  };

  if (!d) return <Panel title={sku}>{error ? <ErrorNote text={error} /> : "Loading…"}</Panel>;
  return (
    <Panel
      title={`${d.sku} · ${d.name}`}
      actions={
        <button onClick={onClose} aria-label="Close" className="text-muted hover:text-ink">
          <X size={16} />
        </button>
      }
    >
      <div className="flex flex-wrap items-end gap-4">
        <div>
          <Barcode kind="ean13" value={d.gtin} height={64} />
          <div className="mt-1 font-mono text-[11px] text-muted">GTIN {d.gtin}</div>
        </div>
        <div className="grid flex-1 grid-cols-2 gap-x-4 gap-y-0.5 text-xs">
          <span className="text-muted">Home pick face</span>
          <span className="font-mono">{d.home}</span>
          <span className="text-muted">Case</span>
          <span>
            {d.item.case_qty} units · GTIN-14 {d.item.case_gtin}
          </span>
          <span className="text-muted">Supplier</span>
          <span>
            {d.supplier.name} ({d.supplier.lead_time_hours.join("-")} h)
          </span>
          <span className="text-muted">Unit cost · weight</span>
          <span>
            ${d.unit_cost.toFixed(2)} · {d.item.weight_kg} kg
          </span>
          <span className="text-muted">Shelf life</span>
          <span>{d.item.shelf_life_days ? `${d.item.shelf_life_days} days (FEFO)` : "not expiry-controlled"}</span>
          {d.serial_controlled && (
            <>
              <span className="text-muted">Serials in stock</span>
              <span>{d.serials_in_stock}</span>
            </>
          )}
        </div>
      </div>

      <div className="mt-3 grid grid-cols-4 gap-2 text-center text-xs">
        {[
          ["On hand", d.on_hand],
          ["Allocated", d.allocated],
          ["Available to promise", d.atp],
          ["On order", d.on_order],
          ["Demand / hour", d.demand_per_hour],
          ["Reorder point", d.reorder_point],
          ["Order-up-to", d.order_up_to],
          ["Pick face min / max", `${d.pick_min} / ${d.pick_max}`],
        ].map(([label, v]) => (
          <div key={label as string} className="rounded-control bg-canvas p-2">
            <div className="tabular text-base font-semibold">{v}</div>
            <div className="text-muted">{label}</div>
          </div>
        ))}
      </div>

      <h3 className="mb-1 mt-4 text-xs font-semibold uppercase tracking-wide text-muted">Stock by location and lot</h3>
      <div className="overflow-x-auto">
        <table className="w-full text-xs">
          <thead>
            <tr>
              <th className={th}>Location</th>
              <th className={th}>Lot</th>
              <th className={th}>Expiry</th>
              <th className={th}>Status</th>
              <th className={th}>Plate (SSCC)</th>
              <th className={`${th} text-right`}>Qty</th>
              <th className={`${th} text-right`}>Alloc.</th>
            </tr>
          </thead>
          <tbody>
            {d.stock.map((r, i) => (
              <tr key={i} className="border-t border-border">
                <td className={`${td} font-mono`}>{r.location}</td>
                <td className={`${td} font-mono`}>{r.lot}</td>
                <td className={td}>{r.expiry ?? "–"}</td>
                <td className={td}>
                  <Badge value={r.status} />
                </td>
                <td className={`${td} font-mono text-[10px]`}>{r.lpn ?? ""}</td>
                <td className={`${td} tabular text-right`}>{r.qty}</td>
                <td className={`${td} tabular text-right`}>{r.allocated || ""}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {d.purchase_orders.length > 0 && (
        <p className="mt-2 text-xs text-muted">
          On order:{" "}
          {d.purchase_orders
            .map((p) => `${p.po_id} (${p.qty - p.received} units, ${p.status.toLowerCase()})`)
            .join(", ")}
        </p>
      )}

      <div className="mt-4 flex flex-wrap gap-2">
        <button
          type="button"
          className={`${ghost} flex items-center gap-1`}
          onClick={() => void wms.openLabel(`items/${d.sku}`)}
        >
          <Printer size={14} /> Item label
        </button>
        <Can permission="wms:count">
          <button className={ghost} onClick={() => act(() => wms.createCount(d.home), `Count created for ${d.home}`)}>
            Count pick face
          </button>
        </Can>
        <Can permission="wms:hold">
          {d.on_hold > 0 ? (
            <button
              className={ghost}
              onClick={() =>
                act(() => wms.hold({ sku: d.sku, reason: "released by operator", release: true, user }), "Released")
              }
            >
              Release hold
            </button>
          ) : (
            <button
              className={ghost}
              onClick={() => act(() => wms.hold({ sku: d.sku, reason: "operator hold", release: false, user }), "Held")}
            >
              Hold all stock
            </button>
          )}
        </Can>
      </div>
      {note && <p className="mt-2 text-xs text-success">{note}</p>}
      <ErrorNote text={error} />

      <h3 className="mb-1 mt-4 text-xs font-semibold uppercase tracking-wide text-muted">Recent transactions</h3>
      <div className="max-h-64 overflow-auto">
        <table className="w-full text-xs">
          <tbody>
            {d.transactions.map((t) => (
              <tr key={t.txn_id} className="border-t border-border">
                <td className={`${td} whitespace-nowrap font-mono text-muted`}>{clock(t.tick)}</td>
                <td className={td}>
                  <Badge value={t.type} />
                </td>
                <td className={`${td} tabular text-right`}>{t.qty}</td>
                <td className={`${td} font-mono`}>
                  {t.from_loc ?? ""} {t.to_loc ? `→ ${t.to_loc}` : ""}
                </td>
                <td className={td}>{t.reason ?? t.ref ?? ""}</td>
                <td className={`${td} text-muted`}>{t.user}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </Panel>
  );
}
