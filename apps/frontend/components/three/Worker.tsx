"use client";

import { useFrame } from "@react-three/fiber";
import { Capsule } from "@react-three/drei";
import { useRef } from "react";
import type { Group } from "three";
import type { WarehouseState } from "@/lib/types";
import { useSim } from "@/lib/store";
import { gridToWorld } from "./coords";

/** Shortest signed angle from a to b. */
function angleDelta(a: number, b: number) {
  return Math.atan2(Math.sin(b - a), Math.cos(b - a));
}

const SKIN = "#c68a64";
const TROUSERS = "#2b3240";
const VEST = "#d7f205";
const REFLECT = "#e8eef2";

/**
 * Warehouse associate (dynamic obstacle): 1.78 m tall, hi-vis vest with reflective tape,
 * hard hat, safety boots. Walks at the simulator pace with a swing-arm gait; stands idle
 * when blocked. Faces +X like the robots.
 */
export function Worker({ target, still = false, pose = "walk" }: { target: [number, number, number]; still?: boolean; pose?: "walk" | "work" }) {
  const root = useRef<Group>(null);
  const legL = useRef<Group>(null);
  const legR = useRef<Group>(null);
  const armL = useRef<Group>(null);
  const armR = useRef<Group>(null);
  const torso = useRef<Group>(null);
  const phase = useRef(Math.random() * 10);

  useFrame((state, dt) => {
    const g = root.current;
    if (!g) return;
    let speed = 0;
    if (!still) {
      // Workers step every 2 ticks in the simulator, so they walk at half the robot pace.
      const interval = useSim.getState().tickInterval * 2;
      const dx = target[0] - g.position.x;
      const dz = target[2] - g.position.z;
      const dist = Math.hypot(dx, dz);
      if (dist > 3) g.position.set(target[0], 0, target[2]);
      else if (dist > 1e-3) {
        const step = Math.min(dist, (dt / interval) * 1.05);
        g.position.x += (dx / dist) * step;
        g.position.z += (dz / dist) * step;
        speed = step / Math.max(dt, 1e-3);
        g.rotation.y += angleDelta(g.rotation.y, Math.atan2(-dz, dx)) * (1 - Math.exp(-dt * 8));
      }
    }
    const walking = speed > 0.05;
    phase.current += dt * (walking ? 7 : 0);
    const swing = walking ? Math.sin(phase.current) * 0.55 : 0;
    if (legL.current) legL.current.rotation.z = swing;
    if (legR.current) legR.current.rotation.z = -swing;
    if (pose === "work") {
      // Packing motion: arms forward, small reaching cycle.
      const t = state.clock.elapsedTime + phase.current;
      if (armL.current) armL.current.rotation.z = 1.0 + Math.sin(t * 2.2) * 0.25;
      if (armR.current) armR.current.rotation.z = 1.1 + Math.cos(t * 2.2) * 0.25;
      if (torso.current) torso.current.rotation.z = -0.12;
    } else {
      if (armL.current) armL.current.rotation.z = -swing * 0.8;
      if (armR.current) armR.current.rotation.z = swing * 0.8;
    }
    if (torso.current && walking) torso.current.position.y = Math.abs(Math.cos(phase.current)) * 0.025;
  });

  const leg = (ref: React.RefObject<Group | null>, z: number) => (
    <group ref={ref} position={[0, 0.92, z]}>
      <Capsule args={[0.075, 0.72, 4, 12]} position={[0, -0.43, 0]} castShadow>
        <meshStandardMaterial color={TROUSERS} roughness={0.9} />
      </Capsule>
      {/* Safety boot */}
      <mesh position={[0.05, -0.86, 0]} castShadow>
        <boxGeometry args={[0.28, 0.12, 0.12]} />
        <meshStandardMaterial color="#2a1d14" roughness={0.7} />
      </mesh>
    </group>
  );

  const arm = (ref: React.RefObject<Group | null>, z: number) => (
    <group ref={ref} position={[0, 1.42, z]}>
      <Capsule args={[0.055, 0.5, 4, 10]} position={[0, -0.3, 0]} castShadow>
        <meshStandardMaterial color="#3b4658" roughness={0.85} />
      </Capsule>
      <mesh position={[0, -0.6, 0]} castShadow>
        <sphereGeometry args={[0.055, 12, 10]} />
        <meshStandardMaterial color="#1d1f22" roughness={0.8} />
      </mesh>
    </group>
  );

  return (
    <group ref={root} position={target} userData={{ label: "worker" }}>
      {leg(legL, 0.1)}
      {leg(legR, -0.1)}
      <group ref={torso}>
        {/* Torso: long-sleeve work shirt */}
        <Capsule args={[0.17, 0.42, 4, 16]} position={[0, 1.2, 0]} scale={[0.75, 1, 1.1]} castShadow>
          <meshStandardMaterial color="#3b4658" roughness={0.85} />
        </Capsule>
        {/* Hi-vis vest */}
        <Capsule args={[0.178, 0.36, 4, 16]} position={[0, 1.22, 0]} scale={[0.78, 1, 1.12]} castShadow>
          <meshStandardMaterial color={VEST} roughness={0.6} emissive={VEST} emissiveIntensity={0.08} />
        </Capsule>
        {/* Reflective bands */}
        {[1.08, 1.24].map((y) => (
          <mesh key={y} position={[0, y, 0]} scale={[0.79, 1, 1.13]}>
            <cylinderGeometry args={[0.182, 0.182, 0.04, 24, 1, true]} />
            <meshStandardMaterial color={REFLECT} metalness={0.6} roughness={0.2} />
          </mesh>
        ))}
        {/* Neck + head */}
        <mesh position={[0, 1.55, 0]}>
          <cylinderGeometry args={[0.05, 0.055, 0.08, 12]} />
          <meshStandardMaterial color={SKIN} roughness={0.7} />
        </mesh>
        <mesh position={[0.01, 1.66, 0]} scale={[1, 1.15, 0.95]} castShadow>
          <sphereGeometry args={[0.1, 20, 16]} />
          <meshStandardMaterial color={SKIN} roughness={0.65} />
        </mesh>
        {/* Hard hat with brim */}
        <mesh position={[0.01, 1.73, 0]} castShadow>
          <sphereGeometry args={[0.115, 20, 12, 0, Math.PI * 2, 0, Math.PI / 2]} />
          <meshPhysicalMaterial color="#f5c400" roughness={0.3} clearcoat={0.8} />
        </mesh>
        <mesh position={[0.05, 1.73, 0]}>
          <cylinderGeometry args={[0.13, 0.13, 0.012, 24]} />
          <meshPhysicalMaterial color="#f5c400" roughness={0.3} clearcoat={0.8} />
        </mesh>
        {arm(armL, 0.22)}
        {arm(armR, -0.22)}
      </group>
    </group>
  );
}

const NO_OBSTACLES: WarehouseState["obstacles"] = []; // stable fallback for the zustand selector

/** Warehouse associates from the live state (obstacles of type WORKER). */
export function WorkerLayer({ width, height }: { width: number; height: number }) {
  const obstacles = useSim((s) => s.state?.obstacles ?? NO_OBSTACLES);
  return (
    <group>
      {obstacles
        .filter((o) => o.type === "WORKER")
        .map((o, i) => (
          <Worker key={i} target={gridToWorld(o.position[0], o.position[1], width, height)} />
        ))}
    </group>
  );
}
