"use client";

import { Camera, ScanLine, X } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { protectedObjectUrl } from "@/lib/auth";
import { wms } from "@/lib/wms";

// Shared pieces of the WMS screens: the operator name, the scan box, badges, barcodes.

interface BarcodeDetectorLike {
  detect(source: CanvasImageSource): Promise<{ rawValue: string }[]>;
}

declare global {
  interface Window {
    BarcodeDetector?: new (opts: { formats: string[] }) => BarcodeDetectorLike;
  }
}

/**
 * Scan input. Handheld USB / Bluetooth scanners type the code and press Enter (keyboard wedge),
 * so they work here as they do in any WMS. The camera button reads barcodes with the phone or
 * webcam where the browser has the BarcodeDetector API (Chrome on Android, macOS, ChromeOS).
 */
export function ScanBox({
  onScan,
  placeholder = "Scan or type a barcode, then Enter",
  autoFocus = false,
}: {
  onScan: (code: string) => void;
  placeholder?: string;
  autoFocus?: boolean;
}) {
  const [value, setValue] = useState("");
  const [camera, setCamera] = useState(false);
  const input = useRef<HTMLInputElement>(null);
  useEffect(() => {
    if (autoFocus) input.current?.focus();
  }, [autoFocus]);
  return (
    <div className="flex gap-2">
      <form
        className="flex flex-1 items-center gap-2 rounded-control border border-border bg-canvas px-2 focus-within:border-accent"
        onSubmit={(e) => {
          e.preventDefault();
          const code = value.trim();
          if (code) onScan(code);
          setValue("");
        }}
      >
        <ScanLine size={16} className="text-muted" />
        <input
          ref={input}
          value={value}
          onChange={(e) => setValue(e.target.value)}
          placeholder={placeholder}
          aria-label="Barcode"
          className="w-full bg-transparent py-1.5 font-mono text-sm outline-none"
        />
      </form>
      <button
        type="button"
        onClick={() => setCamera(true)}
        title="Scan with the camera"
        className="rounded-control border border-border px-2 text-muted hover:text-ink"
      >
        <Camera size={16} />
      </button>
      {camera && (
        <CameraScanner
          onClose={() => setCamera(false)}
          onCode={(code) => {
            setCamera(false);
            onScan(code);
          }}
        />
      )}
    </div>
  );
}

function CameraScanner({ onClose, onCode }: { onClose: () => void; onCode: (code: string) => void }) {
  const video = useRef<HTMLVideoElement>(null);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    if (!window.BarcodeDetector) {
      setError("This browser cannot read barcodes from the camera. Use a handheld scanner or type the code.");
      return;
    }
    const detector = new window.BarcodeDetector({
      formats: ["ean_13", "code_128", "data_matrix", "qr_code", "upc_a"],
    });
    let stream: MediaStream | null = null;
    let stopped = false;
    navigator.mediaDevices
      .getUserMedia({ video: { facingMode: "environment" } })
      .then(async (s) => {
        stream = s;
        if (!video.current) return;
        video.current.srcObject = s;
        await video.current.play();
        while (!stopped && video.current) {
          const found = await detector.detect(video.current).catch(() => []);
          if (found.length) {
            onCode(found[0].rawValue);
            return;
          }
          await new Promise((r) => setTimeout(r, 250));
        }
      })
      .catch(() => setError("Camera not available (permission denied or no camera)."));
    return () => {
      stopped = true;
      stream?.getTracks().forEach((t) => t.stop());
    };
  }, [onCode]);
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60" onClick={onClose}>
      <div className="w-[420px] rounded-card bg-surface p-4" onClick={(e) => e.stopPropagation()}>
        <div className="mb-2 flex items-center justify-between text-sm font-semibold">
          Scan with the camera
          <button onClick={onClose} aria-label="Close">
            <X size={16} />
          </button>
        </div>
        {error ? (
          <p className="text-sm text-muted">{error}</p>
        ) : (
          <video ref={video} className="w-full rounded-control bg-black" muted playsInline />
        )}
      </div>
    </div>
  );
}

const TONE: Record<string, string> = {
  AVAILABLE: "bg-success/15 text-success",
  OPEN: "bg-accent/15 text-accent",
  IN_TRANSIT: "bg-accent/15 text-accent",
  AT_DOCK: "bg-warning/15 text-warning",
  RECEIVING: "bg-warning/15 text-warning",
  CLOSED: "bg-border text-muted",
  MATCHED: "bg-success/15 text-success",
  ADJUSTED: "bg-success/15 text-success",
  PENDING_APPROVAL: "bg-danger/15 text-danger",
  HOLD: "bg-warning/15 text-warning",
  QC_HOLD: "bg-warning/15 text-warning",
  DAMAGED: "bg-danger/15 text-danger",
  EXPIRED: "bg-danger/15 text-danger",
  A: "bg-accent/20 text-accent",
  // returns
  EXPECTED: "bg-accent/10 text-accent",
  RECEIVED: "bg-warning/15 text-warning",
  RESTOCKED: "bg-success/15 text-success",
  SCRAPPED: "bg-border text-muted",
  // outbound
  WAITING_STOCK: "bg-warning/15 text-warning",
  READY: "bg-accent/10 text-accent",
  ON_HOLD: "bg-danger/15 text-danger",
  RELEASED: "bg-accent/15 text-accent",
  PICKING: "bg-accent/20 text-accent",
  AT_PACK: "bg-warning/15 text-warning",
  PACKED: "bg-success/10 text-success",
  IN_LANE: "bg-success/10 text-success",
  LOADED: "bg-success/15 text-success",
  SHIPPED: "bg-success/25 text-success",
  CANCELLED: "bg-border text-muted",
  DEPARTED: "bg-border text-muted",
  SCHEDULED: "bg-accent/15 text-accent",
  FAIL: "bg-danger/15 text-danger",
  PASS: "bg-success/15 text-success",
  AUDITED: "bg-success/15 text-success",
};

export function Badge({ value }: { value: string }) {
  return (
    <span className={`rounded px-1.5 py-0.5 text-[11px] font-medium ${TONE[value] ?? "bg-border/70 text-muted"}`}>
      {value.replaceAll("_", " ")}
    </span>
  );
}

export function Barcode({
  kind,
  value,
  height = 48,
}: {
  kind: "ean13" | "code128" | "gs1-128";
  value: string;
  height?: number;
}) {
  // The SVG comes from the backend (reportlab, the encoder that prints the labels). It is a
  // protected endpoint, so it is fetched with the access token and shown from an object URL.
  const [src, setSrc] = useState<string | null>(null);
  useEffect(() => {
    let url: string | null = null;
    let alive = true;
    protectedObjectUrl(wms.barcodeUrl(kind, value))
      .then((u) => {
        url = u;
        if (alive) setSrc(u);
        else URL.revokeObjectURL(u);
      })
      .catch(() => undefined);
    return () => {
      alive = false;
      if (url) URL.revokeObjectURL(url);
    };
  }, [kind, value]);
  if (!src) return <div style={{ height, width: height * 2.5 }} className="animate-pulse rounded bg-border/60" />;
  // eslint-disable-next-line @next/next/no-img-element -- an object URL of a generated SVG
  return <img src={src} alt={`${kind} ${value}`} style={{ height }} className="bg-white p-1" />;
}

export function Panel({
  title,
  actions,
  children,
}: {
  title: string;
  actions?: React.ReactNode;
  children: React.ReactNode;
}) {
  return (
    <section className="rounded-card border border-border bg-surface p-4">
      <div className="mb-3 flex flex-wrap items-center gap-2">
        <h2 className="mr-auto text-sm font-semibold">{title}</h2>
        {actions}
      </div>
      {children}
    </section>
  );
}

export function ErrorNote({ text }: { text: string | null }) {
  return text ? <div className="rounded-control border border-danger/50 bg-danger/10 p-2 text-sm">{text}</div> : null;
}

export const th = "px-2 py-1.5 text-left text-[11px] font-semibold uppercase tracking-wide text-muted";
export const td = "px-2 py-1.5";
export const input =
  "rounded-control border border-border bg-canvas px-2 py-1.5 text-sm outline-none focus:border-accent";
export const button = "rounded-control bg-accent px-3 py-1.5 text-sm font-medium text-white disabled:opacity-50";
export const ghost = "rounded-control border border-border px-3 py-1.5 text-sm hover:border-accent";

const TICKS_PER_HOUR = 600; // configs/simulation.yaml: one tick is 6 simulated seconds

/** A tick as simulated clock time, e.g. "Day 2 14:30". */
export function clock(tick: number | null | undefined): string {
  if (tick === null || tick === undefined) return "–";
  const hours = tick / TICKS_PER_HOUR;
  const day = Math.floor(hours / 24) + 1;
  const h = Math.floor(hours % 24);
  const m = Math.floor((hours % 1) * 60);
  return `Day ${day} ${String(h).padStart(2, "0")}:${String(m).padStart(2, "0")}`;
}

/** Ticks as a duration in simulated minutes. */
export const minutes = (ticks: number | null | undefined) => (ticks == null ? "–" : `${Math.round(ticks / 10)} min`);

/** Download a table as CSV (opens in Excel; formulas in cells are neutralised by the server). */
export function ExportButton({ name, label = "Export CSV" }: { name: string; label?: string }) {
  return (
    <button
      type="button"
      onClick={() => void wms.exportCsv(name)}
      title={`Download ${name} as CSV`}
      className="rounded-control border border-border px-2 py-1 text-xs hover:border-accent"
    >
      {label}
    </button>
  );
}
