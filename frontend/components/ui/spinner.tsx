import { cn } from "@/lib/utils";
import { Loader2 } from "lucide-react";

/**
 * The one spinner (LP-47) — a consistent spinning indicator for in-flight
 * actions. Decorative (`aria-hidden`); the button it sits in conveys the busy
 * state to assistive tech (disabled + its label). Default size suits a button;
 * override with `className` (e.g. `h-5 w-5`).
 */
export function Spinner({ className }: { className?: string }) {
  return <Loader2 className={cn("h-4 w-4 animate-spin", className)} aria-hidden />;
}

/**
 * Wraps a content-loading region (LP-47) so assistive tech knows it's busy:
 * `aria-busy` on the region while loading, plus a visually-hidden live cue. The
 * skeletons inside are `aria-hidden`, so this is the only thing a screen reader
 * announces while content loads.
 */
export function LoadingRegion({
  loading,
  label = "Loading",
  children,
  className,
}: {
  loading: boolean;
  label?: string;
  children: React.ReactNode;
  className?: string;
}) {
  return (
    <div aria-busy={loading} className={className}>
      {loading && <output className="sr-only">{label}</output>}
      {children}
    </div>
  );
}
