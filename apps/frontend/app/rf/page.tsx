"use client";

import { ArrowLeft, CheckCircle2, MapPin, PackageSearch, Shuffle, XCircle } from "lucide-react";
import Link from "next/link";
import { useCallback, useEffect, useState } from "react";
import { EStopButton } from "@/components/layout/EStop";
import { ScanBox } from "@/components/wms/shared";
import { useAuth, useCan } from "@/lib/auth";
import { rf, RF_LABEL, type RfSummary, type RfTask } from "@/lib/rf";
import { wms, type WmsScanResult, type WmsStockRow } from "@/lib/wms";

type View = { name: "menu" } | { name: "task"; types?: string[] } | { name: "move" } | { name: "lookup" };

const big = "w-full rounded-card px-4 py-4 text-left text-lg font-semibold";

function buzz(ok: boolean) {
  try {
    navigator.vibrate?.(ok ? 60 : [120, 60, 120]); // handhelds: feel the result without looking
  } catch {
    /* not supported */
  }
}

/** Handheld screens for floor staff: one task at a time, confirmed by scanning. */
export default function HandheldPage() {
  const [view, setView] = useState<View>({ name: "menu" });
  const user = useAuth((s) => s.user);
  return (
    <div className="flex min-h-screen flex-col bg-canvas">
      <header className="flex items-center gap-2 border-b border-border bg-surface px-3 py-2">
        {view.name === "menu" ? (
          <Link href={user?.home ?? "/"} className="rounded p-2 text-muted" aria-label="Back to the control center">
            <ArrowLeft size={18} />
          </Link>
        ) : (
          <button onClick={() => setView({ name: "menu" })} className="rounded p-2 text-muted" aria-label="Menu">
            <ArrowLeft size={18} />
          </button>
        )}
        <div className="min-w-0 flex-1 leading-tight">
          <div className="font-semibold">Handheld</div>
          <div className="truncate text-xs text-muted">{user?.full_name}</div>
        </div>
        <EStopButton />
      </header>
      <main className="mx-auto w-full max-w-md flex-1 p-3">
        {view.name === "menu" && <Menu go={setView} />}
        {view.name === "task" && <TaskFlow types={view.types} done={() => setView({ name: "menu" })} />}
        {view.name === "move" && <MoveFlow />}
        {view.name === "lookup" && <Lookup />}
      </main>
    </div>
  );
}

function Menu({ go }: { go: (v: View) => void }) {
  const [s, setS] = useState<RfSummary | null>(null);
  const canMove = useCan("wms:move");
  useEffect(() => {
    const load = () =>
      rf
        .summary()
        .then(setS)
        .catch(() => undefined);
    void load();
    const id = setInterval(load, 4000);
    return () => clearInterval(id);
  }, []);
  const types = Object.keys(s?.open ?? {});
  return (
    <div className="space-y-2">
      {s?.my_task && (
        <button onClick={() => go({ name: "task" })} className={`${big} bg-warning text-white`}>
          Continue my task {s.my_task}
        </button>
      )}
      {types.length > 0 && (
        <button onClick={() => go({ name: "task" })} className={`${big} bg-accent text-white`}>
          Next task <span className="float-right">{Object.values(s!.open).reduce((a, b) => a + b, 0)}</span>
        </button>
      )}
      {types.map((t) => (
        <button
          key={t}
          onClick={() => go({ name: "task", types: [t] })}
          className={`${big} border border-border bg-surface`}
        >
          {RF_LABEL[t] ?? t}
          <span className="float-right tabular">{s!.open[t]}</span>
          {s!.auto[t] && <div className="text-xs font-normal text-muted">associates also do this automatically</div>}
        </button>
      ))}
      {canMove && (
        <button onClick={() => go({ name: "move" })} className={`${big} border border-border bg-surface`}>
          <Shuffle size={18} className="mr-2 inline" /> Move stock
        </button>
      )}
      <button onClick={() => go({ name: "lookup" })} className={`${big} border border-border bg-surface`}>
        <PackageSearch size={18} className="mr-2 inline" /> Look up a barcode
      </button>
      {s && !types.length && <p className="p-2 text-sm text-muted">Your role has no handheld tasks.</p>}
    </div>
  );
}

function Result({ ok, text, next, back }: { ok: boolean; text: string; next?: () => void; back?: () => void }) {
  return (
    <div className={`rounded-card p-5 text-white ${ok ? "bg-success" : "bg-danger"}`} role="status">
      <div className="flex items-center gap-2 text-lg font-semibold">
        {ok ? <CheckCircle2 /> : <XCircle />} {ok ? "Done" : "Not done"}
      </div>
      <p className="mt-1">{text}</p>
      <div className="mt-4 flex gap-2">
        {next && (
          <button onClick={next} className="flex-1 rounded-control bg-white/90 py-3 font-semibold text-ink">
            {ok ? "Next task" : "Try again"}
          </button>
        )}
        {back && (
          <button onClick={back} className="rounded-control border border-white/70 px-4 py-3">
            Menu
          </button>
        )}
      </div>
    </div>
  );
}

function TaskFlow({ types, done }: { types?: string[]; done: () => void }) {
  const [task, setTask] = useState<RfTask | null | undefined>(undefined);
  const [values, setValues] = useState<Record<string, number | null>>({});
  const [scan, setScan] = useState("");
  const [result, setResult] = useState<{ ok: boolean; text: string } | null>(null);

  const next = useCallback(async () => {
    setResult(null);
    setScan("");
    try {
      const t = (await rf.next(types)).task;
      setTask(t);
      setValues(Object.fromEntries((t?.inputs ?? []).map((i) => [i.name, i.default])));
    } catch (e) {
      setResult({ ok: false, text: (e as Error).message });
    }
  }, [types]);

  useEffect(() => {
    void next();
  }, [next]);

  const confirm = async (scanned: string) => {
    if (!task) return;
    try {
      const r = await rf.confirm(task.task_id, scanned, values);
      buzz(true);
      setResult({ ok: true, text: r.result });
    } catch (e) {
      buzz(false);
      setResult({ ok: false, text: (e as Error).message });
    }
  };

  if (result) {
    return <Result ok={result.ok} text={result.text} next={result.ok ? next : () => setResult(null)} back={done} />;
  }
  if (task === undefined) return <p className="p-2 text-muted">Getting your task…</p>;
  if (task === null) {
    return (
      <div className="rounded-card border border-border bg-surface p-5">
        <p className="font-semibold">Nothing to do here right now.</p>
        <div className="mt-3 flex gap-2">
          <button onClick={next} className="flex-1 rounded-control bg-accent py-3 text-white">
            Check again
          </button>
          <button onClick={done} className="rounded-control border border-border px-4 py-3">
            Menu
          </button>
        </div>
      </div>
    );
  }
  const needsInput = task.inputs.length > 0;
  return (
    <div className="space-y-3">
      <div className="rounded-card border border-border bg-surface p-4">
        <div className="text-xs uppercase tracking-wide text-muted">
          {task.title} · {task.task_id}
        </div>
        {task.go_to && (
          <div className="mt-1 flex items-center gap-2 font-mono text-3xl font-bold">
            <MapPin size={22} className="text-accent" /> {task.go_to}
          </div>
        )}
        <ol className="mt-2 list-decimal space-y-1 pl-5 text-sm">
          {task.steps.map((s, i) => (
            <li key={i}>{s}</li>
          ))}
        </ol>
      </div>
      {task.inputs.map((i) => (
        <label key={i.name} className="block">
          <span className="text-sm text-muted">{i.label}</span>
          <input
            type="number"
            inputMode="numeric"
            min={0}
            value={values[i.name] ?? ""}
            onChange={(e) => setValues({ ...values, [i.name]: e.target.value === "" ? null : Number(e.target.value) })}
            className="mt-1 w-full rounded-control border border-border bg-surface px-3 py-3 text-2xl tabular outline-none focus:border-accent"
          />
        </label>
      ))}
      {task.scan && (
        <div>
          <div className="mb-1 text-sm font-medium">{task.scan.label}</div>
          <ScanBox
            autoFocus={!needsInput}
            placeholder="Scan to confirm"
            onScan={(code) => (needsInput ? setScan(code) : void confirm(code))}
          />
          {needsInput && scan && <div className="mt-1 font-mono text-xs text-muted">scanned {scan}</div>}
        </div>
      )}
      {needsInput && (
        <button
          disabled={!!task.scan && !scan}
          onClick={() => void confirm(scan)}
          className="w-full rounded-control bg-accent py-4 text-lg font-semibold text-white disabled:opacity-40"
        >
          Confirm
        </button>
      )}
      <button
        onClick={async () => {
          await rf.release(task.task_id).catch(() => undefined);
          done();
        }}
        className="w-full rounded-control border border-border py-3 text-sm text-muted"
      >
        Skip: give the task back
      </button>
    </div>
  );
}

function MoveFlow() {
  const user = useAuth((s) => s.user?.username ?? "");
  const [from, setFrom] = useState<string | null>(null);
  const [rows, setRows] = useState<WmsStockRow[]>([]);
  const [row, setRow] = useState<WmsStockRow | null>(null);
  const [qty, setQty] = useState(1);
  const [result, setResult] = useState<{ ok: boolean; text: string } | null>(null);
  const reset = () => {
    setFrom(null);
    setRows([]);
    setRow(null);
    setResult(null);
  };
  if (result) return <Result ok={result.ok} text={result.text} next={reset} />;
  if (!from) {
    return (
      <div className="space-y-2">
        <p className="font-semibold">1 · Scan the location you take stock from</p>
        <ScanBox
          autoFocus
          onScan={async (code) => {
            const r = await wms.scan(code).catch(() => null);
            if (!r?.location) {
              buzz(false);
              setResult({ ok: false, text: `${code} is not a location` });
              return;
            }
            setFrom(r.location.code);
            setRows((r.location.stock ?? []).filter((s) => s.status === "AVAILABLE"));
          }}
        />
      </div>
    );
  }
  if (!row) {
    return (
      <div className="space-y-2">
        <p className="font-semibold">2 · What do you take from {from}?</p>
        {rows.map((r, i) => (
          <button
            key={i}
            onClick={() => {
              setRow(r);
              setQty(Math.min(r.qty, 1));
            }}
            className={`${big} border border-border bg-surface text-base`}
          >
            {r.sku} · lot {r.lot} <span className="float-right">{r.qty}</span>
            {r.lpn && <div className="font-mono text-xs font-normal text-muted">plate {r.lpn}</div>}
          </button>
        ))}
        {!rows.length && <p className="text-sm text-muted">No available stock at {from}.</p>}
      </div>
    );
  }
  return (
    <div className="space-y-3">
      <p className="font-semibold">
        3 · How many of {row.sku} (max {row.qty}), then scan where they go
      </p>
      <input
        type="number"
        inputMode="numeric"
        min={1}
        max={row.qty}
        value={qty}
        onChange={(e) => setQty(Number(e.target.value))}
        className="w-full rounded-control border border-border bg-surface px-3 py-3 text-2xl tabular"
      />
      <ScanBox
        placeholder="Scan the destination location"
        onScan={async (to) => {
          try {
            await wms.move({
              sku: row.sku,
              qty,
              from_location: from,
              to_location: to.toUpperCase(),
              lot: row.lot,
              user,
            });
            buzz(true);
            setResult({ ok: true, text: `${qty} × ${row.sku} moved from ${from} to ${to.toUpperCase()}` });
          } catch (e) {
            buzz(false);
            setResult({ ok: false, text: (e as Error).message });
          }
        }}
      />
    </div>
  );
}

function Lookup() {
  const [r, setR] = useState<WmsScanResult | null>(null);
  const [error, setError] = useState<string | null>(null);
  return (
    <div className="space-y-3">
      <ScanBox
        autoFocus
        placeholder="Scan an item, location, plate or carton"
        onScan={async (code) => {
          try {
            setR(await wms.scan(code));
            setError(null);
          } catch (e) {
            setError((e as Error).message);
          }
        }}
      />
      {error && <p className="text-danger">{error}</p>}
      {r && (
        <div className="space-y-2 rounded-card border border-border bg-surface p-4 text-sm">
          {r.scan.errors?.length ? <p className="text-danger">{r.scan.errors.join(", ")}</p> : null}
          {r.item && (
            <div>
              <div className="text-lg font-semibold">{r.item.name}</div>
              <div className="font-mono text-xs">
                {r.item.sku} · pick face {r.item.home}
              </div>
              <div className="mt-1">
                Available to promise <b>{r.item.atp}</b> · on hand {r.item.on_hand} · pick face {r.item.pick_face}
              </div>
            </div>
          )}
          {r.location && (
            <div>
              <div className="font-mono text-lg font-semibold">{r.location.code}</div>
              {(r.location.stock ?? []).map((s, i) => (
                <div key={i} className="flex justify-between border-t border-border py-1">
                  <span>
                    {s.sku} · {s.lot} {s.status !== "AVAILABLE" && `· ${s.status}`}
                  </span>
                  <b>{s.qty}</b>
                </div>
              ))}
            </div>
          )}
          {r.plate && (
            <div>
              <div className="font-mono">plate {r.plate.sscc}</div>
              {r.plate.stock.map((s, i) => (
                <div key={i}>
                  {s.qty} × {s.sku} at {s.location}
                </div>
              ))}
            </div>
          )}
          {!r.item && !r.location && !r.plate && <p className="text-muted">Nothing found for this barcode.</p>}
        </div>
      )}
    </div>
  );
}
