"use client";

import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { useAttachPdf, useConditions } from "@/lib/api/conditions";
import { getErrorMessage } from "@/lib/errors/api-error";
import { notifyError, notifySuccess } from "@/lib/toast";
import type { ConditionEnrichResult, ConditionRound } from "@/lib/types/conditions";
import { Info } from "lucide-react";
import { useState } from "react";
import { ImportedConditions } from "./imported-conditions";
import { RoundDetailsSheet } from "./round-details-sheet";
import { RoundStrip } from "./round-strip";

/**
 * The file's conditions after at least one round has been imported (S1-05, S1-08).
 *
 * ⚠️ THIS BRANCH DID NOT EXIST, AND ITS ABSENCE WAS A REAL DEFECT. An imported round fell through
 * the dashboard's `parsing` / `parse_failed` / empty-draft checks straight into `RoundReview` — so
 * importing put a processor back on a review screen, editing and re-importing rows that are no
 * longer drafts at all. `draft_rows` is CLEARED on import, so the screen would have shown nothing to
 * review while offering to import it.
 *
 * ⚠️ THE STRIP SHOWS EVERY ROUND, INCLUDING DISCARDED ONES. The dashboard filters those out of "what
 * am I working on"; this is a different question — "what has happened to this file" — and a round
 * silently vanishing from the history reads as data loss.
 */
export function ImportedView({
  fileId,
  rounds,
  onPaste,
  onAddByHand,
  onUploadAnother,
}: {
  fileId: string;
  /** Every round on the file, newest first — the strip's own order. */
  rounds: ConditionRound[];
  onPaste: () => void;
  onAddByHand: () => void;
  onUploadAnother: () => void;
}) {
  const conditions = useConditions(fileId);
  const attach = useAttachPdf(fileId);

  const [openRound, setOpenRound] = useState<ConditionRound | null>(null);
  const [enrichment, setEnrichment] = useState<ConditionEnrichResult | null>(null);

  const newest = rounds.find((round) => round.status === "imported") ?? rounds[0];

  return (
    <div className="flex flex-col gap-3">
      <div className="flex flex-wrap items-center gap-2">
        <Button variant="outline" size="sm" onClick={onAddByHand}>
          Add a condition
        </Button>
        <Button variant="outline" size="sm" onClick={onPaste}>
          Paste
        </Button>
        {/* Primary, per S1-05: the next round almost always arrives as the lender's next letter. */}
        <Button size="sm" onClick={onUploadAnother}>
          Upload sheet
        </Button>
      </div>

      <RoundStrip
        rounds={rounds}
        total={conditions.data?.length ?? 0}
        busyRoundId={attach.isPending ? (openRound?.id ?? null) : null}
        onOpenDetails={(round) => {
          // A round opened from the strip shows no enrich callout — that belongs to an attach that
          // just happened, not to every visit.
          setEnrichment(null);
          setOpenRound(round);
        }}
        onAttachPdf={(roundId, file) =>
          attach.mutate(
            { roundId, file },
            {
              onSuccess: (result) => {
                notifySuccess({
                  title: "The lender’s PDF was attached",
                  consequence: "It merged into that round. No new conditions, no second round.",
                });
                // Open the details sheet on the round that was just enriched, carrying the result so
                // it can say what the PDF actually filled in (S1-09).
                setEnrichment(result);
                setOpenRound(rounds.find((round) => round.id === result.round_id) ?? null);
              },
              onError: (error) =>
                notifyError({
                  title: "That PDF could not be attached",
                  whatToDo: getErrorMessage(error),
                }),
            },
          )
        }
      />

      {/* ⚠️ THE SENTENCE IS THE DESIGN'S, VERBATIM, AND IT IS THE WHOLE PROMISE OF STAGE 1. Nothing
          here is marked cleared or removed, and only the lender clears a condition — which is why
          the imported list has no status control of any kind (design rule 3, ADR-404). */}
      <p className="flex items-start gap-2 rounded-md border border-input bg-muted/40 p-2.5 text-xs text-muted-foreground">
        <Info className="mt-0.5 h-3.5 w-3.5 shrink-0" aria-hidden />
        This is the lender’s list exactly as issued. Only the lender clears a condition — nothing
        here is marked cleared or removed.
      </p>

      {newest && newest.completeness === "partial" && newest.status === "imported" ? (
        // S1-08: a round pasted as "just some" leaves everything it did not mention alone, and the
        // screen says so rather than letting absence read as removal.
        <p className="text-xs text-muted-foreground">
          Round {newest.round_number} was{" "}
          {newest.sources.some((s) => s.kind === "paste") ? "pasted" : "read"} as just some.
          Conditions that weren’t in it were left as they are — nothing is removed or cleared.
        </p>
      ) : null}

      {conditions.isPending ? (
        <div className="flex flex-col gap-2" aria-busy>
          <Skeleton className="h-24 w-full" />
          <Skeleton className="h-24 w-full" />
        </div>
      ) : (
        <ImportedConditions conditions={conditions.data ?? []} />
      )}

      <RoundDetailsSheet
        round={openRound}
        enrichment={enrichment}
        open={openRound !== null}
        onOpenChange={(next) => {
          if (!next) {
            setOpenRound(null);
            setEnrichment(null);
          }
        }}
      />
    </div>
  );
}
