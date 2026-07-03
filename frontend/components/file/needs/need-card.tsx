import { NeedActions } from "@/components/file/needs/need-actions";
import { PRIORITY_META, STATE_META, isProposed, sourceLabel } from "@/lib/loan-files/needs";
import type { NeedsItemPublic } from "@/lib/types/needs-item";
import { cn } from "@/lib/utils";
import { FileCheck2, Sparkles } from "lucide-react";

/**
 * One need on the dashboard (LP-70). Shows its state (a colored dot + pill), its
 * title/description, its source tag, and — the trust-making element — its
 * REASONING ("why is this here?", from LP-69), set apart in an inset note.
 * A proposed need gets a quiet left accent: it's awaiting the processor's review.
 */
export function NeedCard({ fileId, need }: { fileId: string; need: NeedsItemPublic }) {
  const state = STATE_META[need.status];
  const proposed = isProposed(need);
  const isAi = need.origin === "ai_reasoning" || need.origin === "suggestion";
  const showPriority = need.priority !== "standard";

  return (
    <li
      className={cn(
        "rounded-lg border border-gray-200/80 bg-white px-3.5 py-3 transition-colors",
        proposed && "border-l-[3px] border-l-primary",
      )}
    >
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0 flex-1">
          <div className="flex items-start gap-2">
            {/* Dot nudged down to sit on the first line now that the title can wrap. */}
            <span
              className={cn("mt-1.5 h-2 w-2 shrink-0 rounded-full", state.dotClass)}
              aria-hidden
            />
            {/* AI-generated titles are long descriptive sentences — wrap in full (no truncate),
                so the processor reads the whole need. The Confirm button + menu stay top-aligned. */}
            <p className="min-w-0 text-sm font-semibold text-gray-900">{need.title}</p>
          </div>

          {need.description && (
            <p className="mt-1 pl-4 text-xs text-gray-500">{need.description}</p>
          )}

          <div className="mt-2 flex flex-wrap items-center gap-1.5 pl-4">
            <span
              className={cn(
                "inline-flex items-center rounded-full border px-2 py-0.5 text-[11px] font-medium",
                state.pillClass,
              )}
            >
              {state.label}
            </span>
            {proposed && (
              <span className="inline-flex items-center rounded-full border border-primary/20 bg-primary/10 px-2 py-0.5 text-[11px] font-medium text-primary">
                Proposed — review
              </span>
            )}
            {showPriority && (
              <span
                className={cn(
                  "inline-flex items-center rounded-full border px-2 py-0.5 text-[11px] font-medium",
                  PRIORITY_META[need.priority].className,
                )}
              >
                {PRIORITY_META[need.priority].label}
              </span>
            )}
            <span className="text-[11px] font-medium uppercase tracking-wide text-gray-400">
              {sourceLabel(need.origin)}
            </span>
          </div>
        </div>

        <NeedActions fileId={fileId} need={need} />
      </div>

      {/* The "why" — explainability made visible (LP-69). The distinctive element. */}
      {need.reasoning && (
        <div className="mt-2.5 ml-4 flex gap-2 rounded-md bg-primary/[0.04] px-3 py-2">
          <Sparkles className="mt-0.5 h-3.5 w-3.5 shrink-0 text-primary/70" aria-hidden />
          <p className="text-xs leading-relaxed text-gray-600">
            <span className="sr-only">{isAi ? "AI reasoning: " : "Reasoning: "}</span>
            {need.reasoning}
          </p>
        </div>
      )}

      {/* HONEST SATISFACTION (LP-108): a graded need with documents attached (received) says so —
          the system verified a document is PRESENT, not that the full requirement (all accounts /
          months / years) is met. The processor confirms that coverage; never a false "satisfied". */}
      {need.status === "received" && (
        <div className="mt-2.5 ml-4 flex gap-2 rounded-md border border-info/20 bg-info/[0.06] px-3 py-2">
          <FileCheck2 className="mt-0.5 h-3.5 w-3.5 shrink-0 text-info" aria-hidden />
          <p className="text-xs leading-relaxed text-gray-600">
            Documents attached — confirm this covers the full requirement (all accounts / months /
            years). The system verified a document is present, not the complete coverage.
          </p>
        </div>
      )}

      {/* The matched document (evidence). LP-108: a graded received need shows "Attached: {doc}";
          a verified need shows "Satisfied by {doc}". */}
      {need.satisfied_by_document_filename && (
        <div className="mt-2 ml-4 flex items-center gap-1.5 text-xs text-gray-500">
          <FileCheck2
            className={cn(
              "h-3.5 w-3.5 shrink-0",
              need.status === "verified" ? "text-success" : "text-info",
            )}
            aria-hidden
          />
          <span className="truncate">
            {need.status === "verified" ? "Satisfied by " : "Attached: "}
            <span className="font-medium text-gray-700">{need.satisfied_by_document_filename}</span>
          </span>
        </div>
      )}

      {/* The reason a need was waived or rejected. */}
      {need.reason && <p className="mt-2 ml-4 text-xs italic text-gray-500">{need.reason}</p>}
    </li>
  );
}
