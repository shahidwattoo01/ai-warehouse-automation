"use client";

import { useLayoutEffect, useRef } from "react";
import {
  Color,
  Euler,
  type BufferGeometry,
  type InstancedMesh,
  type Material,
  Matrix4,
  Quaternion,
  Vector3,
} from "three";

export interface Placement {
  p: [number, number, number];
  s?: [number, number, number];
  r?: [number, number, number];
  c?: string;
}

const m = new Matrix4();
const q = new Quaternion();
const e = new Euler();
const pos = new Vector3();
const scl = new Vector3();
const col = new Color();

/**
 * One draw call for many copies of the same part. Placements are written straight into the
 * instance matrices (no per-instance React components), so thousands of rack parts stay cheap.
 */
export function InstancedParts({
  items,
  geometry,
  material,
  castShadow = true,
  receiveShadow = true,
}: {
  items: Placement[];
  geometry: BufferGeometry;
  material: Material;
  castShadow?: boolean;
  receiveShadow?: boolean;
}) {
  const ref = useRef<InstancedMesh>(null);

  useLayoutEffect(() => {
    const mesh = ref.current;
    if (!mesh) return;
    items.forEach((it, i) => {
      e.set(...(it.r ?? [0, 0, 0]));
      q.setFromEuler(e);
      pos.set(...it.p);
      scl.set(...(it.s ?? [1, 1, 1]));
      m.compose(pos, q, scl);
      mesh.setMatrixAt(i, m);
      if (it.c) mesh.setColorAt(i, col.set(it.c));
    });
    mesh.instanceMatrix.needsUpdate = true;
    if (mesh.instanceColor) mesh.instanceColor.needsUpdate = true;
    mesh.computeBoundingSphere();
  }, [items]);

  if (!items.length) return null;
  return (
    <instancedMesh
      key={items.length}
      ref={ref}
      args={[geometry, material, items.length]}
      castShadow={castShadow}
      receiveShadow={receiveShadow}
    />
  );
}
