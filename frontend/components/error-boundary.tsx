"use client";

import { Button } from "@/components/ui/button";
import { RotateCw, TriangleAlert } from "lucide-react";
import { Component, type ErrorInfo, type ReactNode } from "react";

/**
 * Top-level React error boundary (LP-46) — the no-white-screen guarantee.
 *
 * A render-time throw anywhere in the subtree is caught here and replaced with a
 * clean, friendly fallback ("Something went wrong" + a Retry) instead of an
 * unmounted, blank page. Retry bumps a key to remount the subtree (recovering
 * from transient render errors without a full page reload); the fallback also
 * offers a hard reload as a last resort.
 *
 * The error is logged to the console for debugging — we never render the raw
 * error text/stack to the user (it could carry internals). Pass `onReset` to
 * also clear related state (e.g. invalidate queries) when the user retries.
 */
interface ErrorBoundaryProps {
  children: ReactNode;
  /** Optional custom fallback; receives a reset callback. */
  fallback?: (reset: () => void) => ReactNode;
  /** Called when the user retries, before the subtree remounts. */
  onReset?: () => void;
}

interface ErrorBoundaryState {
  hasError: boolean;
  /** Bumped on reset to force a fresh subtree mount. */
  resetKey: number;
}

export class ErrorBoundary extends Component<ErrorBoundaryProps, ErrorBoundaryState> {
  override state: ErrorBoundaryState = { hasError: false, resetKey: 0 };

  static getDerivedStateFromError(): Partial<ErrorBoundaryState> {
    return { hasError: true };
  }

  override componentDidCatch(error: Error, info: ErrorInfo): void {
    // Safe, developer-facing log only — never shown to the user.
    if (process.env.NODE_ENV !== "production") {
      console.error("ErrorBoundary caught an error:", error, info.componentStack);
    }
  }

  reset = (): void => {
    this.props.onReset?.();
    this.setState((s) => ({ hasError: false, resetKey: s.resetKey + 1 }));
  };

  override render(): ReactNode {
    if (this.state.hasError) {
      if (this.props.fallback) return this.props.fallback(this.reset);
      return <DefaultErrorFallback onRetry={this.reset} />;
    }
    // Keying on resetKey forces a clean remount of the subtree on retry.
    return <div key={this.state.resetKey}>{this.props.children}</div>;
  }
}

/** The default friendly fallback — centered, on-brand, with recovery actions. */
export function DefaultErrorFallback({ onRetry }: { onRetry: () => void }) {
  return (
    <div
      role="alert"
      className="flex min-h-[50vh] flex-col items-center justify-center px-6 py-16 text-center"
    >
      <span className="flex h-14 w-14 items-center justify-center rounded-full bg-destructive/10 text-destructive">
        <TriangleAlert className="h-7 w-7" />
      </span>
      <h1 className="mt-5 text-xl font-semibold text-gray-900">Something went wrong</h1>
      <p className="mt-2 max-w-md text-sm text-gray-500">
        An unexpected error interrupted this view. You can try again — if it keeps happening, reload
        the page.
      </p>
      <div className="mt-6 flex items-center gap-3">
        <Button type="button" onClick={onRetry} className="gap-1.5">
          <RotateCw className="h-4 w-4" />
          Try again
        </Button>
        <Button
          type="button"
          variant="outline"
          onClick={() => {
            if (typeof window !== "undefined") window.location.reload();
          }}
        >
          Reload page
        </Button>
      </div>
    </div>
  );
}
