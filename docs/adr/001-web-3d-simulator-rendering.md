# ADR 001 — Realistic 3D rendering with React Three Fiber

**Status:** Accepted · 2026-10-09

## Context

The simulator must look like a real warehouse — robots, racking, pallets, packing stations and workers rendered as real-world objects (Isaac Sim quality as the reference), not labelled boxes. The development and demo machine has no local GPU; GPU training runs on Colab, Kaggle or Azure.

## Decision

- **Simulation logic** stays in Python (`simulation/`): grid, tick loop, physics-lite movement, events. It is the single source of truth.
- **Rendering** happens in the browser with **React Three Fiber + drei** (Three.js) inside the Next.js Control Center, driven by the WebSocket state stream.
- Realism comes from **PBR glTF/GLB models** (`apps/frontend/public/models/`), **HDRI environment lighting**, soft shadows, ambient occlusion, tone mapping and smooth interpolation between ticks.
- **Synthetic camera frames** for computer vision come from the same 3D scene, captured offscreen by a headless browser script, together with ground-truth labels from simulator state.

## Consequences

- Runs on any laptop with a WebGL2 browser; no RTX GPU or Omniverse install needed.
- Visual quality depends on good assets; asset sourcing and optimisation (Draco/meshopt compression, LODs) is a tracked task.
- NVIDIA Isaac Sim is not used. A future high-fidelity renderer could consume the same `warehouse_state`, since rendering is decoupled from logic.
