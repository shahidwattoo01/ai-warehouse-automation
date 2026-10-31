"use client";

import { LabelMenu } from "@/components/wms/LabelMenu";
import { useCallback, useEffect, useState } from "react";
import { Badge, ErrorNote, Panel, ScanBox, button, td, th } from "@/components/wms/shared";
import { useCan } from "@/lib/auth";
import { outbound, type Carton, type CustomerOrderRow } from "@/lib/outbound";

type Result = (m: { ok: boolean; text: string }) => void;

/** Packing stations: totes waiting for a packer, cartons that failed the weight check, and the
 *  cartons packed most recently (each with its shipping label). */
export function Packing({ onResult, autoPack }: { onResult: Result; autoPack: boolean }) {
  const [queue, setQueue] = useState<CustomerOrderRow[]>([]);
  const [cartons, setCartons] = useState<Carton[]>([]);
  const [error, setError] = useState<string | null>(null);
  const canShip = useCan("wms:ship");

  const load = useCallback(async () => {
    try {
      const [q, c] = await Promise.all([outbound.orders("AT_PACK"), outbound.cartons()]);
      setQueue(q.orders);
      setCartons(c);
      setError(null);
    } catch (e) {
      setError((e as Error).message);
    }
  }, []);

  useEffect(() => {
    void load();
    const id = setInterval(load, 3000);
    return () => clearInterval(id);
  }, [load]);

  const run = async (what: string, call: () => Promise<unknown>) => {
    try {
      await call();
      onResult({ ok: true, text: what });
      await load();
    } catch (e) {
      onResult({ ok: false, text: (e as Error).message });
    }
  };

  const failed = cartons.filter((c) => c.check === "FAIL" && c.status === "PACKED");
  return (
    <div className="grid items-start gap-4 lg:grid-cols-2">
      <div className="space-y-4">
        <Panel title={`Totes at the packing stations (${queue.length})`}>
          <p className="mb-2 text-xs text-muted">
            {autoPack
              ? "Packers at each station pack these automatically. Switch packing to manual under Inventory → Work queue to pack here yourself."
              : "Packing is manual: pack each tote here (cartons are chosen by volume and weight, then weighed)."}
          </p>
          <ErrorNote text={error} />
          <table className="w-full text-sm">
            <thead>
              <tr>
                <th className={th}>Order</th>
                <th className={th}>Station</th>
                <th className={th}>Units</th>
                <th className={th}>Truck</th>
                <th className={th} />
              </tr>
            </thead>
            <tbody>
              {queue.map((o) => (
                <tr key={o.order_id} className="border-t border-border">
                  <td className={`${td} font-mono text-xs`}>{o.order_id}</td>
                  <td className={td}>{o.station}</td>
                  <td className={td}>{o.units}</td>
                  <td className={`${td} text-xs`}>
                    {o.service} {o.departure_at}
                  </td>
                  <td className={td}>
                    {canShip && !autoPack && (
                      <button
                        className={button}
                        onClick={() => run(`${o.order_id} packed`, () => outbound.pack(o.order_id))}
                      >
                        Pack
                      </button>
                    )}
                  </td>
                </tr>
              ))}
              {!queue.length && (
                <tr>
                  <td className={`${td} text-muted`} colSpan={5}>
                    No totes waiting.
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </Panel>
        <Panel title={`Weight check failed (${failed.length})`}>
          <p className="mb-2 text-xs text-muted">
            The scale differs from the expected weight by more than 3 %: wrong or missing unit. Re-open, correct and
            weigh again (scan the carton).
          </p>
          {canShip && (
            <div className="mb-2">
              <ScanBox
                onScan={(code) => run("carton corrected and sent to its lane", () => outbound.audit(code))}
                placeholder="Scan the carton's SSCC to confirm the audit"
              />
            </div>
          )}
          {failed.map((c) => (
            <div key={c.sscc} className="flex gap-2 border-t border-border py-1 text-xs">
              <span className="font-mono">{c.sscc}</span>
              <span>{c.order_id}</span>
              <span className="text-danger">
                {c.scale_kg} kg, expected {c.weight_kg}
              </span>
            </div>
          ))}
        </Panel>
      </div>
      <Panel title="Packed cartons">
        <div className="max-h-[70vh] overflow-auto">
          <table className="w-full text-xs">
            <thead className="sticky top-0 bg-surface">
              <tr>
                <th className={th}>SSCC</th>
                <th className={th}>Order</th>
                <th className={th}>Box</th>
                <th className={th}>Weight</th>
                <th className={th}>Status</th>
                <th className={th}>Packed</th>
                <th className={th} />
              </tr>
            </thead>
            <tbody>
              {cartons.slice(0, 120).map((c) => (
                <tr key={c.sscc} className="border-t border-border">
                  <td className={`${td} font-mono`}>{c.sscc}</td>
                  <td className={td}>
                    {c.order_id}
                    {c.of > 1 && (
                      <span className="text-muted">
                        {" "}
                        ({c.seq}/{c.of})
                      </span>
                    )}
                  </td>
                  <td className={td}>{c.size}</td>
                  <td className={td}>{c.scale_kg} kg</td>
                  <td className={td}>
                    <Badge value={c.status} /> {c.check !== "PASS" && <Badge value={c.check} />}
                  </td>
                  <td className={td}>
                    {c.packed_at_time}
                    <div className="text-muted">{c.packed_by}</div>
                  </td>
                  <td className={td}>
                    <LabelMenu kind="shipping" target={c.sscc} />
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Panel>
    </div>
  );
}
