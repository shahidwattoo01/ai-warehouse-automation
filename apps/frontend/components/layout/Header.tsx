"use client";

import { Pause, Play, RotateCcw } from "lucide-react";
import { useState } from "react";
import { api } from "@/lib/api";
import { useSim } from "@/lib/store";
import { Can } from "./Can";
import { EStopButton } from "./EStop";
import { StrategySelect } from "./StrategySelect";
import { ThemeToggle } from "./ThemeToggle";
import { UserMenu } from "./UserMenu";

export function Header({ title }: { title: string }) {
  const running = useSim((s) => s.state?.running ?? false);
  const [pending, setPending] = useState(false);
  // Flip the button as soon as the server confirms (the state stream also reports it).
  const toggle = async () => {
    setPending(true);
    try {
      const res = running ? await api.simulation.pause() : await api.simulation.start();
      useSim.setState((s) => (s.state ? { state: { ...s.state, running: res.running } } : {}));
    } finally {
      setPending(false);
    }
  };
  return (
    <header className="flex h-14 items-center justify-between border-b border-border px-6">
      <h1 className="text-xl font-semibold">{title}</h1>
      <div className="flex items-center gap-2">
        <EStopButton />
        <Can
          permission="simulation:control"
          fallback={
            <span className="rounded-control border border-border px-3 py-1.5 text-sm text-muted">
              {running ? "Running" : "Paused"}
            </span>
          }
        >
          <button
            onClick={() => void toggle()}
            disabled={pending}
            aria-pressed={running}
            className="flex items-center gap-2 rounded-control border border-border px-3 py-1.5 text-sm disabled:opacity-60"
          >
            {running ? <Pause size={16} /> : <Play size={16} />} {running ? "Pause" : "Start"}
          </button>
          <select
            aria-label="Simulation speed"
            onChange={(e) => api.simulation.speed(Number(e.target.value))}
            defaultValue="1"
            className="rounded-control border border-border bg-surface px-2 py-1.5 text-sm"
          >
            {[0.5, 1, 2, 5, 10].map((v) => (
              <option key={v} value={v}>
                {v}×
              </option>
            ))}
          </select>
          <button
            onClick={() =>
              confirm("Reset the simulation? The current run will be saved and closed.") && api.simulation.reset()
            }
            className="rounded-control border border-border p-2"
            aria-label="Reset simulation"
          >
            <RotateCcw size={16} />
          </button>
          <StrategySelect />
        </Can>
        <ThemeToggle />
        <Can permission="copilot:use">
          <a
            href="/copilot"
            className="rounded-control border border-accent bg-accent/15 px-3 py-1.5 text-sm font-semibold"
          >
            Ask Copilot <kbd className="ml-1 font-mono text-muted">/</kbd>
          </a>
        </Can>
        <UserMenu />
      </div>
    </header>
  );
}
