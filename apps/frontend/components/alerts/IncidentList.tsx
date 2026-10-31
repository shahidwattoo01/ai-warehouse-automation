"use client";

import { useState } from "react";
import { alerts, SEVERITY_DOT, type Incident } from "@/lib/alerts";
import { useCan } from "@/lib/auth";

/** Incidents with acknowledge / resolve (a short note is optional). */
export function IncidentList({
  incidents,
  onChanged,
  compact = false,
}: {
  incidents: Incident[];
  onChanged: () => void;
  compact?: boolean;
}) {
  const canHandle = useCan("alerts:handle");
  const [open, setOpen] = useState<string | null>(null);
  const [note, setNote] = useState("");
  const [error, setError] = useState<string | null>(null);

  const act = async (fn: typeof alerts.acknowledge, id: string) => {
    try {
      await fn(id, note || undefined);
      setNote("");
      setError(null);
      onChanged();
    } catch (e) {
      setError((e as Error).message);
    }
  };

  if (!incidents.length) return <p className="py-2 text-xs text-muted">No alerts here.</p>;
  return (
    <ul className="divide-y divide-border/70 text-sm">
      {error && <li className="py-1 text-xs text-danger">{error}</li>}
      {incidents.map((i) => (
        <li key={i.alert_id} className={`py-2 ${i.status === "RESOLVED" ? "opacity-60" : ""}`}>
          <div className="flex items-start gap-2">
            <span className={`mt-1.5 h-2 w-2 shrink-0 rounded-full ${SEVERITY_DOT[i.severity]}`} />
            <div className="min-w-0 flex-1">
              <div className="flex flex-wrap items-center gap-x-2">
                <span className="font-medium">{i.title}</span>
                {i.escalated && i.status === "OPEN" && (
                  <span className="rounded bg-danger px-1 text-[10px] font-semibold text-white">ESCALATED</span>
                )}
                {i.status === "ACKNOWLEDGED" && (
                  <span className="rounded bg-accent/15 px-1 text-[10px] text-accent">ack {i.acknowledged_by}</span>
                )}
                {i.status === "RESOLVED" && (
                  <span className="rounded bg-border px-1 text-[10px] text-muted">resolved by {i.resolved_by}</span>
                )}
              </div>
              <div className="text-xs text-muted">
                {i.detail}
                {!compact && ` · ${i.name}`} · {i.opened_time} · {i.minutes_open} min
              </div>
              {open === i.alert_id && !compact && (
                <ol className="mt-1 space-y-0.5 text-[11px] text-muted">
                  {i.history.map((h, n) => (
                    <li key={n}>
                      {h.at.slice(11, 16)} {h.event.toLowerCase()} {h.user !== "system" && `· ${h.user}`}{" "}
                      {h.note && `· ${h.note}`}
                    </li>
                  ))}
                </ol>
              )}
            </div>
            <div className="flex shrink-0 items-center gap-1">
              {!compact && (
                <button
                  onClick={() => setOpen(open === i.alert_id ? null : i.alert_id)}
                  className="rounded px-1.5 py-0.5 text-[11px] text-muted hover:text-ink"
                >
                  {open === i.alert_id ? "hide" : "history"}
                </button>
              )}
              {canHandle && i.status === "OPEN" && (
                <button
                  onClick={() => act(alerts.acknowledge, i.alert_id)}
                  className="rounded-control border border-accent px-2 py-0.5 text-xs text-accent hover:bg-accent/10"
                >
                  Acknowledge
                </button>
              )}
              {canHandle && i.status !== "RESOLVED" && (
                <button
                  onClick={() => act(alerts.resolve, i.alert_id)}
                  className="rounded-control border border-border px-2 py-0.5 text-xs hover:border-accent"
                >
                  Resolve
                </button>
              )}
            </div>
          </div>
        </li>
      ))}
      {canHandle && !compact && (
        <li className="pt-2">
          <input
            value={note}
            onChange={(e) => setNote(e.target.value)}
            placeholder="Optional note for your next acknowledge / resolve"
            className="w-full rounded-control border border-border bg-canvas px-2 py-1 text-xs outline-none focus:border-accent"
          />
        </li>
      )}
    </ul>
  );
}
