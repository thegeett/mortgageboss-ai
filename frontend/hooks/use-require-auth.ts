"use client";

import { useAuthStore, useIsAuthenticated } from "@/lib/stores/auth-store";
import { usePathname, useRouter } from "next/navigation";
import { useEffect } from "react";

/**
 * Client-side route guard (LP-25).
 *
 * Redirects unauthenticated users to `/login`, preserving the attempted path in
 * a `next` query param so login can send them back. This is **UX, not
 * security** — the backend is the real boundary (every protected endpoint
 * verifies the Bearer token and the live user). It only avoids rendering
 * authenticated chrome to someone who isn't signed in.
 *
 * Returns the current auth flags so a layout can render a loader / nothing while
 * the redirect is in flight.
 */
export function useRequireAuth(): { isInitializing: boolean; isAuthenticated: boolean } {
  const router = useRouter();
  const pathname = usePathname();
  const isInitializing = useAuthStore((state) => state.isInitializing);
  const isAuthenticated = useIsAuthenticated();

  useEffect(() => {
    if (!isInitializing && !isAuthenticated) {
      const next = encodeURIComponent(pathname);
      router.replace(`/login?next=${next}`);
    }
  }, [isInitializing, isAuthenticated, pathname, router]);

  return { isInitializing, isAuthenticated };
}
