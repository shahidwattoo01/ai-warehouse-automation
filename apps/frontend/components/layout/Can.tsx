"use client";

import { useCan } from "@/lib/auth";

/**
 * Shows its children only to users holding `permission` (or `fallback` to the others). This is
 * for the screen only; the backend checks the permission on every request.
 */
export function Can({
  permission,
  children,
  fallback = null,
}: {
  permission: string;
  children: React.ReactNode;
  fallback?: React.ReactNode;
}) {
  return <>{useCan(permission) ? children : fallback}</>;
}
