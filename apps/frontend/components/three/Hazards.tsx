"use client";

import { RoundedBox } from "@react-three/drei";
import type { Closure, WarehouseState } from "@/lib/types";
import { useSim } from "@/lib/store";
import { gridToWorld } from "./coords";
import { cartonTexture, hazardTexture, signTexture, woodTexture } from "./textures";

/** Deterministic 0..1 value per hazard id, so a parcel keeps its pose between frames. */
function jitter(id: string, salt: number) {
  let h = 2166136261 ^ salt;
  for (let i = 0; i < id.length; i++) h = Math.imul(h ^ id.charCodeAt(i), 16777619);
  return ((h >>> 0) % 10000) / 10000;
}

/** A parcel dropped on the floor: a taped carton, slightly turned and off-centre. */
function DroppedParcel({ id }: { id: string }) {
  const w = 0.4 + jitter(id, 1) * 0.25;
  const h = 0.25 + jitter(id, 2) * 0.2;
  const d = 0.3 + jitter(id, 3) * 0.2;
  const tipped = jitter(id, 4) < 0.35;
  return (
    <group
      position={[(jitter(id, 5) - 0.5) * 0.4, 0, (jitter(id, 6) - 0.5) * 0.4]}
      rotation={[0, jitter(id, 7) * Math.PI, tipped ? 0.18 : 0]}
    >
      <RoundedBox args={[w, h, d]} radius={0.015} position={[0, h / 2, 0]} castShadow receiveShadow>
        <meshStandardMaterial map={cartonTexture()} roughness={0.9} />
      </RoundedBox>
    </group>
  );
}

/** A pallet that fell off a rack or a truck: tilted deck boards with two loose cartons. */
function FallenPallet({ id }: { id: string }) {
  const yaw = jitter(id, 11) * Math.PI;
  return (
    <group rotation={[0, yaw, 0]}>
      <group rotation={[0.12, 0, 0.06]} position={[0, 0.08, 0]}>
        {[-0.5, 0, 0.5].map((x) => (
          <mesh key={x} position={[x, 0.05, 0]} castShadow receiveShadow>
            <boxGeometry args={[0.1, 0.1, 0.8]} />
            <meshStandardMaterial map={woodTexture()} roughness={0.85} />
          </mesh>
        ))}
        <mesh position={[0, 0.115, 0]} castShadow receiveShadow>
          <boxGeometry args={[1.2, 0.025, 0.8]} />
          <meshStandardMaterial map={woodTexture()} roughness={0.85} />
        </mesh>
      </group>
      {[0.3, -0.35].map((x, i) => (
        <RoundedBox
          key={x}
          args={[0.45, 0.32, 0.38]}
          radius={0.015}
          position={[x, 0.16, 0.55 - i * 0.95]}
          rotation={[0, jitter(id, 12 + i) * 2, i ? 0.25 : 0]}
          castShadow
        >
          <meshStandardMaterial map={cartonTexture()} roughness={0.9} />
        </RoundedBox>
      ))}
    </group>
  );
}

/** Folding barrier with hazard-striped boards and an "AISLE CLOSED" sign, across an aisle end. */
function Barrier({ label }: { label: string }) {
  return (
    <group>
      {[-0.45, 0.45].map((z) => (
        <group key={z} position={[0, 0, z]}>
          <mesh position={[0, 0.5, 0]} castShadow>
            <boxGeometry args={[0.05, 1.0, 0.05]} />
            <meshStandardMaterial color="#e8e8e8" roughness={0.5} />
          </mesh>
          <mesh position={[0, 0.02, 0]} receiveShadow>
            <boxGeometry args={[0.35, 0.04, 0.12]} />
            <meshStandardMaterial color="#1b1b1b" roughness={0.8} />
          </mesh>
        </group>
      ))}
      {[0.85, 0.45].map((y) => (
        <mesh key={y} position={[0, y, 0]} castShadow>
          <boxGeometry args={[0.03, 0.16, 0.95]} />
          <meshStandardMaterial map={hazardTexture()} roughness={0.6} />
        </mesh>
      ))}
      <mesh position={[0.02, 1.15, 0]} rotation={[0, Math.PI / 2, 0]}>
        <planeGeometry args={[0.9, 0.24]} />
        <meshStandardMaterial map={signTexture(label, "#c62828", "#ffffff")} side={2} />
      </mesh>
    </group>
  );
}

/** Barriers at both ends of a closed aisle (each one labelled as a blocked path). */
function ClosedAisle({ closure, width, height }: { closure: Closure; width: number; height: number }) {
  const xs = closure.cells.map((c) => c[0]);
  const y = closure.cells[0][1];
  const ends = [Math.min(...xs), Math.max(...xs)];
  return (
    <>
      {ends.map((x, i) => {
        const [wx, , wz] = gridToWorld(x, y, width, height);
        return (
          <group
            key={x}
            position={[wx + (i === 0 ? -0.3 : 0.3), 0, wz]}
            rotation={[0, i === 0 ? Math.PI : 0, 0]}
            userData={{ label: "blocked_path", id: `${closure.aisle_id}:${i ? "east" : "west"}` }}
          >
            <Barrier label={`${closure.name.toUpperCase()} CLOSED`} />
          </group>
        );
      })}
    </>
  );
}

const NO_OBSTACLES: WarehouseState["obstacles"] = [];
const NO_CLOSURES: Closure[] = [];

/** Dropped parcels, fallen pallets and closed aisles from the live state. */
export function Hazards({ width, height }: { width: number; height: number }) {
  const obstacles = useSim((s) => s.state?.obstacles ?? NO_OBSTACLES);
  const closures = useSim((s) => s.state?.closures ?? NO_CLOSURES);
  return (
    <group>
      {obstacles
        .filter((o) => o.type === "PACKAGE" || o.type === "DEBRIS")
        .map((o) => {
          const id = o.obstacle_id ?? `${o.position[0]},${o.position[1]}`;
          const [x, , z] = gridToWorld(o.position[0], o.position[1], width, height);
          return (
            <group
              key={id}
              position={[x, 0, z]}
              userData={{ label: o.type === "PACKAGE" ? "package" : "obstacle", id }}
            >
              {o.type === "PACKAGE" ? <DroppedParcel id={id} /> : <FallenPallet id={id} />}
            </group>
          );
        })}
      {closures.map((c) => (
        <ClosedAisle key={c.hazard_id} closure={c} width={width} height={height} />
      ))}
    </group>
  );
}
