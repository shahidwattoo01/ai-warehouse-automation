"use client";

// Camera-dataset studio: renders the same 3D warehouse as the operator UI from a given camera and
// returns the image plus 2D bounding boxes of every visible object. scripts/capture_frames.py
// drives it in a headless browser through window.__capture:
//
//   load(layout, state)  show one simulator state (robots, workers, parcels, closed aisles)
//   shoot(camera)        render one frame -> { image (PNG data URL), labels }
//
// Labels are exact because the scene itself is the ground truth. Each object is approximated by a
// box (robot: oriented box; worker, parcel, pallet, barrier: their world bounds; rack bay: its
// frame). Points sampled on the box faces are projected into the image and kept only where the
// depth buffer shows nothing in front of them, so the box covers the visible part of the object
// and hidden objects (behind racks, out of view) get no label.

import { Canvas, useThree } from "@react-three/fiber";
import { useEffect } from "react";
import {
  ACESFilmicToneMapping,
  Box3,
  FloatType,
  Frustum,
  Matrix4,
  type Object3D,
  type PerspectiveCamera,
  ShaderMaterial,
  SRGBColorSpace,
  Vector3,
  WebGLRenderTarget,
} from "three";
import { QUALITY } from "@/lib/quality";
import { useSim } from "@/lib/store";
import type { LayoutSnapshot, WarehouseState } from "@/lib/types";
import { Building } from "./Building";
import { gridToWorld } from "./coords";
import { Hazards } from "./Hazards";
import { Props } from "./Props";
import { Racking } from "./Racking";
import { RobotFleet, robotNodes } from "./RobotFleet";
import { SceneLighting } from "./SceneLighting";
import { Stations } from "./Stations";
import { WorkerLayer } from "./Worker";

const W = 640;
const H = 480;
export const CLASSES = ["robot", "worker", "shelf", "package", "obstacle", "blocked_path"] as const;
const ROBOT_BOX = { min: new Vector3(-0.47, 0, -0.35), max: new Vector3(0.47, 1.6, 0.35) };
const SHELF_HALF = { x: 0.5, z: 0.45, h: 4.6 };
const SAMPLES = 6; // points per box edge on every face

export interface CameraSpec {
  position: [number, number, number];
  target: [number, number, number];
  fov: number;
  exposure?: number;
  exclude?: string[]; // object ids not to label (the robot carrying the camera)
}

export interface Label {
  cls: (typeof CLASSES)[number];
  id: string;
  bbox: [number, number, number, number]; // x0, y0, x1, y1 in pixels
  visible: number; // share of in-view sample points that are not hidden
  truncated: boolean; // part of the object lies outside the image
}

interface Candidate {
  cls: Label["cls"];
  id: string;
  points: Vector3[]; // world-space sample points on the box surface
  bounds: Box3;
}

// View-space distance shader: 1 / distance (0 = nothing there), works for instanced meshes too.
const DEPTH = new ShaderMaterial({
  vertexShader: /* glsl */ `
    #include <common>
    varying float vDist;
    void main() {
      #include <begin_vertex>
      #include <project_vertex>
      vDist = -mvPosition.z;
    }`,
  fragmentShader: /* glsl */ `
    varying float vDist;
    void main() { gl_FragColor = vec4(1.0 / max(vDist, 1e-3), 0.0, 0.0, 1.0); }`,
});

function boxSurface(min: Vector3, max: Vector3, matrix?: Matrix4): Vector3[] {
  const pts: Vector3[] = [];
  const lerp = (a: number, b: number, t: number) => a + (b - a) * t;
  for (let i = 0; i < SAMPLES; i++) {
    for (let j = 0; j < SAMPLES; j++) {
      const u = i / (SAMPLES - 1);
      const v = j / (SAMPLES - 1);
      const x = lerp(min.x, max.x, u);
      const y = lerp(min.y, max.y, v);
      const zz = lerp(min.z, max.z, u);
      const yy = lerp(min.y, max.y, u);
      const xv = lerp(min.x, max.x, v);
      const zv = lerp(min.z, max.z, v);
      pts.push(
        new Vector3(x, y, min.z), new Vector3(x, y, max.z), // front / back
        new Vector3(min.x, yy, zv), new Vector3(max.x, yy, zv), // left / right
        new Vector3(xv, min.y, zz), new Vector3(xv, max.y, zz), // bottom / top
      ); // fmt: skip
    }
  }
  if (matrix) pts.forEach((p) => p.applyMatrix4(matrix));
  return pts;
}

function frames(n: number) {
  return new Promise<void>((resolve) => {
    const step = (k: number) => (k <= 0 ? resolve() : requestAnimationFrame(() => step(k - 1)));
    step(n);
  });
}

function Harness() {
  const gl = useThree((s) => s.gl);
  const scene = useThree((s) => s.scene);
  const camera = useThree((s) => s.camera) as PerspectiveCamera;

  useEffect(() => {
    const target = new WebGLRenderTarget(W, H, { type: FloatType, depthBuffer: true });
    const pixels = new Float32Array(W * H * 4);

    function candidates(layout: LayoutSnapshot, state: WarehouseState, exclude: Set<string>): Candidate[] {
      const out: Candidate[] = [];
      for (const r of state.robots) {
        const node = robotNodes.get(r.robot_id);
        if (!node || exclude.has(r.robot_id)) continue;
        node.updateMatrixWorld();
        const points = boxSurface(ROBOT_BOX.min, ROBOT_BOX.max, node.matrixWorld);
        out.push({ cls: "robot", id: r.robot_id, points, bounds: new Box3().setFromPoints(points) });
      }
      let w = 0;
      scene.traverse((o: Object3D) => {
        const label = o.userData?.label as Label["cls"] | undefined;
        if (!label) return;
        const bounds = new Box3().setFromObject(o, true);
        if (bounds.isEmpty()) return;
        const id = (o.userData.id as string | undefined) ?? `${label}-${++w}`;
        out.push({ cls: label, id, points: boxSurface(bounds.min, bounds.max), bounds });
      });
      for (const s of layout.shelves) {
        const [x, , z] = gridToWorld(s.x, s.y, layout.width, layout.height);
        const min = new Vector3(x - SHELF_HALF.x, 0, z - SHELF_HALF.z);
        const max = new Vector3(x + SHELF_HALF.x, SHELF_HALF.h, z + SHELF_HALF.z);
        out.push({ cls: "shelf", id: s.shelf_id, points: [], bounds: new Box3(min, max) });
      }
      return out;
    }

    function label(c: Candidate, view: Matrix4, viewProj: Matrix4): Label | null {
      if (!c.points.length) c.points = boxSurface(c.bounds.min, c.bounds.max);
      const e = viewProj.elements;
      const v = view.elements;
      let x0 = Infinity, y0 = Infinity, x1 = -Infinity, y1 = -Infinity; // prettier-ignore
      let seen = 0;
      let inView = 0;
      let outside = 0;
      for (const p of c.points) {
        const dist = -(v[2] * p.x + v[6] * p.y + v[10] * p.z + v[14]);
        if (dist < camera.near) continue;
        const cw = e[3] * p.x + e[7] * p.y + e[11] * p.z + e[15];
        const nx = (e[0] * p.x + e[4] * p.y + e[8] * p.z + e[12]) / cw;
        const ny = (e[1] * p.x + e[5] * p.y + e[9] * p.z + e[13]) / cw;
        const px = ((nx + 1) / 2) * W;
        const py = ((1 - ny) / 2) * H;
        if (px < 0 || px >= W || py < 0 || py >= H) {
          outside++;
          continue;
        }
        inView++;
        const inv = pixels[((H - 1 - Math.floor(py)) * W + Math.floor(px)) * 4];
        const surface = inv > 0 ? 1 / inv : Infinity;
        if (dist > surface + 0.05 + 0.012 * dist) continue; // something is in front of it
        seen++;
        x0 = Math.min(x0, px);
        y0 = Math.min(y0, py);
        x1 = Math.max(x1, px);
        y1 = Math.max(y1, py);
      }
      if (seen < 3 || x1 - x0 < 6 || y1 - y0 < 6 || (x1 - x0) * (y1 - y0) < 80) return null;
      const r = (n: number) => Math.round(n * 10) / 10;
      return {
        cls: c.cls,
        id: c.id,
        bbox: [r(x0), r(y0), r(Math.min(x1 + 1, W)), r(Math.min(y1 + 1, H))],
        visible: Math.round((seen / Math.max(inView, 1)) * 100) / 100,
        truncated: outside > 0,
      };
    }

    async function shoot(spec: CameraSpec) {
      const { layout, state } = useSim.getState();
      if (!layout || !state) throw new Error("load() a layout and a state first");
      camera.fov = spec.fov;
      camera.aspect = W / H;
      camera.near = 0.05;
      camera.far = 250;
      camera.position.set(...spec.position);
      camera.lookAt(...spec.target);
      camera.updateProjectionMatrix();
      gl.toneMappingExposure = spec.exposure ?? 1.05;
      await frames(6); // robots and workers reach their cells, shadows update
      camera.updateMatrixWorld();
      scene.updateMatrixWorld();

      gl.setRenderTarget(null);
      gl.render(scene, camera);
      const image = gl.domElement.toDataURL("image/png");

      // Depth pass: distance to the nearest surface for every pixel.
      const background = scene.background;
      const fog = scene.fog;
      scene.background = null;
      scene.fog = null;
      scene.overrideMaterial = DEPTH;
      gl.setRenderTarget(target);
      gl.setClearColor(0x000000, 0);
      gl.clear();
      gl.render(scene, camera);
      gl.readRenderTargetPixels(target, 0, 0, W, H, pixels);
      gl.setRenderTarget(null);
      scene.overrideMaterial = null;
      scene.background = background;
      scene.fog = fog;

      const view = camera.matrixWorldInverse;
      const viewProj = new Matrix4().multiplyMatrices(camera.projectionMatrix, view);
      const frustum = new Frustum().setFromProjectionMatrix(viewProj);
      const labels: Label[] = [];
      for (const c of candidates(layout, state, new Set(spec.exclude ?? []))) {
        if (!frustum.intersectsBox(c.bounds)) continue;
        const l = label(c, view, viewProj);
        if (l) labels.push(l);
      }
      return { image, labels, width: W, height: H };
    }

    window.__capture = {
      ready: true,
      classes: CLASSES,
      renderer: (() => {
        const ctx = gl.getContext();
        const info = ctx.getExtension("WEBGL_debug_renderer_info");
        return info ? String(ctx.getParameter(info.UNMASKED_RENDERER_WEBGL)) : "unknown";
      })(),
      load(layout: LayoutSnapshot, state: WarehouseState) {
        // A tiny tick interval makes robots and workers glide to their cells within a few frames.
        useSim.setState({ layout, state, tickInterval: 0.02, lastTickAt: performance.now() });
      },
      shoot,
    };
    return () => {
      target.dispose();
      delete window.__capture;
    };
  }, [gl, scene, camera]);
  return null;
}

declare global {
  interface Window {
    __capture?: {
      ready: boolean;
      classes: readonly string[];
      renderer: string;
      load: (layout: LayoutSnapshot, state: WarehouseState) => void;
      shoot: (spec: CameraSpec) => Promise<{ image: string; labels: Label[]; width: number; height: number }>;
    };
  }
}

export function CaptureStudio() {
  const layout = useSim((s) => s.layout);
  const width = layout?.width ?? 80;
  const depth = layout?.height ?? 50;
  const q = QUALITY.balanced;
  return (
    <div style={{ position: "fixed", left: 0, top: 0, width: W, height: H, zIndex: 1000, background: "#000" }}>
      <Canvas
        shadows
        dpr={1}
        style={{ width: W, height: H }}
        camera={{ fov: 60, near: 0.05, far: 250, position: [0, 30, 30] }}
        gl={{
          antialias: true,
          preserveDrawingBuffer: true,
          toneMapping: ACESFilmicToneMapping,
          outputColorSpace: SRGBColorSpace,
          powerPreference: "high-performance",
        }}
      >
        <color attach="background" args={["#e7e4dd"]} />
        <SceneLighting width={width} depth={depth} quality={q} layoutKey={layout?.name ?? ""} />
        {layout && (
          <>
            <Building
              width={width}
              height={depth}
              zones={layout.zones}
              blocked={layout.blocked}
              oneWay={layout.one_way ?? []}
              parkingAreas={layout.parking_areas ?? []}
            />
            <Racking shelves={layout.shelves} width={width} height={depth} detail="full" />
            <Stations stations={layout.stations} width={width} height={depth} />
            <Props width={width} height={depth} />
            <RobotFleet width={width} height={depth} castShadows />
            <WorkerLayer width={width} height={depth} />
            <Hazards width={width} height={depth} />
          </>
        )}
        <Harness />
      </Canvas>
    </div>
  );
}
