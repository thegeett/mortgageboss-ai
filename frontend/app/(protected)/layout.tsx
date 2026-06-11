"use client";

import { FullScreenLoader } from "@/components/full-screen-loader";
import { AppShell } from "@/components/layout/app-shell";
import { useRequireAuth } from "@/hooks/use-require-auth";

/**
 * Layout for the authenticated app (LP-27). Every page in the `(protected)`
 * route group inherits BOTH the protection and the shell from here — protection
 * is structural (one check), not repeated per page. The `/login` page lives
 * outside this group and so renders without the shell.
 *
 * Protection coordinates with the LP-25 silent-refresh on load: while the
 * initial session check is in flight (`isInitializing`) we show a loader and do
 * NOT redirect, so a page refresh doesn't flash the login screen or bounce an
 * already-authenticated user. Only once it resolves as unauthenticated does
 * `useRequireAuth` redirect to `/login`. This is UX, not security — the backend
 * is the real boundary.
 */
export default function ProtectedLayout({ children }: { children: React.ReactNode }) {
  const { isInitializing, isAuthenticated } = useRequireAuth();

  if (isInitializing) {
    return <FullScreenLoader label="Restoring your session…" />;
  }

  if (!isAuthenticated) {
    // useRequireAuth's redirect effect is firing; render nothing meanwhile.
    return null;
  }

  return <AppShell>{children}</AppShell>;
}
