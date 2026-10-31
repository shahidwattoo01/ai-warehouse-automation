"use client";

import { useCan } from "@/lib/auth";
import { useCallback, useEffect, useState } from "react";
import { wms, type WmsTask, type WmsTxn } from "@/lib/wms";
import { Badge, clock, ErrorNote, ExportButton, input, Panel, td, th } from "./shared";

const TYPES = [
  "RECEIVE",
  "PUTAWAY",
  "MOVE",
  "REPLENISH",
  "ALLOCATE",
  "DEALLOCATE",
  "PICK",
  "SHORT_PICK",
  "PACK",
  "LOAD",
  "SHIP",
  "ADJUST",
  "STATUS",
  "RETURN",
];

/** The inventory ledger: every stock change, who made it, why, and its reference document. */
export function Ledger() {
  const [f, setF] = useState({ sku: "", location: "", type: "", ref: "", user: "" });
  const [rows, setRows] = useState<WmsTxn[]>([]);
  const [error, setError] = useState<string | null>(null);
  const load = useCallback(
    () =>
      wms
        .transactions({ ...f, limit: 300 })
        .then(setRows)
        .catch((e: Error) => setError(e.message)),
    [f],
  );
  useEffect(() => {
    void load();
    const id = setInterval(load, 4000);
    return () => clearInterval(id);
  }, [load]);
  const field = (key: keyof typeof f, label: string) => (
    <input
      className={`${input} w-36`}
      placeholder={label}
      aria-label={label}
      value={f[key]}
      onChange={(e) => setF({ ...f, [key]: e.target.value })}
    />
  );
  return (
    <Panel title="Inventory ledger" actions={<ExportButton name="transactions" />}>
      <div className="mb-3 flex flex-wrap gap-2">
        {field("sku", "SKU")}
        {field("location", "Location")}
        {field("ref", "Order / PO / count")}
        {field("user", "User")}
        <select
          className={input}
          value={f.type}
          onChange={(e) => setF({ ...f, type: e.target.value })}
          aria-label="Type"
        >
          <option value="">All types</option>
          {TYPES.map((t) => (
            <option key={t}>{t}</option>
          ))}
        </select>
      </div>
      <ErrorNote text={error} />
      <div className="max-h-[66vh] overflow-auto">
        <table className="w-full text-sm">
          <thead className="sticky top-0 bg-surface">
            <tr>
              <th className={th}>#</th>
              <th className={th}>Time</th>
              <th className={th}>Type</th>
              <th className={th}>SKU</th>
              <th className={`${th} text-right`}>Qty</th>
              <th className={th}>From → to</th>
              <th className={th}>Lot</th>
              <th className={th}>Reason / status</th>
              <th className={th}>Reference</th>
              <th className={th}>User</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((t) => (
              <tr key={t.txn_id} className="border-t border-border">
                <td className={`${td} tabular text-xs text-muted`}>{t.txn_id}</td>
                <td className={`${td} whitespace-nowrap font-mono text-xs`}>{clock(t.tick)}</td>
                <td className={td}>
                  <Badge value={t.type} />
                </td>
                <td className={`${td} font-mono text-xs`}>{t.sku}</td>
                <td className={`${td} tabular text-right`}>{t.qty}</td>
                <td className={`${td} font-mono text-xs`}>
                  {t.from_loc ?? ""}
                  {t.to_loc && t.to_loc !== t.from_loc ? ` → ${t.to_loc}` : ""}
                </td>
                <td className={`${td} font-mono text-xs`}>{t.lot ?? ""}</td>
                <td className={`${td} text-xs`}>{t.reason ?? t.status ?? ""}</td>
                <td className={`${td} font-mono text-xs`}>{t.ref ?? ""}</td>
                <td className={`${td} text-xs text-muted`}>{t.user}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </Panel>
  );
}

const TASK_NAMES: Record<string, string> = {
  REPLENISH_URGENT: "Urgent replenishment",
  RECEIVE: "Receive plate",
  PUTAWAY: "Put away plate",
  REPLENISH: "Replenish pick face",
  RETURN: "Inspect return",
  QUARANTINE: "Quarantine / scrap",
  COUNT: "Cycle count",
};

/** Work queue: tasks by priority and what each associate is doing. */
export function Work() {
  const [data, setData] = useState<{ tasks: WmsTask[]; associates: { name: string; task: string | null }[] } | null>(
    null,
  );
  useEffect(() => {
    const load = () =>
      wms
        .tasks()
        .then(setData)
        .catch(() => undefined);
    void load();
    const id = setInterval(load, 3000);
    return () => clearInterval(id);
  }, []);
  const describe = (t: WmsTask) =>
    Object.entries(t.data)
      .filter(([k]) => k !== "arrived")
      .map(([, v]) => String(v))
      .join(" · ");
  return (
    <div className="grid gap-4 xl:grid-cols-[1fr_300px]">
      <Panel title={`Open tasks (${data?.tasks.length ?? 0})`}>
        <table className="w-full text-sm">
          <thead>
            <tr>
              <th className={th}>Priority</th>
              <th className={th}>Task</th>
              <th className={th}>Details</th>
              <th className={th}>Created</th>
              <th className={th}>Status</th>
              <th className={th}>Associate</th>
            </tr>
          </thead>
          <tbody>
            {data?.tasks.map((t) => (
              <tr key={t.task_id} className="border-t border-border">
                <td className={`${td} tabular`}>{t.priority}</td>
                <td className={td}>{TASK_NAMES[t.type] ?? t.type}</td>
                <td className={`${td} font-mono text-xs`}>{describe(t)}</td>
                <td className={`${td} text-xs text-muted`}>{clock(t.created)}</td>
                <td className={td}>
                  <Badge value={t.status} />
                </td>
                <td className={td}>{t.assignee ?? ""}</td>
              </tr>
            ))}
          </tbody>
        </table>
        {data?.tasks.length === 0 && <p className="p-2 text-sm text-muted">All work is done.</p>}
      </Panel>
      <div className="space-y-4">
        <AutoTasks />
        <Panel title="Associates">
          <ul className="space-y-1 text-sm">
            {data?.associates.map((a) => (
              <li key={a.name} className="flex justify-between">
                <span>{a.name}</span>
                <span className={a.task ? "text-ink" : "text-muted"}>{a.task ? "working" : "free"}</span>
              </li>
            ))}
          </ul>
        </Panel>
      </div>
    </div>
  );
}

/** Which work the associates do by themselves; the rest waits for an operator with a scanner. */
function AutoTasks() {
  const canSet = useCan("wms:settings");
  const [auto, setAuto] = useState<Record<string, boolean> | null>(null);
  useEffect(() => {
    wms
      .settings()
      .then((s) => setAuto(s.auto_tasks))
      .catch(() => undefined);
  }, []);
  if (!auto) return null;
  const toggle = (type: string) =>
    wms
      .setAutoTasks({ [type]: !auto[type] })
      .then((s) => setAuto(s.auto_tasks))
      .catch(() => undefined);
  return (
    <Panel title="Done by associates automatically">
      <ul className="space-y-1 text-sm">
        {Object.entries(auto).map(([type, on]) => (
          <li key={type} className="flex items-center justify-between">
            <span>{TASK_NAMES[type] ?? type}</span>
            <button
              onClick={() => toggle(type)}
              disabled={!canSet}
              title={canSet ? undefined : "Only supervisors can change this"}
              className={`rounded-full px-2 py-0.5 text-xs ${on ? "bg-success/15 text-success" : "bg-border text-muted"}`}
            >
              {on ? "automatic" : "by operators"}
            </button>
          </li>
        ))}
      </ul>
      <p className="mt-2 text-[11px] text-muted">
        Switch receiving to &quot;by operators&quot; to receive trucks yourself at the Receiving station.
      </p>
    </Panel>
  );
}
