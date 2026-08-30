"use client";

/**
 * The aggression dial (LP-79) — the per-file verification thoroughness control.
 *
 * Three confidence cutoffs (Conservative → Balanced → Thorough) that filter the
 * already-computed findings (LP-78): a finding is in-scope (shown + blocking) at/above
 * the active cutoff. Moving the dial re-filters INSTANTLY — it never re-runs the AI and
 * never recolors a finding (it changes which findings are in scope, not their severity).
 * A user-level default applies unless this file overrides it.
 */

import { Spinner } from "@/components/ui/spinner";
import type { Aggression, AggressionLevel } from "@/lib/types/verification";
import { cn } from "@/lib/utils";
import { Gauge } from "lucide-react";

const ORDER: AggressionLevel[] = ["conservative", "balanced", "thorough"];

export const AGGRESSION_META: Record<AggressionLevel, { label: string; blurb: string }> = {
  conservative: {
    label: "Conservative",
    blurb: "Only findings the system is very sure about — short and high-signal.",
  },
  balanced: {
    label: "Balanced",
    blurb: "High and reasonably-confident findings, without the speculative noise.",
  },
  thorough: {
    label: "Thorough",
    blurb:
      "Almost everything, including low-confidence hunches — catches more, with more false positives.",
  },
};

export function AggressionDial({
  aggression,
  activeLevel,
  onPick,
  onResetToDefault,
  onSetAsDefault,
  busy,
}: {
  aggression: Aggression;
  activeLevel: AggressionLevel;
  onPick: (level: AggressionLevel) => void;
  onResetToDefault: () => void;
  onSetAsDefault: () => void;
  busy: boolean;
}) {
  const overriding = aggression.override !== null;
  const cutoff = aggression.cutoffs[activeLevel];
  const isDefault = activeLevel === aggression.default;

  return (
    <section
      className="rounded-lg border border-border bg-muted/60 p-3"
      aria-label="Verification thoroughness"
    >
      <div className="mb-2 flex items-center justify-between gap-2">
        <span className="inline-flex items-center gap-1.5 text-xs font-medium text-foreground-2">
          <Gauge className="h-3.5 w-3.5 text-primary" />
          Thoroughness
          {busy && <Spinner className="h-3 w-3 text-muted-foreground" />}
        </span>
        <span className="text-[11px] tabular-nums text-muted-foreground">
          shows findings ≥ {Math.round(cutoff * 100)}% confidence
        </span>
      </div>

      {/* The segmented dial — Conservative (most scrutiny filtered out) → Thorough.
          Toggle-button pattern (aria-pressed) so the active level is announced; the
          surrounding <section> already labels the group. */}
      <div className="flex gap-1 rounded-md border border-border bg-card p-1">
        {ORDER.map((level) => {
          const active = level === activeLevel;
          return (
            <button
              key={level}
              type="button"
              aria-pressed={active}
              disabled={busy}
              onClick={() => onPick(level)}
              className={cn(
                "flex-1 rounded px-2 py-1.5 text-xs font-medium transition-colors",
                "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/40",
                active
                  ? "bg-primary text-primary-foreground shadow-sm"
                  : "text-muted-foreground hover:bg-muted hover:text-foreground",
                busy && "cursor-not-allowed opacity-70",
              )}
            >
              {AGGRESSION_META[level].label}
            </button>
          );
        })}
      </div>

      <p className="mt-2 text-[11px] leading-relaxed text-muted-foreground">
        {AGGRESSION_META[activeLevel].blurb}
      </p>

      <div className="mt-2 flex flex-wrap items-center gap-x-3 gap-y-1 text-[11px]">
        {overriding ? (
          <>
            <span className="text-muted-foreground">
              Overridden for this file (your default is{" "}
              <span className="font-medium text-foreground-2">
                {AGGRESSION_META[aggression.default].label}
              </span>
              )
            </span>
            <button
              type="button"
              disabled={busy}
              onClick={onResetToDefault}
              className="text-primary underline-offset-2 hover:underline disabled:opacity-50"
            >
              Reset to default
            </button>
          </>
        ) : (
          <span className="text-muted-foreground">Using your default.</span>
        )}
        {!isDefault && (
          <button
            type="button"
            disabled={busy}
            onClick={onSetAsDefault}
            className="text-muted-foreground underline-offset-2 hover:text-foreground-2 hover:underline disabled:opacity-50"
          >
            Set {AGGRESSION_META[activeLevel].label} as my default
          </button>
        )}
      </div>
    </section>
  );
}
