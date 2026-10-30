"use client";

import { useCan } from "@/lib/auth";
import dynamic from "next/dynamic";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Screen } from "@/components/layout/Screen";
import { FEED_H, FEED_W, type FeedCamera } from "@/components/three/feed";
import { api } from "@/lib/api";
import { useSim } from "@/lib/store";
import type { DetectionResult, LayoutSnapshot, VisionStatus, WarehouseState } from "@/lib/types";

const CameraWall = dynamic(() => import("@/components/three/CameraFeed").then((m) => m.CameraWall), {
  ssr: false,
});
const CameraFeed = dynamic(() => import("@/components/three/CameraFeed").then((m) => m.CameraFeed), {
  ssr: false,
});

// Fixed cameras of the camera dataset (scripts/capture_frames.py): grid (x, y, height) -> look at (x, y).
const CCTV: [[number, number, number], [number, number]][] = [
  [[2.5, 4.5, 6.0], [18, 14]], [[37.0, 4.5, 6.0], [22, 14]], [[42.5, 4.5, 6.0], [58, 14]],
  [[77.0, 4.5, 6.0], [62, 14]], [[2.5, 42.0, 6.0], [18, 32]], [[37.0, 42.0, 6.0], [22, 32]],
  [[42.5, 42.0, 6.0], [58, 32]], [[77.0, 42.0, 6.0], [62, 32]], [[39.5, 1.5, 5.0], [39.5, 22]],
  [[39.5, 47.0, 5.0], [39.5, 26]], [[2.0, 22.5, 5.0], [30, 22.5]], [[78.0, 22.5, 5.0], [50, 22.5]],
  [[5.0, 45.0, 4.5], [30, 47.5]], [[75.0, 45.0, 4.5], [50, 47.5]], [[2.0, 2.0, 5.0], [25, 2]],
  [[78.0, 2.0, 5.0], [55, 2]],
]; // prettier-ignore

const CLASS_COLOR: Record<string, string> = {
  robot: "#2f6fe0",
  worker: "#e0182d",
  shelf: "#8a94a3",
  package: "#f08c00",
  obstacle: "#c2410c",
  blocked_path: "#b8008a",
};
const CLASS_LABEL: Record<string, string> = {
  robot: "Robot",
  worker: "Worker",
  shelf: "Shelf",
  package: "Dropped parcel",
  obstacle: "Obstacle (pallet)",
  blocked_path: "Closed-aisle barrier",
};

interface CameraOption {
  key: string;
  group: string;
  label: string;
  camera: FeedCamera;
}

function cameras(layout: LayoutSnapshot | null, state: WarehouseState | null): CameraOption[] {
  if (!layout) return [];
  const { width: w, height: h } = layout;
  const world = (x: number, y: number, z: number): [number, number, number] => [x - w / 2 + 0.5, z, y - h / 2 + 0.5];
  const out: CameraOption[] = [
    {
      key: "overview-above",
      group: "Whole warehouse",
      label: "Overview from above",
      camera: {
        kind: "fixed",
        position: world(w / 2, h / 2 + 22, 72),
        target: world(w / 2, h / 2, 0),
        fov: 62,
      },
    },
    {
      key: "overview-corner",
      group: "Whole warehouse",
      label: "Overview from the south-west corner",
      camera: {
        kind: "fixed",
        position: world(-4, h + 4, 26),
        target: world(w / 2, h / 2 - 4, 0),
        fov: 62,
      },
    },
  ];
  if (w >= 80 && h >= 48) {
    CCTV.forEach(([[x, y, z], [tx, ty]], i) =>
      out.push({ key: `cctv-${i}`, group: "Fixed CCTV", label: `CCTV ${i + 1}`,
                 camera: { kind: "fixed", position: world(x, y, z), target: world(tx, ty, 0.5), fov: 64 } }),
    ); // prettier-ignore
  }
  const shelves = new Set(layout.shelves.map((s) => `${s.x},${s.y}`));
  for (const o of state?.obstacles ?? []) {
    if (o.type !== "PACKAGE" && o.type !== "DEBRIS") continue;
    const [hx, hy] = o.position;
    for (let k = 0; k < 8; k++) {
      const a = (k * Math.PI) / 4;
      const x = hx + 5 * Math.cos(a);
      const y = hy + 5 * Math.sin(a);
      const cell = `${Math.round(x)},${Math.round(y)}`;
      if (x < 0 || y < 0 || x >= w || y >= h || shelves.has(cell)) continue;
      out.push({
        key: `hazard-${o.obstacle_id ?? `${hx},${hy}`}`,
        group: "Hazard cameras",
        label: `${o.type === "PACKAGE" ? "Dropped parcel" : "Fallen pallet"} at (${hx}, ${hy})`,
        camera: {
          kind: "fixed",
          position: world(x, y, 3.2),
          target: world(hx, hy, 0.2),
          fov: 55,
        },
      });
      break;
    }
  }
  for (const c of state?.closures ?? []) {
    const aisle = layout.aisles?.find((a) => a.aisle_id === c.aisle_id);
    if (!aisle) continue;
    out.push({
      key: `aisle-${c.aisle_id}`,
      group: "Closed aisles",
      label: `${aisle.name ?? c.aisle_id} (${c.reason})`,
      camera: {
        kind: "fixed",
        position: world(aisle.x_start - 2.5, aisle.y, 3.0),
        target: world(aisle.x_end, aisle.y, 0.8),
        fov: 65,
      },
    });
  }
  for (const r of state?.robots ?? []) {
    out.push({ key: `robot-${r.robot_id}`, group: "Robot cameras", label: `${r.robot_id} forward camera`,
               camera: { kind: "robot", robotId: r.robot_id, fov: 78 } }); // prettier-ignore
  }
  return out;
}

/** Detection boxes and labels over an analysed frame (scales with it: SVG in image pixels). */
function Boxes({
  result,
  showShelves = false,
  labels = true,
}: {
  result: DetectionResult;
  showShelves?: boolean;
  labels?: boolean;
}) {
  return (
    <svg
      viewBox={`0 0 ${result.width} ${result.height}`}
      className="pointer-events-none absolute inset-0 h-full w-full"
    >
      {result.detections
        .filter((d) => showShelves || d.cls !== "shelf")
        .map((d, i) => {
          const [x1, y1, x2, y2] = d.box;
          const color = CLASS_COLOR[d.cls] ?? "#fff";
          const tag = `${CLASS_LABEL[d.cls] ?? d.cls} ${Math.round(d.conf * 100)}%`;
          const tagW = tag.length * 5.6 + 6;
          const tagY = y1 >= 14 ? y1 - 13 : y2; // above the box, or below it at the top edge
          return (
            <g key={i}>
              <rect
                x={x1}
                y={y1}
                width={x2 - x1}
                height={y2 - y1}
                fill="none"
                stroke={color}
                strokeWidth={d.safety ? 2.5 : 1.5}
              />
              {labels && d.cls !== "shelf" && (
                <>
                  <rect x={x1} y={tagY} width={tagW} height={13} rx={2} fill={color} opacity={0.9} />
                  <text x={x1 + 3} y={tagY + 10} fontSize={10} fill="white" fontWeight={600}>
                    {tag}
                  </text>
                </>
              )}
            </g>
          );
        })}
    </svg>
  );
}

const PLURAL: Record<string, string> = {
  worker: "Workers",
  package: "Dropped parcels",
  obstacle: "Obstacles (pallets)",
  blocked_path: "Closed-aisle barriers",
};

/** "2 workers · 1 dropped parcel" for the safety classes found in one frame. */
function safetySummary(result: DetectionResult): string {
  const parts = ["worker", "package", "obstacle", "blocked_path"]
    .filter((c) => result.counts[c])
    .map((c) => `${result.counts[c]} ${(result.counts[c] > 1 ? PLURAL[c] : CLASS_LABEL[c]).toLowerCase()}`);
  return parts.join(" · ");
}

interface WallDetection {
  result: DetectionResult;
  image: string; // the exact frame that was analysed (boxes are drawn on it)
  at: number; // Date.now() when it was analysed
  shotAt: number; // when that frame was photographed
}

export default function VisionPage() {
  const canDetect = useCan("vision:use");
  const layout = useSim((s) => s.layout);
  const state = useSim((s) => s.state);
  // Re-list cameras only when the set of hazards, closures or robots changes, not every tick.
  const signature = [
    layout?.name,
    state?.obstacles.map((o) => o.obstacle_id ?? o.position.join(",")).join("|"),
    state?.closures?.map((c) => c.aisle_id).join("|"),
    state?.robots.length,
  ].join("/");
  const options = useMemo(() => cameras(layout, state), [signature]); // eslint-disable-line react-hooks/exhaustive-deps

  const [selected, setSelected] = useState("cctv-0");
  const option = options.find((o) => o.key === selected) ?? options[0];
  const [status, setStatus] = useState<VisionStatus | null>(null);
  const [result, setResult] = useState<DetectionResult | null>(null);
  const [frame, setFrame] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [auto, setAuto] = useState(false);
  const [showShelves, setShowShelves] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const capture = useRef<(() => string) | null>(null);
  const onCapture = useCallback((fn: () => string) => {
    capture.current = fn;
  }, []);

  useEffect(() => {
    // Also starts loading the model on the server, so the first detection is quick.
    api.vision
      .status()
      .then(setStatus)
      .catch((e: Error) => setError(e.message));
  }, []);

  const detect = useCallback(async () => {
    if (!capture.current || busy) return;
    setBusy(true);
    setError(null);
    const image = capture.current();
    try {
      const res = await api.vision.detect(image);
      setFrame(image);
      setResult(res);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }, [busy]);

  useEffect(() => {
    if (!auto) return;
    const id = setInterval(() => void detect(), 3000);
    return () => clearInterval(id);
  }, [auto, detect]);

  const groups = [...new Set(options.map((o) => o.group))];

  // Camera wall: thumbnails of many cameras, photographed in turn by one renderer.
  const [view, setView] = useState<"single" | "wall">("single");
  const [wallGroup, setWallGroup] = useState<string>("All");
  const [shots, setShots] = useState<Record<string, string>>({});
  const shotAt = useRef<Record<string, number>>({});
  const onShot = useCallback((key: string, image: string) => {
    shotAt.current[key] = Date.now();
    setShots((s) => ({ ...s, [key]: image }));
  }, []);
  const wallCameras = options.filter((o) => wallGroup === "All" || o.group === wallGroup);
  const openCamera = (key: string) => {
    setSelected(key);
    setView("single");
  };

  // Detection on the wall: per camera, or all cameras one after another, results shown in place.
  const [wallDet, setWallDet] = useState<Record<string, WallDetection>>({});
  const [detecting, setDetecting] = useState<string | null>(null); // camera being analysed
  const [scanning, setScanning] = useState(false);
  const [keepScanning, setKeepScanning] = useState(false);
  const [showBoxes, setShowBoxes] = useState(true);
  const [progress, setProgress] = useState<{ done: number; total: number } | null>(null);
  const shotsRef = useRef(shots);
  shotsRef.current = shots;
  const wallKeys = useRef<string[]>([]);
  wallKeys.current = wallCameras.map((o) => o.key);
  const keepRef = useRef(keepScanning);
  keepRef.current = keepScanning;

  const detectCamera = useCallback(async (key: string) => {
    const image = shotsRef.current[key];
    if (!image) return;
    const taken = shotAt.current[key] ?? Date.now();
    setDetecting(key);
    try {
      const res = await api.vision.detect(image);
      setWallDet((d) => ({ ...d, [key]: { result: res, image, at: Date.now(), shotAt: taken } }));
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setDetecting(null);
    }
  }, []);

  useEffect(() => {
    if (!scanning) return;
    let cancelled = false;
    (async () => {
      do {
        const keys = [...wallKeys.current];
        for (let i = 0; i < keys.length && !cancelled; i++) {
          setProgress({ done: i, total: keys.length });
          await detectCamera(keys[i]);
        }
        if (!cancelled) setProgress({ done: keys.length, total: keys.length });
      } while (!cancelled && keepRef.current);
      if (!cancelled) setScanning(false);
    })();
    return () => {
      cancelled = true;
    };
  }, [scanning, detectCamera]);

  // Live detection for moving robots: keep analysing the cameras of robots that are driving, each
  // as soon as it has a newer photo than its last detection, the least recently analysed first.
  // Parked or idle robots are skipped (their view does not change).
  const [autoRobots, setAutoRobots] = useState(true);
  const moving = new Set((state?.robots ?? []).filter((r) => r.route.length > 0).map((r) => r.robot_id));
  const movingRef = useRef(moving);
  movingRef.current = moving;
  const wallDetRef = useRef(wallDet);
  wallDetRef.current = wallDet;
  const movingOnWall = wallCameras.filter((o) => o.camera.kind === "robot" && moving.has(o.camera.robotId)).length;

  useEffect(() => {
    if (view !== "wall" || !autoRobots || scanning) return;
    let cancelled = false;
    (async () => {
      while (!cancelled) {
        const due = wallKeys.current
          .filter((k) => k.startsWith("robot-") && movingRef.current.has(k.slice(6)))
          .filter((k) => (shotAt.current[k] ?? 0) > (wallDetRef.current[k]?.shotAt ?? 0))
          .sort((a, b) => (wallDetRef.current[a]?.at ?? 0) - (wallDetRef.current[b]?.at ?? 0));
        if (due.length) await detectCamera(due[0]);
        else await new Promise((r) => setTimeout(r, 1000));
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [view, autoRobots, scanning, detectCamera]);

  // Single view: a robot camera keeps being analysed while the robot drives.
  useEffect(() => {
    if (option?.camera.kind === "robot") setAuto(true);
  }, [option?.key]); // eslint-disable-line react-hooks/exhaustive-deps

  // Safety summary over the cameras on the wall: how many cameras see each hazard class.
  const wallAlerts = ["worker", "package", "obstacle", "blocked_path"].map((c) => ({
    cls: c,
    cameras: wallCameras.filter((o) => (wallDet[o.key]?.result.counts[c] ?? 0) > 0).length,
  }));
  const analysed = wallCameras.filter((o) => wallDet[o.key]).length;

  return (
    <Screen title="Vision · object detection on the live warehouse">
      <div className="mb-4 flex flex-wrap items-center gap-3">
        <div className="flex overflow-hidden rounded-control border border-border text-sm" role="tablist">
          {(["single", "wall"] as const).map((v) => (
            <button
              key={v}
              role="tab"
              aria-selected={view === v}
              onClick={() => setView(v)}
              className={`px-3 py-1.5 ${view === v ? "bg-accent text-white" : "bg-surface text-muted hover:text-ink"}`}
            >
              {v === "single" ? "Single camera + detection" : `Camera wall (${options.length})`}
            </button>
          ))}
        </div>
        {view === "wall" && (
          <div className="flex flex-wrap gap-1.5 text-xs">
            {["All", ...groups].map((g) => (
              <button
                key={g}
                onClick={() => setWallGroup(g)}
                className={`rounded-full border px-2.5 py-1 ${
                  wallGroup === g ? "border-accent bg-accent/10 text-ink" : "border-border text-muted hover:text-ink"
                }`}
              >
                {g} ({g === "All" ? options.length : options.filter((o) => o.group === g).length})
              </button>
            ))}
          </div>
        )}
      </div>

      {view === "wall" && (
        <>
          <CameraWall cameras={wallCameras} intervalMs={3000} onShot={onShot} />
          <div className="mb-3 flex flex-wrap items-center gap-3 rounded-card border border-border bg-surface p-3 text-xs">
            <button
              onClick={() => setScanning((s) => !s)}
              disabled={!status?.available || !canDetect}
              className={`rounded-control px-3 py-1.5 font-medium text-white disabled:opacity-50 ${
                scanning ? "bg-danger" : "bg-accent"
              }`}
            >
              {scanning ? "Stop" : `Detect all ${wallCameras.length} cameras`}
            </button>
            <label className="flex items-center gap-1 text-muted">
              <input type="checkbox" checked={keepScanning} onChange={(e) => setKeepScanning(e.target.checked)} />
              Keep scanning
            </label>
            <label className="flex items-center gap-1 text-muted">
              <input type="checkbox" checked={showBoxes} onChange={(e) => setShowBoxes(e.target.checked)} />
              Show detections on the cameras
            </label>
            <label
              className="flex items-center gap-1 text-muted"
              title="Robots that are driving are analysed again and again, each time their camera has a new photo"
            >
              <input type="checkbox" checked={autoRobots} onChange={(e) => setAutoRobots(e.target.checked)} />
              Live detection for moving robots
              {autoRobots && (
                <span className={movingOnWall ? "text-success" : ""}>
                  ({scanning ? "paused while scanning" : `${movingOnWall} moving on this wall`})
                </span>
              )}
            </label>
            {progress && (
              <span className="flex items-center gap-2 text-muted">
                <span className="h-1.5 w-32 overflow-hidden rounded bg-border">
                  <span
                    className="block h-full bg-accent transition-all"
                    style={{ width: `${(progress.done / Math.max(progress.total, 1)) * 100}%` }}
                  />
                </span>
                {scanning ? `Scanning ${progress.done + 1} / ${progress.total}` : `Scanned ${progress.done} cameras`}
              </span>
            )}
            <span className="ml-auto text-muted">
              {analysed} / {wallCameras.length} analysed ·{" "}
              {wallAlerts.map((a) => (
                <span key={a.cls} className="ml-2" style={{ color: a.cameras ? CLASS_COLOR[a.cls] : undefined }}>
                  {CLASS_LABEL[a.cls]}: {a.cameras} {a.cameras === 1 ? "camera" : "cameras"}
                </span>
              ))}
            </span>
          </div>
          <p className="mb-3 text-xs text-muted">
            Cameras refresh every few seconds (one renderer photographs them in turn, so the laptop stays responsive). A
            camera with detections shows the frame that was analysed, with its age; detection takes about 1 s per camera
            on an idle laptop, longer when the CPU is busy.
          </p>
          <div className="grid grid-cols-2 gap-3 md:grid-cols-3 xl:grid-cols-4 2xl:grid-cols-6">
            {wallCameras.map((o) => {
              const det = wallDet[o.key];
              const withBoxes = showBoxes && det;
              const alerts = det ? safetySummary(det.result) : "";
              const image = withBoxes ? det.image : shots[o.key];
              return (
                <div
                  key={o.key}
                  className={`overflow-hidden rounded-card border bg-surface ${
                    detecting === o.key ? "border-accent" : alerts ? "border-danger/60" : "border-border"
                  }`}
                >
                  <div className="relative aspect-[4/3] w-full bg-black">
                    {image ? (
                      // eslint-disable-next-line @next/next/no-img-element
                      <img src={image} alt={o.label} className="h-full w-full" />
                    ) : (
                      <div className="flex h-full items-center justify-center text-[11px] text-white/60">
                        Connecting…
                      </div>
                    )}
                    {withBoxes && <Boxes result={det.result} labels={false} />}
                    {withBoxes && (
                      <span className="absolute right-1 top-1 rounded bg-black/60 px-1.5 py-0.5 text-[10px] text-white">
                        analysed {Math.max(0, Math.round((Date.now() - det.at) / 1000))} s ago
                      </span>
                    )}
                    {detecting === o.key && (
                      <span className="absolute inset-0 flex items-center justify-center bg-black/30 text-xs font-medium text-white">
                        Detecting…
                      </span>
                    )}
                  </div>
                  <div className="px-2 py-1.5 text-xs">
                    <div className="flex items-center justify-between gap-2">
                      <span className="truncate font-medium">{o.label}</span>
                      <span className="flex shrink-0 gap-1">
                        <button
                          onClick={() => void detectCamera(o.key)}
                          disabled={!shots[o.key] || detecting === o.key || !status?.available || !canDetect}
                          className="rounded-control border border-border px-1.5 py-0.5 hover:border-accent hover:text-accent disabled:opacity-40"
                          title="Run the detector on this camera"
                        >
                          Detect
                        </button>
                        <button
                          onClick={() => openCamera(o.key)}
                          className="rounded-control border border-border px-1.5 py-0.5 text-muted hover:border-accent hover:text-accent"
                          title="Open this camera large"
                        >
                          Open
                        </button>
                      </span>
                    </div>
                    <div className="mt-0.5 truncate text-[11px]">
                      {det ? (
                        alerts ? (
                          <span className="text-danger">⚠ {alerts}</span>
                        ) : (
                          <span className="text-success">
                            ✓ No hazards · {det.result.counts.robot ?? 0}{" "}
                            {det.result.counts.robot === 1 ? "robot" : "robots"} in view
                          </span>
                        )
                      ) : (
                        <span className="text-muted">{o.group}</span>
                      )}
                    </div>
                  </div>
                </div>
              );
            })}
          </div>
        </>
      )}

      {view === "single" && (
        <>
          <div className="grid gap-4 lg:grid-cols-2">
            <section className="min-w-0 rounded-card border border-border bg-surface p-3">
              <div className="mb-2 flex flex-wrap items-center gap-2 text-xs">
                <label className="flex items-center gap-2 text-muted">
                  Camera
                  <select
                    value={option?.key ?? ""}
                    onChange={(e) => setSelected(e.target.value)}
                    className="rounded-control border border-border bg-canvas px-2 py-1 text-ink"
                    aria-label="Camera"
                  >
                    {groups.map((g) => (
                      <optgroup key={g} label={g}>
                        {options
                          .filter((o) => o.group === g)
                          .map((o) => (
                            <option key={o.key} value={o.key}>
                              {o.label}
                            </option>
                          ))}
                      </optgroup>
                    ))}
                  </select>
                </label>
                <button
                  onClick={() => void detect()}
                  disabled={busy || !status?.available || !canDetect}
                  className="rounded-control bg-accent px-3 py-1 font-medium text-white disabled:opacity-50"
                >
                  {busy ? "Detecting…" : "Detect now"}
                </button>
                <label className="flex items-center gap-1 text-muted">
                  <input type="checkbox" checked={auto} onChange={(e) => setAuto(e.target.checked)} />
                  Auto (every 3 s)
                </label>
              </div>
              <div className="aspect-[4/3] w-full overflow-hidden rounded-control bg-black">
                {option && <CameraFeed camera={option.camera} onCapture={onCapture} />}
              </div>
              <p className="mt-1 text-[11px] text-muted">
                Live view · sent to the detector as a {FEED_W} × {FEED_H} frame, rendered like its training images
              </p>
            </section>

            <section className="min-w-0 rounded-card border border-border bg-surface p-3">
              <div className="mb-2 flex h-[26px] items-center justify-between text-xs">
                <span className="text-muted">Last analysed frame</span>
                <label className="flex items-center gap-1 text-muted">
                  <input type="checkbox" checked={showShelves} onChange={(e) => setShowShelves(e.target.checked)} />
                  Show shelves
                </label>
              </div>
              <div className="relative aspect-[4/3] w-full overflow-hidden rounded-control bg-canvas">
                {frame ? (
                  // eslint-disable-next-line @next/next/no-img-element
                  <img src={frame} alt="Analysed camera frame" className="h-full w-full" />
                ) : (
                  <div className="flex h-full items-center justify-center text-sm text-muted">
                    {status?.available === false ? "No detector trained yet" : "Press “Detect now”"}
                  </div>
                )}
                {frame && result && <Boxes result={result} showShelves={showShelves} />}
              </div>
              <p className="mt-1 text-[11px] text-muted">
                {result
                  ? `${result.detections.length} objects · model time ${(result.inference_ms / 1000).toFixed(1)} s on the server CPU`
                  : " "}
              </p>
            </section>
          </div>

          <div className="mt-4 grid gap-4 md:grid-cols-3">
            <div className="rounded-card border border-border bg-surface p-4">
              <div className="mb-2 text-xs font-semibold uppercase tracking-wide text-muted">Safety alerts</div>
              {!result ? (
                <p className="text-sm text-muted">No frame analysed yet.</p>
              ) : result.safety_alerts.length === 0 ? (
                <p className="text-sm text-success">No workers, dropped parcels, obstacles or barriers in view.</p>
              ) : (
                <ul className="space-y-1.5">
                  {result.safety_alerts.map((d, i) => (
                    <li key={i} className="flex items-center justify-between gap-3 text-sm">
                      <span style={{ color: CLASS_COLOR[d.cls] }} className="font-medium">
                        ⚠ {CLASS_LABEL[d.cls]}
                      </span>
                      <span className="flex items-center gap-2">
                        <span className="h-1.5 w-16 overflow-hidden rounded bg-border">
                          <span
                            className="block h-full"
                            style={{
                              width: `${d.conf * 100}%`,
                              background: CLASS_COLOR[d.cls],
                            }}
                          />
                        </span>
                        <span className="tabular w-10 text-right text-muted">{Math.round(d.conf * 100)}%</span>
                      </span>
                    </li>
                  ))}
                </ul>
              )}
              <p className="mt-3 border-t border-border pt-2 text-[11px] leading-relaxed text-muted">
                The percentage is the detector&apos;s <b>confidence</b> that the box holds that object, not an accuracy.
                Low values (e.g. 19 %) are usually distant or partly hidden objects: safety classes are reported from a
                low confidence on purpose, so that a possible person is not missed.
              </p>
            </div>

            <div className="rounded-card border border-border bg-surface p-4">
              <div className="mb-2 text-xs font-semibold uppercase tracking-wide text-muted">Objects in this frame</div>
              <table className="w-full text-sm">
                <thead>
                  <tr className="text-[11px] text-muted">
                    <th className="pb-1 text-left font-normal">Class</th>
                    <th className="pb-1 text-right font-normal">Found</th>
                    <th className="pb-1 text-right font-normal">Shown from</th>
                  </tr>
                </thead>
                <tbody>
                  {Object.keys(CLASS_LABEL).map((c) => (
                    <tr key={c}>
                      <td className="py-0.5">
                        <span
                          className="mr-2 inline-block h-2 w-2 rounded-full"
                          style={{ background: CLASS_COLOR[c] }}
                        />
                        {CLASS_LABEL[c]}
                      </td>
                      <td className="tabular text-right">{result?.counts[c] ?? 0}</td>
                      <td className="tabular text-right text-muted">
                        {status?.thresholds[c] !== undefined
                          ? `${Math.round(status.thresholds[c] * 100)}% confidence`
                          : ""}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>

            <div className="rounded-card border border-border bg-surface p-4 text-sm">
              <div className="mb-2 text-xs font-semibold uppercase tracking-wide text-muted">Model</div>
              {status ? (
                <div className="space-y-1.5">
                  <div className="font-medium">{status.algorithm ?? status.model}</div>
                  <div className="text-muted">
                    Test images ({status.image_size} px): mAP@0.5 {status.test.mAP50?.toFixed(3) ?? "—"}, precision{" "}
                    {status.test.precision?.toFixed(3) ?? "—"}, recall {status.test.recall?.toFixed(3) ?? "—"}
                  </div>
                  {status.test_960_gpu && (
                    <div className="text-muted">At 960 px on a GPU: mAP@0.5 {status.test_960_gpu.mAP50.toFixed(3)}</div>
                  )}
                  <div className={status.loaded ? "text-success" : "text-warning"}>
                    {status.loaded ? "● Model loaded" : "● Model loading on the server…"}
                  </div>
                </div>
              ) : (
                <p className="text-muted">Connecting…</p>
              )}
              {error && (
                <p className="mt-2 rounded-control border border-danger/40 bg-danger/10 p-2 text-xs text-danger">
                  {error}
                </p>
              )}
            </div>
          </div>
        </>
      )}
    </Screen>
  );
}
