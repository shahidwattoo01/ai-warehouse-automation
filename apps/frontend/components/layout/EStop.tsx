"use client";

import { OctagonX, RotateCcw, ShieldCheck } from "lucide-react";
import { useState } from "react";
import { create } from "zustand";
import { safety } from "@/lib/safety";
import { useCan } from "@/lib/auth";
import { useSim } from "@/lib/store";
import type { SafetyState } from "@/lib/types";

// The answer of a stop / release / reset request, shown at once. The live stream can still
// deliver older states for a moment (e.g. a backlog after running fast), so the newest by
// simulation tick wins: a stop is never hidden by a message from before it.
// It expires after 30 s (a reset simulation starts again at tick 0).
const useLocal = create<{ s: SafetyState | null; at: number }>(() => ({ s: null, at: 0 }));

function apply(next: SafetyState) {
  useLocal.setState({ s: next, at: Date.now() });
}

/** The current safety state: the newer of the live stream and the last request's answer. */
export function useSafety(): SafetyState | undefined {
  const stream = useSim((st) => st.state?.safety);
  const { s: local, at } = useLocal();
  if (local && Date.now() - at < 30_000 && (!stream || local.tick >= stream.tick)) return local;
  return stream;
}

/** The emergency stop button: one press, no confirmation, for every logged-in user. */
export function EStopButton() {
  const current = useSafety();
  const engaged = current?.state === "ESTOP" && current.stop?.scope === "fleet";
  const [busy, setBusy] = useState(false);
  return (
    <button
      onClick={async () => {
        setBusy(true);
        try {
          apply(await safety.estop());
        } catch (e) {
          alert((e as Error).message);
        } finally {
          setBusy(false);
        }
      }}
      disabled={busy || engaged}
      title="Emergency stop: every robot stops where it is"
      aria-label="Emergency stop"
      className="flex shrink-0 items-center gap-1.5 whitespace-nowrap rounded-control border-2 border-red-700 bg-red-600 px-3 py-1.5 text-sm font-bold uppercase tracking-wide text-white shadow-sm hover:bg-red-700 disabled:opacity-60"
    >
      <OctagonX size={16} /> E-stop
    </button>
  );
}

/** Across the top of every page while a stop is engaged or waiting for a reset. */
export function SafetyBanner() {
  const s = useSafety();
  const canReset = useCan("safety:reset");
  const [error, setError] = useState<string | null>(null);
  if (!s || s.state === "NORMAL") return null;
  const where = s.stop?.scope === "zone" ? `robots in ${s.stop.zone}` : "all robots";
  const act = async (call: () => Promise<SafetyState>) => {
    try {
      apply(await call());
      setError(null);
    } catch (e) {
      setError((e as Error).message);
    }
  };
  const engaged = s.state === "ESTOP";
  return (
    <div
      role="alert"
      className={`flex flex-wrap items-center gap-3 px-6 py-2 text-sm text-white ${engaged ? "bg-red-600" : "bg-amber-600"}`}
    >
      <OctagonX size={18} />
      <b className="uppercase tracking-wide">{engaged ? "Emergency stop" : "Stop released, waiting for reset"}</b>
      <span>
        {engaged
          ? `${s.robots_held.length} ${where === "all robots" ? "robots" : where} held · ${s.stop?.reason} · by ${s.stop?.by}`
          : `${s.robots_held.length} robots still holding. Check that the area is clear, then reset to restart.`}
      </span>
      {error && <span className="rounded bg-white/20 px-2 py-0.5">{error}</span>}
      {canReset && (
        <div className="ml-auto flex gap-2">
          {engaged ? (
            <button
              onClick={() => act(() => safety.release())}
              className="flex items-center gap-1 rounded-control bg-white/20 px-3 py-1 font-semibold hover:bg-white/30"
            >
              <ShieldCheck size={14} /> Release
            </button>
          ) : (
            <>
              {error?.includes("person") && (
                <button
                  onClick={() => act(() => safety.reset(true))}
                  title="Logged under your name"
                  className="rounded-control border border-white/60 px-3 py-1 font-semibold hover:bg-white/10"
                >
                  Area checked, reset anyway
                </button>
              )}
              <button
                onClick={() => act(() => safety.reset())}
                className="flex items-center gap-1 rounded-control bg-white px-3 py-1 font-semibold text-amber-700 hover:bg-white/90"
              >
                <RotateCcw size={14} /> Reset and restart robots
              </button>
            </>
          )}
        </div>
      )}
    </div>
  );
}
