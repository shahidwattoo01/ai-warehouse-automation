"use client";

import { Can } from "@/components/layout/Can";
import { Check, Send, X } from "lucide-react";
import { useCallback, useEffect, useRef, useState } from "react";
import { AgentPanel } from "@/components/copilot/AgentPanel";
import { Screen } from "@/components/layout/Screen";
import { api } from "@/lib/api";
import type { CopilotHistoryItem, CopilotReply, CopilotStatus, ToolCall } from "@/lib/types";

// Operator copilot (Phase 6): plain-language commands. Read-only questions are answered at once;
// actions that change the warehouse are shown as a card and run only after "Approve".

const EXAMPLES = [
  "where is robot 7?",
  "pause R-12 now",
  "how many high priority orders are waiting?",
  "how many units of P-A-05-12 are left?",
  "close aisle 30 for maintenance",
  "keep robot 5 out of aisle 12",
  "what's the route for R3 to packing station 2?",
  "give me a fleet overview",
  "order me a pizza",
];

const ENTITY_COLOR: Record<string, string> = {
  ROBOT: "bg-accent/15 text-accent",
  ORDER: "bg-warning/15 text-warning",
  AISLE: "bg-danger/15 text-danger",
  PRODUCT: "bg-success/15 text-success",
};

interface Turn {
  id: number;
  text: string;
  reply?: CopilotReply;
  error?: string;
  outcome?: { ok: boolean; answer: string };
}

function callText(c: ToolCall): string {
  const args = Object.entries(c.arguments)
    .map(([k, v]) => `${k}=${typeof v === "string" ? v : JSON.stringify(v)}`)
    .join(", ");
  return `${c.name}(${args})`;
}

function Understanding({ reply }: { reply: CopilotReply }) {
  const u = reply.understanding;
  return (
    <div className="mt-2 space-y-1.5 border-t border-border pt-2 text-xs">
      <div className="flex flex-wrap items-center gap-1.5">
        <span className="text-muted">Intent</span>
        <span className="rounded bg-canvas px-1.5 py-0.5 font-mono">{u.intent}</span>
        <span className="text-muted">{Math.round(u.confidence * 100)}% confident</span>
        {u.entities.map((e, i) => (
          <span key={i} className={`rounded px-1.5 py-0.5 ${ENTITY_COLOR[e.type] ?? "bg-canvas text-ink"}`}>
            {e.type}: <b>{e.value}</b> <span className="opacity-60">“{e.text}”</span>
          </span>
        ))}
      </div>
      {u.tool_calls.map((c, i) => (
        <div key={i} className="font-mono text-[11px] text-muted">
          → {callText(c)} {u.requires_approval && <span className="text-warning">· needs approval</span>}
        </div>
      ))}
    </div>
  );
}

export default function CopilotPage() {
  const [status, setStatus] = useState<CopilotStatus | null>(null);
  const [turns, setTurns] = useState<Turn[]>([]);
  const [text, setText] = useState("");
  const [busy, setBusy] = useState(false);
  const [history, setHistory] = useState<CopilotHistoryItem[]>([]);
  const input = useRef<HTMLInputElement>(null);
  const end = useRef<HTMLDivElement>(null);
  const nextId = useRef(1);

  const refresh = useCallback(() => {
    api.copilot
      .status()
      .then(setStatus)
      .catch(() => undefined);
    api.copilot
      .history()
      .then(setHistory)
      .catch(() => undefined);
  }, []);

  useEffect(() => {
    refresh();
    input.current?.focus();
    const id = setInterval(refresh, 5000);
    return () => clearInterval(id);
  }, [refresh]);

  useEffect(() => {
    end.current?.scrollIntoView({ behavior: "smooth", block: "end" });
  }, [turns]);

  const send = async (message: string) => {
    const t = message.trim();
    if (!t || busy) return;
    const id = nextId.current++;
    setTurns((all) => [...all, { id, text: t }]);
    setText("");
    setBusy(true);
    try {
      const reply = await api.copilot.chat(t);
      setTurns((all) => all.map((x) => (x.id === id ? { ...x, reply } : x)));
    } catch (e) {
      setTurns((all) => all.map((x) => (x.id === id ? { ...x, error: (e as Error).message } : x)));
    } finally {
      setBusy(false);
      refresh();
      input.current?.focus();
    }
  };

  const decide = async (turn: Turn, approve: boolean) => {
    const action = turn.reply?.action;
    if (!action) return;
    const outcome = approve ? await api.copilot.approve(action.id) : await api.copilot.reject(action.id);
    setTurns((all) => all.map((x) => (x.id === turn.id ? { ...x, outcome } : x)));
    refresh();
  };

  return (
    <Screen title="Copilot · operator commands">
      <div className="grid gap-4 xl:grid-cols-[1fr_340px]">
        <section className="flex min-h-[70vh] flex-col rounded-card border border-border bg-surface">
          <div className="flex-1 space-y-3 overflow-auto p-4">
            {turns.length === 0 && (
              <div className="text-sm text-muted">
                <p className="mb-2">
                  Type a command in plain words. Questions are answered at once; anything that changes the warehouse
                  (pause a robot, close an aisle, create an order …) is shown as a card and runs only after you approve
                  it. Try:
                </p>
                <div className="flex flex-wrap gap-1.5">
                  {EXAMPLES.map((e) => (
                    <button
                      key={e}
                      onClick={() => void send(e)}
                      className="rounded-full border border-border px-2.5 py-1 text-xs hover:border-accent hover:text-ink"
                    >
                      {e}
                    </button>
                  ))}
                </div>
              </div>
            )}
            {turns.map((turn) => (
              <div key={turn.id} className="space-y-1.5">
                <div className="ml-auto w-fit max-w-[80%] rounded-card bg-accent px-3 py-2 text-sm text-white">
                  {turn.text}
                </div>
                <div className="w-fit max-w-[90%] rounded-card border border-border bg-canvas px-3 py-2 text-sm">
                  {!turn.reply && !turn.error && <span className="text-muted">Thinking…</span>}
                  {turn.error && <span className="text-danger">{turn.error}</span>}
                  {turn.reply && (
                    <>
                      <div>{turn.reply.answer}</div>
                      {turn.reply.action && !turn.outcome && (
                        <div
                          className={`mt-2 flex items-center gap-2 rounded-control border p-2 ${
                            turn.reply.action.unsure
                              ? "border-danger/60 bg-danger/10"
                              : "border-warning/50 bg-warning/10"
                          }`}
                        >
                          <span className="flex-1 text-xs">
                            <b>{turn.reply.action.unsure ? "Not sure, check first:" : "Approval needed:"}</b>{" "}
                            {turn.reply.action.summary}
                          </span>
                          <Can
                            permission="copilot:approve"
                            fallback={<span className="text-xs text-muted">Waiting for an operator or supervisor</span>}
                          >
                            <button
                              onClick={() => void decide(turn, true)}
                              className="flex items-center gap-1 rounded-control bg-success px-2.5 py-1 text-xs font-medium text-white"
                            >
                              <Check size={14} /> Approve
                            </button>
                            <button
                              onClick={() => void decide(turn, false)}
                              className="flex items-center gap-1 rounded-control border border-border px-2.5 py-1 text-xs"
                            >
                              <X size={14} /> Cancel
                            </button>
                          </Can>
                        </div>
                      )}
                      {turn.outcome && (
                        <div className={`mt-2 text-xs ${turn.outcome.ok ? "text-success" : "text-danger"}`}>
                          {turn.outcome.answer}
                        </div>
                      )}
                      <Understanding reply={turn.reply} />
                    </>
                  )}
                </div>
              </div>
            ))}
            <div ref={end} />
          </div>
          <form
            onSubmit={(e) => {
              e.preventDefault();
              void send(text);
            }}
            className="flex gap-2 border-t border-border p-3"
          >
            <input
              ref={input}
              value={text}
              onChange={(e) => setText(e.target.value)}
              maxLength={500}
              placeholder='e.g. "pause robot 12" or "how many orders are waiting?"'
              aria-label="Command"
              className="flex-1 rounded-control border border-border bg-canvas px-3 py-2 text-sm outline-none focus:border-accent"
            />
            <button
              type="submit"
              disabled={busy || !text.trim()}
              className="flex items-center gap-1.5 rounded-control bg-accent px-3 py-2 text-sm font-medium text-white disabled:opacity-50"
            >
              <Send size={14} /> Send
            </button>
          </form>
        </section>

        <aside className="space-y-3 text-sm">
          <div className="rounded-card border border-border bg-surface p-4">
            <div className="mb-2 text-xs font-semibold uppercase tracking-wide text-muted">How it understands</div>
            <ol className="list-decimal space-y-1 pl-4 text-xs text-muted">
              <li>
                <b className="text-ink">Intent</b>: what you want (17 kinds)
              </li>
              <li>
                <b className="text-ink">Entities</b>: robot, order, aisle, product, priority …
              </li>
              <li>
                <b className="text-ink">Tool call</b>: the exact action, checked against the live warehouse
              </li>
            </ol>
            <div className="mt-3 text-xs">
              Model: <b>{status?.algorithm ?? (status ? "loading…" : "connecting…")}</b>
            </div>
            <p className="mt-1 text-[11px] text-muted">
              Changes to the warehouse always need your approval; unclear messages get a question back.
            </p>
          </div>
          <div className="rounded-card border border-border bg-surface p-4">
            <div className="mb-2 text-xs font-semibold uppercase tracking-wide text-muted">Audit trail</div>
            {history.length === 0 ? (
              <p className="text-xs text-muted">No commands yet.</p>
            ) : (
              <ul className="space-y-1.5 text-xs">
                {history.slice(0, 12).map((h, i) => (
                  <li key={i} className="border-b border-border pb-1 last:border-0">
                    <div className="flex justify-between gap-2">
                      <span className="truncate">{h.text}</span>
                      <span className="shrink-0 font-mono text-muted">t{h.tick}</span>
                    </div>
                    <div
                      className={
                        h.outcome.startsWith("approved")
                          ? "text-success"
                          : h.outcome === "rejected"
                            ? "text-danger"
                            : "text-muted"
                      }
                    >
                      {h.outcome}
                    </div>
                  </li>
                ))}
              </ul>
            )}
          </div>
        </aside>
      </div>
      <div className="mt-4">
        <AgentPanel />
      </div>
    </Screen>
  );
}
