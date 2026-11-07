"use client";

import { useEffect, useState } from "react";
import { Screen } from "@/components/layout/Screen";
import { api } from "@/lib/api";
import type { SiteReportRow, SitesReport } from "@/lib/types";

function kpiCell(value: number | null, unit: string, lowerBetter: boolean) {
  if (value === null) return <span className="text-muted">—</span>;
  return (
    <span className={lowerBetter ? (value > 0 ? "text-warning" : "text-success") : "text-success"}>
      {value.toFixed(1)}<span className="ml-0.5 text-xs text-muted">{unit}</span>
    </span>
  );
}

function ReportTable({ rows }: { rows: SiteReportRow[] }) {
  if (rows.length === 0) {
    return (
      <div className="rounded-card border border-border bg-surface p-8 text-center text-sm text-muted">
        No simulation runs have been tagged to a site yet. Assign a site to a run to see per-client metrics here.
      </div>
    );
  }
  return (
    <div className="rounded-card border border-border bg-surface">
      <table className="w-full text-sm">
        <thead>
          <tr className="border-b border-border text-left text-xs text-muted">
            <th className="px-5 py-3">Site</th>
            <th className="px-4 py-3">Client</th>
            <th className="px-4 py-3">Runs</th>
            <th className="px-4 py-3">Throughput</th>
            <th className="px-4 py-3">Late %</th>
            <th className="px-4 py-3">Avg completion</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => (
            <tr key={row.site_id} className="border-b border-border/50 last:border-0 hover:bg-border/20">
              <td className="px-5 py-3 font-medium">{row.site_name}</td>
              <td className="px-4 py-3 text-muted">{row.client_name}</td>
              <td className="px-4 py-3 tabular-nums">{row.runs}</td>
              <td className="px-4 py-3 tabular-nums">{kpiCell(row.throughput_per_hour, "orders/h", false)}</td>
              <td className="px-4 py-3 tabular-nums">{kpiCell(row.late_percent, "%", true)}</td>
              <td className="px-4 py-3 tabular-nums">{kpiCell(row.avg_completion_ticks, " ticks", true)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export default function ReportsPage() {
  const [data, setData] = useState<SitesReport | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api.sites
      .reports()
      .then(setData)
      .catch((e) => setError(String(e.message ?? e)));
  }, []);

  return (
    <Screen title="Reports">
      <div className="space-y-6">
        <div>
          <h1 className="text-lg font-semibold">Per-client / per-site Reports</h1>
          <p className="mt-0.5 text-sm text-muted">
            Throughput, late orders and completion time for each warehouse site and 3PL client (Phase 12, PR-33)
          </p>
        </div>

        {error && (
          <div className="rounded-card border border-danger/40 bg-danger/10 px-4 py-3 text-sm text-danger">
            {error}
          </div>
        )}

        {data && (
          <div className="grid grid-cols-2 gap-4 sm:grid-cols-3">
            {[
              { label: "Clients", value: data.clients.length },
              { label: "Sites", value: data.sites.length },
              { label: "Sites in report", value: data.report.length },
            ].map(({ label, value }) => (
              <div key={label} className="rounded-card border border-border bg-surface p-4">
                <div className="text-xs text-muted">{label}</div>
                <div className="mt-1 text-2xl font-semibold tabular-nums">{value}</div>
              </div>
            ))}
          </div>
        )}

        {data && <ReportTable rows={data.report} />}

        {data && data.clients.length > 0 && (
          <div className="rounded-card border border-border bg-surface">
            <div className="border-b border-border px-5 py-3 text-sm font-medium">Clients & sites</div>
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-border/50 text-left text-xs text-muted">
                  <th className="px-5 py-2">Client</th>
                  <th className="px-4 py-2">Sites</th>
                  <th className="px-4 py-2">Status</th>
                </tr>
              </thead>
              <tbody>
                {data.clients.map((client) => {
                  const clientSites = data.sites.filter((s) => s.client_id === client.client_id);
                  return (
                    <tr key={client.client_id} className="border-b border-border/40 last:border-0 hover:bg-border/20">
                      <td className="px-5 py-2 font-medium">{client.name}</td>
                      <td className="px-4 py-2 text-muted">
                        {clientSites.map((s) => s.name).join(", ") || "—"}
                      </td>
                      <td className="px-4 py-2">
                        <span className={`rounded px-1.5 py-0.5 text-xs ${client.active ? "bg-success/15 text-success" : "bg-muted/20 text-muted"}`}>
                          {client.active ? "active" : "inactive"}
                        </span>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </Screen>
  );
}
