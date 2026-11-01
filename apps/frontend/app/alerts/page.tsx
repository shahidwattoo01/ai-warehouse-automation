"use client";

import { useCallback, useEffect, useState } from "react";
import { IncidentList } from "@/components/alerts/IncidentList";
import { Screen } from "@/components/layout/Screen";
import { ErrorNote, Panel, td, th } from "@/components/wms/shared";
import {
  alerts,
  type AlertRule,
  type AlertSummary,
  type Channel,
  type Incident,
  type Notification,
} from "@/lib/alerts";
import { useCan } from "@/lib/auth";

const TABS = [
  ["active", "Active"],
  ["RESOLVED", "Resolved"],
  ["all", "All"],
] as const;

/** Alert centre: incidents from the alert rules, the rules themselves and the notification log. */
export default function AlertsPage() {
  const [status, setStatus] = useState<string>("active");
  const [incidents, setIncidents] = useState<Incident[]>([]);
  const [summary, setSummary] = useState<AlertSummary | null>(null);
  const [rules, setRules] = useState<Record<string, AlertRule>>({});
  const [channels, setChannels] = useState<Channel[]>([]);
  const [log, setLog] = useState<Notification[]>([]);
  const [error, setError] = useState<string | null>(null);
  const canConfigure = useCan("alerts:configure");

  const load = useCallback(async () => {
    try {
      const [l, r, n] = await Promise.all([alerts.list(status), alerts.rules(), alerts.notifications()]);
      setIncidents(l.incidents);
      setSummary(l.summary);
      setRules(r.rules);
      setChannels(r.channels);
      setLog(n);
      setError(null);
    } catch (e) {
      setError((e as Error).message);
    }
  }, [status]);

  useEffect(() => {
    void load();
    const id = setInterval(load, 4000);
    return () => clearInterval(id);
  }, [load]);

  const change = async (id: string, c: Partial<AlertRule>) => {
    try {
      await alerts.updateRule(id, c);
      await load();
    } catch (e) {
      setError((e as Error).message);
    }
  };

  const toggle = (list: Channel[], ch: Channel) => (list.includes(ch) ? list.filter((x) => x !== ch) : [...list, ch]);

  return (
    <Screen title="Alerts">
      <ErrorNote text={error} />
      {/* Side by side only on wide screens; the rules table needs ~640 px. */}
      <div className="grid items-start gap-4 2xl:grid-cols-[minmax(0,1fr)_minmax(560px,45%)]">
        <Panel
          title={
            summary
              ? `Incidents · ${summary.open} open, ${summary.acknowledged} acknowledged${summary.escalated ? `, ${summary.escalated} escalated` : ""}`
              : "Incidents"
          }
          actions={
            <div className="flex gap-1 text-xs">
              {TABS.map(([id, label]) => (
                <button
                  key={id}
                  onClick={() => setStatus(id)}
                  className={`rounded-full border px-2 py-0.5 ${status === id ? "border-accent bg-accent/15 font-semibold" : "border-border text-muted"}`}
                >
                  {label}
                </button>
              ))}
            </div>
          }
        >
          <div className="max-h-[70vh] overflow-auto pr-1">
            <IncidentList incidents={incidents} onChanged={load} />
          </div>
        </Panel>

        <div className="min-w-0 space-y-4">
          <Panel title="Rules">
            <p className="mb-2 text-xs text-muted">
              Checked every 3 simulated minutes. Not acknowledged within the escalation time: escalated and notified
              again. Changes last until the backend restarts (defaults: configs/alert_rules.yaml).
            </p>
            <div className="overflow-x-auto">
              <table className="w-full text-xs">
                <thead>
                  <tr>
                    <th className={th}>On</th>
                    <th className={th}>Rule</th>
                    <th className={th}>Threshold</th>
                    <th className={th}>Escalate</th>
                    <th className={th}>Notify</th>
                    <th className={th}>Escalate to</th>
                  </tr>
                </thead>
                <tbody>
                  {Object.entries(rules).map(([id, r]) => (
                    <tr key={id} className="border-t border-border">
                      <td className={td}>
                        <input
                          type="checkbox"
                          checked={r.enabled}
                          disabled={!canConfigure}
                          onChange={(e) => void change(id, { enabled: e.target.checked })}
                          aria-label={`${r.name} on`}
                        />
                      </td>
                      <td className={td}>
                        <span
                          className={`mr-1 inline-block h-2 w-2 rounded-full ${r.severity === "critical" ? "bg-danger" : r.severity === "warning" ? "bg-warning" : "bg-muted"}`}
                        />
                        {r.name}
                      </td>
                      <td className={td}>
                        {r.threshold === null ? (
                          <span className="text-muted">—</span>
                        ) : (
                          <input
                            type="number"
                            defaultValue={r.threshold}
                            disabled={!canConfigure}
                            onBlur={(e) =>
                              Number(e.target.value) !== r.threshold &&
                              void change(id, { threshold: Number(e.target.value) })
                            }
                            className="w-16 rounded border border-border bg-canvas px-1"
                            aria-label={`${r.name} threshold`}
                          />
                        )}{" "}
                        <span className="text-muted">{r.unit}</span>
                      </td>
                      <td className={td}>
                        <input
                          type="number"
                          defaultValue={r.escalate_after_min}
                          disabled={!canConfigure}
                          onBlur={(e) =>
                            Number(e.target.value) !== r.escalate_after_min &&
                            void change(id, { escalate_after_min: Number(e.target.value) })
                          }
                          className="w-12 rounded border border-border bg-canvas px-1"
                          aria-label={`${r.name} escalation minutes`}
                        />{" "}
                        min
                      </td>
                      {(["notify", "escalate_to"] as const).map((field) => (
                        <td key={field} className={`${td} whitespace-nowrap`}>
                          {channels
                            .filter((c) => c !== "screen")
                            .map((c) => (
                              <label key={c} className="mr-2 inline-flex items-center gap-0.5">
                                <input
                                  type="checkbox"
                                  checked={r[field].includes(c)}
                                  disabled={!canConfigure}
                                  onChange={() => void change(id, { [field]: toggle(r[field], c) })}
                                />
                                {c}
                              </label>
                            ))}
                        </td>
                      ))}
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </Panel>

          <Panel
            title="Notifications"
            actions={
              canConfigure ? (
                <div className="flex gap-1">
                  {(["email", "webhook"] as const).map((c) => (
                    <button
                      key={c}
                      onClick={async () => {
                        await alerts.test(c).catch((e) => setError((e as Error).message));
                        await load();
                      }}
                      className="rounded-control border border-border px-2 py-0.5 text-xs hover:border-accent"
                    >
                      Test {c}
                    </button>
                  ))}
                </div>
              ) : undefined
            }
          >
            <p className="mb-2 text-xs text-muted">
              Email needs SMTP_HOST and ALERT_EMAIL_TO, the webhook ALERT_WEBHOOK_URL (Slack, Teams or any URL taking
              JSON) in .env.
            </p>
            <div className="max-h-64 overflow-auto">
              <table className="w-full text-xs">
                <tbody>
                  {log.map((n, i) => (
                    <tr key={i} className="border-t border-border">
                      <td className={`${td} whitespace-nowrap text-muted`}>{n.at?.slice(11, 19)}</td>
                      <td className={`${td} font-mono`}>{n.alert_id}</td>
                      <td className={td}>{n.channel}</td>
                      <td className={td}>{n.why}</td>
                      <td
                        className={`${td} ${n.status === "FAILED" ? "text-danger" : n.status === "SENT" ? "text-success" : "text-muted"}`}
                        title={n.detail ?? undefined}
                      >
                        {n.status.replace("_", " ").toLowerCase()}
                      </td>
                    </tr>
                  ))}
                  {!log.length && (
                    <tr>
                      <td className={`${td} text-muted`}>Nothing sent yet.</td>
                    </tr>
                  )}
                </tbody>
              </table>
            </div>
          </Panel>
        </div>
      </div>
    </Screen>
  );
}
