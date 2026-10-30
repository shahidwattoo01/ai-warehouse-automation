"use client";

import { Environment, Lightformer, SoftShadows } from "@react-three/drei";
import { useFrame, useThree } from "@react-three/fiber";
import { Suspense, useEffect, useRef } from "react";
import type { QualitySettings } from "@/lib/quality";

/**
 * Indoor image-based lighting from light panels (no HDRI download needed): rows of high-bay
 * fixtures overhead and bright dock openings give metal and plastic believable reflections.
 * `width`/`depth` are the floor size in metres.
 */
function PanelEnvironment({ width, depth }: { width: number; depth: number }) {
  const xs = [-0.375, -0.225, -0.075, 0.075, 0.225, 0.375].map((f) => f * width);
  const zs = [-0.25, 0, 0.25].map((f) => f * depth);
  return (
    <Environment resolution={256} frames={1} background={false}>
      <color attach="background" args={["#2a2f36"]} />
      {xs.map((x) =>
        zs.map((z) => (
          <Lightformer
            key={`${x}:${z}`}
            form="rect"
            intensity={2.2}
            color="#fff6e8"
            position={[x, 9, z]}
            rotation-x={Math.PI / 2}
            scale={[4, 1.2, 1]}
          />
        )),
      )}
      <Lightformer
        form="rect"
        intensity={1.2}
        color="#dfe9f5"
        position={[0, 3, -depth / 2 - 5]}
        scale={[width, 4, 1]}
      />
      <Lightformer
        form="rect"
        intensity={0.5}
        color="#c9d3df"
        position={[-width / 2 - 5, 4, 0]}
        rotation-y={Math.PI / 2}
        scale={[depth, 5, 1]}
      />
      <Lightformer
        form="rect"
        intensity={0.5}
        color="#c9d3df"
        position={[width / 2 + 5, 4, 0]}
        rotation-y={-Math.PI / 2}
        scale={[depth, 5, 1]}
      />
    </Environment>
  );
}

/**
 * Static shadows for low-end GPUs: render the shadow map for a few frames after the scene loads,
 * then freeze it (racks don't move); robots then use blob shadows instead of casting.
 */
function ShadowUpdates({ dynamic, layoutKey }: { dynamic: boolean; layoutKey: string }) {
  const gl = useThree((s) => s.gl);
  const frames = useRef(0);
  useEffect(() => {
    gl.shadowMap.autoUpdate = dynamic;
    frames.current = 0;
  }, [gl, dynamic, layoutKey]);
  useFrame(() => {
    if (!dynamic && frames.current < 5) {
      gl.shadowMap.needsUpdate = true;
      frames.current++;
    }
  });
  return null;
}

/** All lights for the warehouse: environment panels, fill light and a shadow-casting key light. */
export function SceneLighting({
  width,
  depth,
  quality,
  layoutKey,
}: {
  width: number;
  depth: number;
  quality: QualitySettings;
  layoutKey: string;
}) {
  const k = Math.max(width, depth) / 40; // scale relative to the small 40 m layout
  const half = { x: width / 2 + 4, z: depth / 2 + 4 }; // shadow camera covers the floor plus walls
  return (
    <>
      <ShadowUpdates dynamic={quality.dynamicShadows} layoutKey={layoutKey} />
      {quality.softShadows && <SoftShadows size={18} samples={12} focus={0.6} />}
      <Suspense fallback={null}>
        <PanelEnvironment width={width + 20} depth={depth + 10} />
      </Suspense>
      <ambientLight intensity={0.15} />
      <hemisphereLight args={["#e9eef5", "#3a3631", 0.45]} />
      <directionalLight
        position={[14 * k, 28 * k, 10 * k]}
        intensity={1.9}
        color="#fff4e6"
        castShadow
        shadow-mapSize={[quality.shadowMapSize, quality.shadowMapSize]}
        shadow-camera-left={-half.x}
        shadow-camera-right={half.x}
        shadow-camera-top={half.z}
        shadow-camera-bottom={-half.z}
        shadow-camera-near={1}
        shadow-camera-far={90 * k}
        shadow-bias={-0.0003}
        shadow-normalBias={0.02}
      />
    </>
  );
}
