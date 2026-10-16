"use client";

import { Pause, Play, RotateCcw } from "lucide-react";
import { api } from "@/lib/api";
import { useSim } from "@/lib/store";
import { StrategySelect } from "./StrategySelect";
import { ThemeToggle } from "./ThemeToggle";

export function Header({ title }: { title: string }) {
  const running = useSim((s) => s.state?.running ?? false);
  return (
    <header className="flex h-14 items-center justify-between border-b border-border px-6">
      <h1 className="text-xl font-semibold">{title}</h1>
      <div className="flex items-center gap-2">
        <button
          onClick={() => (running ? api.simulation.pause() : api.simulation.start())}
          className="flex items-center gap-2 rounded-control border border-border px-3 py-1.5 text-sm"
        >
          {running ? <Pause size={16} /> : <Play size={16} />} {running ? "Pause" : "Start"}
        </button>
        <select
          aria-label="Simulation speed"
          onChange={(e) => api.simulation.speed(Number(e.target.value))}
          defaultValue="1"
          className="rounded-control border border-border bg-surface px-2 py-1.5 text-sm"
        >
          {[0.5, 1, 2, 5, 10].map((v) => <option key={v} value={v}>{v}×</option>)}
        </select>
        <button
          onClick={() => confirm("Reset the simulation? The current run will be saved and closed.") && api.simulation.reset()}
          className="rounded-control border border-border p-2"
          aria-label="Reset simulation"
        >
          <RotateCcw size={16} />
        </button>
        <StrategySelect />
        <ThemeToggle />
        <a href="/copilot" className="rounded-control border border-accent bg-accent/15 px-3 py-1.5 text-sm font-semibold">
          Ask Copilot <kbd className="ml-1 font-mono text-muted">/</kbd>
        </a>
      </div>
    </header>
  );
}
