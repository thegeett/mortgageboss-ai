import { cn } from "@/lib/utils";

/**
 * Base skeleton (LP-5) — a calm pulsing placeholder. Decorative by default
 * (`aria-hidden`), so screen readers skip the shapes; the surrounding loading
 * region carries the accessible "loading" cue (LP-47).
 */
function Skeleton({ className, ...props }: React.HTMLAttributes<HTMLDivElement>) {
  return (
    <div
      aria-hidden
      className={cn("animate-pulse rounded-md bg-gray-200/70", className)}
      {...props}
    />
  );
}

/**
 * A block of text-line skeletons (LP-47). The last line is shorter by default so
 * it reads like a paragraph; pass explicit `widths` to shape-match a known body.
 * One primitive instead of bespoke line stacks per surface (cards, feeds, panels).
 */
function SkeletonText({
  lines = 3,
  widths,
  className,
}: {
  lines?: number;
  widths?: string[];
  className?: string;
}) {
  // Map over the element values (not the index param) so each key is stable.
  const rows = Array.from({ length: lines }, (_, i) => i);
  return (
    <div className={cn("space-y-2", className)}>
      {rows.map((row) => (
        <Skeleton
          key={row}
          className={cn("h-4", widths?.[row] ?? (row === lines - 1 ? "w-2/3" : "w-full"))}
        />
      ))}
    </div>
  );
}

/**
 * A vertical stack of identical row-shaped skeletons (LP-47) — for lists whose
 * rows share a height (documents, needs). Shape-match by passing the real row
 * height via `itemClassName` (e.g. `h-[58px]`) so content arrival doesn't shift.
 */
function SkeletonRows({
  count = 3,
  itemClassName,
  className,
}: {
  count?: number;
  itemClassName?: string;
  className?: string;
}) {
  const rows = Array.from({ length: count }, (_, i) => i);
  return (
    <div className={cn("space-y-2", className)}>
      {rows.map((row) => (
        <Skeleton key={row} className={cn("h-12 w-full rounded-lg", itemClassName)} />
      ))}
    </div>
  );
}

export { Skeleton, SkeletonText, SkeletonRows };
