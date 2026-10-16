"use client";

import { usePathname } from "next/navigation";
import { useEffect } from "react";
import { useSim } from "@/lib/store";

/**
 * Opens the single shared simulator stream for the whole app. The camera-dataset page (/capture)
 * is fed scene by scene by scripts/capture_frames.py instead, so it never opens the stream.
 */
export function SimProvider({ children }: { children: React.ReactNode }) {
  const connect = useSim((s) => s.connect);
  const capture = usePathname()?.startsWith("/capture") ?? false;
  useEffect(() => (capture ? undefined : connect()), [connect, capture]);
  return <>{children}</>;
}
