"use client";

import { OrbitControls } from "@react-three/drei";
import { useFrame, useThree } from "@react-three/fiber";
import { useEffect, useRef } from "react";
import { MOUSE, Plane, Raycaster, TOUCH, Vector2, Vector3 } from "three";
import type { OrbitControls as OrbitControlsImpl } from "three-stdlib";
import { create } from "zustand";
import { useSim } from "@/lib/store";

/** Named camera views; each is resolved against the current floor size. */
export type ViewName = "overview" | "top" | "nw" | "ne" | "sw" | "se";

export const VIEW_LABEL: Record<ViewName, string> = {
  overview: "Overview",
  top: "Top",
  nw: "NW",
  ne: "NE",
  sw: "SW",
  se: "SE",
};

/** Lets buttons outside the Canvas ask the camera inside it to fly somewhere. */
export const useCameraView = create<{ request: { view: ViewName; at: number } | null; go: (view: ViewName) => void }>(
  (set) => ({ request: null, go: (view) => set({ request: { view, at: Date.now() } }) }),
);

const FLY_SECONDS = 0.9;
const floor = new Plane(new Vector3(0, 1, 0), 0);
const ray = new Raycaster();
const pointer = new Vector2();
const hit = new Vector3();

/** Camera position and look-at point for a named view, on a `width` x `depth` metre floor. */
function viewPose(view: ViewName, width: number, depth: number, compact: boolean): [Vector3, Vector3] {
  const k = Math.max(width, depth) / 40;
  const hx = width / 2;
  const hz = depth / 2;
  if (view === "overview") {
    return compact
      ? [new Vector3(0, 30 * k, 30 * k), new Vector3(0, 0.8, 2 * k)]
      : [new Vector3(-18 * k, 16 * k, 24 * k), new Vector3(0, 0.8, 2 * k)];
  }
  if (view === "top") return [new Vector3(0, 55 * k, 0.01), new Vector3(0, 0, 0)];
  // Corner views: look at the area around a corner from slightly inside the building.
  const sx = view === "nw" || view === "sw" ? -1 : 1;
  const sz = view === "nw" || view === "ne" ? -1 : 1;
  const target = new Vector3(sx * hx * 0.7, 0.5, sz * hz * 0.7);
  const eye = new Vector3(sx * hx * 0.25, 9 * Math.max(k, 1), sz * hz * 0.25);
  return [eye, target];
}

/**
 * Free 360° camera for the warehouse, like browsing a zoomable photo:
 * - left-drag rotates all the way round, right-drag (or Shift + left-drag) slides along the floor
 * - the wheel / pinch zooms toward the point under the cursor, down to close inspection distance
 * - double-click flies to that spot on the floor; view buttons fly to the corners, top or overview
 * The look-at point is kept inside the building so the view never drifts off into empty space.
 */
export function ViewControls({ width, depth, compact }: { width: number; depth: number; compact: boolean }) {
  const controls = useRef<OrbitControlsImpl>(null);
  const camera = useThree((s) => s.camera);
  const gl = useThree((s) => s.gl);
  const request = useCameraView((s) => s.request);
  const fly = useRef<{ fromEye: Vector3; fromTarget: Vector3; eye: Vector3; target: Vector3; t: number } | null>(null);
  const k = Math.max(width, depth) / 40;

  const flyTo = (eye: Vector3, target: Vector3) => {
    const c = controls.current;
    if (!c) return;
    useSim.getState().selectRobot(null); // stop following a robot, the user chose a place
    fly.current = { fromEye: camera.position.clone(), fromTarget: c.target.clone(), eye, target, t: 0 };
  };

  // View buttons.
  useEffect(() => {
    if (!request) return;
    const [eye, target] = viewPose(request.view, width, depth, compact);
    flyTo(eye, target);
    useCameraView.setState({ request: null }); // handled; a remounted scene must not replay it
  }, [request]); // only a new request should fly, not a layout change

  // Double-click: fly to the clicked spot on the floor, keeping the current viewing direction.
  useEffect(() => {
    const el = gl.domElement;
    const onDoubleClick = (e: MouseEvent) => {
      const c = controls.current;
      if (!c) return;
      const rect = el.getBoundingClientRect();
      pointer.set(((e.clientX - rect.left) / rect.width) * 2 - 1, -((e.clientY - rect.top) / rect.height) * 2 + 1);
      ray.setFromCamera(pointer, camera);
      if (!ray.ray.intersectPlane(floor, hit)) return;
      const target = hit.clone().setY(0.5);
      const offset = camera.position.clone().sub(c.target);
      offset.setLength(Math.min(offset.length(), 10)); // come in close, never zoom back out
      flyTo(target.clone().add(offset), target);
    };
    el.addEventListener("dblclick", onDoubleClick);
    return () => el.removeEventListener("dblclick", onDoubleClick);
  }, [gl, camera]); // flyTo only reads refs

  useFrame((_, dt) => {
    const c = controls.current;
    if (!c) return;
    const f = fly.current;
    if (f) {
      f.t = Math.min(1, f.t + dt / FLY_SECONDS);
      const s = f.t * f.t * (3 - 2 * f.t); // ease in-out
      camera.position.lerpVectors(f.fromEye, f.eye, s);
      c.target.lerpVectors(f.fromTarget, f.target, s);
      if (f.t >= 1) fly.current = null;
      c.update();
    }
    // Keep the look-at point over the floor (plus a small margin), moving the camera with it.
    const x = Math.min(Math.max(c.target.x, -width / 2 - 2), width / 2 + 2);
    const z = Math.min(Math.max(c.target.z, -depth / 2 - 2), depth / 2 + 2);
    if (x !== c.target.x || z !== c.target.z) {
      camera.position.x += x - c.target.x;
      camera.position.z += z - c.target.z;
      c.target.x = x;
      c.target.z = z;
    }
  });

  return (
    <OrbitControls
      ref={controls}
      makeDefault
      target={[0, 0.8, 2 * k]}
      enableDamping
      dampingFactor={0.08}
      zoomToCursor
      screenSpacePanning={false} // pan slides along the floor, like moving a map
      panSpeed={1.2}
      rotateSpeed={0.7}
      zoomSpeed={1.2}
      minDistance={1.2}
      maxDistance={90 * k}
      maxPolarAngle={Math.PI / 2.05} // stop just above the floor
      mouseButtons={{ LEFT: MOUSE.ROTATE, MIDDLE: MOUSE.DOLLY, RIGHT: MOUSE.PAN }}
      touches={{ ONE: TOUCH.ROTATE, TWO: TOUCH.DOLLY_PAN }}
      onStart={() => {
        fly.current = null; // the user took over
      }}
    />
  );
}
