"use client";

/**
 * The verification stats row (LP-88) — at-a-glance "where does this file stand".
 *
 * Five counts above the findings: TOTAL findings, RED (blocking), YELLOW (warning),
 * RESOLVED, and OUTSTANDING NEEDS. Red/Yellow count the OPEN in-scope set at the active
 * dial cutoff (so they agree with the list below + the blocking computation); resolved +
 * total are over the full stored set; needs comes from the needs list.
 */

import { useNeeds } from "@/lib/api/needs";
import { outstandingNeedsCount } from "@/lib/loan-files/needs";
import type { AggressionLevel, VerificationStatus } from "@/lib/types/verification";
import { cn } from "@/lib/utils";

export function VerificationStats({
  fileId,
  data,
  activeLevel,
}: {
  fileId: string;
  data: VerificationStatus;
  activeLevel: AggressionLevel;
}) {
  const { data: needs } = useNeeds(fileId);
  const cutoff = data.aggression.cutoffs[activeLevel];
  const openInScope = data.findings.filter(
    (f) => f.resolution_status === "open" && f.confidence >= cutoff,
  );
  const red = openInScope.filter((f) => f.status === "red").length;
  const yellow = openInScope.filter((f) => f.status === "yellow").length;
  const resolved = data.findings.filter((f) => f.resolution_status !== "open").length;
  const needsCount = needs ? outstandingNeedsCount(needs) : 0;

  const tiles: { label: string; value: number; tone: string }[] = [
    { label: "Findings", value: data.findings.length, tone: "text-gray-900" },
    { label: "Blocking", value: red, tone: red > 0 ? "text-destructive" : "text-gray-400" },
    { label: "Warnings", value: yellow, tone: yellow > 0 ? "text-warning" : "text-gray-400" },
    { label: "Resolved", value: resolved, tone: resolved > 0 ? "text-success" : "text-gray-400" },
    { label: "Needs", value: needsCount, tone: needsCount > 0 ? "text-info" : "text-gray-400" },
  ];

  return (
    <div className="grid grid-cols-5 gap-2">
      {tiles.map((t) => (
        <div
          key={t.label}
          className="rounded-lg border border-gray-200 bg-white px-2 py-1.5 text-center"
        >
          <div className={cn("text-lg font-semibold tabular-nums leading-none", t.tone)}>
            {t.value}
          </div>
          <div className="mt-0.5 text-[10px] font-medium uppercase tracking-wide text-gray-400">
            {t.label}
          </div>
        </div>
      ))}
    </div>
  );
}
