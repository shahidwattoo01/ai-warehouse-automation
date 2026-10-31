"use client";

import { Search, X } from "lucide-react";
import { LabelMenu } from "@/components/wms/LabelMenu";
import { useCallback, useEffect, useRef, useState } from "react";
import { Badge, ErrorNote, ExportButton, Panel, button, ghost, input, td, th } from "@/components/wms/shared";
import { useCan } from "@/lib/auth";
import { outbound, PIPELINE, type CustomerOrderDetail, type CustomerOrderRow } from "@/lib/outbound";

/** Customer orders from intake to truck: pipeline counts, a searchable list and the order's
 *  detail beside it, with hold / release / partial shipment / cancel for order managers. */
export function CustomerOrders({ onResult }: { onResult: (m: { ok: boolean; text: string }) => void }) {
  const [status, setStatus] = useState<string>("open");
  const [q, setQ] = useState("");
  const [rows, setRows] = useState<CustomerOrderRow[]>([]);
  const [counts, setCounts] = useState<Record<string, number>>({});
  const [open, setOpen] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const latest = useRef(0); // only the newest request may fill the list (filters change fast)

  const load = useCallback(async () => {
    const mine = ++latest.current;
    try {
      const r = await outbound.orders(status, q);
      if (mine !== latest.current) return;
      setRows(r.orders);
      setCounts(r.by_status);
      setError(null);
    } catch (e) {
      setError((e as Error).message);
    }
  }, [status, q]);

  useEffect(() => {
    void load();
    const id = setInterval(load, 4000);
    return () => clearInterval(id);
  }, [load]);

  return (
    <div className="grid items-start gap-4 lg:grid-cols-[minmax(0,1fr)_minmax(380px,40%)]">
      <Panel
        title="Customer orders"
        actions={
          <>
            <ExportButton name="orders" />
            <label className="flex items-center gap-1 rounded-control border border-border bg-canvas px-2">
              <Search size={14} className="text-muted" />
              <input
                value={q}
                onChange={(e) => setQ(e.target.value)}
                placeholder="Order, customer or city"
                className="w-48 bg-transparent py-1 text-sm outline-none"
              />
            </label>
          </>
        }
      >
        <div className="mb-3 flex flex-wrap gap-1 text-xs">
          <Chip active={status === "open"} onClick={() => setStatus("open")}>
            Open {Object.entries(counts).reduce((n, [s, c]) => n + (s === "SHIPPED" || s === "CANCELLED" ? 0 : c), 0)}
          </Chip>
          {PIPELINE.map(([s, label]) => (
            <Chip key={s} active={status === s} onClick={() => setStatus(s)}>
              {label} {counts[s] ?? 0}
            </Chip>
          ))}
        </div>
        <ErrorNote text={error} />
        <div className="max-h-[62vh] overflow-auto">
          <table className="w-full text-sm">
            <thead className="sticky top-0 bg-surface">
              <tr>
                <th className={th}>Order</th>
                <th className={th}>Status</th>
                <th className={th}>Customer</th>
                <th className={th}>Service</th>
                <th className={th}>Truck</th>
                <th className={th}>Units</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((r) => (
                <tr
                  key={r.order_id}
                  onClick={() => setOpen(r.order_id)}
                  className={`cursor-pointer border-t border-border hover:bg-accent/5 ${open === r.order_id ? "bg-accent/10" : ""}`}
                >
                  <td className={`${td} font-mono text-xs`}>
                    {r.order_id}
                    {r.parent && <span className="ml-1 text-[10px] text-muted">backorder</span>}
                    {r.external_ref && <div className="text-[10px] text-muted">ERP {r.external_ref}</div>}
                  </td>
                  <td className={td}>
                    <Badge value={r.status} />
                    {r.missed > 0 && <span className="ml-1 text-[10px] text-danger">missed {r.missed}</span>}
                  </td>
                  <td className={td}>
                    <div className="truncate">{r.customer}</div>
                    <div className="text-[11px] text-muted">{r.city}</div>
                  </td>
                  <td className={td}>
                    {r.service}
                    <div className="text-[11px] text-muted">{r.priority}</div>
                  </td>
                  <td className={`${td} text-xs`}>
                    {r.status === "SHIPPED" ? r.shipped_at : r.departure_at}
                    {r.status !== "SHIPPED" && r.status !== "CANCELLED" && (
                      <div className={`text-[11px] ${r.minutes_to_cutoff < 30 ? "text-danger" : "text-muted"}`}>
                        cut-off {r.minutes_to_cutoff < 0 ? "passed" : `in ${r.minutes_to_cutoff} min`}
                      </div>
                    )}
                  </td>
                  <td className={td}>{r.units}</td>
                </tr>
              ))}
              {!rows.length && (
                <tr>
                  <td className={`${td} text-muted`} colSpan={6}>
                    No orders here.
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      </Panel>
      <div className="lg:sticky lg:top-0">
        {open ? (
          <OrderDetail id={open} onClose={() => setOpen(null)} onChanged={load} onResult={onResult} />
        ) : (
          <Panel title="Order detail">
            <p className="text-sm text-muted">Select an order to see its lines, cartons, truck and history.</p>
          </Panel>
        )}
      </div>
    </div>
  );
}

function Chip({ active, onClick, children }: { active: boolean; onClick: () => void; children: React.ReactNode }) {
  return (
    <button
      onClick={onClick}
      className={`rounded-full border px-2 py-0.5 ${active ? "border-accent bg-accent/15 font-semibold" : "border-border text-muted hover:text-ink"}`}
    >
      {children}
    </button>
  );
}

function OrderDetail({
  id,
  onClose,
  onChanged,
  onResult,
}: {
  id: string;
  onClose: () => void;
  onChanged: () => void;
  onResult: (m: { ok: boolean; text: string }) => void;
}) {
  const [d, setD] = useState<CustomerOrderDetail | null>(null);
  const [reason, setReason] = useState("");
  const [asking, setAsking] = useState<"hold" | "cancel" | null>(null);
  const [error, setError] = useState<string | null>(null);
  const canManage = useCan("orders:manage");

  const load = useCallback(async () => {
    try {
      setD(await outbound.order(id));
      setError(null);
    } catch (e) {
      setError((e as Error).message);
    }
  }, [id]);

  useEffect(() => {
    void load();
    const t = setInterval(load, 4000);
    return () => clearInterval(t);
  }, [load]);

  const act = async (what: string, call: () => Promise<unknown>) => {
    try {
      await call();
      onResult({ ok: true, text: `${id}: ${what}` });
      setAsking(null);
      setReason("");
      await load();
      onChanged();
    } catch (e) {
      onResult({ ok: false, text: (e as Error).message });
    }
  };

  if (!d)
    return (
      <Panel title={id}>{error ? <ErrorNote text={error} /> : <p className="text-sm text-muted">Loading…</p>}</Panel>
    );
  const onRobot = d.robot_status === "ASSIGNED" || d.robot_status === "IN_PROGRESS";
  const can = {
    hold: ["WAITING_STOCK", "READY", "RELEASED"].includes(d.status) && !onRobot,
    releaseHold: d.status === "ON_HOLD",
    release: d.status === "READY",
    partial: d.status === "WAITING_STOCK" && d.customer_detail.allow_partial,
    cancel: ["WAITING_STOCK", "READY", "ON_HOLD", "RELEASED", "AT_PACK", "PACKED"].includes(d.status) && !onRobot,
  };

  return (
    <Panel
      title={`Order ${d.order_id}`}
      actions={
        <button onClick={onClose} aria-label="Close" className="rounded p-1 text-muted hover:text-ink">
          <X size={16} />
        </button>
      }
    >
      <div className="space-y-4 text-sm">
        <div className="flex flex-wrap items-center gap-2">
          <Badge value={d.status} />
          <span className="text-xs text-muted">
            {d.priority} · {d.source.toLowerCase()} · created {d.created_at}
          </span>
          {d.hold_reason && <span className="text-xs text-danger">hold: {d.hold_reason}</span>}
          {d.robot && <span className="text-xs text-muted">robot {d.robot}</span>}
        </div>

        <div className="grid grid-cols-2 gap-3">
          <div className="rounded-control border border-border p-2">
            <div className="text-[11px] uppercase text-muted">Ship to</div>
            <div className="font-medium">{d.customer_detail.name}</div>
            <div className="text-xs">{d.customer_detail.address}</div>
            <div className="text-xs">
              {d.customer_detail.city} {d.customer_detail.postal_code}
            </div>
            <div className="mt-1 text-[11px] text-muted">
              {d.customer_detail.kind} ·{" "}
              {d.customer_detail.allow_partial ? "accepts partial shipments" : "complete orders only"}
            </div>
          </div>
          <div className="rounded-control border border-border p-2">
            <div className="text-[11px] uppercase text-muted">Carrier</div>
            <div className="font-medium">{d.carrier_detail.name}</div>
            <div className="text-xs">
              {d.service} · door {d.carrier_detail.door}
            </div>
            <div className="text-xs">Truck {d.status === "SHIPPED" ? d.shipped_at : d.departure_at}</div>
            <div className="mt-1 text-[11px] text-muted">
              promised {d.promised_at} · robot by {d.pick_by_at}
              {d.on_time !== null && (d.on_time ? " · on time" : " · late")}
            </div>
          </div>
        </div>

        {canManage && (can.hold || can.releaseHold || can.release || can.partial || can.cancel) && (
          <div className="space-y-2">
            <div className="flex flex-wrap gap-2">
              {can.releaseHold && (
                <button className={button} onClick={() => act("hold released", () => outbound.releaseHold(id))}>
                  Release hold
                </button>
              )}
              {can.release && (
                <button className={button} onClick={() => act("released to the robots", () => outbound.release(id))}>
                  Release now
                </button>
              )}
              {can.partial && (
                <button
                  className={button}
                  onClick={() => act("partial shipment, rest on backorder", () => outbound.shipPartial(id))}
                >
                  Ship what is in stock
                </button>
              )}
              {can.hold && (
                <button className={ghost} onClick={() => setAsking("hold")}>
                  Hold
                </button>
              )}
              {can.cancel && (
                <button className={`${ghost} text-danger`} onClick={() => setAsking("cancel")}>
                  Cancel order
                </button>
              )}
            </div>
            {asking && (
              <form
                className="flex gap-2"
                onSubmit={(e) => {
                  e.preventDefault();
                  if (asking === "hold") void act("put on hold", () => outbound.hold(id, reason));
                  else void act("cancelled", () => outbound.cancel(id, reason));
                }}
              >
                <input
                  autoFocus
                  value={reason}
                  onChange={(e) => setReason(e.target.value)}
                  placeholder={asking === "hold" ? "Reason for the hold" : "Reason for cancelling"}
                  className={`${input} flex-1`}
                />
                <button className={button} disabled={reason.trim().length < 3}>
                  {asking === "hold" ? "Hold" : "Cancel order"}
                </button>
              </form>
            )}
            {["AT_PACK", "PACKED"].includes(d.status) && (
              <p className="text-[11px] text-muted">Cancelling now sends a loader to put the picked units back.</p>
            )}
          </div>
        )}

        <table className="w-full text-xs">
          <thead>
            <tr>
              <th className={th}>SKU</th>
              <th className={th}>Ordered</th>
              <th className={th}>Allocated</th>
              <th className={th}>Picked</th>
              <th className={th}>Backorder</th>
              <th className={th}>Shipped</th>
            </tr>
          </thead>
          <tbody>
            {d.order_lines.map((l) => (
              <tr key={l.line} className="border-t border-border">
                <td className={`${td} font-mono`}>{l.sku}</td>
                <td className={td}>{l.ordered}</td>
                <td className={td}>{l.allocated}</td>
                <td className={td}>
                  {l.picked}
                  {l.short > 0 && <span className="ml-1 text-danger">−{l.short}</span>}
                </td>
                <td className={td}>{l.backordered || ""}</td>
                <td className={td}>{l.shipped || ""}</td>
              </tr>
            ))}
          </tbody>
        </table>

        {d.carton_detail.length > 0 && (
          <div>
            <div className="mb-1 text-[11px] uppercase text-muted">Cartons</div>
            {d.carton_detail.map((c) => (
              <div key={c.sscc} className="flex items-center gap-2 border-t border-border py-1 text-xs">
                <span className="font-mono">{c.sscc}</span>
                <span>
                  {c.size} · {c.scale_kg} kg
                </span>
                <Badge value={c.status} />
                {c.check !== "PASS" && <Badge value={c.check} />}
                <span className="ml-auto">
                  <LabelMenu kind="shipping" target={c.sscc} />
                </span>
              </div>
            ))}
          </div>
        )}

        {d.backorders.length > 0 && (
          <div className="text-xs">
            <div className="mb-1 text-[11px] uppercase text-muted">Backorders</div>
            {d.backorders.map((b) => (
              <div key={b.bo_id} className="flex gap-2 border-t border-border py-1">
                <span className="font-mono">{b.bo_id}</span>
                <span>
                  {b.sku} × {b.qty}
                </span>
                <Badge value={b.status} />
                {b.child && <span className="text-muted">ships as {b.child}</span>}
              </div>
            ))}
          </div>
        )}

        <div>
          <div className="mb-1 text-[11px] uppercase text-muted">History</div>
          <ol className="space-y-0.5 text-xs">
            {d.history.map((h, i) => (
              <li key={i} className="flex gap-2">
                <span className="w-28 shrink-0 text-muted">{h.time}</span>
                <span className="font-medium">{h.event.replaceAll("_", " ").toLowerCase()}</span>
                <span className="text-muted">
                  {h.user !== "system" && `${h.user} · `}
                  {h.note}
                </span>
              </li>
            ))}
          </ol>
        </div>
      </div>
    </Panel>
  );
}
