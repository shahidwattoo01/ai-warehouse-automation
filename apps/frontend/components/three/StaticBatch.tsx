"use client";

import { type ReactNode, useLayoutEffect, useRef } from "react";
import { type BufferGeometry, type Group, type Material, Matrix4, Mesh, type Object3D } from "three";
import { mergeGeometries } from "three/examples/jsm/utils/BufferGeometryUtils.js";

/** Put `userData={{ noBatch: true }}` on a group whose meshes move (animated parts, people). */
const NO_BATCH = "noBatch";

function materialKey(m: Material): string {
  const a = m as Material & Record<string, unknown>;
  const hex = (v: unknown) =>
    v && typeof v === "object" && "getHexString" in v ? (v as { getHexString(): string }).getHexString() : "";
  const id = (v: unknown) => (v && typeof v === "object" && "uuid" in v ? (v as { uuid: string }).uuid : "");
  return [
    m.type,
    hex(a.color),
    hex(a.emissive),
    a.emissiveIntensity,
    a.roughness,
    a.metalness,
    a.clearcoat,
    id(a.map),
    id(a.emissiveMap),
    id(a.roughnessMap),
    m.transparent,
    m.opacity,
    m.side,
    a.toneMapped,
    a.alphaTest,
    m.depthWrite,
  ].join("|");
}

/**
 * Merges every static mesh below it that shares a material into one mesh (world transforms baked),
 * then hides the originals. A packing station built from ~70 JSX meshes becomes a handful of draw
 * calls, which is what integrated GPUs need. Children keep their normal JSX structure.
 */
export function StaticBatch({ children }: { children: ReactNode }) {
  const root = useRef<Group>(null);
  const out = useRef<Group>(null);

  useLayoutEffect(() => {
    const src = root.current;
    const dst = out.current;
    if (!src || !dst) return;
    src.updateWorldMatrix(true, true);
    const toLocal = new Matrix4().copy(src.matrixWorld).invert();
    const buckets = new Map<string, { material: Material; parts: BufferGeometry[]; cast: boolean; receive: boolean }>();
    const hidden: Mesh[] = [];

    const walk = (o: Object3D) => {
      if (o.userData?.[NO_BATCH]) return;
      const mesh = o as Mesh;
      if (mesh.isMesh && !(o as { isInstancedMesh?: boolean }).isInstancedMesh && !Array.isArray(mesh.material)) {
        const g = (mesh.geometry.index ? mesh.geometry.toNonIndexed() : mesh.geometry.clone()).applyMatrix4(
          new Matrix4().multiplyMatrices(toLocal, mesh.matrixWorld),
        );
        for (const name of Object.keys(g.attributes))
          if (!["position", "normal", "uv"].includes(name)) g.deleteAttribute(name);
        if (!g.attributes.uv || !g.attributes.normal) return; // unusual geometry: leave it as is
        const key = materialKey(mesh.material as Material);
        const b = buckets.get(key) ?? { material: mesh.material as Material, parts: [], cast: false, receive: false };
        b.parts.push(g);
        b.cast ||= mesh.castShadow;
        b.receive ||= mesh.receiveShadow;
        buckets.set(key, b);
        hidden.push(mesh);
      }
      o.children.forEach(walk);
    };
    src.children.forEach(walk);

    const made: Mesh[] = [];
    for (const b of buckets.values()) {
      const merged = mergeGeometries(b.parts, false);
      b.parts.forEach((p) => p.dispose());
      if (!merged) continue;
      const m = new Mesh(merged, b.material);
      m.castShadow = b.cast;
      m.receiveShadow = b.receive;
      dst.add(m);
      made.push(m);
    }
    // Only hide originals once their merged copy exists.
    hidden.forEach((h) => (h.visible = false));

    return () => {
      for (const m of made) {
        dst.remove(m);
        m.geometry.dispose();
      }
      hidden.forEach((h) => (h.visible = true));
    };
  }, []);

  return (
    <group>
      <group ref={root}>{children}</group>
      <group ref={out} />
    </group>
  );
}
