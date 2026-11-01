"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useEffect, useState } from "react";
import { pagePermission, useAuth } from "@/lib/auth";
import {
  Bell,
  BrainCircuit,
  Bot,
  BookOpen,
  Boxes,
  Cctv,
  LayoutDashboard,
  LineChart,
  MessageSquare,
  PackageCheck,
  PanelLeftClose,
  PanelLeftOpen,
  Plug,
  ShieldAlert,
  ShieldCheck,
  Smartphone,
  Warehouse,
} from "lucide-react";

const NAV = [
  { href: "/dashboard", label: "Dashboard", icon: LayoutDashboard },
  { href: "/simulation", label: "Simulation", icon: Boxes },
  { href: "/fleet", label: "Fleet", icon: Bot },
  { href: "/orders", label: "Orders", icon: PackageCheck },
  { href: "/inventory", label: "Inventory", icon: Warehouse },
  { href: "/rf", label: "Handheld", icon: Smartphone },
  { href: "/vision", label: "Vision", icon: Cctv },
  { href: "/analytics", label: "Analytics", icon: LineChart },
  { href: "/models", label: "AI models", icon: BrainCircuit },
  { href: "/copilot", label: "Copilot", icon: MessageSquare },
  { href: "/knowledge", label: "Knowledge", icon: BookOpen },
  { href: "/integration", label: "Integration", icon: Plug },
  { href: "/alerts", label: "Alerts", icon: Bell },
  { href: "/safety", label: "Safety", icon: ShieldAlert },
  { href: "/admin/users", label: "Users & roles", icon: ShieldCheck },
];

const STORAGE_KEY = "sidebar-open";
const WIDE = 1440; // without a saved choice: names shown above this width, icons only below

export function Sidebar() {
  const path = usePathname();
  const permissions = useAuth((s) => s.user?.permissions);
  // Each role sees only the pages it can open.
  const nav = NAV.filter(({ href }) => {
    const needed = pagePermission(href);
    return !needed || (permissions ?? []).includes(needed);
  });
  // null until mounted: the first render follows the screen width (CSS), so server and browser
  // render the same; afterwards the operator's choice (remembered in this browser) wins.
  const [open, setOpen] = useState<boolean | null>(null);

  useEffect(() => {
    let saved: string | null = null;
    try {
      saved = window.localStorage.getItem(STORAGE_KEY);
    } catch {
      /* storage blocked: follow the screen width */
    }
    setOpen(saved === null ? window.innerWidth > WIDE : saved === "true");
  }, []);

  const toggle = () => {
    const next = !(open ?? window.innerWidth > WIDE);
    setOpen(next);
    try {
      window.localStorage.setItem(STORAGE_KEY, String(next));
    } catch {
      /* not remembered, still toggles */
    }
  };

  // Before mount: the old width rule. After: the explicit state.
  const hideWhenNarrow = open === null ? "max-[1440px]:hidden" : open ? "" : "hidden";
  const width = open === null ? "w-60 max-[1440px]:w-16" : open ? "w-60" : "w-16";
  const expanded = open ?? true;

  return (
    <aside
      className={`flex shrink-0 flex-col border-r border-border bg-surface transition-[width] duration-200 ${width}`}
    >
      <div className="flex items-center justify-between gap-2 px-3 py-4">
        <span className={`truncate pl-2 text-base font-semibold ${hideWhenNarrow}`}>Warehouse AI</span>
        <button
          onClick={toggle}
          aria-label={expanded ? "Collapse sidebar" : "Expand sidebar"}
          aria-expanded={open ?? undefined}
          title={open === false ? "Show names" : "Hide names"}
          className="rounded-control p-2 text-muted hover:bg-border/50 hover:text-ink"
        >
          {open === false ? <PanelLeftOpen size={18} /> : <PanelLeftClose size={18} />}
        </button>
      </div>
      {/* Scrolls on its own when the menu is taller than the window; the header stays. */}
      <nav className="flex min-h-0 flex-1 flex-col gap-1 scroll-quiet overflow-y-auto px-3 pb-16">
        {nav.map(({ href, label, icon: Icon }) => {
          const active = path?.startsWith(href);
          return (
            <Link
              key={href}
              href={href}
              title={label}
              className={`flex items-center gap-3 rounded-control px-3 py-2 text-sm transition-colors ${
                active ? "bg-accent/15 font-semibold text-ink" : "text-muted hover:bg-border/50 hover:text-ink"
              }`}
            >
              <Icon size={18} className="shrink-0" />
              <span className={`truncate ${hideWhenNarrow}`}>{label}</span>
            </Link>
          );
        })}
      </nav>
    </aside>
  );
}
