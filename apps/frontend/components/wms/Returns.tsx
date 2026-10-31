"use client";

import { useCallback, useEffect, useState } from "react";
import { useCan } from "@/lib/auth";
import { wms, type WmsReturn, type WmsReturns } from "@/lib/wms";
import { Badge, ErrorNote, Panel, button, ghost, input, td, th } from "./shared";

const FILTERS: [string | undefined, string][] = [
  ["RECEIVED", "Waiting for inspection"],
  ["EXPECTED", "On the way"],
  [undefined, "All"],
];

/** Customer returns: received parcels wait on QC hold in RET-01 until someone grades them.
 *  As new or opened-but-complete goes back to its pick face; damaged or defective is scrapped. */
export function Returns() {
  const [status, setStatus] = useState<string | undefined>("RECEIVED");
  const [data, setData] = useState<WmsReturns | null>(null);
  const [open, setOpen] = useState<string | null>(null);
  const [message, setMessage] = useState<{ ok: boolean; text: string } | null>(null);
  const canInspect = useCan("wms:receive");

  const load = useCallback(async () => {
    try {
      setData(await wms.returns(status));
    } catch (e) {
      setMessage({ ok: false, text: (e as Error).message });
    }
  }, [status]);

  useEffect(() => {
    void load();
    const id = setInterval(load, 5000);
    return () => clearInterval(id);
  }, [load]);

  const inspect = async (r: WmsReturn, condition: string, note: string) => {
    try {
      const done = await wms.inspectReturn(r.rma_id, condition, note || undefined);
      setMessage({ ok: true, text: `${r.rma_id}: ${done.status.toLowerCase()}` });
      setOpen(null);
      await load();
    } catch (e) {
      setMessage({ ok: false, text: (e as Error).message });
    }
  };

  return (
    <Panel
      title="Customer returns"
      actions={
        <div className="flex gap-1 text-xs">
          {FILTERS.map(([value, label]) => (
            <button
              key={label}
              onClick={() => setStatus(value)}
              className={`rounded-full border px-2 py-0.5 ${status === value ? "border-accent bg-accent/15 font-semibold" : "border-border text-muted"}`}
            >
              {label} {value ? (data?.by_status[value] ?? 0) : ""}
            </button>
          ))}
        </div>
      }
    >
      {data && (
        <p className="mb-3 text-xs text-muted">
          {data.auto_inspection
            ? "Associates inspect returns automatically. Switch return inspection to manual under Work queue to grade them here."
            : "Returns are inspected by hand: grade each parcel below."}{" "}
          Grades:{" "}
          {Object.entries(data.conditions)
            .map(([k, c]) => `${k.toLowerCase()} (${c.label}) → ${c.restock ? "restock" : "scrap"}`)
            .join(" · ")}
          .
        </p>
      )}
      {message && (
        <div className={`mb-2 text-sm ${message.ok ? "text-success" : ""}`}>
          {message.ok ? message.text : <ErrorNote text={message.text} />}
        </div>
      )}
      <div className="max-h-[65vh] overflow-auto">
        <table className="w-full text-sm">
          <thead className="sticky top-0 bg-surface">
            <tr>
              <th className={th}>Return</th>
              <th className={th}>Item</th>
              <th className={th}>Customer · order</th>
              <th className={th}>Reason given</th>
              <th className={th}>Status</th>
              <th className={th}>Inspection</th>
            </tr>
          </thead>
          <tbody>
            {data?.returns.map((r) => (
              <Row
                key={r.rma_id}
                r={r}
                open={open === r.rma_id}
                onOpen={() => setOpen(open === r.rma_id ? null : r.rma_id)}
                canInspect={canInspect}
                conditions={data.conditions}
                onInspect={inspect}
              />
            ))}
            {data && !data.returns.length && (
              <tr>
                <td colSpan={6} className={`${td} text-muted`}>
                  No returns here.
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
    </Panel>
  );
}

function Row({
  r,
  open,
  onOpen,
  canInspect,
  conditions,
  onInspect,
}: {
  r: WmsReturn;
  open: boolean;
  onOpen: () => void;
  canInspect: boolean;
  conditions: WmsReturns["conditions"];
  onInspect: (r: WmsReturn, condition: string, note: string) => void;
}) {
  const [note, setNote] = useState("");
  return (
    <>
      <tr className="border-t border-border">
        <td className={`${td} font-mono text-xs`}>{r.rma_id}</td>
        <td className={td}>
          <div className="truncate">{r.item}</div>
          <div className="font-mono text-[11px] text-muted">
            {r.sku} · {r.qty} unit{r.qty === 1 ? "" : "s"}
          </div>
        </td>
        <td className={td}>
          <div>{r.customer ?? "—"}</div>
          <div className="font-mono text-[11px] text-muted">{r.order_id}</div>
        </td>
        <td className={`${td} text-xs`}>{r.reason}</td>
        <td className={td}>
          <Badge value={r.status} />
          <div className="text-[11px] text-muted">
            {r.status === "EXPECTED" ? `due ${r.due_at}` : r.received_at_time && `in ${r.received_at_time}`}
          </div>
        </td>
        <td className={`${td} text-xs`}>
          {r.condition ? (
            <>
              <b>{r.condition.toLowerCase()}</b> by {r.inspected_by}
              {r.note && <div className="text-muted">{r.note}</div>}
            </>
          ) : r.status === "RECEIVED" && canInspect ? (
            <button className={ghost} onClick={onOpen}>
              {open ? "Close" : "Inspect"}
            </button>
          ) : (
            <span className="text-muted">—</span>
          )}
        </td>
      </tr>
      {open && (
        <tr className="bg-accent/5">
          <td colSpan={6} className="px-2 py-2">
            <div className="flex flex-wrap items-center gap-2">
              <input
                value={note}
                onChange={(e) => setNote(e.target.value)}
                placeholder="Note (optional): what you found"
                className={`${input} min-w-[16rem] flex-1`}
              />
              {Object.entries(conditions).map(([k, c]) => (
                <button
                  key={k}
                  onClick={() => onInspect(r, k, note)}
                  title={`${c.label}: ${c.restock ? "back to its pick face" : "scrapped (RETURN_SCRAP)"}`}
                  className={c.restock ? button : `${ghost} text-danger`}
                >
                  {k.charAt(0) + k.slice(1).toLowerCase()}
                </button>
              ))}
            </div>
          </td>
        </tr>
      )}
    </>
  );
}
