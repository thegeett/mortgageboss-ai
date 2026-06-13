"use client";

import { FullScreenLoader } from "@/components/full-screen-loader";
import { refreshSession } from "@/lib/api/auth";
import { useAuthStore } from "@/lib/stores/auth-store";
import { useEffect, useRef } from "react";

/**
 * Silent-refresh-on-load gate (LP-25).
 *
 * The access token lives only in memory, so a full page load starts with no
 * session. On mount we attempt one silent refresh against the httpOnly refresh
 * cookie: success populates the store ("remembered" user); failure leaves the
 * user unauthenticated. Until that attempt settles we render a loading state
 * rather than children, so neither the login screen nor protected content
 * flashes before we know the auth state.
 */
export function AuthProvider({ children }: { children: React.ReactNode }) {
  const isInitializing = useAuthStore((state) => state.isInitializing);
  const finishInitializing = useAuthStore((state) => state.finishInitializing);
  // Guard against React 18 StrictMode running the effect twice in dev.
  const started = useRef(false);

  useEffect(() => {
    if (started.current) return;
    started.current = true;

    refreshSession()
      .catch(() => {
        // No valid refresh cookie — remain unauthenticated.
        useAuthStore.getState().clearAuth();
      })
      .finally(() => {
        finishInitializing();
      });
  }, [finishInitializing]);

  if (isInitializing) {
    return <FullScreenLoader label="Restoring your session…" />;
  }

  return <>{children}</>;
}
