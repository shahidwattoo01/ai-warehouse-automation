"use client";

import { Line } from "@react-three/drei";
import { type ThreeEvent, useFrame } from "@react-three/fiber";
import { useLayoutEffect, useMemo, useRef } from "react";
import {
  Color,
  type InstancedMesh,
  Matrix4,
  type Mesh,
  MeshBasicMaterial,
  Object3D,
  PlaneGeometry,
  Quaternion,
  Vector3,
} from "three";
import type { Robot as RobotState } from "@/lib/types";
import { useSim } from "@/lib/store";
import { STATUS_COLOR } from "@/lib/status";
import { gridToWorld } from "./coords";
import { BATTERY_CENTER, type GroupName, robotKit, WHEEL_R } from "./robotKit";
import { blobTexture } from "./textures";

const NO_ROBOTS: RobotState[] = []; // stable fallback: a fresh [] in a zustand selector re-renders forever

/** Live robot positions by id (interpolated, not grid), so the camera can follow a robot. */
export const robotNodes = new Map<string, Object3D>();

interface Motion {
  x: number;
  z: number;
  rot: number;
  wheel: number;
  node: Object3D;
}

const UP = new Vector3(0, 1, 0);
const Z = new Vector3(0, 0, 1);
const m = new Matrix4();
const tmp = new Matrix4();
const q = new Quaternion();
const qWheel = new Quaternion();
const pos = new Vector3();
const one = new Vector3(1, 1, 1);
const zero = new Matrix4().makeScale(0, 0, 0);
const col = new Color();
const wheelOffset = new Matrix4();
const batteryPivot = new Matrix4().makeTranslation(BATTERY_CENTER.x, BATTERY_CENTER.y, BATTERY_CENTER.z);
const batteryPivotInv = batteryPivot.clone().invert();
const batteryScale = new Matrix4();

function angleDelta(a: number, b: number) {
  return Math.atan2(Math.sin(b - a), Math.cos(b - a));
}

/**
 * The whole AMR fleet in ~18 draw calls: one InstancedMesh per material group of the robot kit.
 * Each frame every robot drives at constant speed toward its latest simulator cell, turns toward
 * its travel direction, spins its wheels, and shows status on its light band and beacon.
 */
export function RobotFleet({
  width,
  height,
  castShadows = true,
}: {
  width: number;
  height: number;
  /** false on low-end GPUs (static shadow map): a soft blob under each robot stands in. */
  castShadows?: boolean;
}) {
  const robots = useSim((s) => s.state?.robots ?? NO_ROBOTS);
  const selected = useSim((s) => s.selectedRobot);
  const selectRobot = useSim((s) => s.selectRobot);
  const kit = useMemo(() => robotKit(), []);
  const names = useMemo(() => Object.keys(kit) as GroupName[], [kit]);
  const meshes = useRef<Partial<Record<GroupName, InstancedMesh | null>>>({});
  const motion = useRef(new Map<string, Motion>());
  const ring = useRef<Mesh>(null);
  const blobs = useRef<InstancedMesh | null>(null);
  const blobGeo = useMemo(() => new PlaneGeometry(1.25, 0.95).rotateX(-Math.PI / 2), []);
  const blobMat = useMemo(
    () => new MeshBasicMaterial({ map: blobTexture(), transparent: true, depthWrite: false, toneMapped: false }),
    [],
  );
  const live = useRef(robots);
  live.current = robots;
  const count = robots.length;

  // Give tinted groups an instanceColor buffer before the first frame.
  useLayoutEffect(() => {
    for (const name of names) {
      const mesh = meshes.current[name];
      if (mesh && kit[name].tinted) for (let i = 0; i < count; i++) mesh.setColorAt(i, col.set("#ffffff"));
    }
  }, [count, kit, names]);

  useFrame((state, dt) => {
    const list = live.current;
    const interval = useSim.getState().tickInterval;
    const t = state.clock.elapsedTime;
    const ms = meshes.current;

    list.forEach((r, i) => {
      const [tx, , tz] = gridToWorld(r.position[0], r.position[1], width, height);
      let mo = motion.current.get(r.robot_id);
      if (!mo) {
        mo = { x: tx, z: tz, rot: r.heading, wheel: 0, node: new Object3D() };
        motion.current.set(r.robot_id, mo);
        robotNodes.set(r.robot_id, mo.node);
      }
      const dx = tx - mo.x;
      const dz = tz - mo.z;
      const dist = Math.hypot(dx, dz);
      let moved = 0;
      if (dist > 3) {
        mo.x = tx; // teleport after reset / reconnect
        mo.z = tz;
      } else if (dist > 1e-4) {
        moved = Math.min(dist, (dt / interval) * 1.08);
        mo.x += (dx / dist) * moved;
        mo.z += (dz / dist) * moved;
      }
      const want = dist > 0.05 ? Math.atan2(-dz, dx) : r.heading;
      mo.rot += angleDelta(mo.rot, want) * (1 - Math.exp(-dt * 10));
      mo.wheel -= moved / WHEEL_R;
      mo.node.position.set(mo.x, 0, mo.z);
      mo.node.rotation.y = mo.rot; // read by the camera-dataset labeller (app/capture)

      const bob = moved > 0 ? Math.sin(t * 30 + i) * 0.002 : 0;
      q.setFromAxisAngle(UP, mo.rot);
      m.compose(pos.set(mo.x, bob, mo.z), q, one);

      for (const name of names) {
        const mesh = ms[name];
        if (!mesh) continue;
        if (name === "wheels") {
          qWheel.setFromAxisAngle(Z, mo.wheel);
          wheelOffset.compose(pos.set(0, WHEEL_R, 0), qWheel, one);
          mesh.setMatrixAt(i, tmp.multiplyMatrices(m, wheelOffset));
        } else if (name === "contents0" || name === "contents1") {
          mesh.setMatrixAt(i, r.load > (name === "contents0" ? 0 : 1) ? m : zero);
        } else if (name === "battery") {
          batteryScale.makeScale(1, 1, Math.max(0.03, r.battery / 100));
          mesh.setMatrixAt(i, tmp.multiplyMatrices(m, batteryPivot).multiply(batteryScale).multiply(batteryPivotInv));
          col.set(r.battery > 50 ? "#22C55E" : r.battery > 20 ? "#F59E0B" : "#EF4444").multiplyScalar(1.4);
          mesh.setColorAt(i, col);
        } else {
          mesh.setMatrixAt(i, m);
        }
      }
      if (blobs.current) {
        m.compose(pos.set(mo.x, 0.008, mo.z), q, one);
        blobs.current.setMatrixAt(i, m);
      }
      const status = STATUS_COLOR[r.status] ?? STATUS_COLOR.IDLE;
      ms.status?.setColorAt(i, col.set(status).multiplyScalar(2.2));
      const pulse = r.status === "FAULT" ? (Math.sin(t * 10) > 0 ? 3 : 0.25) : 1.6 + Math.sin(t * 3 + i) * 0.6;
      ms.beacon?.setColorAt(i, col.set(status).multiplyScalar(pulse));
    });

    if (blobs.current) {
      blobs.current.count = list.length;
      blobs.current.instanceMatrix.needsUpdate = true;
    }
    for (const name of names) {
      const mesh = ms[name];
      if (!mesh) continue;
      mesh.count = list.length;
      mesh.instanceMatrix.needsUpdate = true;
      if (mesh.instanceColor) mesh.instanceColor.needsUpdate = true;
    }

    const sel = selected ? motion.current.get(selected) : undefined;
    if (ring.current) {
      ring.current.visible = !!sel;
      if (sel) ring.current.position.set(sel.x, 0.012, sel.z);
    }
  });

  const onClick = (e: ThreeEvent<MouseEvent>) => {
    if (e.instanceId === undefined) return;
    e.stopPropagation();
    const r = live.current[e.instanceId];
    if (r) selectRobot(r.robot_id);
  };

  const route = useMemo(() => {
    const r = robots.find((x) => x.robot_id === selected);
    if (!r || !r.route.length) return null;
    return {
      color: STATUS_COLOR[r.status] ?? STATUS_COLOR.IDLE,
      points: [r.position, ...r.route].map(([x, y]) => {
        const [wx, , wz] = gridToWorld(x, y, width, height);
        return [wx, 0.03, wz] as [number, number, number];
      }),
    };
  }, [robots, selected, width, height]);

  return (
    <group>
      <group
        onClick={onClick}
        onPointerOver={() => (document.body.style.cursor = "pointer")}
        onPointerOut={() => (document.body.style.cursor = "")}
      >
        {count > 0 &&
          names.map((name) => (
            <instancedMesh
              key={`${name}:${count}`}
              ref={(el) => {
                meshes.current[name] = el;
              }}
              args={[kit[name].geometry, kit[name].material, count]}
              castShadow={castShadows && kit[name].castShadow}
              receiveShadow
              frustumCulled={false}
            />
          ))}
      </group>
      {!castShadows && count > 0 && (
        <instancedMesh
          key={`blob:${count}`}
          ref={blobs}
          args={[blobGeo, blobMat, count]}
          frustumCulled={false}
          renderOrder={-1}
        />
      )}
      <mesh ref={ring} rotation-x={-Math.PI / 2} visible={false}>
        <ringGeometry args={[0.66, 0.72, 64]} />
        <meshBasicMaterial color="#3B82F6" toneMapped={false} />
      </mesh>
      {route && <Line points={route.points} color={route.color} lineWidth={2} dashed dashSize={0.3} gapSize={0.2} />}
    </group>
  );
}
