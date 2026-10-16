"use client";

import { useMemo } from "react";
import { type BufferGeometry, CanvasTexture, MeshStandardMaterial, PlaneGeometry, SRGBColorSpace } from "three";
import { mergeGeometries } from "three/examples/jsm/utils/BufferGeometryUtils.js";

export interface Sign {
  text: string;
  p: [number, number, number];
  rot: number;
}

const CELL_W = 256;
const CELL_H = 100;
const COLS = 4;

/**
 * All aisle-end signs as ONE mesh: labels are drawn into a shared texture atlas and every sign is
 * a pair of back-to-back planes whose UVs point at its label. (192 separate signs were ~1,150 draw
 * calls, which integrated GPUs cannot afford.)
 */
export function SignBoards({ signs, w = 0.9, h = 0.36 }: { signs: Sign[]; w?: number; h?: number }) {
  const mesh = useMemo(() => {
    if (!signs.length) return null;
    const texts = [...new Set(signs.map((s) => s.text))];
    const rows = Math.ceil(texts.length / COLS);
    const canvas = document.createElement("canvas");
    canvas.width = CELL_W * COLS;
    canvas.height = CELL_H * rows;
    const g = canvas.getContext("2d")!;
    texts.forEach((t, i) => {
      const x = (i % COLS) * CELL_W;
      const y = Math.floor(i / COLS) * CELL_H;
      g.fillStyle = "#0f3d8a";
      g.fillRect(x, y, CELL_W, CELL_H);
      g.strokeStyle = "#ffffff";
      g.lineWidth = 6;
      g.strokeRect(x + 6, y + 6, CELL_W - 12, CELL_H - 12);
      g.fillStyle = "#ffffff";
      g.font = `bold ${Math.floor(CELL_H * 0.55)}px Inter, Arial, sans-serif`;
      g.textAlign = "center";
      g.textBaseline = "middle";
      g.fillText(t, x + CELL_W / 2, y + CELL_H / 2 + 3);
    });
    const tex = new CanvasTexture(canvas);
    tex.colorSpace = SRGBColorSpace;
    tex.anisotropy = 8;

    const cell = (text: string) => {
      const i = texts.indexOf(text);
      const u0 = (i % COLS) / COLS;
      const r = Math.floor(i / COLS);
      return { u0, u1: u0 + 1 / COLS, v0: 1 - (r + 1) / rows, v1: 1 - r / rows };
    };

    const parts: BufferGeometry[] = [];
    for (const s of signs) {
      const c = cell(s.text);
      for (const side of [0, Math.PI]) {
        const plane = new PlaneGeometry(w, h);
        const uv = plane.attributes.uv;
        for (let k = 0; k < uv.count; k++) {
          uv.setXY(k, c.u0 + uv.getX(k) * (c.u1 - c.u0), c.v0 + uv.getY(k) * (c.v1 - c.v0));
        }
        plane.translate(0, 0, 0.011);
        plane.rotateY(side + s.rot);
        plane.translate(...s.p);
        parts.push(plane.toNonIndexed());
      }
    }
    const geometry = mergeGeometries(parts, false)!;
    geometry.computeBoundingSphere();
    return { geometry, material: new MeshStandardMaterial({ map: tex, roughness: 0.5 }) };
  }, [signs, w, h]);

  if (!mesh) return null;
  return <mesh geometry={mesh.geometry} material={mesh.material} />;
}
