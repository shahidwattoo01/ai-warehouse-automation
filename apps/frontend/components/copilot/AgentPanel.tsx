"use client";

import { useState } from "react";
import { Panel } from "@/components/wms/shared";
import { request } from "@/lib/api";
import { useCan } from "@/lib/auth";

interface Step {
  step: number;
  tool: string;
  args: Record<string, unknown>;
  result?: Record<string, unknown>;
  error?: string;
}

interface Pending {
  action_id: string;
  tool: string;
  args: Record<string, unknown>;
}

interface Run {
  request: string;
  answer: string;
  sources: string[];
  steps: Step[];
  pending: Pending[];
  planner: string;
  ms: number;
}

const EXAMPLES = [
  "Robot R30 has stopped. Handle it.",
  "R22 is running hot. What should we do?",
  "Close Aisle 7 for maintenance.",
  "Why was O00025 late?",
  "Prioritise all urgent orders.",
];

function brief(r: Record<string, unknown> | undefined): string {
  if (!r) return "";
  if (typeof r.status === "string") return r.status;
  const keys = Object.keys(r).slice(0, 4);
  return keys.map((k) => `${k}: ${typeof r[k] === "object" ? "…" : String(r[k])}`).join(" · ");
}

/** Phase 8: the operations agent. It looks before it acts, follows the SOPs, and every change to
 *  the warehouse waits for approval. */
export function AgentPanel() {
  const [text, setText] = useState("");
  const [run, setRun] = useState<Run | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [decided, setDecided] = useState<Record<string, string>>({});
  const canApprove = useCan("copilot:approve");

  const go = async (req: string) => {
    setBusy(true);
    setError(null);
    setDecided({});
    try {
      setRun(await request<Run>("/agents/run", { method: "POST", body: JSON.stringify({ request: req }) }));
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  };

  const decide = async (a: Pending, verb: "approve" | "reject") => {
    try {
      const r = await request<{ result?: Record<string, unknown> }>(`/agents/actions/${a.action_id}/${verb}`, {
        method: "POST",
      });
      setDecided((d) => ({ ...d, [a.action_id]: verb === "approve" ? `approved · ${brief(r.result)}` : "rejected" }));
    } catch (e) {
      setDecided((d) => ({ ...d, [a.action_id]: (e as Error).message }));
    }
  };

  return (
    <Panel title={`Operations agent${run ? ` · ${run.planner}` : ""}`}>
      <p className="mb-2 text-xs text-muted">
        Describe a situation. The agent reads the robots, orders and documents through its tools, follows the SOPs and
        proposes actions; anything that changes the warehouse waits for approval.
      </p>
      <form
        className="mb-2 flex gap-2"
        onSubmit={(e) => {
          e.preventDefault();
          if (text.trim()) void go(text.trim());
        }}
      >
        <input
          value={text}
          onChange={(e) => setText(e.target.value)}
          placeholder="e.g. Robot R30 has stopped. Handle it."
          aria-label="Agent request"
          className="flex-1 rounded-control border border-border bg-canvas px-3 py-1.5 text-sm"
        />
        <button
          disabled={busy || !text.trim()}
          className="rounded-control bg-accent px-3 py-1.5 text-sm font-medium text-white disabled:opacity-50"
        >
          {busy ? "Working…" : "Run"}
        </button>
      </form>
      <div className="mb-3 flex flex-wrap gap-1">
        {EXAMPLES.map((x) => (
          <button
            key={x}
            onClick={() => {
              setText(x);
              void go(x);
            }}
            className="rounded-full border border-border px-2 py-0.5 text-[11px] text-muted hover:border-accent hover:text-ink"
          >
            {x}
          </button>
        ))}
      </div>
      {error && <p className="text-xs text-danger">{error}</p>}
      {run && (
        <div className="space-y-3 text-xs">
          <ol className="space-y-1">
            {run.steps.map((s) => (
              <li key={s.step} className="rounded border border-border px-2 py-1">
                <span className="text-muted">{s.step}.</span> <span className="font-mono font-semibold">{s.tool}</span>
                <span className="font-mono text-muted">({JSON.stringify(s.args)})</span>
                <div className={s.error ? "text-danger" : "text-muted"}>{s.error ?? brief(s.result)}</div>
              </li>
            ))}
          </ol>
          <div className="rounded border border-accent/40 bg-accent/5 px-3 py-2 text-sm">
            {run.answer}
            {run.sources.length > 0 && (
              <div className="mt-1 text-[11px] text-muted">Sources: {run.sources.join(", ")}</div>
            )}
          </div>
          {run.pending.map((a) => (
            <div key={a.action_id} className="flex items-center gap-2 rounded border border-warning/50 px-2 py-1">
              <span>
                Waiting for approval: <span className="font-mono">{a.tool}</span>{" "}
                <span className="font-mono text-muted">{JSON.stringify(a.args)}</span>
              </span>
              <span className="ml-auto flex gap-1">
                {decided[a.action_id] ? (
                  <span className="text-muted">{decided[a.action_id]}</span>
                ) : canApprove ? (
                  <>
                    <button
                      onClick={() => void decide(a, "approve")}
                      className="rounded border border-success px-2 py-0.5 text-success"
                    >
                      Approve
                    </button>
                    <button
                      onClick={() => void decide(a, "reject")}
                      className="rounded border border-border px-2 py-0.5"
                    >
                      Reject
                    </button>
                  </>
                ) : (
                  <span className="text-muted">needs a supervisor</span>
                )}
              </span>
            </div>
          ))}
          <div className="text-[11px] text-muted">
            {run.steps.length} steps · {run.ms} ms
          </div>
        </div>
      )}
    </Panel>
  );
}
