"use client";

import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";
import { RotateCw, TriangleAlert, WifiOff } from "lucide-react";
import type { ReactNode } from "react";

/**
 * Inline error state (LP-46) — the consistent "this section couldn't load"
 * panel, with an optional Retry. Used wherever a data read can fail (a list, a
 * card, a drawer) so failures read the same everywhere: a clear icon, a friendly
 * line, and a way forward — never a blank space or a console-only error.
 *
 * Keep messages SAFE and human ("Couldn't load your documents"), never a raw
 * status or server internal.
 */
export function ErrorState({
  title = "Something went wrong",
  message = "We couldn't load this. Please try again.",
  variant = "generic",
  onRetry,
  retryLabel = "Retry",
  className,
  children,
}: {
  title?: string;
  message?: string;
  variant?: "generic" | "network";
  onRetry?: () => void;
  retryLabel?: string;
  className?: string;
  children?: ReactNode;
}) {
  const Icon = variant === "network" ? WifiOff : TriangleAlert;
  return (
    <div
      role="alert"
      className={cn(
        "flex flex-col items-center justify-center gap-3 rounded-lg border border-gray-200 bg-white px-6 py-10 text-center",
        className,
      )}
    >
      <span className="flex h-10 w-10 items-center justify-center rounded-full bg-destructive/10 text-destructive">
        <Icon className="h-5 w-5" />
      </span>
      <div className="space-y-1">
        <p className="text-sm font-semibold text-gray-900">{title}</p>
        <p className="mx-auto max-w-sm text-sm text-gray-500">{message}</p>
      </div>
      {children}
      {onRetry && (
        <Button
          type="button"
          variant="outline"
          size="sm"
          onClick={onRetry}
          className="mt-1 gap-1.5"
        >
          <RotateCw className="h-3.5 w-3.5" />
          {retryLabel}
        </Button>
      )}
    </div>
  );
}

/**
 * Compact inline variant for tight spots (a small card body) — one line + an
 * optional inline Retry, no large panel chrome.
 */
export function InlineErrorState({
  message = "Couldn't load this.",
  onRetry,
  className,
}: {
  message?: string;
  onRetry?: () => void;
  className?: string;
}) {
  return (
    <div
      role="alert"
      className={cn("flex items-center gap-2 py-4 text-sm text-gray-500", className)}
    >
      <TriangleAlert className="h-4 w-4 shrink-0 text-destructive" />
      <span>{message}</span>
      {onRetry && (
        <button
          type="button"
          onClick={onRetry}
          className="font-medium text-primary underline-offset-2 hover:underline focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-1"
        >
          Retry
        </button>
      )}
    </div>
  );
}
