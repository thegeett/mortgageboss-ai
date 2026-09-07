"use client";

import { AuthProvider } from "@/components/auth-provider";
import { ErrorBoundary } from "@/components/error-boundary";
import { makeQueryClient } from "@/lib/query-client";
import { TOASTER_CLASSNAMES } from "@/lib/toast";
import { QueryClientProvider } from "@tanstack/react-query";
import { ReactQueryDevtools } from "@tanstack/react-query-devtools";
import { type ReactNode, useState } from "react";
import { Toaster } from "sonner";

export function Providers({ children }: { children: ReactNode }) {
  const [queryClient] = useState(() => makeQueryClient());

  return (
    <QueryClientProvider client={queryClient}>
      {/* Top-level safety net (LP-46): a render crash anywhere shows the friendly
          fallback instead of a white screen. On reset, clear cached query state so
          a retry refetches cleanly rather than rethrowing the same bad data. */}
      <ErrorBoundary onReset={() => queryClient.clear()}>
        <AuthProvider>{children}</AuthProvider>
      </ErrorBoundary>
      {/* STYLED TO THE TOKENS, not to Sonner's own palette (LP-UI-035).
          `richColors` paints its own greens and reds, which is a second colour
          vocabulary beside the one LP-UI-005 unified — and the standing rule is
          that state lives on a LEFT RAIL and a glyph, never on a fill. So: the
          app's surface and border everywhere, and a 2px rail carrying the tone.
          The mockup shows exactly this, with a third accent rail for a change
          that is neither good news nor bad. */}
      <Toaster closeButton position="top-right" toastOptions={{ classNames: TOASTER_CLASSNAMES }} />
      {process.env.NODE_ENV === "development" && <ReactQueryDevtools initialIsOpen={false} />}
    </QueryClientProvider>
  );
}
