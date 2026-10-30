"use client";

import { useRouter } from "next/navigation";
import { useEffect } from "react";
import { useAuth } from "@/lib/auth";

/** The start page depends on the role: operators and supervisors the dashboard, inventory clerks
 *  the inventory, viewers the analytics, administrators the user management. */
export default function Home() {
  const home = useAuth((s) => s.user?.home);
  const router = useRouter();
  useEffect(() => {
    if (home) router.replace(home);
  }, [home, router]);
  return null;
}
