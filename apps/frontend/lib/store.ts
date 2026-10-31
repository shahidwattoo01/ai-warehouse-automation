"use client";

import { create } from "zustand";
import { refreshSession, useAuth } from "./auth";
import { initialQuality, type Quality, saveQuality } from "./quality";
import type { LayoutSnapshot, Predictions, Strategy, StreamMessage, WarehouseState } from "./types";

const WS_URL = process.env.NEXT_PUBLIC_WS_URL ?? "ws://localhost:8000/api/v1/simulation/stream";

interface SimStore {
  layout: LayoutSnapshot | null;
  state: WarehouseState | null;
  /** Live Phase 3 model predictions, sent with every tick. */
  predictions: Predictions | null;
  /** Phase 4 decision rules in use, sent with every tick. */
  strategy: Strategy | null;
  connected: boolean;
  selectedRobot: string | null;
  lastTickAt: number;
  /** Smoothed seconds between ticks; the 3D scene moves entities at 1 cell per interval. */
  tickInterval: number;
  /** 3D graphics quality preset (see lib/quality.ts). */
  quality: Quality;
  connect: () => () => void;
  selectRobot: (id: string | null) => void;
  setQuality: (q: Quality) => void;
}

/** One shared WebSocket feeds every screen and the 3D scene. */
export const useSim = create<SimStore>((set, get) => ({
  layout: null,
  state: null,
  predictions: null,
  strategy: null,
  connected: false,
  selectedRobot: null,
  lastTickAt: 0,
  tickInterval: 0.5,
  quality: initialQuality(),

  connect: () => {
    let ws: WebSocket | null = null;
    let retry: ReturnType<typeof setTimeout> | undefined;
    let closed = false;
    let delay = 1000; // reconnect backoff: 1 s, doubling up to 10 s

    const open = () => {
      const socket = new WebSocket(WS_URL);
      ws = socket;
      socket.onopen = () => {
        delay = 1000;
        // Authenticate with the first message (browsers cannot add headers to a WebSocket).
        socket.send(JSON.stringify({ type: "auth", token: useAuth.getState().token }));
        set({ connected: true });
      };
      socket.onclose = async (e) => {
        // A socket replaced or shut down on purpose (page change, React re-mount in development)
        // must not mark the live connection as lost: only the current socket reports its state.
        if (closed || socket !== ws) return;
        set({ connected: false });
        if (e.code === 4401 && !(await refreshSession())) return; // logged out: stop retrying
        retry = setTimeout(open, delay); // App Flow §10: auto-reconnect
        delay = Math.min(delay * 2, 10_000);
      };
      socket.onmessage = (e) => {
        let msg: StreamMessage;
        try {
          msg = JSON.parse(e.data);
        } catch {
          return; // ignore a malformed frame rather than breaking the stream
        }
        if (msg.type === "layout") set({ layout: msg.layout });
        else if (msg.type === "tick") {
          const now = performance.now();
          const { lastTickAt, tickInterval } = get();
          const gap = lastTickAt ? (now - lastTickAt) / 1000 : tickInterval;
          const next = gap > 0.03 && gap < 3 ? tickInterval * 0.8 + gap * 0.2 : tickInterval;
          set({
            state: msg.state,
            predictions: msg.predictions ?? null,
            strategy: msg.strategy ?? null,
            lastTickAt: now,
            tickInterval: next,
          });
        }
      };
    };
    open();

    return () => {
      closed = true;
      clearTimeout(retry);
      ws?.close();
    };
  },

  selectRobot: (id) => set({ selectedRobot: id }),
  setQuality: (quality) => {
    saveQuality(quality);
    set({ quality });
  },
}));
