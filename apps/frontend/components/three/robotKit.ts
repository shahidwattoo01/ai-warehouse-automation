"use client";

// Geometry kit for the instanced AMR fleet. The robot (same design as before: collaborative picking
// AMR with a tote tower) is described as a parts table, and parts sharing a material are merged
// into one geometry. The fleet then draws with one InstancedMesh per material group instead of
// ~60 meshes per robot. Robot-local frame: faces +X, origin at floor centre, metres.

import {
  BoxGeometry,
  type BufferGeometry,
  Color,
  CylinderGeometry,
  Euler,
  type Material,
  Matrix4,
  MeshBasicMaterial,
  MeshPhysicalMaterial,
  MeshStandardMaterial,
  PlaneGeometry,
  Quaternion,
  SphereGeometry,
  Vector3,
} from "three";
import { RoundedBoxGeometry } from "three/examples/jsm/geometries/RoundedBoxGeometry.js";
import { mergeGeometries } from "three/examples/jsm/utils/BufferGeometryUtils.js";
import { cartonTexture, screenTexture } from "./textures";

export const WHEEL_R = 0.075;
export const TOTE_LEVELS = [0.56, 0.98];
/** Battery bar centre (geometry is scaled along z about this point). */
export const BATTERY_CENTER = new Vector3(0.36, 0.374, 0.16);

type V3 = [number, number, number];

function place(g: BufferGeometry, pos: V3, rot: V3 = [0, 0, 0]): BufferGeometry {
  const m = new Matrix4().compose(new Vector3(...pos), new Quaternion().setFromEuler(new Euler(...rot)), new Vector3(1, 1, 1));
  return (g.index ? g.toNonIndexed() : g).applyMatrix4(m);
}
const box = (w: number, h: number, d: number, pos: V3, rot?: V3) => place(new BoxGeometry(w, h, d), pos, rot);
const rbox = (w: number, h: number, d: number, r: number, pos: V3, rot?: V3) => place(new RoundedBoxGeometry(w, h, d, 3, r), pos, rot);
const cyl = (rt: number, rb: number, h: number, seg: number, pos: V3, rot?: V3) => place(new CylinderGeometry(rt, rb, h, seg), pos, rot);

function merge(parts: BufferGeometry[]): BufferGeometry {
  // Keep only the attributes every part has, so mergeGeometries accepts them.
  for (const p of parts) for (const name of Object.keys(p.attributes)) if (!["position", "normal", "uv"].includes(name)) p.deleteAttribute(name);
  const g = mergeGeometries(parts, false)!;
  g.computeBoundingSphere();
  return g;
}

export type GroupName =
  | "shell" | "dark" | "orange" | "yellow" | "metal" | "glass" | "gold" | "lights" | "red"
  | "status" | "beacon" | "screen" | "tote0" | "tote1" | "contents0" | "contents1" | "battery" | "wheels";

export interface KitGroup {
  geometry: BufferGeometry;
  material: Material;
  castShadow: boolean;
  /** Per-instance colour driven by robot state (status light, beacon, battery). */
  tinted?: boolean;
}

function tote(y: number): BufferGeometry[] {
  const c = y + 0.125;
  return [
    box(0.5, 0.012, 0.48, [0.06, c - 0.105, 0]),
    box(0.012, 0.22, 0.48, [0.06 - 0.244, c, 0]),
    box(0.012, 0.22, 0.48, [0.06 + 0.244, c, 0]),
    box(0.5, 0.22, 0.012, [0.06, c, -0.234]),
    box(0.5, 0.22, 0.012, [0.06, c, 0.234]),
  ];
}

function contents(y: number): BufferGeometry[] {
  const c = y + 0.125;
  return [box(0.24, 0.12, 0.2, [-0.02, c - 0.04, 0.06]), box(0.16, 0.1, 0.14, [0.18, c - 0.05, -0.08], [0, 0.4, 0])];
}

let kit: Record<GroupName, KitGroup> | null = null;

export function robotKit(): Record<GroupName, KitGroup> {
  if (kit) return kit;
  const sides = [-1, 1];
  const geo: Record<GroupName, BufferGeometry[]> = {
    shell: [
      rbox(0.88, 0.2, 0.64, 0.06, [0, 0.27, 0]), // main body
      rbox(0.2, 1.14, 0.5, 0.05, [-0.32, 0.94, 0]), // rear tower
    ],
    dark: [
      rbox(0.92, 0.12, 0.68, 0.04, [0, 0.11, 0]), // bumper skirt
      ...[[0.34, 0.22], [0.34, -0.22], [-0.34, 0.22], [-0.34, -0.22]].map(([x, z]) => cyl(0.03, 0.03, 0.025, 14, [x, 0.03, z], [Math.PI / 2, 0, 0])), // casters
      box(0.04, 0.03, 0.14, [0.2, 0.42, 0]), // depth camera
      ...TOTE_LEVELS.map((y) => box(0.56, 0.025, 0.54, [0.06, y, 0])), // tote shelves
      cyl(0.018, 0.018, 0.12, 12, [-0.2, 1.42, 0], [0, 0, Math.PI / 2]), // screen arm
      place(new RoundedBoxGeometry(0.025, 0.22, 0.32, 2, 0.008), [-0.12, 1.45, 0], [0, 0, -0.45]), // tablet
      cyl(0.06, 0.06, 0.02, 24, [-0.32, 1.52, 0]), // beacon base
    ],
    orange: [
      ...sides.map((s) => box(0.6, 0.12, 0.01, [-0.05, 0.27, s * 0.322])),
      ...sides.map((s) => box(0.12, 1.0, 0.008, [-0.32, 0.94, s * 0.252])),
    ],
    yellow: [
      ...sides.map((s) => box(0.03, 0.07, 0.58, [s * 0.465, 0.12, 0])), // bumpers
      box(0.07, 0.03, 0.07, [0.36, 0.37, -0.22]), // e-stop housing
      box(0.06, 0.14, 0.04, [-0.32, 1.22, 0.27], [0.15, 0, 0]), // scanner in holster
    ],
    metal: [
      ...[[0.34, 0.22], [0.34, -0.22], [-0.34, 0.22], [-0.34, -0.22]].map(([x, z]) => box(0.04, 0.04, 0.035, [x, 0.065, z])),
      ...sides.map((s) => cyl(0.04, 0.04, 0.004, 20, [0, WHEEL_R, s * 0.316], [Math.PI / 2, 0, 0])), // hubs
    ],
    glass: [
      box(0.03, 0.06, 0.32, [0.455, 0.2, 0]), // front safety scanner
      box(0.03, 0.05, 0.22, [-0.455, 0.2, 0]), // rear scanner
      box(0.1, 0.004, 0.16, [0.36, 0.372, 0.16]), // battery gauge background
    ],
    gold: [box(0.01, 0.02, 0.14, [-0.47, 0.08, 0])],
    lights: sides.map((s) => cyl(0.025, 0.025, 0.01, 20, [0.442, 0.3, s * 0.22], [0, 0, -Math.PI / 2])),
    red: [
      ...sides.map((s) => box(0.01, 0.025, 0.08, [-0.442, 0.3, s * 0.22])),
      cyl(0.028, 0.024, 0.03, 20, [0.36, 0.4, -0.22]), // e-stop mushroom
    ],
    status: [
      box(0.905, 0.018, 0.655, [0, 0.172, 0]), // light band around the body
      ...sides.map((s) => box(0.008, 0.9, 0.025, [-0.218, 0.94, s * 0.2])), // tower light bars
    ],
    beacon: [place(new SphereGeometry(0.05, 24, 12, 0, Math.PI * 2, 0, Math.PI / 2), [-0.32, 1.53, 0])],
    screen: [
      (() => {
        const p = new PlaneGeometry(0.29, 0.19);
        p.rotateY(Math.PI / 2);
        p.translate(0.0135, 0, 0);
        p.rotateZ(-0.45);
        p.translate(-0.12, 1.45, 0);
        return p.toNonIndexed();
      })(),
    ],
    tote0: tote(TOTE_LEVELS[0]),
    tote1: tote(TOTE_LEVELS[1]),
    contents0: contents(TOTE_LEVELS[0]),
    contents1: contents(TOTE_LEVELS[1]),
    battery: [box(0.08, 0.004, 0.15, BATTERY_CENTER.toArray() as V3)],
    // Both drive wheels, centred on the axle so the group can spin about z.
    wheels: sides.map((s) => cyl(WHEEL_R, WHEEL_R, 0.05, 28, [0, 0, s * 0.29], [Math.PI / 2, 0, 0])),
  };

  const bright = (hex: string, k: number) => new Color(hex).multiplyScalar(k);
  const carton = new MeshStandardMaterial({ map: cartonTexture(), roughness: 0.9 });
  const mats: Record<GroupName, [Material, boolean, boolean?]> = {
    shell: [new MeshPhysicalMaterial({ color: "#eef0f2", roughness: 0.32, clearcoat: 0.6, clearcoatRoughness: 0.25 }), true],
    dark: [new MeshStandardMaterial({ color: "#1d2024", roughness: 0.7, metalness: 0.2 }), true],
    orange: [new MeshPhysicalMaterial({ color: "#f26b1d", roughness: 0.35, clearcoat: 0.5 }), false],
    yellow: [new MeshStandardMaterial({ color: "#f2c200", roughness: 0.5 }), false],
    metal: [new MeshStandardMaterial({ color: "#9aa1a8", metalness: 0.85, roughness: 0.3 }), false],
    glass: [new MeshPhysicalMaterial({ color: "#05070a", roughness: 0.05, metalness: 0.2, clearcoat: 1 }), false],
    gold: [new MeshStandardMaterial({ color: "#c9a227", metalness: 1, roughness: 0.25 }), false],
    lights: [new MeshBasicMaterial({ color: bright("#f4f8ff", 3), toneMapped: false }), false],
    red: [new MeshBasicMaterial({ color: bright("#ff2a2a", 1.6), toneMapped: false }), false],
    status: [new MeshBasicMaterial({ color: "#ffffff", toneMapped: false }), false, true],
    beacon: [new MeshBasicMaterial({ color: "#ffffff", toneMapped: false, transparent: true, opacity: 0.92 }), false, true],
    screen: [new MeshBasicMaterial({ map: screenTexture("#3B82F6"), toneMapped: false }), false],
    tote0: [new MeshStandardMaterial({ color: "#1f5fbf", roughness: 0.5 }), true],
    tote1: [new MeshStandardMaterial({ color: "#d9480f", roughness: 0.5 }), true],
    contents0: [carton, false],
    contents1: [carton, false],
    battery: [new MeshBasicMaterial({ color: "#ffffff", toneMapped: false }), false, true],
    wheels: [new MeshStandardMaterial({ color: "#141414", roughness: 0.85 }), true],
  };

  kit = Object.fromEntries(
    (Object.keys(geo) as GroupName[]).map((name) => {
      const [material, castShadow, tinted] = mats[name];
      return [name, { geometry: merge(geo[name]), material, castShadow, tinted }];
    }),
  ) as Record<GroupName, KitGroup>;
  return kit;
}
