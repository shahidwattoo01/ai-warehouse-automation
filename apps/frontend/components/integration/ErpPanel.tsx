"use client";

import { useCallback, useEffect, useState } from "react";
import { Badge, Panel, td, th } from "@/components/wms/shared";
import { request } from "@/lib/api";
import { useCan } from "@/lib/auth";

interface ErpStatus {
  client: string;
  imported: number;
  rejected: number;
  outbox: Record<string, number>;
  last_pull: string | null;
  last_error: string | null;
  poll_minutes: number;
  webhook: boolean;
  recent_imports: { erp_number: string; wms_order_id: string }[];
  rejections: { erp_number: string; reason: string }[];
  log: { at: string; text: string }[];
  mock: {
    orders: Record<string, number>;
    received: Record<string, number>;
    stock_items: number;
    stock_updated: string | null;
    latest_orders: {
      number: string;
      customer_id: string;
      status: string;
      wms_order_id: string | null;
      reason: string | null;
    }[];
  } | null;
}

interface OutRow {
  key: string;
  kind: string;
  status: string;
  attempts: number;
  error: string | null;
  summary: string;
}

const button = "rounded-control border border-border px-2 py-0.5 text-xs hover:border-accent";

/** ERP connection: sales orders in (pull and signed webhook), confirmations and stock out (outbox). */
export function ErpPanel() {
  const [s, setS] = useState<ErpStatus | null>(null);
  const [box, setBox] = useState<OutRow[]>([]);
  const [error, setError] = useState<string | null>(null);
  const canCreate = useCan("orders:create");
  const canManage = useCan("wms:settings");

  const load = useCallback(async () => {
    try {
      const [st, ob] = await Promise.all([
        request<ErpStatus>("/erp/status"),
        request<OutRow[]>("/erp/outbox?limit=40"),
      ]);
      setS(st);
      setBox(ob);
      setError(null);
    } catch (e) {
      setError((e as Error).message);
    }
  }, []);

  useEffect(() => {
    void load();
    const id = setInterval(load, 4000);
    return () => clearInterval(id);
  }, [load]);

  const post = async (path: string, body: unknown = {}) => {
    try {
      await request(path, { method: "POST", body: JSON.stringify(body) });
      await load();
    } catch (e) {
      setError((e as Error).message);
    }
  };

  if (error && !s)
    return (
      <Panel title="ERP connection">
        <p className="text-sm text-muted">{error}</p>
      </Panel>
    );
  if (!s) return null;
  return (
    <Panel
      title={`ERP connection · ${s.client}`}
      actions={
        <div className="flex gap-1">
          {canCreate && s.mock && (
            <>
              <button className={button} onClick={() => void post("/erp/mock/orders", { service: "EXPRESS" })}>
                New express order in the ERP
              </button>
              <button className={button} onClick={() => void post("/erp/mock/orders", { service: "STANDARD" })}>
                New standard order
              </button>
            </>
          )}
          {canManage && (
            <>
              <button className={button} onClick={() => void post("/erp/pull")}>
                Pull now
              </button>
              {(s.outbox.FAILED ?? 0) > 0 && (
                <button className={button} onClick={() => void post("/erp/outbox/retry")}>
                  Retry failed
                </button>
              )}
            </>
          )}
        </div>
      }
    >
      <p className="mb-3 text-xs text-muted">
        Sales orders are pulled every {s.poll_minutes} simulated minutes
        {s.webhook ? " or pushed to the signed webhook" : " (webhook off: set ERP_WEBHOOK_SECRET)"}; each becomes a WMS
        order and is acknowledged. Ship confirmations of ERP orders and hourly stock levels go back through the outbox
        (retried until delivered).
        {s.last_pull && ` Last pull ${s.last_pull}.`}
        {s.last_error && <span className="text-danger"> {s.last_error}</span>}
      </p>
      <div className="mb-3 grid grid-cols-2 gap-2 text-sm md:grid-cols-5">
        <Mini label="Imported" value={s.imported} />
        <Mini label="Rejected" value={s.rejected} warn={s.rejected > 0} />
        <Mini label="Outbox waiting" value={s.outbox.PENDING ?? 0} warn={(s.outbox.PENDING ?? 0) > 5} />
        <Mini label="Delivered" value={s.outbox.SENT ?? 0} />
        <Mini label="Failed" value={s.outbox.FAILED ?? 0} warn={(s.outbox.FAILED ?? 0) > 0} />
      </div>
      <div className="grid gap-4 xl:grid-cols-2">
        <div>
          <div className="mb-1 text-[11px] uppercase text-muted">
            {s.mock ? "Sales orders in the mock ERP" : "Recent imports"}
          </div>
          <table className="w-full text-xs">
            <thead>
              <tr>
                <th className={th}>ERP order</th>
                <th className={th}>Status</th>
                <th className={th}>WMS order / reason</th>
              </tr>
            </thead>
            <tbody>
              {(
                s.mock?.latest_orders ??
                s.recent_imports.map((r) => ({
                  number: r.erp_number,
                  status: "ACCEPTED",
                  wms_order_id: r.wms_order_id,
                  reason: null,
                  customer_id: "",
                }))
              ).map((o) => (
                <tr key={o.number} className="border-t border-border">
                  <td className={`${td} font-mono`}>{o.number}</td>
                  <td className={td}>
                    <Badge value={o.status} />
                  </td>
                  <td className={`${td} ${o.reason ? "text-danger" : "font-mono"}`}>
                    {o.wms_order_id ?? o.reason ?? "—"}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          {s.mock && (
            <p className="mt-2 text-[11px] text-muted">
              The ERP has received {s.mock.received.shipments} ship confirmations and {s.mock.received.stock} stock
              updates ({s.mock.received.duplicates} duplicates ignored)
              {s.mock.stock_updated && `, stock of ${s.mock.stock_items} items`}.
            </p>
          )}
        </div>
        <div>
          <div className="mb-1 text-[11px] uppercase text-muted">Outbox</div>
          <div className="max-h-72 overflow-auto">
            <table className="w-full text-xs">
              <tbody>
                {box.map((m) => (
                  <tr key={m.key} className="border-t border-border">
                    <td className={td}>{m.kind}</td>
                    <td className={td}>{m.summary}</td>
                    <td
                      className={`${td} ${m.status === "FAILED" ? "text-danger" : m.status === "SENT" ? "text-success" : "text-warning"}`}
                      title={m.error ?? undefined}
                    >
                      {m.status.toLowerCase()}
                      {m.attempts > 1 && ` (${m.attempts} tries)`}
                    </td>
                  </tr>
                ))}
                {!box.length && (
                  <tr>
                    <td className={`${td} text-muted`}>Nothing sent yet.</td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>
        </div>
      </div>
    </Panel>
  );
}

function Mini({ label, value, warn = false }: { label: string; value: number; warn?: boolean }) {
  return (
    <div className="rounded-control border border-border px-2 py-1">
      <div className="text-[11px] text-muted">{label}</div>
      <div className={`font-semibold ${warn ? "text-warning" : ""}`}>{value}</div>
    </div>
  );
}
