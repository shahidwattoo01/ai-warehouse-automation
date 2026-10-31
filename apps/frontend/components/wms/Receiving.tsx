"use client";

import { Can } from "@/components/layout/Can";
import { LabelMenu } from "./LabelMenu";
import { Truck } from "lucide-react";
import { useCallback, useEffect, useState } from "react";
import { wms, type WmsPurchaseOrder, type WmsScanResult } from "@/lib/wms";
import { Badge, button, clock, ErrorNote, ghost, input, Panel, ScanBox, td, th } from "./shared";

/**
 * Inbound: purchase orders and their trucks, and a receiving station. The receiving flow is the
 * one used with handheld scanners: scan the pallet (SSCC) → check quantity, lot, expiry, damage →
 * receive → the WMS suggests where to put it → scan the destination location → done.
 * Associates receive the same trucks automatically; plates received here are skipped by them.
 */
export function Receiving({ user }: { user: string }) {
  const [pos, setPos] = useState<WmsPurchaseOrder[]>([]);
  const [status, setStatus] = useState("");
  const [error, setError] = useState<string | null>(null);
  const load = useCallback(
    () =>
      wms
        .purchaseOrders(status || undefined)
        .then(setPos)
        .catch((e: Error) => setError(e.message)),
    [status],
  );
  useEffect(() => {
    void load();
    const id = setInterval(load, 4000);
    return () => clearInterval(id);
  }, [load]);

  return (
    <div className="grid items-start gap-4 lg:grid-cols-[minmax(0,1fr)_minmax(380px,42%)]">
      <Panel
        title="Purchase orders and trucks"
        actions={
          <select className={input} value={status} onChange={(e) => setStatus(e.target.value)} aria-label="Status">
            <option value="">All</option>
            <option value="IN_TRANSIT">In transit</option>
            <option value="AT_DOCK">At the dock</option>
            <option value="RECEIVING">Receiving</option>
            <option value="CLOSED">Closed</option>
          </select>
        }
      >
        <ErrorNote text={error} />
        <div className="max-h-[70vh] space-y-2 overflow-auto">
          {pos.length === 0 && (
            <p className="text-sm text-muted">No purchase orders yet: the planner orders every simulated hour.</p>
          )}
          {pos.map((po) => (
            <details
              key={po.po_id}
              className="rounded-control border border-border p-2 text-sm"
              open={po.status === "AT_DOCK"}
            >
              <summary className="flex cursor-pointer flex-wrap items-center gap-2">
                <span className="font-mono">{po.po_id}</span>
                <Badge value={po.status} />
                <span>{po.supplier}</span>
                {po.dock && (
                  <span className="flex items-center gap-1 text-muted">
                    <Truck size={13} /> {po.dock}
                  </span>
                )}
                <span className="ml-auto text-xs text-muted">
                  {po.plates_received}/{po.asn.length} plates · ETA {clock(po.eta)}
                </span>
              </summary>
              <table className="mt-2 w-full text-xs">
                <thead>
                  <tr>
                    <th className={th}>Plate (SSCC)</th>
                    <th className={th}>SKU</th>
                    <th className={`${th} text-right`}>Qty</th>
                    <th className={th}>Lot</th>
                    <th className={th}>Expiry</th>
                    <th className={th} />
                  </tr>
                </thead>
                <tbody>
                  {po.asn.map((p) => (
                    <tr key={p.sscc} className="border-t border-border">
                      <td className={`${td} font-mono`}>{p.sscc}</td>
                      <td className={`${td} font-mono`}>{p.sku}</td>
                      <td className={`${td} tabular text-right`}>{p.qty}</td>
                      <td className={`${td} font-mono`}>{p.lot}</td>
                      <td className={td}>{p.expiry ?? "–"}</td>
                      <td className={td}>
                        {p.received ? (
                          <Badge value="RECEIVED" />
                        ) : (
                          <LabelMenu
                            align="left"
                            kind="plates"
                            target={p.sscc}
                            text="label"
                            className="inline-flex items-center gap-1 text-accent"
                          />
                        )}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </details>
          ))}
        </div>
      </Panel>
      <div className="lg:sticky lg:top-0 lg:max-h-[calc(100vh-150px)] lg:overflow-auto">
        <Can
          permission="wms:receive"
          fallback={<Panel title="Receiving station">Receiving is done by inventory clerks and supervisors.</Panel>}
        >
          <ReceivingStation user={user} onDone={load} />
        </Can>
      </div>
    </div>
  );
}

function ReceivingStation({ user, onDone }: { user: string; onDone: () => void }) {
  const [scan, setScan] = useState<WmsScanResult | null>(null);
  const [qty, setQty] = useState("");
  const [damaged, setDamaged] = useState("0");
  const [lot, setLot] = useState("");
  const [expiry, setExpiry] = useState("");
  const [suggestion, setSuggestion] = useState<[string, number][] | null>(null);
  const [sscc, setSscc] = useState<string | null>(null);
  const [log, setLog] = useState<string[]>([]);
  const [error, setError] = useState<string | null>(null);
  const plate = scan?.plate?.asn;
  const say = (text: string) => setLog((l) => [text, ...l].slice(0, 12));

  const onScan = async (code: string) => {
    setError(null);
    try {
      const r = await wms.scan(code);
      if (sscc && r.scan.kind === "location") {
        const done = await wms.putaway({ sscc, location: r.scan.code!, user });
        say(
          `Put away ${done.moved} to ${done.to}${done.left_on_plate ? ` (${done.left_on_plate} left on the plate)` : ""}`,
        );
        if (!done.left_on_plate) {
          setSscc(null);
          setSuggestion(null);
        }
        onDone();
        return;
      }
      if (!r.plate) {
        setError(`Scan a pallet label (SSCC). That was a ${r.scan.kind}.`);
        return;
      }
      setScan(r);
      const asn = r.plate.asn;
      setQty(asn ? String(asn.qty) : "");
      setLot(asn?.lot ?? "");
      setExpiry(asn?.expiry ?? "");
      setDamaged("0");
      if (asn?.received && r.plate.stock.length) {
        setSscc(r.plate.sscc);
        setSuggestion(r.putaway_suggestion ?? null);
      } else {
        setSscc(null);
        setSuggestion(null);
      }
    } catch (e) {
      setError((e as Error).message);
    }
  };

  const receive = async () => {
    if (!plate) return;
    try {
      const r = await wms.receive({
        po_id: plate.po_id,
        sscc: plate.sscc,
        qty: Number(qty),
        damaged: Number(damaged),
        lot: lot || null,
        expiry: expiry || null,
        user,
      });
      say(r.result);
      setSscc(plate.sscc);
      setSuggestion(r.putaway_suggestion);
      setScan(null);
      onDone();
    } catch (e) {
      setError((e as Error).message);
    }
  };

  return (
    <Panel title="Receiving station">
      <ScanBox
        onScan={onScan}
        autoFocus
        placeholder={sscc ? "Scan the destination location to put away" : "Scan a pallet label (SSCC)"}
      />
      <ErrorNote text={error} />
      {plate && !plate.received && (
        <div className="mt-3 space-y-2 rounded-control border border-border p-3 text-sm">
          <div className="flex flex-wrap justify-between gap-2">
            <b className="font-mono">{plate.sscc}</b>
            <span className="text-muted">
              {plate.po_id} · {plate.dock ?? "not at a dock yet"}
            </span>
          </div>
          <div>
            {plate.sku} {scan?.item?.name ? `· ${scan.item.name}` : ""}
          </div>
          <div className="grid grid-cols-2 gap-2">
            <label className="text-xs text-muted">
              Units counted (ASN {plate.qty})
              <input
                className={`${input} w-full`}
                value={qty}
                onChange={(e) => setQty(e.target.value)}
                inputMode="numeric"
              />
            </label>
            <label className="text-xs text-muted">
              Of which damaged
              <input
                className={`${input} w-full`}
                value={damaged}
                onChange={(e) => setDamaged(e.target.value)}
                inputMode="numeric"
              />
            </label>
            <label className="text-xs text-muted">
              Lot
              <input className={`${input} w-full font-mono`} value={lot} onChange={(e) => setLot(e.target.value)} />
            </label>
            <label className="text-xs text-muted">
              Expiry
              <input
                className={`${input} w-full`}
                type="date"
                value={expiry}
                onChange={(e) => setExpiry(e.target.value)}
              />
            </label>
          </div>
          <button className={button} onClick={receive} disabled={plate.status === "IN_TRANSIT"}>
            {plate.status === "IN_TRANSIT" ? "Truck not at a dock yet" : "Receive"}
          </button>
        </div>
      )}
      {sscc && suggestion && (
        <div className="mt-3 rounded-control border border-accent/40 bg-accent/5 p-3 text-sm">
          <b>Put away plate {sscc}</b>
          <ul className="mt-1 list-disc pl-5">
            {suggestion.map(([loc, q]) => (
              <li key={loc}>
                {q} units to <span className="font-mono">{loc}</span>
              </li>
            ))}
          </ul>
          <p className="mt-1 text-xs text-muted">Scan the destination location label to confirm.</p>
          <button
            className={`${ghost} mt-2`}
            onClick={() => {
              setSscc(null);
              setSuggestion(null);
            }}
          >
            Leave it for an associate
          </button>
        </div>
      )}
      {log.length > 0 && (
        <ul className="mt-3 space-y-0.5 text-xs text-muted">
          {log.map((l, i) => (
            <li key={i}>✓ {l}</li>
          ))}
        </ul>
      )}
      <p className="mt-3 text-[11px] text-muted">
        Tip: plate numbers are in the purchase orders on the left; type <span className="font-mono">LPN</span> + the
        SSCC, or print the pallet label and scan it.
      </p>
    </Panel>
  );
}
