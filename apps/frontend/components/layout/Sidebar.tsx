"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { Bot, BookOpen, Boxes, LayoutDashboard, LineChart, MessageSquare, PackageCheck, Warehouse } from "lucide-react";

const NAV = [
  { href: "/dashboard", label: "Dashboard", icon: LayoutDashboard },
  { href: "/simulation", label: "Simulation", icon: Boxes },
  { href: "/fleet", label: "Fleet", icon: Bot },
  { href: "/orders", label: "Orders", icon: PackageCheck },
  { href: "/inventory", label: "Inventory", icon: Warehouse },
  { href: "/analytics", label: "Analytics", icon: LineChart },
  { href: "/copilot", label: "Copilot", icon: MessageSquare },
  { href: "/knowledge", label: "Knowledge", icon: BookOpen },
];

export function Sidebar() {
  const path = usePathname();
  return (
    <aside className="flex w-60 shrink-0 flex-col border-r border-border bg-surface max-[1440px]:w-16">
      <div className="px-5 py-5 text-base font-semibold max-[1440px]:hidden">Warehouse AI</div>
      <nav className="flex flex-col gap-1 px-3">
        {NAV.map(({ href, label, icon: Icon }) => {
          const active = path?.startsWith(href);
          return (
            <Link
              key={href}
              href={href}
              className={`flex items-center gap-3 rounded-control px-3 py-2 text-sm transition-colors ${
                active ? "bg-accent/15 font-semibold text-ink" : "text-muted hover:bg-border/50 hover:text-ink"
              }`}
            >
              <Icon size={18} />
              <span className="max-[1440px]:hidden">{label}</span>
            </Link>
          );
        })}
      </nav>
    </aside>
  );
}
