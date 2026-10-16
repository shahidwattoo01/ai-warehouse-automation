"use client";

import { useFrame, useThree } from "@react-three/fiber";
import { useEffect, useRef } from "react";
import { Vector3 } from "three";
import type { OrbitControls as OrbitControlsImpl } from "three-stdlib";
import { useSim } from "@/lib/store";
import { robotNodes } from "./RobotFleet";

const prev = new Vector3();
const delta = new Vector3();
const goal = new Vector3();

/**
 * Click a robot to fly the camera to it and keep it in frame while it drives.
 * The orbit offset is preserved, so the user can still rotate and zoom around it.
 */
export function FollowCamera() {
  const selected = useSim((s) => s.selectedRobot);
  const controls = useThree((s) => s.controls) as OrbitControlsImpl | null;
  const camera = useThree((s) => s.camera);
  const flying = useRef(0);

  useEffect(() => {
    flying.current = selected ? 1.2 : 0; // seconds of fly-in
  }, [selected]);

  useFrame((_, dt) => {
    if (!selected || !controls) return;
    const node = robotNodes.get(selected);
    if (!node) return;
    goal.set(node.position.x, 0.7, node.position.z);
    prev.copy(controls.target);
    const k = flying.current > 0 ? 1 - Math.exp(-dt * 4) : 1;
    controls.target.lerp(goal, k);
    delta.subVectors(controls.target, prev);
    camera.position.add(delta);
    if (flying.current > 0) {
      flying.current -= dt;
      // Pull in to a close inspection distance.
      const offset = camera.position.clone().sub(controls.target);
      const want = 5.5;
      offset.setLength(offset.length() + (want - offset.length()) * (1 - Math.exp(-dt * 3)));
      camera.position.copy(controls.target).add(offset);
    }
    controls.update();
  });

  return null;
}
