import { Loader2 } from "lucide-react";

/**
 * A centered, full-viewport loading state. Used while the on-load silent
 * refresh resolves and while a protected route confirms auth — so we never
 * flash the login screen or protected content before the session is known.
 */
export function FullScreenLoader({ label = "Loading…" }: { label?: string }) {
  return (
    <div className="flex min-h-screen items-center justify-center bg-gray-50">
      <div className="flex flex-col items-center gap-3 text-muted-foreground">
        <Loader2 className="h-6 w-6 animate-spin text-primary" />
        <output aria-live="polite" className="text-sm font-medium">
          {label}
        </output>
      </div>
    </div>
  );
}
