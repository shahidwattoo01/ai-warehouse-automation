"use client";

import { useCan } from "@/lib/auth";
import { Can } from "@/components/layout/Can";
import { useCallback, useEffect, useState } from "react";
import { wms, type WmsCount } from "@/lib/wms";
import { Badge, button, clock, ErrorNote, ghost, input, Panel, ScanBox, td, th } from "./shared";

/**
 * Cycle counting as in a real WMS: counts are **blind** (the counter never sees the system
 * quantity), a difference beyond tolerance is recounted by someone else, and a confirmed
 * difference above the value limit waits for a supervisor before stock is adjusted.
 */
export function Counts({ user }: { user: string }) {
  const canCount = useCan("wms:count");
  const canApprove = useCan("wms:count_approve");
  const [counts, setCounts] = useState<WmsCount[]>([]);
  const [view, setView] = useState<"OPEN" | "PENDING_APPROVAL" | "">("OPEN");
  const [error, setError] = useState<string | null>(null);
  const [entry, setEntry] = useState<Record<string, string>>({});
  const load = useCallback(
    () =>
      wms
        .counts(view || undefined)
        .then(setCounts)
        .catch((e: Error) => setError(e.message)),
    [view],
  );
  useEffect(() => {
    void load();
    const id = setInterval(load, 4000);
    return () => clearInterval(id);
  }, [load]);

  const run = async (fn: () => Promise<unknown>) => {
    try {
      await fn();
      setError(null);
      void load();
    } catch (e) {
      setError((e as Error).message);
    }
  };

  return (
    <Panel
      title="Cycle counts"
      actions={
        <div className="flex gap-1.5">
          {(
            [
              ["OPEN", "To count"],
              ["PENDING_APPROVAL", "Waiting for a supervisor"],
              ["", "History"],
            ] as const
          ).map(([v, label]) => (
            <button
              key={label}
              onClick={() => setView(v)}
              className={`rounded-full border px-2.5 py-0.5 text-xs ${view === v ? "border-accent bg-accent/15" : "border-border text-muted"}`}
            >
              {label}
            </button>
          ))}
        </div>
      }
    >
      <Can permission="wms:count">
        <div className="mb-3 max-w-xl">
          <ScanBox
            placeholder="Scan a pick-face location to create a count"
            onScan={(code) => run(() => wms.createCount(code))}
          />
        </div>
      </Can>
      <ErrorNote text={error} />
      <div className="max-h-[66vh] overflow-auto">
        <table className="w-full text-sm">
          <thead className="sticky top-0 bg-surface">
            <tr>
              <th className={th}>Count</th>
              <th className={th}>Location</th>
              <th className={th}>SKU</th>
              <th className={th}>Reason</th>
              <th className={th}>Created</th>
              <th className={th}>Status</th>
              <th className={`${th} text-right`}>System</th>
              <th className={`${th} text-right`}>Counted</th>
              <th className={`${th} text-right`}>Variance</th>
              <th className={`${th} text-right`}>Value</th>
              <th className={th}>By</th>
              <th className={th} />
            </tr>
          </thead>
          <tbody>
            {counts.map((c) => (
              <tr key={c.count_id} className="border-t border-border">
                <td className={`${td} font-mono text-xs`}>{c.count_id}</td>
                <td className={`${td} font-mono`}>{c.location}</td>
                <td className={`${td} font-mono text-xs`}>{c.sku}</td>
                <td className={td}>{c.reason.toLowerCase().replace("_", " ")}</td>
                <td className={`${td} text-xs text-muted`}>{clock(c.created)}</td>
                <td className={td}>
                  <Badge value={c.status} />
                </td>
                <td className={`${td} tabular text-right`}>{c.status === "OPEN" ? "hidden" : c.expected}</td>
                <td className={`${td} tabular text-right`}>{c.counted ?? ""}</td>
                <td className={`${td} tabular text-right ${c.variance ? "font-semibold text-danger" : ""}`}>
                  {c.variance === null ? "" : c.variance > 0 ? `+${c.variance}` : c.variance}
                </td>
                <td className={`${td} tabular text-right`}>{c.value ? `$${c.value.toFixed(2)}` : ""}</td>
                <td className={`${td} text-xs text-muted`}>{c.decided_by ?? c.counter ?? ""}</td>
                <td className={td}>
                  {c.status === "OPEN" && canCount && (
                    <form
                      className="flex gap-1"
                      onSubmit={(e) => {
                        e.preventDefault();
                        const n = Number(entry[c.count_id]);
                        if (Number.isInteger(n) && n >= 0) void run(() => wms.submitCount(c.count_id, n, user));
                      }}
                    >
                      <input
                        className={`${input} w-20 py-0.5`}
                        inputMode="numeric"
                        placeholder="units"
                        value={entry[c.count_id] ?? ""}
                        onChange={(e) => setEntry({ ...entry, [c.count_id]: e.target.value })}
                        aria-label={`Units counted at ${c.location}`}
                      />
                      <button className={`${button} py-0.5`}>Submit</button>
                    </form>
                  )}
                  {c.status === "PENDING_APPROVAL" && !canApprove && (
                    <span className="text-xs text-muted">needs a supervisor</span>
                  )}
                  {c.status === "PENDING_APPROVAL" && canApprove && (
                    <div className="flex gap-1">
                      <button
                        className={`${button} py-0.5`}
                        onClick={() => run(() => wms.decideCount(c.count_id, true, user))}
                      >
                        Approve
                      </button>
                      <button
                        className={`${ghost} py-0.5`}
                        onClick={() => run(() => wms.decideCount(c.count_id, false, user))}
                      >
                        Reject
                      </button>
                    </div>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
        {counts.length === 0 && <p className="p-2 text-sm text-muted">Nothing here.</p>}
      </div>
    </Panel>
  );
}
