"use client";

import { railClass } from "@/components/status-token";
import type { FindingBreakdown } from "@/lib/types/calculators";
import { cn } from "@/lib/utils";
import { AlertTriangle } from "lucide-react";

/**
 * What is still unresolved, BY SYSTEM (LP-UI-021).
 *
 * ONE component, because there were three — byte-identical copies in
 * `calculator-card`, `dti-calculator` and `ltv-calculator`. Fixing the count in
 * one of them left the other two saying the old thing on the same screen, which
 * is how the DTI panel still read "91" after the shared card had stopped.
 *
 * The number itself was the defect. "91 unresolved findings" reconciled with
 * nothing a processor could see: the verification tabs show 75 governed and 13
 * legacy, and the remaining 3 — deterministic cross-source rules — appear on no
 * screen at all. One figure spanning three generators is also LP-375's
 * separation collapsed, since the governed engine and the legacy sweep are never
 * summed.
 *
 * Named parts instead, each reconcilable with a tab, rendered from the counts the
 * server produced rather than a total divided up here.
 */
export function UnresolvedAlert({ breakdown }: { breakdown: FindingBreakdown }) {
  const plural = (n: number, one: string, many: string) => `${n} ${n === 1 ? one : many}`;
  const parts: string[] = [];
  if (breakdown.governed > 0)
    parts.push(plural(breakdown.governed, "rule finding", "rule findings"));
  if (breakdown.cross_source > 0)
    parts.push(plural(breakdown.cross_source, "cross-check", "cross-checks"));
  if (breakdown.legacy > 0) parts.push(plural(breakdown.legacy, "old finding", "old findings"));
  // Counted server-side, never inferred: a generator this split does not know
  // about gets its own clause rather than inflating one of the three named ones.
  if (breakdown.other > 0) parts.push(`${breakdown.other} other`);

  return (
    <div
      role="alert"
      className={cn(
        railClass("attention"),
        "flex items-start gap-2 py-1.5 pl-3 text-sm text-foreground-2",
      )}
    >
      <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0 text-warning" />
      <span>
        <span className="font-medium text-foreground">{parts.join(", ")} unresolved</span> — this
        calculation may be incomplete until they&rsquo;re applied or overridden.
      </span>
    </div>
  );
}
