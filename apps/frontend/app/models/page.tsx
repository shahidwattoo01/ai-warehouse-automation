"use client";

import { useCallback, useEffect, useState } from "react";
import { Screen } from "@/components/layout/Screen";
import { Badge, ErrorNote, Panel, td, th } from "@/components/wms/shared";
import { request } from "@/lib/api";
import { useCan } from "@/lib/auth";

interface Check {
  status: "NOT_ENOUGH_DATA" | "OK" | "WARN" | "DRIFT";
  samples: number;
  reasons: string[];
  psi: Record<string, number>;
  max_psi?: number;
  performance: Record<string, number | null>;
  confirmed?: number;
}

interface Version {
  version: string;
  status: string;
  created: string | null;
  trained_on: string;
  test: Record<string, number>;
  gate: { test: string; passed: boolean; detail: string }[] | null;
  reason: string | null;
  history: { at: string | null; event: string; by?: string | null }[];
}

interface ModelStatus {
  production: string;
  baseline: Record<string, number>;
  check: Check | null;
  history: { tick: number; status: string; live_mae?: number; live_recall?: number }[];
  live_rows: number;
  versions: Version[];
}

interface Status {
  models: Record<string, ModelStatus>;
  job: { model: string; status: string; reason: string; version?: string; passed?: boolean; error?: string } | null;
  events: { at: number; event: string; model: string; text: string; by: string | null }[];
  counts: Record<string, number>;
  settings: { auto_retrain: boolean; auto_promote: boolean; check_every_ticks: number; window: number };
}

const NAMES: Record<string, string> = { eta: "Delivery time (ETA)", late: "Late-order risk" };

/** The live AI models: are they still right (drift), retraining, versions and the gate. */
export default function ModelsPage() {
  const [s, setS] = useState<Status | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [note, setNote] = useState<string | null>(null);
  const canManage = useCan("models:manage");

  const load = useCallback(async () => {
    try {
      setS(await request<Status>("/mlops/status"));
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

  const act = async (path: string, done: string) => {
    try {
      await request(path, { method: "POST" });
      setNote(done);
      void load();
    } catch (e) {
      setNote((e as Error).message);
    }
  };

  return (
    <Screen title="AI models">
      <ErrorNote text={error} />
      {s && (
        <div className="space-y-4">
          <p className="text-xs text-muted">
            Every finished order shows how right the models were. Checked every {s.settings.check_every_ticks} ticks
            over the last {s.settings.window} orders: input shift against the training data, and live error against the
            test error and against the model&apos;s own first hours in production. Confirmed drift{" "}
            {s.settings.auto_retrain ? "starts retraining" : "is reported (automatic retraining is off)"}; a new version{" "}
            {s.settings.auto_promote ? "goes live only if it passes every gate test" : "waits for approval"}.
          </p>
          {note && <p className="text-xs">{note}</p>}
          {s.job && (
            <p className="text-xs">
              Retraining {NAMES[s.job.model] ?? s.job.model}: <Badge value={s.job.status} />{" "}
              {s.job.version && `${s.job.version} ${s.job.passed ? "passed the gate" : "failed the gate"}`}
              {s.job.error && <span className="text-danger"> {s.job.error}</span>}
            </p>
          )}
          {Object.entries(s.models).map(([key, m]) => (
            <ModelPanel key={key} name={key} m={m} canManage={canManage} busy={s.job?.status === "RUNNING"} act={act} />
          ))}
          <Panel title="Model events">
            <table className="w-full text-xs">
              <tbody>
                {s.events.map((e, i) => (
                  <tr key={i} className="border-t border-border">
                    <td className={`${td} whitespace-nowrap text-muted`}>
                      {new Date(e.at * 1000).toLocaleTimeString()}
                    </td>
                    <td className={td}>{NAMES[e.model] ?? e.model}</td>
                    <td className={`${td} font-mono`}>{e.event}</td>
                    <td className={td}>
                      {e.text}
                      {e.by && <span className="text-muted"> · {e.by}</span>}
                    </td>
                  </tr>
                ))}
                {!s.events.length && (
                  <tr>
                    <td className={`${td} text-muted`}>No model events yet: start the simulation.</td>
                  </tr>
                )}
              </tbody>
            </table>
          </Panel>
        </div>
      )}
    </Screen>
  );
}

function ModelPanel({
  name,
  m,
  canManage,
  busy,
  act,
}: {
  name: string;
  m: ModelStatus;
  canManage: boolean;
  busy: boolean;
  act: (path: string, done: string) => Promise<void>;
}) {
  const c = m.check;
  const perf = c?.performance ?? {};
  const isEta = name === "eta";
  const archived = m.versions.some((v) => v.status === "archived");
  const points = m.history.map((h) => (isEta ? h.live_mae : h.live_recall)).filter((v): v is number => v != null);
  return (
    <Panel
      title={`${NAMES[name] ?? name} · ${m.production} in production`}
      actions={
        canManage ? (
          <div className="flex gap-1">
            <button
              disabled={busy}
              onClick={() => void act(`/mlops/${name}/retrain`, `Retraining ${name} started`)}
              className="rounded-control border border-border px-2 py-0.5 text-xs hover:border-accent disabled:opacity-50"
            >
              Retrain now
            </button>
            {archived && (
              <button
                onClick={() => void act(`/mlops/${name}/rollback`, `${name}: back to the previous version`)}
                className="rounded-control border border-border px-2 py-0.5 text-xs hover:border-accent"
              >
                Roll back
              </button>
            )}
          </div>
        ) : undefined
      }
    >
      <div className="grid gap-4 lg:grid-cols-[minmax(0,1fr)_minmax(0,1fr)]">
        <div className="space-y-2 text-xs">
          <div className="flex flex-wrap items-center gap-2">
            <Badge value={c?.status ?? "NOT_ENOUGH_DATA"} />
            <span className="text-muted">{c ? `${c.samples} recent orders` : "no check yet"}</span>
            {(c?.confirmed ?? 0) > 0 && <span className="text-danger">confirmed {c?.confirmed}×</span>}
          </div>
          {c?.reasons.map((r) => (
            <p key={r}>• {r}</p>
          ))}
          <dl className="grid grid-cols-3 gap-2">
            {isEta ? (
              <>
                <Fig label="Live error" value={perf.live_mae != null ? `${perf.live_mae} ticks` : "—"} />
                <Fig label="Error at go-live" value={perf.start_mae != null ? `${perf.start_mae} ticks` : "—"} />
                <Fig label="Test error" value={m.baseline.MAE != null ? `${m.baseline.MAE} ticks` : "—"} />
              </>
            ) : (
              <>
                <Fig
                  label="Late orders caught"
                  value={
                    perf.late_orders != null ? `${pct(perf.live_recall)} of ${perf.late_orders}` : pct(perf.live_recall)
                  }
                />
                <Fig label="At go-live" value={pct(perf.start_recall)} />
                <Fig label="On the test set" value={pct(m.baseline.recall)} />
              </>
            )}
          </dl>
          {points.length > 1 && <Spark values={points} />}
          {c && Object.keys(c.psi).length > 0 && (
            <div>
              <div className="mb-1 text-muted">Largest input shifts (PSI: &lt; 0.1 stable, &gt; 0.25 major)</div>
              {Object.entries(c.psi).map(([f, v]) => (
                <div key={f} className="flex items-center gap-2">
                  <span className="w-36 truncate font-mono">{f}</span>
                  <div className="h-1.5 flex-1 rounded bg-border/60">
                    <div
                      className={`h-1.5 rounded ${v >= 0.25 ? "bg-danger" : v >= 0.1 ? "bg-warning" : "bg-success"}`}
                      style={{ width: `${Math.min(100, (v / 1) * 100)}%` }}
                    />
                  </div>
                  <span className="w-12 text-right tabular-nums">{v.toFixed(2)}</span>
                </div>
              ))}
            </div>
          )}
        </div>
        <div className="max-h-80 overflow-auto">
          <table className="w-full text-xs">
            <thead className="sticky top-0 bg-surface">
              <tr>
                <th className={th}>Version</th>
                <th className={th}>Status</th>
                <th className={th}>Trained on</th>
                <th className={th}>Gate</th>
                <th className={th} />
              </tr>
            </thead>
            <tbody>
              {m.versions.map((v) => (
                <tr key={v.version} className="border-t border-border align-top">
                  <td className={`${td} font-mono font-semibold`}>{v.version}</td>
                  <td className={td}>
                    <Badge value={v.status.toUpperCase()} />
                  </td>
                  <td className={td}>{v.trained_on}</td>
                  <td className={td}>
                    {v.gate ? (
                      v.gate.map((g) => (
                        <div key={g.test} className={g.passed ? "" : "text-danger"} title={g.detail}>
                          {g.passed ? "✓" : "✗"} {g.test}: {g.detail}
                        </div>
                      ))
                    ) : (
                      <span className="text-muted">trained by notebook</span>
                    )}
                  </td>
                  <td className={td}>
                    {canManage && (v.status === "candidate" || v.status === "archived") && (
                      <button
                        onClick={() => void act(`/mlops/${name}/promote/${v.version}`, `${name} ${v.version} promoted`)}
                        className="rounded border border-border px-1.5 py-0.5 hover:border-accent"
                      >
                        Promote
                      </button>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    </Panel>
  );
}

function pct(v: number | null | undefined): string {
  return v == null ? "—" : `${Math.round(v * 100)}%`;
}

function Fig({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded border border-border px-2 py-1">
      <dt className="text-[11px] text-muted">{label}</dt>
      <dd className="font-semibold">{value}</dd>
    </div>
  );
}

/** Live error over the recent checks. */
function Spark({ values }: { values: number[] }) {
  const w = 240;
  const h = 36;
  const lo = Math.min(...values);
  const hi = Math.max(...values);
  const span = hi - lo || 1;
  const pts = values.map((v, i) => `${(i / (values.length - 1)) * w},${h - ((v - lo) / span) * (h - 4) - 2}`);
  return (
    <svg width={w} height={h} className="text-accent" aria-label="live error over recent checks">
      <polyline points={pts.join(" ")} fill="none" stroke="currentColor" strokeWidth="1.5" />
    </svg>
  );
}
