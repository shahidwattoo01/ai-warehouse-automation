"use client";

import { Truck } from "lucide-react";
import { useCallback, useEffect, useState } from "react";
import { Badge, ErrorNote, Panel, ScanBox, td, th } from "@/components/wms/shared";
import { useCan } from "@/lib/auth";
import { outbound, type Backorder, type Carton, type Trip, type TripManifest, type Wave } from "@/lib/outbound";

type Result = (m: { ok: boolean; text: string }) => void;

/** Shipping docks: the next truck of every carrier with its cut-off, cartons waiting in the sort
 *  lanes, load-by-scan, and the manifests of trucks that have left. */
export function Shipping({ onResult }: { onResult: Result }) {
  const [trips, setTrips] = useState<Trip[]>([]);
  const [lanes, setLanes] = useState<Carton[]>([]);
  const [manifest, setManifest] = useState<TripManifest | null>(null);
  const [error, setError] = useState<string | null>(null);
  const canShip = useCan("wms:ship");

  const load = useCallback(async () => {
    try {
      const [t, l] = await Promise.all([outbound.trips(), outbound.cartons("IN_LANE")]);
      setTrips(t);
      setLanes(l);
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

  const next = Object.values(
    trips
      .filter((t) => t.status === "SCHEDULED")
      .reduce<Record<string, Trip>>((acc, t) => {
        if (!acc[t.carrier] || t.departs < acc[t.carrier].departs) acc[t.carrier] = t;
        return acc;
      }, {}),
  ).sort((a, b) => a.departs - b.departs);
  const departed = trips.filter((t) => t.status === "DEPARTED").sort((a, b) => b.departs - a.departs);

  return (
    <div className="space-y-4">
      <ErrorNote text={error} />
      <div className="grid gap-3 md:grid-cols-3">
        {next.map((t) => {
          const inLane = lanes.filter((c) => c.carrier === t.carrier).length;
          return (
            <section key={t.trip_id} className="rounded-card border border-border bg-surface p-4">
              <div className="flex items-center gap-2">
                <Truck size={18} className="text-accent" />
                <div className="font-semibold">{t.carrier_name}</div>
                <span className="ml-auto text-xs text-muted">
                  {t.service} · {t.door}
                </span>
              </div>
              <div className="mt-2 text-2xl font-semibold">{t.departs_at.slice(-5)}</div>
              <div className={`text-xs ${t.minutes_to_departure < 45 ? "text-danger" : "text-muted"}`}>
                leaves in {t.minutes_to_departure} min · cut-off {t.cutoff_at.slice(-5)}
              </div>
              <dl className="mt-3 grid grid-cols-3 gap-2 text-center text-xs">
                <div>
                  <dt className="text-muted">Loaded</dt>
                  <dd className="text-lg font-semibold">{t.cartons_loaded}</dd>
                </div>
                <div>
                  <dt className="text-muted">In lane</dt>
                  <dd className="text-lg font-semibold">{inLane}</dd>
                </div>
                <div>
                  <dt className="text-muted">Orders on board</dt>
                  <dd className="text-lg font-semibold">
                    {t.orders_on_board}
                    {t.orders_waiting > 0 && (
                      <span className="text-xs font-normal text-warning"> +{t.orders_waiting} to come</span>
                    )}
                  </dd>
                </div>
              </dl>
            </section>
          );
        })}
      </div>

      <div className="grid items-start gap-4 lg:grid-cols-2">
        <Panel title={`Sort lanes (${lanes.length} cartons)`}>
          {canShip && (
            <div className="mb-3">
              <ScanBox
                onScan={async (code) => {
                  try {
                    const c = await outbound.load(code);
                    onResult({ ok: true, text: `${c.sscc} loaded on ${c.trip}` });
                    await load();
                  } catch (e) {
                    onResult({ ok: false, text: (e as Error).message });
                  }
                }}
                placeholder="Scan a carton to load it on its truck"
              />
            </div>
          )}
          <div className="max-h-[50vh] overflow-auto">
            <table className="w-full text-xs">
              <thead className="sticky top-0 bg-surface">
                <tr>
                  <th className={th}>Lane</th>
                  <th className={th}>SSCC</th>
                  <th className={th}>Order</th>
                  <th className={th}>Weight</th>
                </tr>
              </thead>
              <tbody>
                {lanes.map((c) => (
                  <tr key={c.sscc} className="border-t border-border">
                    <td className={td}>{c.location}</td>
                    <td className={`${td} font-mono`}>{c.sscc}</td>
                    <td className={td}>{c.order_id}</td>
                    <td className={td}>{c.scale_kg} kg</td>
                  </tr>
                ))}
                {!lanes.length && (
                  <tr>
                    <td colSpan={4} className={`${td} text-muted`}>
                      The lanes are empty: everything packed is on a trailer.
                    </td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>
        </Panel>
        <Panel title="Trucks that have left">
          <table className="w-full text-xs">
            <thead>
              <tr>
                <th className={th}>Trip</th>
                <th className={th}>Left</th>
                <th className={th}>Cartons</th>
                <th className={th}>Units</th>
                <th className={th}>Weight</th>
                <th className={th}>Orders</th>
              </tr>
            </thead>
            <tbody>
              {departed.slice(0, 20).map((t) => (
                <tr
                  key={t.trip_id}
                  onClick={async () => setManifest(await outbound.trip(t.trip_id))}
                  className={`cursor-pointer border-t border-border hover:bg-accent/5 ${manifest?.trip_id === t.trip_id ? "bg-accent/10" : ""}`}
                >
                  <td className={`${td} font-mono`}>{t.trip_id}</td>
                  <td className={td}>{t.departs_at}</td>
                  <td className={td}>{t.cartons_loaded}</td>
                  <td className={td}>{t.shipped_units}</td>
                  <td className={td}>{t.weight_kg} kg</td>
                  <td className={td}>
                    {t.orders_on_board}
                    {t.orders_late > 0 && <span className="text-danger"> ({t.orders_late} late)</span>}
                  </td>
                </tr>
              ))}
              {!departed.length && (
                <tr>
                  <td colSpan={6} className={`${td} text-muted`}>
                    No truck has left yet.
                  </td>
                </tr>
              )}
            </tbody>
          </table>
          {manifest && (
            <div className="mt-3 border-t border-border pt-2">
              <div className="mb-1 flex items-center gap-2 text-[11px] uppercase text-muted">
                <span className="mr-auto">
                  Manifest {manifest.trip_id} · {manifest.carrier_name}
                </span>
                <button
                  type="button"
                  onClick={() => void outbound.manifestPdf(manifest.trip_id)}
                  className="rounded-control border border-border px-2 py-0.5 normal-case hover:border-accent"
                >
                  PDF (driver signs)
                </button>
                <button
                  type="button"
                  onClick={() => void outbound.manifestCsv(manifest.trip_id)}
                  className="rounded-control border border-border px-2 py-0.5 normal-case hover:border-accent"
                >
                  CSV
                </button>
              </div>
              <div className="max-h-64 overflow-auto">
                <table className="w-full text-xs">
                  <tbody>
                    {manifest.manifest.map((m) => (
                      <tr key={m.sscc} className="border-t border-border">
                        <td className={`${td} font-mono`}>{m.tracking}</td>
                        <td className={td}>{m.order_id}</td>
                        <td className={td}>
                          {m.customer} · {m.city}
                        </td>
                        <td className={td}>{m.weight_kg} kg</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          )}
        </Panel>
      </div>
    </div>
  );
}

/** Backorders waiting for stock and the release waves. */
export function BackordersAndWaves() {
  const [backorders, setBackorders] = useState<Backorder[]>([]);
  const [waves, setWaves] = useState<Wave[]>([]);
  useEffect(() => {
    const load = async () => {
      const [b, w] = await Promise.all([outbound.backorders("OPEN"), outbound.waves()]);
      setBackorders(b);
      setWaves(w);
    };
    void load();
    const id = setInterval(load, 5000);
    return () => clearInterval(id);
  }, []);
  return (
    <div className="grid items-start gap-4 lg:grid-cols-2">
      <Panel title={`Open backorders (${backorders.length})`}>
        <p className="mb-2 text-xs text-muted">
          Units a customer still waits for (partial shipment or short pick). When the stock is available again a
          follow-up order is created automatically.
        </p>
        <table className="w-full text-xs">
          <thead>
            <tr>
              <th className={th}>Backorder</th>
              <th className={th}>Order</th>
              <th className={th}>SKU</th>
              <th className={th}>Units</th>
              <th className={th}>Status</th>
            </tr>
          </thead>
          <tbody>
            {backorders.map((b) => (
              <tr key={b.bo_id} className="border-t border-border">
                <td className={`${td} font-mono`}>{b.bo_id}</td>
                <td className={td}>{b.order_id}</td>
                <td className={`${td} font-mono`}>{b.sku}</td>
                <td className={td}>{b.qty}</td>
                <td className={td}>
                  <Badge value={b.status} />
                </td>
              </tr>
            ))}
            {!backorders.length && (
              <tr>
                <td colSpan={5} className={`${td} text-muted`}>
                  No open backorders.
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </Panel>
      <Panel title="Release waves">
        {waves.length ? (
          <table className="w-full text-xs">
            <thead>
              <tr>
                <th className={th}>Wave</th>
                <th className={th}>Released</th>
                <th className={th}>Orders</th>
                <th className={th}>Units</th>
                <th className={th}>For trucks</th>
              </tr>
            </thead>
            <tbody>
              {waves.map((w) => (
                <tr key={w.wave_id} className="border-t border-border">
                  <td className={`${td} font-mono`}>{w.wave_id}</td>
                  <td className={td}>{w.time}</td>
                  <td className={td}>{w.orders.length}</td>
                  <td className={td}>{w.units}</td>
                  <td className={td}>{w.departures.map((d) => d.slice(-5)).join(", ")}</td>
                </tr>
              ))}
            </tbody>
          </table>
        ) : (
          <p className="text-sm text-muted">
            No waves yet. In continuous release every order goes to the robots as soon as its stock is allocated; switch
            to wave release above to group orders by truck.
          </p>
        )}
      </Panel>
    </div>
  );
}
