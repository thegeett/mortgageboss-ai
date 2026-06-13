"use client";

import { AuthProvider } from "@/components/auth-provider";
import { ErrorBoundary } from "@/components/error-boundary";
import { makeQueryClient } from "@/lib/query-client";
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
      <Toaster richColors closeButton position="top-right" />
      {process.env.NODE_ENV === "development" && <ReactQueryDevtools initialIsOpen={false} />}
    </QueryClientProvider>
  );
}
