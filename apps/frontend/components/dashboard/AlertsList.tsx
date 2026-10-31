"use client";

import Link from "next/link";
import { useCallback, useEffect, useState } from "react";
import { IncidentList } from "@/components/alerts/IncidentList";
import { alerts, type Incident } from "@/lib/alerts";

/** The dashboard's Alerts tab: the active incidents of the alert centre, with acknowledge and
 *  resolve; rules, history and notifications are on the Alerts page. */
export function AlertsList() {
  const [incidents, setIncidents] = useState<Incident[]>([]);
  const load = useCallback(async () => {
    try {
      setIncidents((await alerts.list("active")).incidents);
    } catch {
      // the next poll tries again
    }
  }, []);

  useEffect(() => {
    void load();
    const id = setInterval(load, 4000);
    return () => clearInterval(id);
  }, [load]);

  return (
    <div className="flex min-h-0 flex-1 flex-col">
      <div className="mb-1 flex items-center justify-between text-xs">
        <span className="font-semibold uppercase tracking-wide text-muted">Active alerts ({incidents.length})</span>
        <Link href="/alerts" className="text-accent hover:underline">
          All alerts, rules and history →
        </Link>
      </div>
      <div className="min-h-0 flex-1 overflow-auto pr-1">
        <IncidentList incidents={incidents} onChanged={load} compact />
      </div>
    </div>
  );
}
