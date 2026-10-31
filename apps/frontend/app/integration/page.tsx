"use client";

import { useCallback, useEffect, useState } from "react";
import { Screen } from "@/components/layout/Screen";
import { ErrorNote, Panel, td, th } from "@/components/wms/shared";
import { request } from "@/lib/api";
import { useCan } from "@/lib/auth";

interface VehicleRow {
  serial: string;
  connection: string;
  order_id: string | null;
  last_node: string | null;
  nodes_left: number;
  driving: boolean | null;
  paused: boolean | null;
  battery: number | null;
  errors: string[];
  e_stop: string | null;
  header_id: number | null;
}

interface Status {
  transport: "memory" | "mqtt";
  broker_connected: boolean | null;
  counts: { published: number; received: number; invalid: number };
  invalid: { topic: string; problems: string[] }[];
  topic_example: string;
  version: string;
  vehicles: VehicleRow[];
}

interface Message {
  direction: "in" | "out";
  topic: string;
  payload: Record<string, unknown>;
}

const TOPICS = ["", "order", "instantActions", "state", "connection", "factsheet"];

/** Connections to other systems. VDA 5050: the robots as vehicles, this platform as master control. */
export default function IntegrationPage() {
  const [status, setStatus] = useState<Status | null>(null);
  const [log, setLog] = useState<Message[]>([]);
  const [serial, setSerial] = useState("");
  const [topic, setTopic] = useState("order");
  const [open, setOpen] = useState<number | null>(0);
  const [note, setNote] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const canCommand = useCan("robots:command");

  const load = useCallback(async () => {
    try {
      const q = new URLSearchParams({ limit: "40" });
      if (serial) q.set("serial", serial);
      if (topic) q.set("topic", topic);
      const [s, l] = await Promise.all([
        request<Status>("/vda5050/status"),
        request<Message[]>(`/vda5050/messages?${q}`),
      ]);
      setStatus(s);
      setLog(l);
      setError(null);
    } catch (e) {
      setError((e as Error).message);
    }
  }, [serial, topic]);

  useEffect(() => {
    void load();
    const id = setInterval(load, 3000);
    return () => clearInterval(id);
  }, [load]);

  const send = async (serials: string[], action: string) => {
    try {
      const r = await request<{ action_ids: string[] }>("/vda5050/instant-actions", {
        method: "POST",
        body: JSON.stringify({ serials, action }),
      });
      setNote(
        `${action} sent to ${serials.join(", ")} (${r.action_ids.length} message${r.action_ids.length > 1 ? "s" : ""})`,
      );
    } catch (e) {
      setNote((e as Error).message);
    }
  };

  return (
    <Screen title="Integration">
      <ErrorNote text={error} />
      {status && (
        <div className="space-y-4">
          <section className="grid grid-cols-2 gap-2 md:grid-cols-5">
            <Stat label="Robot interface" value={`VDA 5050 ${status.version}`} />
            <Stat
              label="Transport"
              value={
                status.transport === "mqtt"
                  ? status.broker_connected
                    ? "MQTT · connected"
                    : "MQTT · not connected"
                  : "In-process bus"
              }
              warn={status.transport === "mqtt" && !status.broker_connected}
            />
            <Stat
              label="Vehicles online"
              value={`${status.vehicles.filter((v) => v.connection === "ONLINE").length}/${status.vehicles.length}`}
            />
            <Stat label="Messages sent" value={status.counts.published.toLocaleString()} />
            <Stat
              label="Invalid messages"
              value={status.counts.invalid + status.invalid.length}
              warn={status.counts.invalid + status.invalid.length > 0}
            />
          </section>

          <div className="grid items-start gap-4 xl:grid-cols-[minmax(0,1fr)_minmax(420px,45%)]">
            <Panel
              title="Vehicles (as master control sees them)"
              actions={
                canCommand ? (
                  <div className="flex gap-1">
                    <button
                      onClick={() => void send(["all"], "stateRequest")}
                      className="rounded-control border border-border px-2 py-0.5 text-xs hover:border-accent"
                    >
                      Request all states
                    </button>
                  </div>
                ) : undefined
              }
            >
              <p className="mb-2 text-xs text-muted">
                Each simulated robot speaks VDA 5050 on{" "}
                <span className="font-mono">{status.topic_example.replace("/R1/state", "/{robot}/…")}</span>. Orders go
                out when the dispatcher assigns them; the vehicle reports its progress node by node.
                {status.transport === "memory" && " Set MQTT_URL to put the same messages on an MQTT broker."}
              </p>
              {note && <p className="mb-2 text-xs">{note}</p>}
              <div className="max-h-[60vh] overflow-auto">
                <table className="w-full whitespace-nowrap text-xs">
                  <thead className="sticky top-0 bg-surface">
                    <tr>
                      <th className={th}>Vehicle</th>
                      <th className={th}>Link</th>
                      <th className={th}>Order</th>
                      <th className={th}>Last node</th>
                      <th className={th}>Left</th>
                      <th className={th}>Battery</th>
                      <th className={th}>State</th>
                      <th className={th} />
                    </tr>
                  </thead>
                  <tbody>
                    {status.vehicles.map((v) => (
                      <tr
                        key={v.serial}
                        onClick={() => setSerial(serial === v.serial ? "" : v.serial)}
                        className={`cursor-pointer border-t border-border hover:bg-accent/5 ${serial === v.serial ? "bg-accent/10" : ""}`}
                      >
                        <td className={`${td} font-mono font-semibold`}>{v.serial}</td>
                        <td className={`${td} ${v.connection === "ONLINE" ? "text-success" : "text-danger"}`}>
                          {v.connection}
                        </td>
                        <td className={`${td} font-mono`}>{v.order_id ?? "—"}</td>
                        <td className={`${td} font-mono`}>{v.last_node ?? "—"}</td>
                        <td className={td}>{v.nodes_left}</td>
                        <td className={td}>{v.battery ?? "—"}%</td>
                        <td className={td}>
                          {v.e_stop && v.e_stop !== "NONE" ? (
                            <span className="text-danger">e-stop</span>
                          ) : v.paused ? (
                            "paused"
                          ) : v.driving ? (
                            "driving"
                          ) : (
                            "standing"
                          )}
                          {v.errors.length > 0 && <span className="ml-1 text-danger">{v.errors.join(", ")}</span>}
                        </td>
                        <td className={td} onClick={(e) => e.stopPropagation()}>
                          {canCommand && (
                            <button
                              onClick={() => void send([v.serial], v.paused ? "stopPause" : "startPause")}
                              className="rounded border border-border px-1.5 py-0.5 hover:border-accent"
                            >
                              {v.paused ? "stopPause" : "startPause"}
                            </button>
                          )}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </Panel>

            <Panel
              title={`Messages${serial ? ` · ${serial}` : ""}`}
              actions={
                <select
                  value={topic}
                  onChange={(e) => setTopic(e.target.value)}
                  className="rounded-control border border-border bg-canvas px-2 py-0.5 text-xs"
                >
                  {TOPICS.map((t) => (
                    <option key={t} value={t}>
                      {t || "all topics"}
                    </option>
                  ))}
                </select>
              }
            >
              <div className="max-h-[60vh] space-y-1 overflow-auto text-xs">
                {log.map((msg, i) => (
                  <div key={i} className="rounded border border-border">
                    <button
                      onClick={() => setOpen(open === i ? null : i)}
                      className="flex w-full gap-2 px-2 py-1 text-left hover:bg-accent/5"
                    >
                      <span className={msg.direction === "out" ? "text-accent" : "text-success"}>
                        {msg.direction === "out" ? "→" : "←"}
                      </span>
                      <span className="truncate font-mono">{msg.topic}</span>
                      <span className="ml-auto text-muted">#{String(msg.payload.headerId ?? "")}</span>
                    </button>
                    {open === i && (
                      <pre className="max-h-72 overflow-auto border-t border-border bg-canvas p-2 font-mono text-[11px] leading-snug">
                        {JSON.stringify(msg.payload, null, 2)}
                      </pre>
                    )}
                  </div>
                ))}
                {!log.length && <p className="text-muted">No messages for this filter yet.</p>}
              </div>
            </Panel>
          </div>
        </div>
      )}
    </Screen>
  );
}

function Stat({ label, value, warn = false }: { label: string; value: React.ReactNode; warn?: boolean }) {
  return (
    <div className="rounded-card border border-border bg-surface px-3 py-2">
      <div className="text-[11px] text-muted">{label}</div>
      <div className={`text-base font-semibold ${warn ? "text-warning" : ""}`}>{value}</div>
    </div>
  );
}
