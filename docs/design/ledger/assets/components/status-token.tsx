import type { StatusMeta, Tone } from "@/lib/status";
import { cn } from "@/lib/utils";
import {
  CircleCheckBig,
  CircleDashed,
  CircleX,
  LoaderCircle,
  Sparkles,
  TriangleAlert,
} from "lucide-react";
import type { LucideIcon } from "lucide-react";

/**
 * LEDGER — the one way this app shows a status.                     LP-UI-005
 * ===========================================================================
 * Three channels, always: COLOUR + GLYPH SHAPE + WORD. Never colour alone.
 *
 * Three presentations, one vocabulary:
 *   <StatusToken meta={m} />                 inline glyph + word (the default)
 *   <StatusToken meta={m} variant="dot" />   glyph only, word in the a11y name
 *   <StatusRail tone={m.tone}>…</StatusRail> 2px left rail around a whole row
 *
 * State goes on the LEFT RAIL and the GLYPH, never on a background fill.
 * Fills stack badly — what does a hovered, focused, low-confidence, conflicting
 * row look like? — and they cost text contrast. A rail composes with hover and
 * focus, costs no contrast, and scans vertically down a forty-row list.
 */

const GLYPH: Record<Tone, LucideIcon> = {
  blocking: CircleX,
  attention: TriangleAlert,
  verified: CircleCheckBig,
  progress: LoaderCircle,
  neutral: CircleDashed,
  ai: Sparkles,
};

const TEXT: Record<Tone, string> = {
  blocking: "text-destructive",
  attention: "text-warning",
  verified: "text-success",
  progress: "text-info",
  neutral: "text-muted-foreground",
  ai: "text-ai",
};

const RAIL: Record<Tone, string> = {
  blocking: "border-l-destructive",
  attention: "border-l-warning",
  verified: "border-l-success",
  progress: "border-l-info",
  neutral: "border-l-border-strong",
  ai: "border-l-ai",
};

/** Tinted pill. Use sparingly — a count badge or a filter chip, not a row state. */
const CHIP: Record<Tone, string> = {
  blocking: "bg-destructive/10 text-destructive",
  attention: "bg-warning/10 text-warning",
  verified: "bg-success/10 text-success",
  progress: "bg-info/10 text-info",
  neutral: "bg-muted text-muted-foreground",
  ai: "bg-ai/10 text-ai",
};

export function StatusToken({
  meta,
  variant = "inline",
  className,
}: {
  meta: StatusMeta;
  variant?: "inline" | "dot" | "chip";
  className?: string;
}) {
  const Icon = GLYPH[meta.tone];
  const spin = meta.spin ? "animate-spin" : undefined;

  if (variant === "dot") {
    return (
      <span className={cn("inline-flex", TEXT[meta.tone], className)} title={meta.label}>
        <Icon className={cn("h-3.5 w-3.5", spin)} aria-hidden />
        <span className="sr-only">{meta.label}</span>
      </span>
    );
  }

  if (variant === "chip") {
    return (
      <span
        className={cn(
          "inline-flex items-center gap-1.5 whitespace-nowrap rounded-full px-2 py-0.5 text-xs font-medium",
          CHIP[meta.tone],
          className,
        )}
      >
        <Icon className={cn("h-3 w-3 shrink-0", spin)} aria-hidden />
        {meta.label}
      </span>
    );
  }

  return (
    <span
      className={cn(
        "inline-flex items-center gap-1.5 whitespace-nowrap text-sm",
        TEXT[meta.tone],
        className,
      )}
    >
      <Icon className={cn("h-3.5 w-3.5 shrink-0", spin)} aria-hidden />
      {meta.label}
    </span>
  );
}

/**
 * The 2px left rail. Wraps a row, a finding, a field, a card — anything whose
 * whole state should read at a glance while scanning down a column.
 */
export function StatusRail({
  tone,
  children,
  className,
}: {
  tone: Tone;
  children: React.ReactNode;
  className?: string;
}) {
  return <div className={cn("border-l-2", RAIL[tone], className)}>{children}</div>;
}

/** The rail as a table-cell modifier, for `<td>` in a dense grid. */
export function railClass(tone: Tone): string {
  return cn("border-l-2", RAIL[tone]);
}
