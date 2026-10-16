"use client";

import { useEffect, useState } from "react";
import { api } from "@/lib/api";
import { useSim } from "@/lib/store";

/**
 * Phase 4: switch the running warehouse between decision-rule presets, the same strategies as the
 * optimisation experiments (configs/experiments/E1-E5): E2 is today's baseline, E5 the fully
 * optimised fleet. The change applies between two ticks.
 */
export function StrategySelect() {
  const current = useSim((s) => s.strategy?.preset ?? null);
  const [presets, setPresets] = useState<Record<string, { name: string; description: string }>>({});
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    api.simulation
      .strategy()
      .then((r) => setPresets(r.presets))
      .catch(() => setPresets({}));
  }, []);

  if (!Object.keys(presets).length) return null;
  return (
    <label className="flex items-center gap-1.5 text-xs text-muted" title={current ? presets[current]?.description : undefined}>
      Strategy
      <select
        aria-label="Decision strategy"
        value={current ?? ""}
        disabled={busy}
        onChange={async (e) => {
          setBusy(true);
          try {
            await api.simulation.setPreset(e.target.value);
          } finally {
            setBusy(false);
          }
        }}
        className="max-w-[230px] rounded-control border border-border bg-surface px-2 py-1.5 text-sm text-ink"
      >
        {current === null && <option value="">Custom</option>}
        {Object.entries(presets).map(([id, p]) => (
          <option key={id} value={id}>
            {id} · {p.name}
          </option>
        ))}
      </select>
    </label>
  );
}
