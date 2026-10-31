"use client";

import { Can } from "@/components/layout/Can";
import { LabelMenu } from "./LabelMenu";
import { useCallback, useEffect, useState } from "react";
import { wms, type WmsLocation, type WmsStockRow } from "@/lib/wms";
import { Badge, Barcode, button, ErrorNote, ghost, input, Panel, ScanBox, td, th } from "./shared";

const TYPES = ["PICK", "RESERVE", "DOCK", "STAGING", "QUARANTINE", "RETURNS", "PACK"];

/** Location master and stock control: browse locations, then move or adjust stock at one. */
export function Locations({ user }: { user: string }) {
  const [type, setType] = useState("");
  const [zone, setZone] = useState("");
  const [q, setQ] = useState("");
  const [occupied, setOccupied] = useState(false);
  const [rows, setRows] = useState<{ total: number; locations: WmsLocation[] } | null>(null);
  const [selected, setSelected] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(
    () =>
      wms
        .locations({ type, zone, q, occupied: occupied || undefined, limit: 300 })
        .then(setRows)
        .catch((e: Error) => setError(e.message)),
    [type, zone, q, occupied],
  );
  useEffect(() => {
    void load();
  }, [load]);

  return (
    <div className="grid items-start gap-4 lg:grid-cols-[minmax(0,1fr)_minmax(380px,42%)]">
      <Panel
        title={`Locations${rows ? ` (${rows.total.toLocaleString()})` : ""}`}
        actions={
          q && (
            <LabelMenu
              align="left"
              kind="locations"
              target={q.toUpperCase()}
              text={`Labels for "${q.toUpperCase()}"`}
              className={`${ghost} flex items-center gap-1 text-xs`}
            />
          )
        }
      >
        <div className="mb-3 flex flex-wrap gap-2">
          <div className="min-w-64 flex-1">
            <ScanBox onScan={(code) => setSelected(code)} placeholder="Scan a location label" />
          </div>
          <input
            className={input}
            value={q}
            onChange={(e) => setQ(e.target.value)}
            placeholder="Code starts with… e.g. A-05"
            aria-label="Location code"
          />
          <select className={input} value={type} onChange={(e) => setType(e.target.value)} aria-label="Type">
            <option value="">All types</option>
            {TYPES.map((t) => (
              <option key={t}>{t}</option>
            ))}
          </select>
          <select className={input} value={zone} onChange={(e) => setZone(e.target.value)} aria-label="Zone">
            <option value="">All zones</option>
            {["A", "B", "C", "D"].map((z) => (
              <option key={z}>{z}</option>
            ))}
          </select>
          <label className="flex items-center gap-1 text-xs">
            <input type="checkbox" checked={occupied} onChange={(e) => setOccupied(e.target.checked)} /> occupied only
          </label>
        </div>
        <ErrorNote text={error} />
        <div className="max-h-[62vh] overflow-auto">
          <table className="w-full text-sm">
            <thead className="sticky top-0 bg-surface">
              <tr>
                <th className={th}>Location</th>
                <th className={th}>Type</th>
                <th className={th}>Zone</th>
                <th className={th}>Level</th>
                <th className={th}>Item (pick face)</th>
                <th className={th}>Check</th>
                <th className={`${th} text-right`}>Units</th>
              </tr>
            </thead>
            <tbody>
              {rows?.locations.map((l) => (
                <tr
                  key={l.code}
                  onClick={() => setSelected(l.code)}
                  className={`cursor-pointer border-t border-border hover:bg-canvas ${selected === l.code ? "bg-accent/10" : ""}`}
                >
                  <td className={`${td} font-mono`}>{l.code}</td>
                  <td className={td}>
                    <Badge value={l.type} />
                  </td>
                  <td className={td}>{l.zone ?? ""}</td>
                  <td className={td}>{l.level || ""}</td>
                  <td className={`${td} font-mono text-xs`}>{l.sku ?? ""}</td>
                  <td className={`${td} font-mono`}>{l.check}</td>
                  <td className={`${td} tabular text-right`}>{l.units}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Panel>
      {selected && (
        <div className="lg:sticky lg:top-0 lg:max-h-[calc(100vh-150px)] lg:overflow-auto">
          <LocationPanel code={selected} user={user} onChange={load} />
        </div>
      )}
    </div>
  );
}

function LocationPanel({ code, user, onChange }: { code: string; user: string; onChange: () => void }) {
  const [loc, setLoc] = useState<WmsLocation | null>(null);
  const [reasons, setReasons] = useState<Record<string, string>>({});
  const [row, setRow] = useState<WmsStockRow | null>(null);
  const [qty, setQty] = useState("1");
  const [target, setTarget] = useState("");
  const [reason, setReason] = useState("DAMAGED");
  const [error, setError] = useState<string | null>(null);
  const [note, setNote] = useState<string | null>(null);

  const load = useCallback(
    () =>
      wms
        .location(code)
        .then((l) => {
          setLoc(l);
          setError(null);
        })
        .catch((e: Error) => setError(e.message)),
    [code],
  );
  useEffect(() => {
    void load();
    wms
      .reasons()
      .then(setReasons)
      .catch(() => undefined);
  }, [load]);

  const run = async (fn: () => Promise<unknown>, done: string) => {
    try {
      await fn();
      setNote(done);
      setError(null);
      void load();
      onChange();
    } catch (e) {
      setError((e as Error).message);
    }
  };

  if (!loc) return <Panel title={code}>{error ? <ErrorNote text={error} /> : "Loading…"}</Panel>;
  const n = Number(qty);
  return (
    <Panel title={`${loc.code} · ${loc.type.toLowerCase()}`}>
      <div className="flex items-end justify-between gap-3">
        <Barcode kind="code128" value={loc.code} height={52} />
        <div className="text-right text-xs text-muted">
          check digits <div className="text-3xl font-bold text-ink">{loc.check}</div>
        </div>
      </div>
      <h3 className="mb-1 mt-3 text-xs font-semibold uppercase tracking-wide text-muted">Contents</h3>
      {loc.stock && loc.stock.length > 0 ? (
        <table className="w-full text-xs">
          <thead>
            <tr>
              <th className={th}>SKU</th>
              <th className={th}>Lot</th>
              <th className={th}>Expiry</th>
              <th className={th}>Status</th>
              <th className={`${th} text-right`}>Qty</th>
              <th className={th} />
            </tr>
          </thead>
          <tbody>
            {loc.stock.map((r, i) => (
              <tr key={i} className={`border-t border-border ${row === r ? "bg-accent/10" : ""}`}>
                <td className={`${td} font-mono`}>{r.sku}</td>
                <td className={`${td} font-mono`}>{r.lot}</td>
                <td className={td}>{r.expiry ?? "–"}</td>
                <td className={td}>
                  <Badge value={r.status} />
                </td>
                <td className={`${td} tabular text-right`}>
                  {r.qty}
                  {r.allocated ? <span className="text-muted"> ({r.allocated} alloc.)</span> : null}
                </td>
                <td className={td}>
                  <Can permission="wms:adjust">
                    <button className="text-accent" onClick={() => setRow(r)}>
                      select
                    </button>
                  </Can>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      ) : (
        <p className="text-sm text-muted">Empty.</p>
      )}

      <Can permission="wms:adjust">
        {row && (
          <div className="mt-3 space-y-3 rounded-control border border-border p-3 text-sm">
            <div className="font-medium">
              {row.sku} · lot {row.lot} {row.lpn ? `· plate ${row.lpn}` : ""}
            </div>
            <label className="block text-xs text-muted">
              Quantity
              <input
                className={`${input} ml-2 w-24`}
                value={qty}
                onChange={(e) => setQty(e.target.value)}
                inputMode="numeric"
              />
            </label>
            <div className="flex flex-wrap items-center gap-2">
              <input
                className={`${input} w-40 font-mono`}
                value={target}
                onChange={(e) => setTarget(e.target.value.toUpperCase())}
                placeholder="to location"
                aria-label="Move to location"
              />
              <button
                className={button}
                disabled={!target || !(n > 0)}
                onClick={() =>
                  run(
                    () =>
                      wms.move({
                        sku: row.sku,
                        qty: n,
                        from_location: loc.code,
                        to_location: target,
                        lot: row.lot,
                        user,
                      }),
                    `Moved ${n} to ${target}`,
                  )
                }
              >
                Move
              </button>
            </div>
            <div className="flex flex-wrap items-center gap-2">
              <select className={input} value={reason} onChange={(e) => setReason(e.target.value)} aria-label="Reason">
                {Object.entries(reasons).map(([k, v]) => (
                  <option key={k} value={k} title={v}>
                    {k.replace("_", " ").toLowerCase()}
                  </option>
                ))}
              </select>
              <button
                className={ghost}
                disabled={!(n > 0)}
                onClick={() =>
                  run(
                    () => wms.adjust({ sku: row.sku, location: loc.code, lot: row.lot, delta: -n, reason, user }),
                    `Removed ${n} (${reason})`,
                  )
                }
              >
                − Remove
              </button>
              <button
                className={ghost}
                disabled={!(n > 0)}
                onClick={() =>
                  run(
                    () => wms.adjust({ sku: row.sku, location: loc.code, lot: row.lot, delta: n, reason, user }),
                    `Added ${n} (${reason})`,
                  )
                }
              >
                + Add
              </button>
            </div>
            <p className="text-[11px] text-muted">Adjustments always need a reason and are booked under your name.</p>
          </div>
        )}
      </Can>
      {loc.type === "PICK" && (
        <Can permission="wms:count">
          <button className={`${ghost} mt-3`} onClick={() => run(() => wms.createCount(loc.code), "Count created")}>
            Create count
          </button>
        </Can>
      )}
      {note && <p className="mt-2 text-xs text-success">{note}</p>}
      <ErrorNote text={error} />
    </Panel>
  );
}
