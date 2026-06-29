"use client";

/**
 * The needs-completeness indicator (LP-81) — the false-confidence guard.
 *
 * Verification compares documents against the stated application; if documents are
 * still outstanding, a SPARSE result must not be mistaken for a CLEAN file. This is
 * an indicator, NOT a gate — the processor can still run verification (needs-first →
 * verification-second is the ordering, not a hard block).
 */

import { useNeeds } from "@/lib/api/needs";
import { outstandingNeedsCount } from "@/lib/loan-files/needs";
import { FileText } from "lucide-react";

export function NeedsCompleteness({ fileId }: { fileId: string }) {
  const { data } = useNeeds(fileId);
  if (!data) return null;
  const outstanding = outstandingNeedsCount(data);
  if (outstanding === 0) return null;

  return (
    <div className="flex items-start gap-2 rounded-lg border border-info/30 bg-info/5 px-3 py-2.5 text-sm text-gray-600">
      <FileText className="mt-0.5 h-4 w-4 shrink-0 text-info" />
      <span>
        Verification compares the documents against the stated application. This file has{" "}
        <span className="font-medium text-gray-800">
          {outstanding} outstanding document need{outstanding === 1 ? "" : "s"}
        </span>{" "}
        — results may be incomplete until they&rsquo;re collected.
      </span>
    </div>
  );
}
