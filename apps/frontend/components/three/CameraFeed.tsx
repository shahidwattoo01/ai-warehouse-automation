"use client";

// Cameras for the Vision page (Phase 5). Both components render the live 3D warehouse with the same
// renderer settings as the camera-dataset studio (CaptureStudio: same lighting and tone mapping, no
// fog or post effects), so frames look like the images the detector was trained on.
//
//   CameraFeed  one live camera; `onCapture` receives a function returning a 640 x 480 JPEG frame
//   CameraWall  many cameras at once: ONE renderer photographs every camera in turn every few
//               seconds (one WebGL context instead of dozens of live views, light for a laptop)

import { Canvas, useFrame, useThree } from "@react-three/fiber";
import { useEffect, useRef } from "react";
import {
  ACESFilmicToneMapping,
  type PerspectiveCamera,
  SRGBColorSpace,
  Vector2,
  Vector3,
} from "three";
import { QUALITY } from "@/lib/quality";
import { useSim } from "@/lib/store";
import { Building } from "./Building";
import { Hazards } from "./Hazards";
import { Props } from "./Props";
import { Racking } from "./Racking";
import { RobotFleet, robotNodes } from "./RobotFleet";
import { SceneLighting } from "./SceneLighting";
import { Stations } from "./Stations";
import { WorkerLayer } from "./Worker";

export { FEED_H, FEED_W, type FeedCamera } from "./feed";
import { FEED_H, FEED_W, type FeedCamera } from "./feed";

const UP = new Vector3(0, 1, 0);
const AHEAD = new Vector3();
const GL = {
  antialias: true,
  preserveDrawingBuffer: true,
  toneMapping: ACESFilmicToneMapping,
  toneMappingExposure: 1.05,
  outputColorSpace: SRGBColorSpace,
  powerPreference: "high-performance" as const,
};

/** Point `camera` as `spec` says. Returns false if a robot camera's robot is not in the scene. */
function aim(camera: PerspectiveCamera, spec: FeedCamera): boolean {
  camera.fov = spec.fov;
  camera.aspect = FEED_W / FEED_H;
  camera.near = 0.05;
  camera.far = 250;
  camera.up.copy(UP);
  if (spec.kind === "fixed") {
    camera.position.set(...spec.position);
    camera.lookAt(...spec.target);
  } else {
    const node = robotNodes.get(spec.robotId);
    if (!node) return false;
    // Forward camera 0.55 m above the floor, as in the dataset (scripts/capture_frames.py).
    const fx = Math.cos(node.rotation.y);
    const fz = -Math.sin(node.rotation.y);
    camera.position.set(
      node.position.x + 0.4 * fx,
      0.55,
      node.position.z + 0.4 * fz,
    );
    camera.lookAt(
      AHEAD.set(node.position.x + 8 * fx, 0.4, node.position.z + 8 * fz),
    );
  }
  camera.updateProjectionMatrix();
  return true;
}

/** The warehouse as in the operator view, at the detector's training quality. */
function Warehouse() {
  const layout = useSim((s) => s.layout);
  const width = layout?.width ?? 80;
  const depth = layout?.height ?? 50;
  return (
    <>
      <color attach="background" args={["#e7e4dd"]} />
      <SceneLighting
        width={width}
        depth={depth}
        quality={QUALITY.balanced}
        layoutKey={layout?.name ?? ""}
      />
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
          <Racking
            shelves={layout.shelves}
            width={width}
            height={depth}
            detail="full"
          />
          <Stations stations={layout.stations} width={width} height={depth} />
          <Props width={width} height={depth} />
          <RobotFleet width={width} height={depth} castShadows />
          <WorkerLayer width={width} height={depth} />
          <Hazards width={width} height={depth} />
        </>
      )}
    </>
  );
}

// ----- one live camera ---------------------------------------------------------------------------
function Rig({
  camera: spec,
  onCapture,
}: {
  camera: FeedCamera;
  onCapture: (fn: () => string) => void;
}) {
  const gl = useThree((s) => s.gl);
  const scene = useThree((s) => s.scene);
  const camera = useThree((s) => s.camera) as PerspectiveCamera;

  useEffect(() => {
    aim(camera, spec);
  }, [camera, spec]);

  useEffect(() => {
    onCapture(() => {
      // The view on screen scales with the page; the detector always gets a 640 x 480 frame, its
      // training size. Render once at that size, read it, then restore the on-screen size.
      const shown = gl.getSize(new Vector2());
      gl.setSize(FEED_W, FEED_H, false);
      gl.render(scene, camera);
      const image = gl.domElement.toDataURL("image/jpeg", 0.95);
      gl.setSize(shown.x, shown.y, false);
      gl.render(scene, camera);
      return image;
    });
  }, [gl, scene, camera, onCapture]);

  useFrame(() => {
    if (spec.kind === "robot") aim(camera, spec); // follow the robot
  });
  return null;
}

export function CameraFeed({
  camera,
  onCapture,
}: {
  camera: FeedCamera;
  onCapture: (fn: () => string) => void;
}) {
  return (
    <Canvas shadows dpr={1} style={{ width: "100%", height: "100%" }} gl={GL}>
      <Warehouse />
      <Rig camera={camera} onCapture={onCapture} />
    </Canvas>
  );
}

// ----- many cameras: one renderer, photographed in turn ------------------------------------------
// Wall photos are taken at the detector's training size, so any of them can be sent for detection.
export const THUMB_W = FEED_W;
export const THUMB_H = FEED_H;

function Photographer({
  cameras,
  intervalMs,
  onShot,
}: {
  cameras: { key: string; camera: FeedCamera }[];
  intervalMs: number;
  onShot: (key: string, image: string) => void;
}) {
  const gl = useThree((s) => s.gl);
  const scene = useThree((s) => s.scene);
  const camera = useThree((s) => s.camera) as PerspectiveCamera;
  const advance = useThree((s) => s.advance);
  const list = useRef(cameras);
  list.current = cameras;

  useEffect(() => {
    let stop = false;
    const pause = (ms: number) => new Promise((r) => setTimeout(r, ms));
    (async () => {
      await pause(300); // let the scene load its first state
      while (!stop) {
        const started = performance.now();
        advance(performance.now()); // move robots and workers to their current positions
        gl.setSize(THUMB_W, THUMB_H, false);
        for (const { key, camera: spec } of list.current) {
          if (stop) return;
          if (!aim(camera, spec)) continue;
          gl.render(scene, camera);
          onShot(key, gl.domElement.toDataURL("image/jpeg", 0.9));
          await pause(0); // keep the page responsive between shots
        }
        await pause(Math.max(250, intervalMs - (performance.now() - started)));
      }
    })();
    return () => {
      stop = true;
    };
  }, [gl, scene, camera, advance, intervalMs, onShot]);
  return null;
}

/** Renders nothing visible: it calls `onShot(key, jpeg)` for every camera, every `intervalMs`. */
export function CameraWall(props: {
  cameras: { key: string; camera: FeedCamera }[];
  intervalMs: number;
  onShot: (key: string, image: string) => void;
}) {
  return (
    <div
      aria-hidden
      style={{
        position: "absolute",
        width: 1,
        height: 1,
        overflow: "hidden",
        opacity: 0,
      }}
    >
      <Canvas
        shadows
        dpr={1}
        frameloop="never"
        style={{ width: THUMB_W, height: THUMB_H }}
        gl={GL}
      >
        <Warehouse />
        <Photographer {...props} />
      </Canvas>
    </div>
  );
}
