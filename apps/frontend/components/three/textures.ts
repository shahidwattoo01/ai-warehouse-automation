"use client";

// Procedural PBR textures drawn on canvas, so the scene looks real with no downloaded assets.
// Each texture is created once and cached; swap any of them for photo-scanned maps later.

import { CanvasTexture, RepeatWrapping, SRGBColorSpace, type Texture } from "three";

const cache = new Map<string, Texture>();

/** Draw a canvas texture once and cache it. `height` defaults to `size` (square). */
function make(
  key: string,
  size: number,
  draw: (g: CanvasRenderingContext2D, s: number) => void,
  color = true,
  height = size,
) {
  const hit = cache.get(key);
  if (hit) return hit;
  const canvas = document.createElement("canvas");
  canvas.width = size;
  canvas.height = height;
  draw(canvas.getContext("2d")!, size);
  const tex = new CanvasTexture(canvas);
  tex.wrapS = tex.wrapT = RepeatWrapping;
  tex.anisotropy = 8;
  if (color) tex.colorSpace = SRGBColorSpace;
  cache.set(key, tex);
  return tex;
}

/** Deterministic PRNG so textures are identical on every load. */
function rand(seed: number) {
  let s = seed;
  return () => {
    s = (s * 16807) % 2147483647;
    return (s - 1) / 2147483646;
  };
}

/** Power-trowelled concrete slab: mottled grey, saw-cut joints, tyre scuffs. */
export function concreteTexture() {
  return make("concrete", 1024, (g, s) => {
    const r = rand(7);
    g.fillStyle = "#8e9196";
    g.fillRect(0, 0, s, s);
    for (let i = 0; i < 2600; i++) {
      const v = 120 + Math.floor(r() * 40);
      g.fillStyle = `rgba(${v},${v + 2},${v + 5},${0.05 + r() * 0.08})`;
      const rad = 4 + r() * 40;
      g.beginPath();
      g.arc(r() * s, r() * s, rad, 0, Math.PI * 2);
      g.fill();
    }
    for (let i = 0; i < 40; i++) {
      g.strokeStyle = `rgba(30,30,32,${0.04 + r() * 0.06})`;
      g.lineWidth = 6 + r() * 10;
      g.beginPath();
      const y = r() * s;
      g.moveTo(0, y);
      g.bezierCurveTo(s * 0.3, y + (r() - 0.5) * 120, s * 0.6, y + (r() - 0.5) * 120, s, y + (r() - 0.5) * 60);
      g.stroke();
    }
    g.strokeStyle = "rgba(40,40,44,0.55)";
    g.lineWidth = 3;
    g.strokeRect(0, 0, s, s); // saw-cut joint every tile
  });
}

/** Roughness map for the slab: polished in traffic lanes, duller elsewhere. */
export function concreteRoughness() {
  return make(
    "concrete-rough",
    512,
    (g, s) => {
      const r = rand(11);
      g.fillStyle = "#8a8a8a";
      g.fillRect(0, 0, s, s);
      for (let i = 0; i < 900; i++) {
        const v = 90 + Math.floor(r() * 90);
        g.fillStyle = `rgba(${v},${v},${v},0.25)`;
        g.beginPath();
        g.arc(r() * s, r() * s, 6 + r() * 30, 0, Math.PI * 2);
        g.fill();
      }
    },
    false,
  );
}

/** Rack upright face: blue powder coat with teardrop punch holes. */
export function uprightTexture() {
  return make("upright", 128, (g, s) => {
    g.fillStyle = "#1d4fa6";
    g.fillRect(0, 0, s, s);
    g.fillStyle = "#0b1730";
    for (let y = 8; y < s; y += 32) {
      for (const x of [s * 0.3, s * 0.7]) {
        g.beginPath();
        g.ellipse(x, y, 5, 9, 0, 0, Math.PI * 2);
        g.fill();
      }
    }
    g.fillStyle = "rgba(255,255,255,0.08)";
    g.fillRect(0, 0, 10, s);
  });
}

/** Corrugated cardboard: kraft colour, fibres, a tape strip and a shipping label. */
export function cartonTexture() {
  return make("carton", 256, (g, s) => {
    const r = rand(23);
    g.fillStyle = "#b88a55";
    g.fillRect(0, 0, s, s);
    for (let i = 0; i < 500; i++) {
      g.fillStyle = `rgba(${90 + r() * 60},${60 + r() * 40},${30 + r() * 20},0.12)`;
      g.fillRect(r() * s, r() * s, 1 + r() * 3, 1 + r() * 14);
    }
    g.fillStyle = "rgba(150,110,60,0.6)";
    g.fillRect(s * 0.44, 0, s * 0.12, s); // packing tape
    g.fillStyle = "rgba(255,255,255,0.15)";
    g.fillRect(s * 0.45, 0, s * 0.02, s);
    g.fillStyle = "#f4f1ea";
    g.fillRect(s * 0.62, s * 0.58, s * 0.3, s * 0.26); // label
    g.fillStyle = "#222";
    for (let i = 0; i < 14; i++) g.fillRect(s * 0.64 + i * 4.5, s * 0.62, 2 + (i % 3), s * 0.1);
    g.fillRect(s * 0.64, s * 0.75, s * 0.2, 3);
    g.fillRect(s * 0.64, s * 0.79, s * 0.14, 3);
  });
}

/** Pine pallet deck boards with grain. */
export function woodTexture() {
  return make("wood", 256, (g, s) => {
    const r = rand(31);
    g.fillStyle = "#c9a26b";
    g.fillRect(0, 0, s, s);
    for (let i = 0; i < 90; i++) {
      g.strokeStyle = `rgba(${120 + r() * 40},${80 + r() * 30},${40},${0.15 + r() * 0.2})`;
      g.lineWidth = 1 + r() * 2;
      g.beginPath();
      const y = r() * s;
      g.moveTo(0, y);
      g.quadraticCurveTo(s / 2, y + (r() - 0.5) * 20, s, y + (r() - 0.5) * 10);
      g.stroke();
    }
    for (let i = 0; i < 4; i++) {
      g.fillStyle = "rgba(70,45,20,0.55)";
      g.beginPath();
      g.ellipse(r() * s, r() * s, 4 + r() * 5, 2 + r() * 3, 0, 0, Math.PI * 2);
      g.fill();
    }
  });
}

/** Welded wire-mesh rack deck (used with alphaTest). */
export function meshDeckTexture() {
  return make("mesh-deck", 128, (g, s) => {
    g.clearRect(0, 0, s, s);
    g.strokeStyle = "#c8ccd2";
    g.lineWidth = 3;
    for (let i = 0; i <= s; i += 16) {
      g.beginPath();
      g.moveTo(i, 0);
      g.lineTo(i, s);
      g.stroke();
    }
    g.lineWidth = 2;
    for (let i = 0; i <= s; i += 32) {
      g.beginPath();
      g.moveTo(0, i);
      g.lineTo(s, i);
      g.stroke();
    }
  });
}

/** Insulated sandwich wall panel with vertical ribs. */
export function wallPanelTexture() {
  return make("wall", 256, (g, s) => {
    const grd = g.createLinearGradient(0, 0, s, 0);
    for (let i = 0; i <= 8; i++) {
      grd.addColorStop(i / 8, i % 2 ? "#c6cad0" : "#dfe2e6");
    }
    g.fillStyle = grd;
    g.fillRect(0, 0, s, s);
    g.fillStyle = "rgba(0,0,0,0.12)";
    g.fillRect(0, s - 2, s, 2);
  });
}

/** Roller shutter door slats. */
export function shutterTexture() {
  return make("shutter", 256, (g, s) => {
    for (let y = 0; y < s; y += 16) {
      const grd = g.createLinearGradient(0, y, 0, y + 16);
      grd.addColorStop(0, "#a9b0b8");
      grd.addColorStop(0.5, "#d4d9de");
      grd.addColorStop(1, "#7f868e");
      g.fillStyle = grd;
      g.fillRect(0, y, s, 16);
    }
  });
}

/** Diagonal yellow/black hazard stripes. */
export function hazardTexture() {
  return make("hazard", 128, (g, s) => {
    g.fillStyle = "#f2c200";
    g.fillRect(0, 0, s, s);
    g.fillStyle = "#151515";
    for (let i = -s; i < s * 2; i += 32) {
      g.beginPath();
      g.moveTo(i, 0);
      g.lineTo(i + 16, 0);
      g.lineTo(i + 16 - s, s);
      g.lineTo(i - s, s);
      g.fill();
    }
  });
}

/** Small text sign (zone names, station plates, rack location labels). */
export function signTexture(text: string, bg = "#0f3d8a", fg = "#ffffff", w = 512, h = 128) {
  const draw = (g: CanvasRenderingContext2D) => {
    g.fillStyle = bg;
    g.fillRect(0, 0, w, h);
    g.fillStyle = fg;
    g.font = `bold ${Math.floor(h * 0.62)}px Inter, Arial, sans-serif`;
    g.textAlign = "center";
    g.textBaseline = "middle";
    g.fillText(text, w / 2, h / 2 + 4);
  };
  return make(`sign:${text}:${bg}:${fg}:${w}x${h}`, w, draw, true, h);
}

/** Robot touchscreen UI. */
export function screenTexture(color: string) {
  return make(`screen:${color}`, 128, (g, s) => {
    g.fillStyle = "#0b1220";
    g.fillRect(0, 0, s, s);
    g.fillStyle = color;
    g.fillRect(0, 0, s, 18);
    g.fillStyle = "#e6edf7";
    g.fillRect(12, 34, s - 24, 10);
    g.fillStyle = "#8aa0bf";
    for (let i = 0; i < 4; i++) g.fillRect(12, 56 + i * 14, s - 40 - i * 10, 6);
    g.fillStyle = color;
    g.fillRect(12, s - 26, s - 24, 14);
  });
}

/** Painted floor arrow pointing +X (worn white road paint), for one-way aisles. */
export function arrowTexture() {
  return make("arrow", 128, (g, s) => {
    g.clearRect(0, 0, s, s);
    g.fillStyle = "rgba(240,240,236,0.9)";
    g.beginPath();
    g.moveTo(s * 0.12, s * 0.4);
    g.lineTo(s * 0.55, s * 0.4);
    g.lineTo(s * 0.55, s * 0.22);
    g.lineTo(s * 0.9, s * 0.5);
    g.lineTo(s * 0.55, s * 0.78);
    g.lineTo(s * 0.55, s * 0.6);
    g.lineTo(s * 0.12, s * 0.6);
    g.closePath();
    g.fill();
    // Wear: speckle the paint so it reads as floor marking, not a UI icon.
    const r = rand(5);
    g.globalCompositeOperation = "destination-out";
    for (let i = 0; i < 160; i++) {
      g.fillStyle = `rgba(0,0,0,${0.2 + r() * 0.5})`;
      g.fillRect(r() * s, r() * s, 1 + r() * 3, 1 + r() * 3);
    }
    g.globalCompositeOperation = "source-over";
  });
}

/** Pallet top deck seen as one surface: five pine boards with dark gaps between them. */
export function palletDeckTexture() {
  return make("pallet-deck", 256, (g, s) => {
    g.drawImage(woodTexture().image as HTMLCanvasElement, 0, 0, s, s);
    g.fillStyle = "rgba(25,18,10,0.85)";
    for (let i = 1; i < 5; i++) g.fillRect((s * i) / 5 - 5, 0, 10, s);
    g.fillStyle = "rgba(60,40,20,0.6)";
    for (let i = 0; i < 5; i++) for (const v of [0.08, 0.5, 0.92]) g.fillRect((s * i) / 5 + s * 0.1, s * v - 2, 4, 4); // nail heads
  });
}

/** Soft dark ellipse used as a cheap contact shadow under robots when shadows are static. */
export function blobTexture() {
  return make("blob", 128, (g, s) => {
    const grd = g.createRadialGradient(s / 2, s / 2, 0, s / 2, s / 2, s / 2);
    grd.addColorStop(0, "rgba(0,0,0,0.55)");
    grd.addColorStop(0.6, "rgba(0,0,0,0.35)");
    grd.addColorStop(1, "rgba(0,0,0,0)");
    g.fillStyle = grd;
    g.fillRect(0, 0, s, s);
  });
}

/** Painted AMR parking bay: blue-grey floor paint, white border, large "P". */
export function parkingBayTexture() {
  return make("parking-bay", 256, (g, s) => {
    g.fillStyle = "#2d4a6b";
    g.fillRect(0, 0, s, s);
    g.strokeStyle = "#f2f2ee";
    g.lineWidth = 14;
    g.strokeRect(10, 10, s - 20, s - 20);
    g.fillStyle = "#f2f2ee";
    g.font = `bold ${Math.floor(s * 0.55)}px Inter, Arial, sans-serif`;
    g.textAlign = "center";
    g.textBaseline = "middle";
    g.fillText("P", s / 2, s / 2 + 8);
    // Worn paint, like the other floor markings.
    const r = rand(17);
    g.globalCompositeOperation = "destination-out";
    for (let i = 0; i < 220; i++) {
      g.fillStyle = `rgba(0,0,0,${0.15 + r() * 0.35})`;
      g.fillRect(r() * s, r() * s, 1 + r() * 4, 1 + r() * 4);
    }
    g.globalCompositeOperation = "source-over";
  });
}
