"use client";

import { Printer } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { wms, type LabelKind } from "@/lib/wms";

let printerList: Promise<string[]> | null = null; // asked once per page load

/**
 * One printer icon for a label: open it as a PDF (any office printer), download it as ZPL for a
 * thermal printer, or print it straight to a configured network label printer.
 */
export function LabelMenu({
  kind,
  target: id,
  text,
  className = "",
  align = "right",
}: {
  kind: LabelKind;
  target: string; // SKU, location prefix, SSCC
  text?: string; // button text next to the icon (none: icon only)
  className?: string;
  align?: "left" | "right"; // which edge of the button the menu lines up with
}) {
  const [open, setOpen] = useState(false);
  const [printers, setPrinters] = useState<string[]>([]);
  const [note, setNote] = useState<string | null>(null);
  const box = useRef<HTMLDivElement>(null);
  const path = kind === "locations" ? `locations?prefix=${encodeURIComponent(id)}` : `${kind}/${id}`;

  useEffect(() => {
    if (!open) return;
    printerList ??= wms.printers().catch(() => []);
    void printerList.then(setPrinters);
    const close = (e: MouseEvent) => {
      if (box.current && !box.current.contains(e.target as Node)) setOpen(false);
    };
    document.addEventListener("mousedown", close);
    return () => document.removeEventListener("mousedown", close);
  }, [open]);

  const item = "block w-full px-3 py-1.5 text-left text-xs hover:bg-accent/10";
  return (
    <div ref={box} className="relative inline-block">
      <button
        type="button"
        onClick={() => setOpen(!open)}
        title="Label: PDF, ZPL or print"
        aria-haspopup="menu"
        aria-expanded={open}
        className={className || "inline-flex items-center gap-1 rounded p-1 text-muted hover:text-ink"}
      >
        <Printer size={14} />
        {text}
      </button>
      {open && (
        <div
          role="menu"
          className={`absolute ${align === "left" ? "left-0" : "right-0"} z-30 mt-1 w-56 rounded-control border border-border bg-surface py-1 shadow-lg`}
        >
          <button role="menuitem" className={item} onClick={() => void wms.openLabel(path)}>
            Open as PDF (office printer)
          </button>
          <button role="menuitem" className={item} onClick={() => void wms.downloadZpl(path, `${kind}-${id}.zpl`)}>
            Download ZPL (thermal printer)
          </button>
          {printers.map((p) => (
            <button
              key={p}
              role="menuitem"
              className={item}
              onClick={async () => {
                try {
                  await wms.printLabel(kind, id, p);
                  setNote(`Sent to ${p}`);
                } catch (e) {
                  setNote((e as Error).message);
                }
              }}
            >
              Print on {p}
            </button>
          ))}
          {!printers.length && (
            <div className="px-3 py-1.5 text-[11px] text-muted">No network printers set (LABEL_PRINTERS)</div>
          )}
          {note && <div className="border-t border-border px-3 py-1.5 text-[11px]">{note}</div>}
        </div>
      )}
    </div>
  );
}
