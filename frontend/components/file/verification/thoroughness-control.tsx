"use client";

import { AGGRESSION_META } from "@/components/file/verification/aggression-dial";
import { Button } from "@/components/ui/button";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { Spinner } from "@/components/ui/spinner";
import type { Aggression, AggressionLevel } from "@/lib/types/verification";
import { cn } from "@/lib/utils";
import { Check, Gauge } from "lucide-react";

/**
 * The thoroughness dial, in the header (LP-UI-046).
 *
 * The mockup puts it beside Run verification, and it was not there — it existed
 * only inside the **Old findings** tab, which is the one tab a processor has no
 * reason to open. A control nobody finds is a control that does not exist.
 *
 * WHAT IT FILTERS, SAID OUT LOUD. It re-filters the AI cross-source sweep by
 * confidence. It does NOT touch the governed rule findings, and that is a
 * decision rather than an omission:
 *
 * Measured on a real file — 38 governed findings, and the only two below the
 * Balanced cutoff are `needs_review`, the outcome whose whole purpose is that a
 * person must look at it. A confidence dial over the governed tabs would hide
 * exactly the findings that most need someone, and it would do it at the DEFAULT
 * setting. The governed engine's confidence is not a hunch-strength — a
 * deterministic rule emits 1.0 because the comparison is exact — so filtering on
 * it means something different there than it does over the sweep.
 *
 * A header control implies it governs the page, so the menu says what it governs.
 */
export function ThoroughnessControl({
  aggression,
  activeLevel,
  shownAt,
  onPick,
  busy,
}: {
  aggression: Aggression;
  activeLevel: AggressionLevel;
  /** How many AI-sweep findings survive each level — the mockup's "· 3 shown". */
  shownAt: (level: AggressionLevel) => number;
  onPick: (level: AggressionLevel) => void;
  busy: boolean;
}) {
  const order: AggressionLevel[] = ["conservative", "balanced", "thorough"];

  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <Button variant="outline" size="sm" className="gap-1.5" disabled={busy}>
          {busy ? (
            <Spinner className="h-3.5 w-3.5" />
          ) : (
            <Gauge className="h-3.5 w-3.5 text-primary" />
          )}
          Thoroughness: {AGGRESSION_META[activeLevel].label}
        </Button>
      </DropdownMenuTrigger>
      <DropdownMenuContent align="end" className="w-80">
        {order.map((level) => {
          const cutoff = aggression.cutoffs[level];
          const shown = shownAt(level);
          return (
            <DropdownMenuItem
              key={level}
              onSelect={() => onPick(level)}
              className="flex-col items-start gap-0.5 py-2"
            >
              <span className="flex w-full items-center justify-between gap-2">
                <span
                  className={cn(
                    "text-sm",
                    level === activeLevel ? "font-semibold text-foreground" : "text-foreground-2",
                  )}
                >
                  {AGGRESSION_META[level].label}
                </span>
                {level === activeLevel && <Check className="h-3.5 w-3.5 text-primary" />}
              </span>
              <span className="text-xs text-muted-foreground">
                {/* The threshold AND what it costs, as the mockup has it: a
                    cutoff with no count is a setting whose effect you find out
                    by choosing it. */}
                {cutoff <= 0 ? "every finding" : `≥ ${Math.round(cutoff * 100)}% confidence`} ·{" "}
                {shown} shown
              </span>
            </DropdownMenuItem>
          );
        })}
        <p className="border-t border-border px-2 py-2 text-xs leading-relaxed text-muted-foreground">
          Re-filters the AI cross-source findings already on this file. It never re-runs anything,
          and it never hides a rule finding — those are shown in full on the tabs above.
        </p>
      </DropdownMenuContent>
    </DropdownMenu>
  );
}
