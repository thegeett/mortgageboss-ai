"use client";

import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";
import { RotateCw, TriangleAlert, WifiOff } from "lucide-react";
import type { ReactNode } from "react";

/**
 * The whole-page error (LP-46, rewritten to the mockup in LP-UI-034).
 *
 * NAME WHAT FAILED, WHY, AND THE WAY OUT. `title` and `message` are REQUIRED,
 * which is the point of this change rather than a side effect: the old defaults
 * were "Something went wrong" and "We couldn't load this. Please try again." — an
 * apology followed by an instruction, telling a processor nothing they can act
 * on, and the ticket bans that phrase by name. A required prop means no screen
 * can fall back into it.
 *
 * Two actions, not one. Retry is worth offering when a retry might work, but a
 * page that will not load needs somewhere to GO — the mockup's "Try again" beside
 * "Back to the pipeline". A dead end with a button that keeps failing is worse
 * than a dead end with an exit.
 *
 * Keep messages SAFE and human, never a raw status or a server internal.
 */
export function ErrorState({
  title,
  message,
  variant = "generic",
  onRetry,
  retryLabel = "Try again",
  wayOut,
  className,
  children,
}: {
  /** What failed, in the processor's terms: "This file wouldn't open". */
  title: string;
  /** Why, and what it means for their work. "Nothing was changed" is worth saying. */
  message: string;
  variant?: "generic" | "network";
  onRetry?: () => void;
  retryLabel?: string;
  /** The way out when retrying will not help — usually a link somewhere safe. */
  wayOut?: ReactNode;
  className?: string;
  children?: ReactNode;
}) {
  const Icon = variant === "network" ? WifiOff : TriangleAlert;
  return (
    <div
      role="alert"
      className={cn(
        "flex flex-col items-center justify-center gap-3 rounded-lg border border-border bg-card px-6 py-10 text-center",
        className,
      )}
    >
      <span className="flex h-10 w-10 items-center justify-center rounded-full bg-destructive/10 text-destructive">
        <Icon className="h-5 w-5" />
      </span>
      <div className="space-y-1">
        <p className="text-sm font-semibold text-foreground">{title}</p>
        <p className="mx-auto max-w-sm text-sm text-muted-foreground">{message}</p>
      </div>
      {children}
      {(onRetry || wayOut) && (
        <div className="mt-1 flex flex-wrap items-center justify-center gap-2">
          {onRetry && (
            <Button type="button" variant="outline" size="sm" onClick={onRetry} className="gap-1.5">
              <RotateCw className="h-3.5 w-3.5" />
              {retryLabel}
            </Button>
          )}
          {wayOut}
        </div>
      )}
    </div>
  );
}

/**
 * One section of a page failed (LP-46, rewritten in LP-UI-034).
 *
 * A LEFT RAIL, matching the mockup and the LP-UI-005 rule that state lives on the
 * rail and the glyph rather than on a fill. It also does the job the fill could
 * not: it scopes the failure visually to this section, which is the reassurance
 * the message carries in words.
 *
 * `message` is required for the same reason `title` is above.
 */
export function InlineErrorState({
  message,
  onRetry,
  className,
}: {
  /**
   * What failed, why if it is knowable, and what still worked. The mockup's
   * example is the shape to copy: "Couldn't load the borrowers. The request timed
   * out. The rest of the file loaded fine." A processor's next question after a
   * failure is always how much of the screen they can still trust.
   */
  message: string;
  onRetry?: () => void;
  className?: string;
}) {
  return (
    <div
      role="alert"
      className={cn(
        "flex items-center gap-2 border-l-2 border-l-destructive py-4 pl-3 text-sm text-muted-foreground",
        className,
      )}
    >
      <TriangleAlert className="h-4 w-4 shrink-0 text-destructive" />
      <span>{message}</span>
      {onRetry && (
        <button
          type="button"
          onClick={onRetry}
          className="font-medium text-primary underline-offset-2 hover:underline"
        >
          Retry
        </button>
      )}
    </div>
  );
}
