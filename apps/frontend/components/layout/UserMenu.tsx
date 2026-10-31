"use client";

import { LogOut, UserRound } from "lucide-react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { logout, useAuth } from "@/lib/auth";

/** Who is logged in, their role, and log out. */
export function UserMenu() {
  const user = useAuth((s) => s.user);
  const router = useRouter();
  if (!user) return null;
  return (
    <div className="flex items-center gap-2 border-l border-border pl-3">
      <Link
        href="/account"
        title={`${user.full_name} · ${user.role_label} (my account)`}
        className="flex items-center gap-2 hover:text-accent"
      >
        <UserRound size={16} className="text-muted" />
        <div className="hidden max-w-[150px] leading-tight lg:block">
          <div className="truncate text-sm font-medium">{user.full_name}</div>
          <div className="truncate text-[11px] text-muted">{user.role_label}</div>
        </div>
      </Link>
      <button
        onClick={async () => {
          await logout();
          router.replace("/login");
        }}
        title="Log out"
        aria-label="Log out"
        className="rounded-control border border-border p-2 hover:border-accent"
      >
        <LogOut size={15} />
      </button>
    </div>
  );
}
