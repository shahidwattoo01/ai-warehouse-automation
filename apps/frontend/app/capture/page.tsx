"use client";

import dynamic from "next/dynamic";

const CaptureStudio = dynamic(() => import("@/components/three/CaptureStudio").then((m) => m.CaptureStudio), {
  ssr: false,
});

/** Camera-dataset harness, driven by scripts/capture_frames.py (not part of the operator UI). */
export default function CapturePage() {
  return <CaptureStudio />;
}
