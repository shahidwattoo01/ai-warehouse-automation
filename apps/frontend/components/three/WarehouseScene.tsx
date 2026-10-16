"use client";

import { AdaptiveDpr, PerspectiveCamera } from "@react-three/drei";
import { Canvas } from "@react-three/fiber";
import { Bloom, EffectComposer, N8AO, SMAA, Vignette } from "@react-three/postprocessing";
import { Maximize, Minimize } from "lucide-react";
import type { ReactElement } from "react";
import { ACESFilmicToneMapping, SRGBColorSpace } from "three";
import { QUALITY, type Quality } from "@/lib/quality";
import { useSim } from "@/lib/store";
import { useTheme } from "@/lib/theme";
import { useFullscreen } from "@/lib/useFullscreen";
import { Building } from "./Building";
import { FollowCamera } from "./FollowCamera";
import { Hazards } from "./Hazards";
import { Props } from "./Props";
import { Racking } from "./Racking";
import { RobotFleet } from "./RobotFleet";
import { SceneLighting } from "./SceneLighting";
import { Stations } from "./Stations";
import { useCameraView, VIEW_LABEL, ViewControls, type ViewName } from "./ViewControls";
import { WorkerLayer } from "./Worker";

const QUALITY_LABEL: Record<Quality, string> = { high: "High", balanced: "Balanced", low: "Fast" };

/**
 * Realistic 3D warehouse view driven by the live simulator stream (ADR 001): building, racking,
 * stations, props, the robot fleet and workers, lit by SceneLighting. Camera, fog and shadows scale
 * with the floor size; graphics quality is chosen per GPU (lib/quality.ts).
 */
export function WarehouseScene({ compact = false }: { compact?: boolean }) {
  const layout = useSim((s) => s.layout);
  const quality = useSim((s) => s.quality);
  const setQuality = useSim((s) => s.setQuality);
  const fullscreen = useFullscreen<HTMLDivElement>();
  const goToView = useCameraView((s) => s.go);

  const width = layout?.width ?? 40;
  const depth = layout?.height ?? 28;
  const k = Math.max(width, depth) / 40; // scale relative to the small 40 m layout
  const sceneBg = useTheme((s) => s.theme) === "dark" ? "#050506" : "#e7e4dd";
  const q = QUALITY[quality];
  const effects = [
    q.ambientOcclusion && <N8AO key="ao" halfRes aoRadius={1.2} intensity={2.2} distanceFalloff={0.8} />,
    q.bloom && <Bloom key="bloom" mipmapBlur luminanceThreshold={1.0} intensity={0.55} />,
    q.postAA && <SMAA key="smaa" />,
    q.bloom && <Vignette key="vignette" eskil={false} offset={0.2} darkness={0.45} />,
  ].filter(Boolean) as ReactElement[];

  return (
    <div
      ref={fullscreen.ref}
      className={fullscreen.windowed ? "fixed inset-0 z-50 bg-canvas" : "relative h-full w-full bg-canvas"}
    >
      <Canvas
        key={quality} // antialias and shadow settings are fixed when the WebGL context is created
        shadows
        onPointerMissed={() => useSim.getState().selectRobot(null)}
        dpr={[1, q.maxDpr]}
        gl={{
          antialias: effects.length === 0, // with post effects, SMAA does the antialiasing
          toneMapping: ACESFilmicToneMapping,
          toneMappingExposure: 1.05,
          outputColorSpace: SRGBColorSpace,
          powerPreference: "high-performance",
        }}
        className="rounded-card"
      >
        <color attach="background" args={[sceneBg]} />
        <fog attach="fog" args={[sceneBg, 90 * k, 180 * k]} />
        <PerspectiveCamera
          makeDefault
          position={compact ? [0, 30 * k, 30 * k] : [-18 * k, 16 * k, 24 * k]}
          fov={compact ? 45 : 42}
          near={0.1}
          far={250 * k}
        />
        <ViewControls width={width} depth={depth} compact={compact} />
        <FollowCamera />
        <AdaptiveDpr pixelated />
        <SceneLighting width={width} depth={depth} quality={q} layoutKey={layout?.name ?? ""} />

        {layout && (
          <>
            <Building width={width} height={depth} zones={layout.zones} blocked={layout.blocked} oneWay={layout.one_way ?? []}
              parkingAreas={layout.parking_areas ?? []}
            />
            <Racking shelves={layout.shelves} width={width} height={depth} detail={q.rackDetail} />
            <Stations stations={layout.stations} width={width} height={depth} />
            <Props width={width} height={depth} />
            <RobotFleet width={width} height={depth} castShadows={q.dynamicShadows} />
            <WorkerLayer width={width} height={depth} />
            <Hazards width={width} height={depth} />
          </>
        )}

        {effects.length > 0 && <EffectComposer multisampling={0}>{effects}</EffectComposer>}
      </Canvas>

      <div className="absolute left-3 top-3 flex flex-col items-start gap-1.5">
        <div className="flex overflow-hidden rounded-control border border-border bg-surface/90 text-xs" role="group" aria-label="Camera views">
          {(Object.keys(VIEW_LABEL) as ViewName[]).map((view) => (
            <button
              key={view}
              onClick={() => goToView(view)}
              title={`Camera: ${VIEW_LABEL[view]} view`}
              className="border-l border-border px-2 py-1 text-muted first:border-l-0 hover:bg-canvas hover:text-ink"
            >
              {VIEW_LABEL[view]}
            </button>
          ))}
        </div>
        {!compact && (
          <p className="rounded-control bg-surface/80 px-2 py-1 text-[11px] text-muted">
            Drag: rotate 360° · Right-drag / Shift+drag: move · Scroll: zoom to cursor · Double-click: fly there
          </p>
        )}
      </div>

      <button
        onClick={fullscreen.toggle}
        title={fullscreen.isFull ? "Exit full screen (f)" : "Full screen (f)"}
        aria-label={fullscreen.isFull ? "Exit full screen" : "Full screen"}
        className="absolute bottom-3 right-3 rounded-control border border-border bg-surface/90 p-1.5 text-muted hover:text-ink"
      >
        {fullscreen.isFull ? <Minimize size={16} /> : <Maximize size={16} />}
      </button>
      <label className="absolute bottom-3 left-3 flex items-center gap-2 rounded-control border border-border bg-surface/90 px-2 py-1 text-xs text-muted">
        Graphics
        <select
          value={quality}
          onChange={(e) => setQuality(e.target.value as Quality)}
          className="bg-transparent text-ink outline-none"
          aria-label="Graphics quality"
        >
          {(Object.keys(QUALITY_LABEL) as Quality[]).map((level) => (
            <option key={level} value={level} className="bg-surface">
              {QUALITY_LABEL[level]}
            </option>
          ))}
        </select>
      </label>
    </div>
  );
}
