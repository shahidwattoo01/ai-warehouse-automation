"use client";

import { RoundedBox } from "@react-three/drei";
import { StaticBatch } from "./StaticBatch";
import { cartonTexture, hazardTexture, signTexture, woodTexture } from "./textures";

const WHEEL = { color: "#141414", roughness: 0.85 } as const;

/** Counterbalance forklift (approx. 2.3 t class): body, overhead guard, mast, forks, seat. Faces +X. */
export function Forklift() {
  return (
    <group>
      {/* Chassis + counterweight */}
      <RoundedBox args={[1.6, 0.7, 1.1]} radius={0.08} position={[-0.1, 0.55, 0]} castShadow receiveShadow>
        <meshPhysicalMaterial color="#e8590c" roughness={0.4} clearcoat={0.5} />
      </RoundedBox>
      <RoundedBox args={[0.5, 0.75, 1.12]} radius={0.12} position={[-0.75, 0.75, 0]} castShadow>
        <meshStandardMaterial color="#2b2f36" roughness={0.6} metalness={0.3} />
      </RoundedBox>
      {/* Wheels */}
      {[
        [0.45, 0.5],
        [0.45, -0.5],
        [-0.6, 0.48],
        [-0.6, -0.48],
      ].map(([x, z], i) => (
        <mesh key={i} position={[x, 0.3, z]} rotation-x={Math.PI / 2} castShadow>
          <cylinderGeometry args={[i < 2 ? 0.3 : 0.24, i < 2 ? 0.3 : 0.24, 0.22, 24]} />
          <meshStandardMaterial {...WHEEL} />
        </mesh>
      ))}
      {/* Seat and steering */}
      <RoundedBox args={[0.4, 0.15, 0.45]} radius={0.05} position={[-0.3, 1.0, 0]} castShadow>
        <meshStandardMaterial color="#1a1a1a" roughness={0.7} />
      </RoundedBox>
      <RoundedBox args={[0.12, 0.45, 0.45]} radius={0.05} position={[-0.5, 1.25, 0]} castShadow>
        <meshStandardMaterial color="#1a1a1a" roughness={0.7} />
      </RoundedBox>
      <mesh position={[0.2, 1.25, 0]} rotation-z={0.6}>
        <torusGeometry args={[0.14, 0.015, 8, 24]} />
        <meshStandardMaterial color="#111" />
      </mesh>
      {/* Overhead guard */}
      {[
        [0.35, 0.5],
        [0.35, -0.5],
        [-0.65, 0.5],
        [-0.65, -0.5],
      ].map(([x, z], i) => (
        <mesh key={i} position={[x, 1.55, z]} rotation-z={i < 2 ? -0.08 : 0} castShadow>
          <boxGeometry args={[0.06, 1.3, 0.06]} />
          <meshStandardMaterial color="#1f1f1f" metalness={0.5} roughness={0.5} />
        </mesh>
      ))}
      <mesh position={[-0.13, 2.2, 0]} castShadow>
        <boxGeometry args={[1.15, 0.06, 1.06]} />
        <meshStandardMaterial color="#1f1f1f" metalness={0.5} roughness={0.5} />
      </mesh>
      {/* Beacon */}
      <mesh position={[-0.6, 2.28, 0.4]}>
        <cylinderGeometry args={[0.05, 0.05, 0.1, 16]} />
        <meshStandardMaterial color="#ff8c00" emissive="#ff8c00" emissiveIntensity={2} toneMapped={false} />
      </mesh>
      {/* Mast, carriage and forks */}
      {[0.32, -0.32].map((z) => (
        <mesh key={z} position={[0.82, 1.2, z]} castShadow>
          <boxGeometry args={[0.1, 2.3, 0.08]} />
          <meshStandardMaterial color="#2b2f36" metalness={0.6} roughness={0.4} />
        </mesh>
      ))}
      <mesh position={[0.9, 0.45, 0]} castShadow>
        <boxGeometry args={[0.06, 0.5, 0.8]} />
        <meshStandardMaterial color="#2b2f36" metalness={0.6} roughness={0.4} />
      </mesh>
      {[0.22, -0.22].map((z) => (
        <mesh key={z} position={[1.45, 0.24, z]} castShadow>
          <boxGeometry args={[1.1, 0.045, 0.1]} />
          <meshStandardMaterial color="#3a3f46" metalness={0.8} roughness={0.35} />
        </mesh>
      ))}
    </group>
  );
}

/** EUR-style wooden pallet, optionally with a wrapped carton load. Origin at floor centre. */
export function Pallet({ load = true, layers = 2 }: { load?: boolean; layers?: number }) {
  const ch = 0.32;
  return (
    <group>
      {[-0.32, -0.16, 0, 0.16, 0.32].map((x) => (
        <mesh key={x} position={[x, 0.133, 0]} castShadow receiveShadow>
          <boxGeometry args={[0.12, 0.022, 1.2]} />
          <meshStandardMaterial map={woodTexture()} roughness={0.85} />
        </mesh>
      ))}
      {[-0.55, 0, 0.55].map((z) => (
        <group key={z}>
          {[-0.33, 0, 0.33].map((x) => (
            <mesh key={x} position={[x, 0.06, z]} castShadow>
              <boxGeometry args={[0.12, 0.1, 0.1]} />
              <meshStandardMaterial map={woodTexture()} color="#b08d5f" roughness={0.9} />
            </mesh>
          ))}
          <mesh position={[0, 0.011, z]} receiveShadow>
            <boxGeometry args={[0.8, 0.022, 0.1]} />
            <meshStandardMaterial map={woodTexture()} roughness={0.85} />
          </mesh>
        </group>
      ))}
      {load && (
        <group position={[0, 0.144, 0]}>
          {Array.from({ length: layers }, (_, l) =>
            [-0.19, 0.19].flatMap((x) =>
              [-0.4, 0, 0.4].map((z) => (
                <mesh key={`${l}${x}${z}`} position={[x, ch * l + ch / 2, z]} castShadow receiveShadow>
                  <boxGeometry args={[0.37, ch - 0.005, 0.39]} />
                  <meshStandardMaterial map={cartonTexture()} roughness={0.92} />
                </mesh>
              )),
            ),
          )}
          <mesh position={[0, (ch * layers) / 2, 0]}>
            <boxGeometry args={[0.79, ch * layers + 0.01, 1.2]} />
            <meshPhysicalMaterial
              color="#e8f1f8"
              transparent
              opacity={0.2}
              roughness={0.1}
              clearcoat={1}
              depthWrite={false}
            />
          </mesh>
        </group>
      )}
    </group>
  );
}

/** Hand pallet jack. Faces +X. */
export function PalletJack() {
  return (
    <group>
      {[0.2, -0.2].map((z) => (
        <mesh key={z} position={[0.5, 0.05, z]} castShadow>
          <boxGeometry args={[1.1, 0.07, 0.16]} />
          <meshStandardMaterial color="#d9480f" metalness={0.4} roughness={0.45} />
        </mesh>
      ))}
      <mesh position={[-0.12, 0.25, 0]} castShadow>
        <boxGeometry args={[0.22, 0.4, 0.5]} />
        <meshStandardMaterial color="#d9480f" metalness={0.4} roughness={0.45} />
      </mesh>
      <mesh position={[-0.35, 0.75, 0]} rotation-z={0.45} castShadow>
        <cylinderGeometry args={[0.02, 0.02, 1.1, 10]} />
        <meshStandardMaterial color="#222" />
      </mesh>
      <mesh position={[-0.6, 1.25, 0]} rotation-x={Math.PI / 2}>
        <torusGeometry args={[0.1, 0.02, 8, 20]} />
        <meshStandardMaterial color="#222" />
      </mesh>
    </group>
  );
}

/** Steel safety bollard filled with concrete, painted yellow with black bands. */
export function Bollard() {
  return (
    <group>
      <mesh position={[0, 0.6, 0]} castShadow>
        <cylinderGeometry args={[0.07, 0.07, 1.2, 20]} />
        <meshStandardMaterial map={hazardTexture()} roughness={0.45} metalness={0.3} />
      </mesh>
      <mesh position={[0, 1.21, 0]}>
        <sphereGeometry args={[0.07, 16, 8, 0, Math.PI * 2, 0, Math.PI / 2]} />
        <meshStandardMaterial color="#f2c200" roughness={0.45} />
      </mesh>
    </group>
  );
}

/** Wall-mounted fire extinguisher point with sign. */
export function FirePoint() {
  return (
    <group>
      <mesh position={[0, 0.55, 0.12]} castShadow>
        <cylinderGeometry args={[0.08, 0.08, 0.55, 18]} />
        <meshStandardMaterial color="#c1121f" roughness={0.35} metalness={0.2} />
      </mesh>
      <mesh position={[0, 0.88, 0.12]}>
        <cylinderGeometry args={[0.03, 0.04, 0.1, 12]} />
        <meshStandardMaterial color="#222" />
      </mesh>
      <mesh position={[0, 1.6, 0.01]}>
        <planeGeometry args={[0.35, 0.35]} />
        <meshStandardMaterial map={signTexture("FIRE", "#c1121f", "#ffffff", 256, 256)} />
      </mesh>
    </group>
  );
}

/** Same dock door spacing as Building. */
function doorXs(width: number) {
  const n = Math.max(3, Math.floor(width / 7));
  return Array.from({ length: n }, (_, i) => -width / 2 + (width / n) * (i + 0.5));
}

/**
 * Non-simulated set dressing outside the robot grid: dock staging, a parked forklift and
 * pallet jack, bollards and fire points. Positions are derived from the grid size.
 */
export function Props({ width, height }: { width: number; height: number }) {
  const north = -height / 2 - 1.5; // dock apron strip between the grid and the north wall
  const south = height / 2 + 1.8;
  return (
    <StaticBatch>
      <group position={[-width / 2 + 1.2, 0, north]}>
        <Forklift />
      </group>
      {[-9, -7.8, 6, 7.2, 13].map((x, i) => (
        <group key={x} position={[x, 0, north + (i % 2) * 0.2]} rotation-y={Math.PI / 2}>
          <Pallet layers={1 + (i % 3)} />
        </group>
      ))}
      <group position={[-6.4, 0, north]} rotation-y={Math.PI / 2}>
        <Pallet load={false} />
        <group position={[0, 0.145, 0]}>
          <Pallet load={false} />
        </group>
      </group>
      <group position={[2, 0, north + 0.4]} rotation-y={0.3}>
        <PalletJack />
      </group>
      {/* Bollards protecting the dock door frames */}
      {doorXs(width)
        .flatMap((d) => [d - 1.9, d + 1.9])
        .map((x) => (
          <group key={x} position={[x, 0, -height / 2 - 0.3]}>
            <Bollard />
          </group>
        ))}
      <group position={[width / 2 + 1.5, 0, south]}>
        <Pallet load layers={3} />
      </group>
    </StaticBatch>
  );
}
