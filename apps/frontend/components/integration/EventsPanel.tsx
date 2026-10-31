"use client";

import { useEffect, useRef, useState } from "react";
import { Panel, td, th } from "@/components/wms/shared";
import { request } from "@/lib/api";

interface Ev {
  topic: string;
  type: string;
  subject: string | null;
  time: string;
  sequence: number;
  data: Record<string, unknown>;
}

interface Catalog {
  events: { topic: string; type: string; meaning: string }[];
  transport: "mqtt" | "memory";
  mqtt_topic_filter: string;
  stream: string;
  counts: Record<string, number>;
  sequence: number;
  subscribers: number;
}

const FILTERS = ["", "robots", "orders", "floor", "safety", "alerts", "inventory"];

function short(data: Record<string, unknown>): string {
  const text = data.text ?? data.title;
  if (typeof text === "string") return text;
  if (data.from && data.to) return `${data.from} → ${data.to}`;
  return Object.entries(data)
    .slice(0, 3)
    .map(([k, v]) => `${k} ${typeof v === "object" ? "…" : String(v)}`)
    .join(" · ");
}

/** Platform events for other systems (CloudEvents on MQTT topics, SSE, replay). */
export function EventsPanel() {
  const [cat, setCat] = useState<Catalog | null>(null);
  const [events, setEvents] = useState<Ev[]>([]);
  const [prefix, setPrefix] = useState("");
  const [showCatalog, setShowCatalog] = useState(false);
  const last = useRef(0);

  useEffect(() => {
    last.current = 0;
    setEvents([]);
    let stop = false;
    const load = async () => {
      try {
        const [c, fresh] = await Promise.all([
          request<Catalog>("/events/catalog"),
          request<Ev[]>(`/events?after=${last.current}&limit=200${prefix ? `&prefix=${prefix}` : ""}`),
        ]);
        if (stop) return;
        setCat(c);
        if (fresh.length) {
          last.current = fresh[fresh.length - 1].sequence;
          const newestFirst = [...fresh].reverse(); // a copy: state updaters must not mutate
          setEvents((old) => [...newestFirst, ...old].slice(0, 150));
        }
      } catch {
        // try again on the next poll
      }
    };
    void load();
    const id = setInterval(load, 2000);
    return () => {
      stop = true;
      clearInterval(id);
    };
  }, [prefix]);

  if (!cat) return null;
  return (
    <Panel
      title={`Event stream · ${cat.sequence.toLocaleString()} events`}
      actions={
        <div className="flex gap-1">
          <select
            value={prefix}
            onChange={(e) => setPrefix(e.target.value)}
            className="rounded-control border border-border bg-canvas px-2 py-0.5 text-xs"
          >
            {FILTERS.map((f) => (
              <option key={f} value={f}>
                {f || "all events"}
                {f && cat.counts[f] ? ` (${cat.counts[f]})` : ""}
              </option>
            ))}
          </select>
          <button
            onClick={() => setShowCatalog(!showCatalog)}
            className="rounded-control border border-border px-2 py-0.5 text-xs hover:border-accent"
          >
            {showCatalog ? "Hide catalogue" : "Event catalogue"}
          </button>
        </div>
      }
    >
      <p className="mb-2 text-xs text-muted">
        Other systems subscribe to <span className="font-mono">{cat.mqtt_topic_filter}</span>{" "}
        {cat.transport === "mqtt" ? "on the MQTT broker" : "(MQTT once MQTT_URL is set)"}, or over HTTP with Server-Sent
        Events: <span className="font-mono">GET /api/v1/events/stream?prefix=orders</span> (bearer token). Each event is
        a CloudEvents 1.0 message with a running <span className="font-mono">sequence</span>; after a disconnect,{" "}
        <span className="font-mono">GET /api/v1/events?after=…</span> replays what was missed. {cat.subscribers} live
        stream{cat.subscribers === 1 ? "" : "s"} now.
      </p>
      {showCatalog && (
        <table className="mb-3 w-full text-xs">
          <tbody>
            {cat.events.map((e) => (
              <tr key={e.topic} className="border-t border-border">
                <td className={`${td} font-mono`}>{e.topic}</td>
                <td className={td}>{e.meaning}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
      <div className="max-h-80 overflow-auto">
        <table className="w-full text-xs">
          <thead className="sticky top-0 bg-surface">
            <tr>
              <th className={th}>#</th>
              <th className={th}>Time</th>
              <th className={th}>Topic</th>
              <th className={th}>Subject</th>
              <th className={th}>Data</th>
            </tr>
          </thead>
          <tbody>
            {events.map((e) => (
              <tr key={e.sequence} className="border-t border-border">
                <td className={`${td} tabular text-muted`}>{e.sequence}</td>
                <td className={`${td} whitespace-nowrap text-muted`}>{e.time.slice(11, 19)}</td>
                <td className={`${td} font-mono`}>{e.topic.replace("warehouse/v1/", "")}</td>
                <td className={`${td} font-mono`}>{e.subject ?? ""}</td>
                <td className={`${td} max-w-[28rem] truncate`} title={JSON.stringify(e.data)}>
                  {short(e.data)}
                </td>
              </tr>
            ))}
            {!events.length && (
              <tr>
                <td colSpan={5} className={`${td} text-muted`}>
                  No events yet: start the simulation.
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
    </Panel>
  );
}
