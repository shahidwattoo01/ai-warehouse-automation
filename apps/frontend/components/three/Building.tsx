"use client";

import { useFrame } from "@react-three/fiber";
import { useMemo, useRef } from "react";
import {
  BoxGeometry,
  CylinderGeometry,
  type Group,
  type Material,
  MeshStandardMaterial,
  PlaneGeometry,
  type Texture,
  Vector3,
} from "three";
import type { ParkingAreaSnapshot, Zone } from "@/lib/types";
import { gridToWorld } from "./coords";
import { InstancedParts, type Placement } from "./Instanced";
import { FirePoint } from "./Props";
import { StaticBatch } from "./StaticBatch";
import { SignBoards, type Sign } from "./SignBoards";
import {
  arrowTexture,
  parkingBayTexture,
  concreteRoughness,
  concreteTexture,
  hazardTexture,
  shutterTexture,
  signTexture,
  wallPanelTexture,
} from "./textures";

const MARGIN = 3; // floor beyond the grid on each side (dock apron, charger alcoves)
const WALL_H = 8;
const TAPE = 0.1;

/**
 * Warehouse shell: power-trowelled concrete slab with saw-cut joints, painted lane and zone
 * markings, insulated wall panels with a concrete kerb, roller-shutter dock doors with levellers,
 * steel H-columns with impact guards and high-bay LED fixtures.
 * Walls are single-sided facing inward, so they vanish when the camera orbits outside them.
 */
export function Building({
  width,
  height,
  zones,
  blocked,
  oneWay = [],
  parkingAreas = [],
}: {
  width: number;
  height: number;
  zones: Zone[];
  blocked: [number, number][];
  oneWay?: { y: number; x_start: number; x_end: number; dir: "east" | "west" }[];
  parkingAreas?: ParkingAreaSnapshot[];
}) {
  const W = width + MARGIN * 2;
  const H = height + MARGIN * 2;
  const lampGroup = useRef<Group>(null);
  useFrame(({ camera }) => {
    if (lampGroup.current) lampGroup.current.visible = camera.position.y < 7;
  });

  const floor = useMemo(() => {
    const map = concreteTexture().clone();
    map.repeat.set(W / 6, H / 6);
    map.needsUpdate = true;
    const rough = concreteRoughness().clone();
    rough.repeat.set(W / 9, H / 9);
    rough.needsUpdate = true;
    return new MeshStandardMaterial({ map, roughnessMap: rough, roughness: 0.62, metalness: 0.02 });
  }, [W, H]);

  const wall = useMemo(() => {
    const mk = (len: number) => {
      const t = wallPanelTexture().clone();
      t.repeat.set(len / 1.0, 1);
      t.needsUpdate = true;
      return new MeshStandardMaterial({ map: t, roughness: 0.55, metalness: 0.3 });
    };
    return { long: mk(W), short: mk(H) };
  }, [W, H]);

  const zoneTape = useMemo(() => {
    const items: Placement[] = [];
    zones
      .filter((z) => !z.zone_id.startsWith("AISLE"))
      .forEach((z) => {
        const [x0, y0, x1, y1] = z.bounds;
        const w = x1 - x0 + 1;
        const h = y1 - y0 + 1;
        const cx = x0 + w / 2 - width / 2;
        const cz = y0 + h / 2 - height / 2;
        items.push(
          { p: [cx, 0.004, cz - h / 2], s: [w, TAPE, 1], r: [-Math.PI / 2, 0, 0] },
          { p: [cx, 0.004, cz + h / 2], s: [w, TAPE, 1], r: [-Math.PI / 2, 0, 0] },
          { p: [cx - w / 2, 0.004, cz], s: [TAPE, h, 1], r: [-Math.PI / 2, 0, 0] },
          { p: [cx + w / 2, 0.004, cz], s: [TAPE, h, 1], r: [-Math.PI / 2, 0, 0] },
        );
      });
    // Main aisle edge lines and dashed centre line.
    const aisle = zones.find((z) => z.zone_id.startsWith("AISLE"));
    if (aisle) {
      const [x0, , x1] = aisle.bounds;
      const left = x0 - width / 2;
      const right = x1 + 1 - width / 2;
      items.push(
        { p: [left, 0.004, 0], s: [TAPE, height, 1], r: [-Math.PI / 2, 0, 0] },
        { p: [right, 0.004, 0], s: [TAPE, height, 1], r: [-Math.PI / 2, 0, 0] },
      );
      for (let z = -height / 2 + 0.5; z < height / 2; z += 2) {
        items.push({ p: [(left + right) / 2, 0.004, z], s: [0.08, 1, 1], r: [-Math.PI / 2, 0, 0], c: "#ffffff" });
      }
    }
    return items;
  }, [zones, width, height]);

  // Painted direction arrows every 4 m along each one-way aisle segment.
  // Painted parking bays (one per cell) and a sign per parking area.
  const parking = useMemo(() => {
    const bays: Placement[] = [];
    const signs: Sign[] = [];
    for (const area of parkingAreas) {
      for (const [x, y] of area.cells) {
        const [wx, , wz] = gridToWorld(x, y, width, height);
        bays.push({ p: [wx, 0.005, wz], s: [0.94, 0.94, 1], r: [-Math.PI / 2, 0, 0] });
      }
      // Sign above the middle bay, facing into the building.
      const [mx, my] = area.cells[Math.floor(area.cells.length / 2)];
      const [wx, , wz] = gridToWorld(mx, my, width, height);
      const alongX = area.cells.every(([, y]) => y === my);
      const towardCentre = alongX ? (wz < 0 ? 0 : Math.PI) : wx < 0 ? Math.PI / 2 : -Math.PI / 2;
      signs.push({ text: `${area.area_id} PARKING`, p: [wx, 2.4, wz], rot: towardCentre });
    }
    return { bays, signs };
  }, [parkingAreas, width, height]);

  const arrows = useMemo(() => {
    const items: Placement[] = [];
    for (const seg of oneWay) {
      for (let x = seg.x_start + 1; x <= seg.x_end - 1; x += 4) {
        const [wx, , wz] = gridToWorld(x, seg.y, width, height);
        items.push({ p: [wx, 0.006, wz], s: [0.9, 0.55, 1], r: [-Math.PI / 2, 0, seg.dir === "east" ? 0 : Math.PI] });
      }
    }
    return items;
  }, [oneWay, width, height]);

  const zoneLabels = useMemo(
    () =>
      zones
        .filter((z) => !z.zone_id.startsWith("AISLE"))
        .map((z) => {
          const [x0, y0, x1] = z.bounds;
          const [x, , zz] = gridToWorld((x0 + x1) / 2, y0, width, height);
          return { id: z.zone_id, text: z.name.toUpperCase(), p: [x, 0.005, zz - 0.45] as [number, number, number] };
        }),
    [zones, width, height],
  );

  // Structural columns from the layout (portal-frame wall columns live in <Wall>).
  const columns = useMemo(() => {
    const interior = blocked
      .map(([x, y]) => gridToWorld(x, y, width, height))
      .map(([x, , z]) => [x, z] as [number, number]);
    return { interior };
  }, [blocked, width, height]);

  const geo = useMemo(
    () => ({
      box: new BoxGeometry(1, 1, 1),
      plane: new PlaneGeometry(1, 1),
      lamp: new CylinderGeometry(0.2, 0.27, 0.16, 24),
      cable: new CylinderGeometry(0.008, 0.008, 1, 4),
    }),
    [],
  );
  const mats = useMemo(
    () => ({
      tape: new MeshStandardMaterial({ color: "#f0b400", roughness: 0.5 }),
      parkingBay: new MeshStandardMaterial({ map: parkingBayTexture(), roughness: 0.6 }),
      arrow: new MeshStandardMaterial({ map: arrowTexture(), transparent: true, roughness: 0.55, depthWrite: false }),
      steel: new MeshStandardMaterial({ color: "#596570", metalness: 0.7, roughness: 0.4 }),
      guard: new MeshStandardMaterial({ map: hazardTexture(), roughness: 0.5 }),
      lamp: new MeshStandardMaterial({ color: "#c3c8ce", metalness: 0.8, roughness: 0.3 }),
      lampGlow: new MeshStandardMaterial({
        color: "#ffffff",
        emissive: "#fffaf0",
        emissiveIntensity: 3,
        toneMapped: false,
      }),
      cable: new MeshStandardMaterial({ color: "#222" }),
    }),
    [],
  );

  const steelParts = useMemo(() => {
    const items: Placement[] = [];
    const guards: Placement[] = [];
    const h = (x: number, z: number, tall: number) => {
      // H-section: two flanges + web.
      items.push({ p: [x, tall / 2, z - 0.14], s: [0.3, tall, 0.025] });
      items.push({ p: [x, tall / 2, z + 0.14], s: [0.3, tall, 0.025] });
      items.push({ p: [x, tall / 2, z], s: [0.02, tall, 0.28] });
    };
    columns.interior.forEach(([x, z]) => {
      h(x, z, WALL_H + 1);
      guards.push({ p: [x, 0.5, z], s: [0.55, 1.0, 0.55] });
    });
    return { items, guards };
  }, [columns]);

  // High-bay LED fixtures on a 6 x 5 m grid at 7.5 m.
  const lamps = useMemo(() => {
    const body: Placement[] = [];
    const glow: Placement[] = [];
    const cables: Placement[] = [];
    for (let x = -W / 2 + 4; x < W / 2 - 2; x += 6) {
      for (let z = -H / 2 + 3.5; z < H / 2 - 2; z += 5) {
        body.push({ p: [x, 7.5, z] });
        glow.push({ p: [x, 7.415, z], s: [0.46, 0.46, 1], r: [Math.PI / 2, 0, 0] });
        cables.push({ p: [x, 7.5 + 0.5, z] });
      }
    }
    return { body, glow, cables };
  }, [W, H]);

  // Dock doors on the north wall.
  const doors = useMemo(() => {
    const n = Math.max(3, Math.floor(width / 7));
    return Array.from({ length: n }, (_, i) => -width / 2 + (width / n) * (i + 0.5));
  }, [width]);

  const shutter = useMemo(() => {
    const t = shutterTexture().clone();
    t.repeat.set(1, 6);
    t.needsUpdate = true;
    return t;
  }, []);

  return (
    <group>
      {/* Concrete slab */}
      <mesh rotation-x={-Math.PI / 2} receiveShadow material={floor}>
        <planeGeometry args={[W, H]} />
      </mesh>

      {/* Painted markings */}
      <InstancedParts items={zoneTape} geometry={geo.plane} material={mats.tape} castShadow={false} />
      <InstancedParts items={arrows} geometry={geo.plane} material={mats.arrow} castShadow={false} />
      <InstancedParts items={parking.bays} geometry={geo.plane} material={mats.parkingBay} castShadow={false} />
      <SignBoards signs={parking.signs} w={1.6} h={0.4} />
      {zoneLabels.map((z) => (
        <mesh key={z.id} position={z.p} rotation-x={-Math.PI / 2}>
          <planeGeometry args={[3.2, 0.6]} />
          <meshStandardMaterial map={signTexture(z.text, "#00000000", "#e8e8e8")} transparent roughness={0.6} />
        </mesh>
      ))}

      {/* Walls (each with its portal columns and fittings); north wall carries the dock doors */}
      <Wall position={[0, 0, -H / 2]} rotation={0} length={W} material={wall.long} steel={mats.steel} box={geo.box}>
        {doors.map((x, i) => (
          <DockDoor key={i} x={x} index={i} shutter={shutter} />
        ))}
        {doors.slice(0, -1).map((x, i) => (
          <group key={`fire${i}`} position={[x + (doors[1] - doors[0]) / 2, 0, 0.01]}>
            <FirePoint />
          </group>
        ))}
      </Wall>
      <Wall
        position={[0, 0, H / 2]}
        rotation={Math.PI}
        length={W}
        material={wall.long}
        steel={mats.steel}
        box={geo.box}
      />
      <Wall
        position={[-W / 2, 0, 0]}
        rotation={Math.PI / 2}
        length={H}
        material={wall.short}
        steel={mats.steel}
        box={geo.box}
      />
      <Wall
        position={[W / 2, 0, 0]}
        rotation={-Math.PI / 2}
        length={H}
        material={wall.short}
        steel={mats.steel}
        box={geo.box}
      />

      {/* Steel structure */}
      <InstancedParts items={steelParts.items} geometry={geo.box} material={mats.steel} />
      <InstancedParts items={steelParts.guards} geometry={geo.box} material={mats.guard} />

      {/* High-bay lights (hidden when the camera is above them, i.e. where the roof would be) */}
      <group ref={lampGroup}>
        <InstancedParts items={lamps.body} geometry={geo.lamp} material={mats.lamp} castShadow={false} />
        <InstancedParts
          items={lamps.glow}
          geometry={geo.plane}
          material={mats.lampGlow}
          castShadow={false}
          receiveShadow={false}
        />
        <InstancedParts
          items={lamps.cables}
          geometry={geo.cable}
          material={mats.cable}
          castShadow={false}
          receiveShadow={false}
        />
      </group>
    </group>
  );
}

const _cam = new Vector3();
const _normal = new Vector3();

/**
 * One wall: concrete kerb, insulated panels and H-section portal columns every 6 m.
 * Local +Z points into the building; the whole wall hides while the camera is outside it.
 */
function Wall({
  position,
  rotation,
  length,
  material,
  steel,
  box,
  children,
}: {
  position: [number, number, number];
  rotation: number;
  length: number;
  material: Material;
  steel: Material;
  box: BoxGeometry;
  children?: React.ReactNode;
}) {
  const ref = useRef<Group>(null);
  useFrame(({ camera }) => {
    const g = ref.current;
    if (!g) return;
    _normal.set(Math.sin(rotation), 0, Math.cos(rotation));
    _cam.copy(camera.position).sub(g.position);
    g.visible = _cam.dot(_normal) > 0;
  });
  const columns = useMemo(() => {
    const items: Placement[] = [];
    for (let x = -length / 2 + 0.3; x <= length / 2; x += 6) {
      items.push({ p: [x - 0.14, WALL_H / 2, 0.16], s: [0.025, WALL_H, 0.3] });
      items.push({ p: [x + 0.14, WALL_H / 2, 0.16], s: [0.025, WALL_H, 0.3] });
      items.push({ p: [x, WALL_H / 2, 0.16], s: [0.28, WALL_H, 0.02] });
    }
    return items;
  }, [length]);
  return (
    <group ref={ref} position={position} rotation-y={rotation}>
      <mesh position={[0, WALL_H / 2, 0]} material={material} receiveShadow>
        <planeGeometry args={[length, WALL_H]} />
      </mesh>
      <mesh position={[0, 0.6, 0.002]} receiveShadow>
        <planeGeometry args={[length, 1.2]} />
        <meshStandardMaterial color="#9a9c9e" roughness={0.9} />
      </mesh>
      <InstancedParts items={columns} geometry={box} material={steel} />
      <StaticBatch>{children}</StaticBatch>
    </group>
  );
}

/** Roller-shutter dock door with frame guards, header box, rubber bumpers and dock leveller. */
function DockDoor({ x, index, shutter }: { x: number; index: number; shutter: Texture }) {
  return (
    <group position={[x, 0, 0.02]}>
      <mesh position={[0, 1.6, 0]}>
        <planeGeometry args={[3, 3.2]} />
        <meshStandardMaterial map={shutter} metalness={0.6} roughness={0.35} />
      </mesh>
      {[-1.6, 1.6].map((dx) => (
        <mesh key={dx} position={[dx, 1.7, 0.05]}>
          <boxGeometry args={[0.2, 3.4, 0.1]} />
          <meshStandardMaterial map={hazardTexture()} roughness={0.5} />
        </mesh>
      ))}
      <mesh position={[0, 3.45, 0.15]}>
        <boxGeometry args={[3.4, 0.35, 0.3]} />
        <meshStandardMaterial color="#47515b" metalness={0.6} roughness={0.4} />
      </mesh>
      {[-1.1, 1.1].map((dx) => (
        <mesh key={dx} position={[dx, 1.05, 0.08]}>
          <boxGeometry args={[0.25, 0.45, 0.14]} />
          <meshStandardMaterial color="#151515" roughness={0.9} />
        </mesh>
      ))}
      <mesh position={[0, 0.01, 0.9]} rotation-x={-Math.PI / 2} receiveShadow>
        <planeGeometry args={[2.6, 1.8]} />
        <meshStandardMaterial color="#4a5058" metalness={0.7} roughness={0.5} />
      </mesh>
      <mesh position={[0, 3.9, 0.02]}>
        <planeGeometry args={[1.2, 0.35]} />
        <meshStandardMaterial map={signTexture(`DOCK ${index + 1}`, "#1f2937")} />
      </mesh>
    </group>
  );
}
