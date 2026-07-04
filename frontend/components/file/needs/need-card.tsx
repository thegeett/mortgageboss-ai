import { NeedActions, NeedDuplicateFlag } from "@/components/file/needs/need-actions";
import {
  PRIORITY_META,
  SOURCE_ATTRIBUTION_META,
  STATE_META,
  isProposed,
  sourceLabel,
} from "@/lib/loan-files/needs";
import type { NeedSource, NeedsItemPublic } from "@/lib/types/needs-item";
import { cn } from "@/lib/utils";
import { FileCheck2, FileSearch, Sparkles } from "lucide-react";

/**
 * The need's SOURCE (LP-110) — the specific data that TRIGGERED it, honestly attributed by origin
 * so the reasoning is FALSIFIABLE: the processor can verify the AI didn't misread. Mirrors the
 * finding "Source" section (a bordered inset + a trust pill). A deterministic rule reads as certain;
 * an AI-identified source is marked "verify" and links to the underlying record where one exists.
 */
function NeedSourceNote({ source }: { source: NeedSource }) {
  const meta = SOURCE_ATTRIBUTION_META[source.attribution];
  return (
    <div className="mt-2 ml-4 rounded-md border border-gray-100 bg-gray-50/70 px-3 py-2">
      <div className="flex items-center gap-1.5 text-[11px] font-medium uppercase tracking-wide text-gray-400">
        <FileSearch className="h-3.5 w-3.5 shrink-0" aria-hidden />
        Source
        <span
          className={cn(
            "rounded px-1 py-px text-[10px] font-medium normal-case tracking-normal",
            meta.pillClass,
          )}
        >
          {meta.pill}
        </span>
      </div>
      <ul className="mt-1 space-y-1">
        {source.facts.map((fact) => (
          <li key={fact.ref ?? `${fact.kind}:${fact.label}`} className="text-xs text-gray-600">
            <span className="text-gray-400">{meta.lead}: </span>
            <span className="font-medium text-gray-700">{fact.label}</span>
            {/* Ground to the verifiable record — name the finding's source document (LP-105). */}
            {fact.document_filename && (
              <span className="mt-0.5 flex items-center gap-1.5 text-gray-500">
                <FileCheck2 className="h-3 w-3 shrink-0 text-info" aria-hidden />
                <span className="truncate">{fact.document_filename}</span>
              </span>
            )}
          </li>
        ))}
      </ul>
      {/* GROUNDED-STARTER (validate-with-Priya): the AI's cited source is its own reading — mark it
          so the processor checks the AI cited the RIGHT triggering fact. */}
      {meta.aiIdentified && (
        <p className="mt-1 text-[10px] text-gray-400">
          AI-identified — verify this is the right triggering fact; the AI may have misread.
        </p>
      )}
    </div>
  );
}

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

      {/* The SOURCE (LP-110) — the specific data the reasoning stands on, so it's FALSIFIABLE. Sits
          with the "why": the reasoning is the argument, the source is the checkable fact under it. */}
      {need.source && <NeedSourceNote source={need.source} />}

      {/* The possible-duplicate flag (LP-111) — the AI SURFACES a likely duplicate; the processor
          disposes (merge / keep both). Never a silent merge. */}
      {need.possible_duplicate_of && <NeedDuplicateFlag fileId={fileId} need={need} />}

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

      {/* The matched documents (evidence). LP-109: a graded need shows ALL matching documents
          (derive-on-read) so the processor confirms coverage against the full set; a simple-presence
          need shows its single satisfying document. */}
      {need.matching_documents.length > 0 ? (
        <div className="mt-2 ml-4">
          <p className="text-[11px] font-medium uppercase tracking-wide text-gray-400">
            {need.matching_documents.length} matching document
            {need.matching_documents.length === 1 ? "" : "s"}
          </p>
          <ul className="mt-1 space-y-0.5">
            {need.matching_documents.map((doc) => (
              <li key={doc.id} className="flex items-center gap-1.5 text-xs text-gray-600">
                <FileCheck2 className="h-3.5 w-3.5 shrink-0 text-info" aria-hidden />
                <span className="truncate font-medium text-gray-700">{doc.filename}</span>
              </li>
            ))}
          </ul>
        </div>
      ) : (
        need.satisfied_by_document_filename && (
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
              <span className="font-medium text-gray-700">
                {need.satisfied_by_document_filename}
              </span>
            </span>
          </div>
        )
      )}

      {/* The reason a need was waived or rejected. */}
      {need.reason && <p className="mt-2 ml-4 text-xs italic text-gray-500">{need.reason}</p>}
    </li>
  );
}
