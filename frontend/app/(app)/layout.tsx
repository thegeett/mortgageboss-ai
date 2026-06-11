"use client";

import { FullScreenLoader } from "@/components/full-screen-loader";
import { useRequireAuth } from "@/hooks/use-require-auth";

/**
 * Layout for the authenticated area. Any page under the `(app)` route group is
 * protected: an unauthenticated visitor is redirected to `/login` (UX only —
 * the backend enforces real access control on every request).
 *
 * While the session is being restored, or while the redirect is in flight, we
 * render a loader / nothing rather than the protected UI, so it never flashes.
 */
export default function AppLayout({ children }: { children: React.ReactNode }) {
  const { isInitializing, isAuthenticated } = useRequireAuth();

  if (isInitializing) {
    return <FullScreenLoader label="Restoring your session…" />;
  }

  if (!isAuthenticated) {
    // The redirect effect in useRequireAuth is firing; render nothing meanwhile.
    return null;
  }

  return <>{children}</>;
}
