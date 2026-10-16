"use client";

import { useMemo } from "react";
import { BoxGeometry, CylinderGeometry, DoubleSide, MeshPhysicalMaterial, MeshStandardMaterial, PlaneGeometry } from "three";
import type { Shelf } from "@/lib/types";
import { gridToWorld } from "./coords";
import { InstancedParts, type Placement } from "./Instanced";
import { SignBoards } from "./SignBoards";
import { cartonTexture, hazardTexture, meshDeckTexture, palletDeckTexture, signTexture, uprightTexture, woodTexture } from "./textures";

const BAY = 1.0; // bay pitch along the row (1 grid cell)
const DEPTH = 0.9; // frame depth
const BEAM_LEVELS = [1.15, 2.3, 3.45]; // beam heights in metres; pallets also sit on the floor
const UPRIGHT_H = 4.6;
const PALLET = { w: 0.8, d: 1.0, h: 0.144 };

/** Deterministic per-slot randomness so the stock picture is stable between renders. */
function hash(...n: number[]) {
  let h = 2166136261;
  for (const v of n) h = Math.imul(h ^ (v + 0x9e3779b9), 16777619);
  return ((h >>> 0) % 10000) / 10000;
}

/**
 * Selective pallet racking modelled like real steel racking: perforated blue uprights with
 * base plates and anchor bolts, braced frames, orange step beams, wire mesh decks,
 * wooden pallets carrying shrink-wrapped carton stacks, beam location labels and aisle signs.
 * Everything is instanced: about a dozen draw calls however many bays there are.
 */
export function Racking({
  shelves,
  width,
  height,
  detail = "full",
}: {
  shelves: Shelf[];
  width: number;
  height: number;
  /** "lite" skips shrink-wrap, labels, diagonal bracing and base plates for integrated GPUs. */
  detail?: "full" | "lite";
}) {
  const mats = useMemo(() => {
    const up = uprightTexture().clone();
    up.repeat.set(1, UPRIGHT_H * 2.5);
    up.needsUpdate = true;
    const deck = meshDeckTexture().clone();
    deck.repeat.set(4, 4);
    deck.needsUpdate = true;
    return {
      upright: new MeshStandardMaterial({ map: up, metalness: 0.55, roughness: 0.38 }),
      brace: new MeshStandardMaterial({ color: "#2459b8", metalness: 0.6, roughness: 0.4 }),
      plate: new MeshStandardMaterial({ color: "#5d646c", metalness: 0.8, roughness: 0.45 }),
      beam: new MeshStandardMaterial({ color: "#e0561b", metalness: 0.45, roughness: 0.38 }),
      deck: new MeshStandardMaterial({ map: deck, alphaTest: 0.4, transparent: false, side: DoubleSide, metalness: 0.8, roughness: 0.35 }),
      wood: new MeshStandardMaterial({ map: palletDeckTexture(), roughness: 0.85 }),
      block: new MeshStandardMaterial({ color: "#a98458", map: woodTexture(), roughness: 0.9 }),
      carton: new MeshStandardMaterial({ map: cartonTexture(), roughness: 0.92 }),
      wrap: new MeshPhysicalMaterial({
        color: "#e8f1f8", transparent: true, opacity: 0.22, roughness: 0.12, metalness: 0, clearcoat: 1, depthWrite: false,
      }),
      bin: new MeshStandardMaterial({ roughness: 0.55 }),
      label: new MeshStandardMaterial({ map: signTexture("|| ||| | ||", "#ffffff", "#111111"), roughness: 0.6 }),
      guard: new MeshStandardMaterial({ map: hazardTexture(), roughness: 0.5 }),
    };
  }, []);

  const geo = useMemo(
    () => ({
      box: new BoxGeometry(1, 1, 1),
      upright: new BoxGeometry(0.08, UPRIGHT_H, 0.07),
      brace: new CylinderGeometry(0.012, 0.012, 1, 6),
      plane: new PlaneGeometry(1, 1),
    }),
    [],
  );

  const parts = useMemo(() => {
    const uprights: Placement[] = [];
    const plates: Placement[] = [];
    const braces: Placement[] = [];
    const diagonals: Placement[] = [];
    const braceBars: Placement[] = [];
    const lite = detail === "lite";
    const beams: Placement[] = [];
    const decks: Placement[] = [];
    const boards: Placement[] = [];
    const blocks: Placement[] = [];
    const cartons: Placement[] = [];
    const wraps: Placement[] = [];
    const bins: Placement[] = [];
    const labels: Placement[] = [];
    const guards: Placement[] = [];
    const frameSeen = new Set<string>();
    const cartonTints = ["#ffffff", "#f1e3cf", "#e6d2b5", "#fff4e2"];
    const binColors = ["#1f5fbf", "#3a4450", "#d9480f"];

    const addFrame = (fx: number, z: number) => {
      const key = `${fx.toFixed(2)}:${z.toFixed(2)}`;
      if (frameSeen.has(key)) return;
      frameSeen.add(key);
      for (const dz of [-DEPTH / 2, DEPTH / 2]) {
        uprights.push({ p: [fx, UPRIGHT_H / 2, z + dz] });
        plates.push({ p: [fx, 0.005, z + dz], s: [0.16, 0.01, 0.14] });
      }
      // Frame bracing: horizontals + zig-zag diagonals in the YZ plane.
      const bays = [0.15, 1.2, 2.25, 3.3, 4.35];
      if (lite) {
        // Two square-section horizontals per frame: ~10x fewer triangles than round bracing.
        for (const y of [bays[0], bays[bays.length - 1]]) braceBars.push({ p: [fx, y, z], s: [0.03, 0.03, DEPTH] });
        return;
      }
      for (let i = 0; i < bays.length; i++) {
        braces.push({ p: [fx, bays[i], z], s: [1, DEPTH, 1], r: [Math.PI / 2, 0, 0] });
        if (i < bays.length - 1) {
          const dy = bays[i + 1] - bays[i];
          const len = Math.hypot(dy, DEPTH);
          const ang = Math.atan2(DEPTH, dy) * (i % 2 ? 1 : -1);
          diagonals.push({ p: [fx, (bays[i] + bays[i + 1]) / 2, z], s: [1, len, 1], r: [ang, 0, 0] });
        }
      }
    };

    // Pallet load at (x, y, z) where y is the support surface.
    const addPallet = (x: number, y: number, z: number, seed: number, bayId: number, level: number) => {
      // Top deck (boards drawn in the texture) on three block runners: 4 parts per pallet, so
      // thousands of pallets stay cheap in the large layout.
      boards.push({ p: [x, y + PALLET.h - 0.011, z], s: [PALLET.w, 0.022, PALLET.d] });
      for (const bz of [-1, 0, 1]) {
        blocks.push({ p: [x, y + 0.061, z + bz * (PALLET.d / 2 - 0.05)], s: [PALLET.w, 0.122, 0.1] });
      }
      const top = y + PALLET.h;
      const maxH = level < BEAM_LEVELS.length ? 0.86 : 0.95;
      if (seed < 0.55) {
        // Mixed carton stack, 2 x 2 footprint, 1-3 layers, wrapped.
        const layers = 1 + Math.floor(hash(bayId, level, 3) * 3);
        const ch = Math.min(maxH / layers, 0.34);
        for (let l = 0; l < layers; l++) {
          if (lite) {
            // One box per layer, carton texture tiled across it.
            cartons.push({ p: [x, top + ch * l + ch / 2, z], s: [0.76, ch - 0.004, 0.92], c: cartonTints[Math.floor(hash(bayId, l) * 4)] });
            continue;
          }
          for (const cx of [-0.19, 0.19]) {
            for (const cz of [-0.23, 0.23]) {
              if (l === layers - 1 && hash(bayId, level, l, cx, cz) < 0.2) continue;
              const j = (hash(bayId, l, cx * 10, cz * 10) - 0.5) * 0.02;
              cartons.push({ p: [x + cx + j, top + ch * l + ch / 2, z + cz], s: [0.37, ch - 0.004, 0.45], c: cartonTints[Math.floor(hash(bayId, l, cz) * 4)] });
            }
          }
        }
        wraps.push({ p: [x, top + (ch * layers) / 2, z], s: [0.78, ch * layers + 0.01, 0.94] });
      } else if (seed < 0.75) {
        // One large appliance carton.
        const h = 0.55 + hash(bayId, level, 9) * (maxH - 0.6);
        cartons.push({ p: [x, top + h / 2, z], s: [0.74, h, 0.9], r: [0, Math.PI / 2, 0], c: cartonTints[1] });
      } else if (seed < 0.87) {
        // Plastic small-parts bins on the pallet.
        for (const bx of [-0.2, 0.2]) {
          for (const bz of [-0.24, 0.24]) {
            // Open-top plastic tote: floor + 4 walls, filled with stock.
            const c = binColors[Math.floor(hash(bayId, level, bx * 10, bz * 10) * 3)];
            const bxp = x + bx, bzp = z + bz, t = 0.015;
            if (lite) {
              bins.push({ p: [bxp, top + 0.13, bzp], s: [0.38, 0.26, 0.46], c });
              continue;
            }
            bins.push(
              { p: [bxp, top + 0.01, bzp], s: [0.38, 0.02, 0.46], c },
              { p: [bxp - 0.19 + t / 2, top + 0.13, bzp], s: [t, 0.26, 0.46], c },
              { p: [bxp + 0.19 - t / 2, top + 0.13, bzp], s: [t, 0.26, 0.46], c },
              { p: [bxp, top + 0.13, bzp - 0.23 + t / 2], s: [0.38, 0.26, t], c },
              { p: [bxp, top + 0.13, bzp + 0.23 - t / 2], s: [0.38, 0.26, t], c },
            );
            cartons.push({ p: [bxp, top + 0.1, bzp], s: [0.32, 0.17, 0.4], c: cartonTints[2] });
          }
        }
      }
      // else: empty pallet
    };

    // Group shelves into rows for row-end protection and aisle signs.
    const rows = new Map<string, Shelf[]>();
    shelves.forEach((s, bayId) => {
      const [x, , z] = gridToWorld(s.x, s.y, width, height);
      addFrame(x - BAY / 2, z);
      addFrame(x + BAY / 2, z);
      const key = `${s.zone_id}:${s.y}`;
      rows.set(key, [...(rows.get(key) ?? []), s]);

      const levels = Math.min(s.levels - 1, BEAM_LEVELS.length);
      for (let lv = 0; lv < levels; lv++) {
        const y = BEAM_LEVELS[lv];
        for (const dz of [-DEPTH / 2, DEPTH / 2]) {
          beams.push({ p: [x, y, z + dz + Math.sign(dz) * 0.035], s: [BAY - 0.08, 0.11, 0.05] });
        }
        decks.push({ p: [x, y + 0.058, z], s: [BAY - 0.1, DEPTH + 0.02, 1], r: [-Math.PI / 2, 0, 0] });
        // Location barcode label on the aisle-facing beam(s).
        for (const dz of [-1, 1]) labels.push({ p: [x, y, z + dz * (DEPTH / 2 + 0.062)], s: [0.22, 0.07, 1], r: [0, dz > 0 ? 0 : Math.PI, 0] });
      }
      // Storage positions: floor + each beam level.
      const supports = [0, ...BEAM_LEVELS.slice(0, levels).map((y) => y + 0.065)];
      supports.forEach((y, lv) => {
        const seed = hash(bayId, lv);
        if (seed < 0.93) addPallet(x, y, z, seed, bayId, lv);
      });
    });

    const signs: { text: string; p: [number, number, number]; rot: number }[] = [];
    rows.forEach((row) => {
      const xs = row.map((s) => s.x);
      const first = row[0];
      const [x0, , z] = gridToWorld(Math.min(...xs), first.y, width, height);
      const [x1] = gridToWorld(Math.max(...xs), first.y, width, height);
      for (const [x, dir] of [[x0 - BAY / 2 - 0.12, -1], [x1 + BAY / 2 + 0.12, 1]] as const) {
        guards.push({ p: [x, 0.2, z], s: [0.08, 0.4, DEPTH + 0.15] });
        signs.push({
          text: `${first.zone_id.replace("ZONE_", "")}-${String(first.y).padStart(2, "0")}`,
          p: [x + dir * 0.05, 3.9, z],
          rot: dir > 0 ? Math.PI / 2 : -Math.PI / 2,
        });
      }
    });

    return { uprights, plates, braces, diagonals, braceBars, beams, decks, boards, blocks, cartons, wraps, bins, labels, guards, signs };
  }, [shelves, width, height, detail]);

  const full = detail === "full";
  return (
    <group>
      <InstancedParts items={parts.uprights} geometry={geo.upright} material={mats.upright} />
      {full && <InstancedParts items={parts.plates} geometry={geo.box} material={mats.plate} castShadow={false} />}
      <InstancedParts items={parts.braces} geometry={geo.brace} material={mats.brace} />
      <InstancedParts items={parts.braceBars} geometry={geo.box} material={mats.brace} />
      {full && <InstancedParts items={parts.diagonals} geometry={geo.brace} material={mats.brace} />}
      <InstancedParts items={parts.beams} geometry={geo.box} material={mats.beam} />
      <InstancedParts items={parts.decks} geometry={geo.plane} material={mats.deck} />
      <InstancedParts items={parts.boards} geometry={geo.box} material={mats.wood} />
      <InstancedParts items={parts.blocks} geometry={geo.box} material={mats.block} castShadow={false} />
      <InstancedParts items={parts.cartons} geometry={geo.box} material={mats.carton} />
      <InstancedParts items={parts.bins} geometry={geo.box} material={mats.bin} />
      {full && <InstancedParts items={parts.wraps} geometry={geo.box} material={mats.wrap} castShadow={false} receiveShadow={false} />}
      {full && <InstancedParts items={parts.labels} geometry={geo.plane} material={mats.label} castShadow={false} />}
      <InstancedParts items={parts.guards} geometry={geo.box} material={mats.guard} />
      <SignBoards signs={parts.signs} />
    </group>
  );
}
