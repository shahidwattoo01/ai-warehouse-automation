"use client";

import { BookOpen, FileText, Search } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { Screen } from "@/components/layout/Screen";
import { api } from "@/lib/api";
import type { DocType, KnowledgeAnswer, KnowledgeDocument, KnowledgeSource, KnowledgeStatus } from "@/lib/types";

// Knowledge assistant (Phase 7, RAG): answers from the warehouse documents, each statement
// citing its section. When the documents do not cover a question it says so, and still shows
// the closest passages.

const EXAMPLES = [
  "What do we do when a robot overheats?",
  "How many charging bays are there?",
  "When is a product reordered?",
  "When does the express truck leave?",
  "How do I restart the fleet after an emergency stop?",
  "Can a person walk into a closed aisle?",
  "What should happen when a robot's battery falls below the low threshold?",
  "What is the Wi-Fi password for the robot network?",
];

const DOC_TYPES: { value: DocType | null; label: string }[] = [
  { value: null, label: "All documents" },
  { value: "sop", label: "SOPs" },
  { value: "manual", label: "Manuals" },
  { value: "safety", label: "Safety" },
  { value: "maintenance", label: "Maintenance" },
  { value: "policy", label: "Inventory & shipping" },
];

const CITATION = /\[([A-Z]{2,4}-[\d.]+)\]/g;

function AnswerText({ text, onCite }: { text: string; onCite: (id: string) => void }) {
  const parts = text.split(CITATION); // odd indexes are section ids
  return (
    <p className="leading-relaxed">
      {parts.map((part, i) =>
        i % 2 === 1 ? (
          <button
            key={i}
            onClick={() => onCite(part)}
            className="mx-0.5 rounded bg-accent/15 px-1.5 py-0.5 font-mono text-[11px] text-accent hover:bg-accent/25"
          >
            {part}
          </button>
        ) : (
          <span key={i}>{part}</span>
        ),
      )}
    </p>
  );
}

function SourceCard({ source, rank, onOpen }: { source: KnowledgeSource; rank: number; onOpen: () => void }) {
  return (
    <button
      onClick={onOpen}
      className="w-full rounded-control border border-border bg-canvas p-3 text-left hover:border-accent"
    >
      <div className="flex items-center justify-between gap-2 text-xs">
        <span className="font-mono font-semibold text-accent">
          {rank}. {source.section_id}
        </span>
        <span className="text-muted">score {source.score.toFixed(2)}</span>
      </div>
      <div className="mt-0.5 text-xs text-muted">
        {source.title} · {source.heading}
      </div>
      <p className="mt-1.5 line-clamp-3 text-xs">{source.text}</p>
    </button>
  );
}

export default function KnowledgePage() {
  const [status, setStatus] = useState<KnowledgeStatus | null>(null);
  const [docs, setDocs] = useState<KnowledgeDocument[]>([]);
  const [question, setQuestion] = useState("");
  const [docType, setDocType] = useState<DocType | null>(null);
  const [answer, setAnswer] = useState<KnowledgeAnswer | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [viewer, setViewer] = useState<KnowledgeSource | null>(null);
  const input = useRef<HTMLInputElement>(null);

  // Poll the status until the models have loaded, then fetch the document list once.
  useEffect(() => {
    let stop = false;
    const poll = async () => {
      try {
        const s = await api.rag.status();
        if (stop) return;
        setStatus(s);
        if (s.loaded) {
          setDocs(await api.rag.documents());
          return;
        }
      } catch {
        /* backend not up yet */
      }
      if (!stop) setTimeout(poll, 2000);
    };
    void poll();
    input.current?.focus();
    return () => {
      stop = true;
    };
  }, []);

  const ask = async (text: string) => {
    const q = text.trim();
    if (q.length < 3 || busy) return;
    setQuestion(q);
    setBusy(true);
    setError(null);
    try {
      setAnswer(await api.rag.query(q, docType));
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  };

  const open = async (sectionId: string) => {
    const known = answer?.sources.find((s) => s.section_id === sectionId);
    try {
      setViewer(known ?? (await api.rag.section(sectionId)));
    } catch (e) {
      setError((e as Error).message);
    }
  };

  return (
    <Screen title="Knowledge · warehouse documents">
      <div className="grid gap-4 xl:grid-cols-[1fr_380px]">
        <section className="space-y-4">
          <form
            onSubmit={(e) => {
              e.preventDefault();
              void ask(question);
            }}
            className="rounded-card border border-border bg-surface p-4"
          >
            <div className="flex gap-2">
              <input
                ref={input}
                value={question}
                onChange={(e) => setQuestion(e.target.value)}
                maxLength={500}
                placeholder="Ask about procedures, safety rules, robots, stock…"
                aria-label="Question"
                className="flex-1 rounded-control border border-border bg-canvas px-3 py-2 text-sm outline-none focus:border-accent"
              />
              <button
                type="submit"
                disabled={busy || question.trim().length < 3}
                className="flex items-center gap-1.5 rounded-control bg-accent px-3 py-2 text-sm font-medium text-white disabled:opacity-50"
              >
                <Search size={14} /> {busy ? "Searching…" : "Ask"}
              </button>
            </div>
            <div className="mt-3 flex flex-wrap gap-1.5">
              {DOC_TYPES.map((t) => (
                <button
                  type="button"
                  key={t.label}
                  onClick={() => setDocType(t.value)}
                  className={`rounded-full border px-2.5 py-0.5 text-xs ${
                    docType === t.value ? "border-accent bg-accent/15 text-ink" : "border-border text-muted"
                  }`}
                >
                  {t.label}
                </button>
              ))}
            </div>
            {!answer && (
              <div className="mt-3 flex flex-wrap gap-1.5">
                {EXAMPLES.map((e) => (
                  <button
                    type="button"
                    key={e}
                    onClick={() => void ask(e)}
                    className="rounded-full border border-border px-2.5 py-1 text-xs text-muted hover:border-accent hover:text-ink"
                  >
                    {e}
                  </button>
                ))}
              </div>
            )}
          </form>

          {error && <div className="rounded-card border border-danger/50 bg-danger/10 p-3 text-sm">{error}</div>}

          {answer && (
            <div className="space-y-3 rounded-card border border-border bg-surface p-4 text-sm">
              <div className="text-xs font-semibold uppercase tracking-wide text-muted">Answer</div>
              {answer.covered ? (
                <AnswerText text={answer.answer} onCite={(id) => void open(id)} />
              ) : (
                <div className="rounded-control border border-warning/50 bg-warning/10 p-3">
                  <b>Not covered.</b> {answer.answer} The closest passages are below.
                </div>
              )}
              <div className="text-[11px] text-muted">
                {answer.generator} · {answer.retriever} retrieval · {answer.ms} ms
              </div>
              <div className="text-xs font-semibold uppercase tracking-wide text-muted">
                {answer.covered ? "Sources" : "Closest passages"}
              </div>
              <div className="grid gap-2 md:grid-cols-3">
                {answer.sources.map((s, i) => (
                  <SourceCard key={s.chunk_id} source={s} rank={i + 1} onOpen={() => setViewer(s)} />
                ))}
              </div>
            </div>
          )}

          {viewer && (
            <div className="rounded-card border border-accent/40 bg-surface p-4 text-sm">
              <div className="flex items-center justify-between">
                <div className="flex items-center gap-2 font-semibold">
                  <FileText size={15} /> <span className="font-mono">{viewer.section_id}</span> · {viewer.heading}
                </div>
                <button onClick={() => setViewer(null)} className="text-xs text-muted hover:text-ink">
                  Close
                </button>
              </div>
              <div className="mt-0.5 text-xs text-muted">{viewer.title}</div>
              <pre className="mt-3 whitespace-pre-wrap font-sans text-sm leading-relaxed">{viewer.text}</pre>
            </div>
          )}
        </section>

        <aside className="space-y-3 text-sm">
          <div className="rounded-card border border-border bg-surface p-4">
            <div className="mb-2 text-xs font-semibold uppercase tracking-wide text-muted">How it answers</div>
            <ol className="list-decimal space-y-1 pl-4 text-xs text-muted">
              <li>
                <b className="text-ink">Retrieve</b>: keyword + meaning search over the document sections, best 3
                re-ranked
              </li>
              <li>
                <b className="text-ink">Check</b>: too weak a match → &quot;not covered&quot; instead of a guess
              </li>
              <li>
                <b className="text-ink">Answer</b> from those sections only, citing each one
              </li>
            </ol>
            <div className="mt-3 text-xs">
              {status?.loaded ? (
                <>
                  {status.documents} documents · {status.chunks} sections · {status.store} search
                </>
              ) : status?.error ? (
                <span className="text-danger">Unavailable: {status.error}</span>
              ) : (
                "Loading the documents and models…"
              )}
            </div>
          </div>
          <div className="rounded-card border border-border bg-surface p-4">
            <div className="mb-2 flex items-center gap-1.5 text-xs font-semibold uppercase tracking-wide text-muted">
              <BookOpen size={13} /> Documents
            </div>
            <div className="max-h-[60vh] space-y-2 overflow-auto">
              {docs.map((d) => (
                <details key={d.doc_id} className="text-xs">
                  <summary className="cursor-pointer font-medium">
                    {d.title} <span className="text-muted">({d.sections.length})</span>
                  </summary>
                  <ul className="mt-1 space-y-0.5 pl-3">
                    {d.sections.map((s) => (
                      <li key={s.section_id}>
                        <button onClick={() => void open(s.section_id)} className="text-left text-muted hover:text-ink">
                          <span className="font-mono">{s.section_id}</span> {s.heading}
                        </button>
                      </li>
                    ))}
                  </ul>
                </details>
              ))}
            </div>
          </div>
        </aside>
      </div>
    </Screen>
  );
}
