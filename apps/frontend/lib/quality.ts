"use client";

// Graphics quality presets for the 3D scene. The large layout has ~100k rack parts, so a laptop
// with integrated graphics needs lighter settings than a gaming GPU. The level is chosen from the
// GPU name on first visit, can be changed in the UI, and is remembered per browser.

export type Quality = "high" | "balanced" | "low";

export interface QualitySettings {
  softShadows: boolean; // PCSS soft shadows (expensive per pixel)
  ambientOcclusion: boolean; // N8AO post effect
  bloom: boolean; // glow on LEDs
  postAA: boolean; // SMAA via the effect composer (otherwise native MSAA)
  shadowMapSize: number;
  dynamicShadows: boolean; // false: static shadows rendered once; robots use blob shadows instead
  maxDpr: number;
  rackDetail: "full" | "lite"; // lite drops shrink-wrap, barcode labels, diagonal bracing, base plates
}

export const QUALITY: Record<Quality, QualitySettings> = {
  high: {
    softShadows: true,
    ambientOcclusion: true,
    bloom: true,
    postAA: true,
    shadowMapSize: 4096,
    dynamicShadows: true,
    maxDpr: 1.75,
    rackDetail: "full",
  },
  balanced: {
    softShadows: false,
    ambientOcclusion: false,
    bloom: true,
    postAA: true,
    shadowMapSize: 2048,
    dynamicShadows: true,
    maxDpr: 1,
    rackDetail: "full",
  },
  low: {
    softShadows: false,
    ambientOcclusion: false,
    bloom: false,
    postAA: false,
    shadowMapSize: 2048,
    dynamicShadows: false,
    maxDpr: 1,
    rackDetail: "lite",
  },
};

const KEY = "warehouse.quality";

/** Integrated / mobile GPUs start on "low"; everything else on "high". */
function detect(): Quality {
  try {
    const gl = document.createElement("canvas").getContext("webgl2");
    const info = gl?.getExtension("WEBGL_debug_renderer_info");
    const name = info ? String(gl!.getParameter(info.UNMASKED_RENDERER_WEBGL)) : "";
    if (/intel|uhd|iris|mali|adreno|powervr|swiftshader|llvmpipe/i.test(name)) return "low";
  } catch {
    // fall through
  }
  return "high";
}

export function initialQuality(): Quality {
  if (typeof window === "undefined") return "balanced";
  const fromUrl = new URLSearchParams(window.location.search).get("quality");
  if (fromUrl === "high" || fromUrl === "balanced" || fromUrl === "low") return fromUrl;
  try {
    const saved = window.localStorage.getItem(KEY);
    if (saved === "high" || saved === "balanced" || saved === "low") return saved;
  } catch {
    // storage blocked: use detection
  }
  return detect();
}

export function saveQuality(q: Quality) {
  try {
    window.localStorage.setItem(KEY, q);
  } catch {
    // storage blocked: setting lasts for this page only
  }
}
