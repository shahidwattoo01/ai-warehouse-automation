"use client";

import { useFrame } from "@react-three/fiber";
import { RoundedBox } from "@react-three/drei";
import { useRef } from "react";
import type { Group } from "three";
import type { Station } from "@/lib/types";
import { gridToWorld } from "./coords";
import { StaticBatch } from "./StaticBatch";
import { cartonTexture, hazardTexture, screenTexture, signTexture, woodTexture } from "./textures";
import { Worker } from "./Worker";

const STEEL = { color: "#9aa3ab", metalness: 0.85, roughness: 0.32 } as const;

/** Rollers that visibly turn, carrying a couple of parcels along the outfeed conveyor. */
function Conveyor({ length }: { length: number }) {
  const rollers = useRef<Group>(null);
  const parcels = useRef<Group>(null);
  useFrame((_, dt) => {
    rollers.current?.children.forEach((r) => (r.rotation.y += dt * 6));
    parcels.current?.children.forEach((p) => {
      p.position.x += dt * 0.35;
      if (p.position.x > length / 2 - 0.2) p.position.x = -length / 2 + 0.2;
    });
  });
  const n = Math.floor(length / 0.12);
  return (
    <group>
      {/* Side rails */}
      {[-0.32, 0.32].map((z) => (
        <mesh key={z} position={[0, 0.9, z]} castShadow>
          <boxGeometry args={[length, 0.1, 0.03]} />
          <meshStandardMaterial {...STEEL} />
        </mesh>
      ))}
      {/* Legs */}
      {[-length / 2 + 0.1, 0, length / 2 - 0.1].flatMap((x) =>
        [-0.3, 0.3].map((z) => (
          <mesh key={`${x}${z}`} position={[x, 0.42, z]} castShadow>
            <boxGeometry args={[0.04, 0.84, 0.04]} />
            <meshStandardMaterial {...STEEL} />
          </mesh>
        )),
      )}
      <group ref={rollers} userData={{ noBatch: true }}>
        {Array.from({ length: n }, (_, i) => (
          <mesh key={i} position={[-length / 2 + 0.06 + i * 0.12, 0.9, 0]} rotation-x={Math.PI / 2}>
            <cylinderGeometry args={[0.024, 0.024, 0.62, 12]} />
            <meshStandardMaterial color="#c3c9cf" metalness={0.95} roughness={0.2} />
          </mesh>
        ))}
      </group>
      <group ref={parcels} userData={{ noBatch: true }}>
        {[-0.6, 0.5].map((x, i) => (
          <mesh key={x} position={[x, 1.02, 0]} castShadow>
            <boxGeometry args={[0.36, 0.2 + i * 0.06, 0.3]} />
            <meshStandardMaterial map={cartonTexture()} roughness={0.9} />
          </mesh>
        ))}
      </group>
    </group>
  );
}

function PackingStation({ station }: { station: Station }) {
  return (
    <group>
      {/* Three robot drop-off bays in front of the bench (matches the engine's drop_bays) */}
      {[-1, 0, 1].map((dx) => (
        <group key={dx} position={[dx, 0, 0]}>
          <mesh rotation-x={-Math.PI / 2} position={[0, 0.006, 0]}>
            <planeGeometry args={[0.96, 0.96]} />
            <meshStandardMaterial map={hazardTexture()} roughness={0.7} transparent opacity={0.85} />
          </mesh>
          <mesh rotation-x={-Math.PI / 2} position={[0, 0.007, 0]}>
            <planeGeometry args={[0.8, 0.8]} />
            <meshStandardMaterial color="#7d8288" roughness={0.6} />
          </mesh>
        </group>
      ))}

      <group position={[0, 0, 1.05]}>
        {/* Workbench: steel frame, butcher-block top, lower shelf with flat-packed boxes */}
        {[[-0.9, -0.3], [-0.9, 0.3], [0.9, -0.3], [0.9, 0.3]].map(([x, z], i) => (
          <mesh key={i} position={[x, 0.45, z]} castShadow>
            <boxGeometry args={[0.05, 0.9, 0.05]} />
            <meshStandardMaterial {...STEEL} />
          </mesh>
        ))}
        <RoundedBox args={[2.0, 0.05, 0.75]} radius={0.01} position={[0, 0.92, 0]} castShadow receiveShadow>
          <meshStandardMaterial map={woodTexture()} color="#e0c49a" roughness={0.6} />
        </RoundedBox>
        <mesh position={[0, 0.2, 0]} receiveShadow>
          <boxGeometry args={[1.85, 0.03, 0.65]} />
          <meshStandardMaterial {...STEEL} />
        </mesh>
        {[0, 1, 2, 3].map((i) => (
          <mesh key={i} position={[-0.3, 0.23 + i * 0.012, 0]} castShadow>
            <boxGeometry args={[1.1, 0.01, 0.55]} />
            <meshStandardMaterial map={cartonTexture()} roughness={0.95} />
          </mesh>
        ))}
        {/* Overhead light bar and upright frame */}
        {[-0.95, 0.95].map((x) => (
          <mesh key={x} position={[x, 1.45, 0.3]} castShadow>
            <boxGeometry args={[0.04, 1.1, 0.04]} />
            <meshStandardMaterial {...STEEL} />
          </mesh>
        ))}
        <mesh position={[0, 2.0, 0.3]} castShadow>
          <boxGeometry args={[1.95, 0.06, 0.12]} />
          <meshStandardMaterial {...STEEL} />
        </mesh>
        <mesh position={[0, 1.965, 0.24]} rotation-x={Math.PI / 2}>
          <planeGeometry args={[1.8, 0.06]} />
          <meshStandardMaterial color="#ffffff" emissive="#fff6e5" emissiveIntensity={2.5} toneMapped={false} />
        </mesh>
        {/* Station sign */}
        <mesh position={[0, 2.25, 0.3]}>
          <planeGeometry args={[0.9, 0.24]} />
          <meshStandardMaterial map={signTexture(station.station_id.replace("_", " "), "#14532d")} />
        </mesh>
        {/* Monitor on a VESA arm */}
        <mesh position={[0.6, 1.1, 0.25]}>
          <cylinderGeometry args={[0.015, 0.015, 0.36, 10]} />
          <meshStandardMaterial color="#2a2d31" metalness={0.6} roughness={0.4} />
        </mesh>
        <group position={[0.6, 1.36, 0.22]} rotation-x={-0.1}>
          <RoundedBox args={[0.55, 0.34, 0.035]} radius={0.01} castShadow>
            <meshStandardMaterial color="#141518" roughness={0.4} />
          </RoundedBox>
          <mesh position={[0, 0, 0.019]}>
            <planeGeometry args={[0.51, 0.3]} />
            <meshStandardMaterial map={screenTexture("#22C55E")} emissive="#ffffff" emissiveMap={screenTexture("#22C55E")} emissiveIntensity={0.8} toneMapped={false} />
          </mesh>
        </group>
        {/* Label printer, tape gun, open shipping box on the bench */}
        <RoundedBox args={[0.25, 0.18, 0.22]} radius={0.02} position={[-0.75, 1.04, 0.1]} castShadow>
          <meshStandardMaterial color="#e9ecef" roughness={0.4} />
        </RoundedBox>
        <mesh position={[-0.2, 1.08, -0.05]} castShadow>
          <boxGeometry args={[0.45, 0.28, 0.35]} />
          <meshStandardMaterial map={cartonTexture()} roughness={0.9} />
        </mesh>
        <mesh position={[0.15, 0.98, -0.15]} rotation-x={Math.PI / 2} castShadow>
          <torusGeometry args={[0.05, 0.02, 8, 20]} />
          <meshStandardMaterial color="#c9a26b" roughness={0.6} />
        </mesh>
        {/* Packer standing behind the bench, facing the robot */}
        <group position={[0.1, 0, 0.75]} rotation-y={Math.PI / 2}>
          <group userData={{ noBatch: true }}>
            <Worker target={[0, 0, 0]} still pose="work" />
          </group>
        </group>
      </group>

      {/* Outfeed conveyor running along the wall */}
      <group position={[2.3, 0, 1.05]}>
        <Conveyor length={2.4} />
      </group>
    </group>
  );
}

function ChargingDock({ side }: { side: number }) {
  // `side` = -1 for a dock on the west wall, +1 for the east wall. The unit sits outside the
  // robot's cell, its contacts facing the robot.
  return (
    <group>
      <mesh rotation-x={-Math.PI / 2} position={[0, 0.006, 0]}>
        <planeGeometry args={[0.95, 0.95]} />
        <meshStandardMaterial color="#1f6f43" roughness={0.6} />
      </mesh>
      <mesh rotation-x={-Math.PI / 2} position={[0, 0.007, 0]}>
        <ringGeometry args={[0.22, 0.27, 6]} />
        <meshStandardMaterial color="#e9fbe9" roughness={0.6} />
      </mesh>
      <group position={[side * 0.68, 0, 0]} rotation-y={side > 0 ? Math.PI : 0}>
        {/* Charger cabinet */}
        <RoundedBox args={[0.32, 0.9, 0.55]} radius={0.03} position={[0, 0.45, 0]} castShadow receiveShadow>
          <meshStandardMaterial color="#2d3238" metalness={0.35} roughness={0.5} />
        </RoundedBox>
        <mesh position={[0.165, 0.7, 0]} rotation-y={Math.PI / 2}>
          <planeGeometry args={[0.4, 0.12]} />
          <meshStandardMaterial map={signTexture("CHARGE", "#14532d")} />
        </mesh>
        {/* Status LEDs */}
        {[-0.1, 0, 0.1].map((z) => (
          <mesh key={z} position={[0.166, 0.55, z]} rotation-y={Math.PI / 2}>
            <circleGeometry args={[0.018, 16]} />
            <meshStandardMaterial color="#22C55E" emissive="#22C55E" emissiveIntensity={2.5} toneMapped={false} />
          </mesh>
        ))}
        {/* Spring-loaded floor contacts */}
        <mesh position={[0.24, 0.08, 0]} castShadow>
          <boxGeometry args={[0.18, 0.06, 0.24]} />
          <meshStandardMaterial color="#1b1d21" roughness={0.6} />
        </mesh>
        {[-0.05, 0.05].map((z) => (
          <mesh key={z} position={[0.33, 0.08, z]}>
            <boxGeometry args={[0.01, 0.02, 0.05]} />
            <meshStandardMaterial color="#c9a227" metalness={1} roughness={0.25} />
          </mesh>
        ))}
        {/* Mains conduit up the wall */}
        <mesh position={[-0.12, 2.0, 0]}>
          <cylinderGeometry args={[0.025, 0.025, 2.2, 10]} />
          <meshStandardMaterial color="#8a9198" metalness={0.7} roughness={0.4} />
        </mesh>
      </group>
    </group>
  );
}

/** Packing benches with conveyor and packer, and wall-side charging docks (one per charging bay). */
export function Stations({ stations, width, height }: { stations: Station[]; width: number; height: number }) {
  return (
    <StaticBatch>
      {stations.map((s) => {
        if (s.type === "PACKING") {
          const [x, , z] = gridToWorld(s.x, s.y, width, height);
          return (
            <group key={s.station_id} position={[x, 0, z]}>
              <PackingStation station={s} />
            </group>
          );
        }
        const half = Math.floor(s.capacity / 2);
        const side = s.x < width / 2 ? -1 : 1;
        return (
          <group key={s.station_id}>
            {Array.from({ length: half * 2 + 1 }, (_, i) => {
              const [x, , z] = gridToWorld(s.x, s.y - half + i, width, height);
              return (
                <group key={i} position={[x, 0, z]}>
                  <ChargingDock side={side} />
                </group>
              );
            })}
          </group>
        );
      })}
    </StaticBatch>
  );
}
