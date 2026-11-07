"use client";

import { useEffect, useState } from "react";
import { Screen } from "@/components/layout/Screen";
import { api } from "@/lib/api";
import type { RLHistoryEntry, RLStatus } from "@/lib/types";

function RewardCurve({ history }: { history: RLHistoryEntry[] }) {
  if (history.length === 0) {
    return <div className="text-sm text-muted">No training history yet — click Train to start.</div>;
  }
  const rewards = history.map((h) => h.mean_reward);
  const min = Math.min(...rewards);
  const max = Math.max(...rewards);
  const range = max - min || 1;
  const W = 480;
  const H = 120;
  const pad = 8;
  const pts = history.map((h, i) => {
    const x = pad + (i / Math.max(1, history.length - 1)) * (W - 2 * pad);
    const y = pad + ((1 - (h.mean_reward - min) / range) * (H - 2 * pad));
    return `${x},${y}`;
  });

  return (
    <div className="rounded-card border border-border bg-surface p-4">
      <div className="mb-2 text-xs text-muted">Mean reward per 50-episode checkpoint</div>
      <svg viewBox={`0 0 ${W} ${H}`} className="w-full" style={{ height: H }}>
        <polyline
          points={pts.join(" ")}
          fill="none"
          stroke="var(--color-accent)"
          strokeWidth="2"
          strokeLinejoin="round"
        />
        {history.map((h, i) => {
          const x = pad + (i / Math.max(1, history.length - 1)) * (W - 2 * pad);
          const y = pad + ((1 - (h.mean_reward - min) / range) * (H - 2 * pad));
          return (
            <circle key={i} cx={x} cy={y} r="3" fill="var(--color-accent)" opacity="0.8">
              <title>ep {h.episode}: reward {h.mean_reward.toFixed(1)}, ε={h.eps}</title>
            </circle>
          );
        })}
      </svg>
      <div className="mt-1 flex justify-between text-xs text-muted">
        <span>ep {history[0]?.episode}</span>
        <span>ep {history[history.length - 1]?.episode}</span>
      </div>
    </div>
  );
}

function HistoryTable({ history }: { history: RLHistoryEntry[] }) {
  if (history.length === 0) return null;
  return (
    <div className="rounded-card border border-border bg-surface">
      <table className="w-full text-xs">
        <thead>
          <tr className="border-b border-border text-left text-muted">
            <th className="px-4 py-2">Episode</th>
            <th className="px-4 py-2">Mean reward</th>
            <th className="px-4 py-2">Deliveries / ep</th>
            <th className="px-4 py-2">Epsilon</th>
          </tr>
        </thead>
        <tbody>
          {history.map((h) => (
            <tr key={h.episode} className="border-b border-border/50 last:border-0 hover:bg-border/30">
              <td className="px-4 py-1.5 font-mono">{h.episode}</td>
              <td className="px-4 py-1.5">{h.mean_reward.toFixed(2)}</td>
              <td className="px-4 py-1.5">{h.mean_deliveries.toFixed(1)}</td>
              <td className="px-4 py-1.5">{h.eps.toFixed(4)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export default function RLPage() {
  const [status, setStatus] = useState<RLStatus | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [training, setTraining] = useState(false);
  const [trainResult, setTrainResult] = useState<{ version: string; metrics: Record<string, number> } | null>(null);

  const load = () => {
    api.rl
      .status()
      .then(setStatus)
      .catch((e) => setError(String(e.message ?? e)));
  };

  useEffect(() => {
    load();
    const id = setInterval(load, 10_000);
    return () => clearInterval(id);
  }, []);

  const handleTrain = async () => {
    setTraining(true);
    setTrainResult(null);
    setError(null);
    try {
      const r = await api.rl.train();
      setTrainResult(r);
      load();
    } catch (e: unknown) {
      setError(String((e as Error).message ?? e));
    } finally {
      setTraining(false);
    }
  };

  return (
    <Screen title="RL Training">
      <div className="space-y-6">
        <div className="flex items-center justify-between">
          <div>
            <h1 className="text-lg font-semibold">Multi-Agent RL Training</h1>
            <p className="mt-0.5 text-sm text-muted">
              Shared-policy DQN — all robots share one network (Phase 9, PR-MARL)
            </p>
          </div>
          <button
            onClick={handleTrain}
            disabled={training || !status?.enabled}
            className="rounded-control bg-accent px-4 py-2 text-sm font-medium text-white hover:bg-accent/90 disabled:opacity-50"
          >
            {training ? "Training…" : "Train"}
          </button>
        </div>

        {error && (
          <div className="rounded-card border border-danger/40 bg-danger/10 px-4 py-3 text-sm text-danger">
            {error}
          </div>
        )}

        {trainResult && (
          <div className="rounded-card border border-success/40 bg-success/10 px-4 py-3 text-sm">
            Training complete — version <span className="font-mono">{trainResult.version}</span>.
            Mean reward (last 20): {trainResult.metrics.mean_reward_last20?.toFixed(2)},
            deliveries: {trainResult.metrics.mean_deliveries_last20?.toFixed(1)}
          </div>
        )}

        {status && (
          <div className="grid grid-cols-2 gap-4 sm:grid-cols-4">
            {[
              { label: "MARL enabled", value: status.enabled ? "Yes" : "No" },
              { label: "Episodes", value: status.config.episodes ?? "—" },
              { label: "Episode ticks", value: status.config.episode_ticks ?? "—" },
              { label: "History points", value: status.history.length },
            ].map(({ label, value }) => (
              <div key={label} className="rounded-card border border-border bg-surface p-4">
                <div className="text-xs text-muted">{label}</div>
                <div className="mt-1 text-xl font-semibold tabular-nums">{String(value)}</div>
              </div>
            ))}
          </div>
        )}

        {status && <RewardCurve history={status.history} />}

        {status && <HistoryTable history={status.history} />}
      </div>
    </Screen>
  );
}
