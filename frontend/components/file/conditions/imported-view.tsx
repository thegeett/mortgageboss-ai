"use client";

import { ConfirmReadingFor } from "@/components/file/conditions/confirm-reading-dialog";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import {
  useAddItem,
  useAttachPdf,
  useConditions,
  useOwner,
  usePrepStatus,
  useReopen,
  useVerdict,
} from "@/lib/api/conditions";
import { getErrorMessage } from "@/lib/errors/api-error";
import { notifyError, notifySuccess } from "@/lib/toast";
import type {
  Condition,
  ConditionEnrichResult,
  ConditionPrepStatus,
  ConditionRound,
  OwnerHint,
} from "@/lib/types/conditions";
import { Info } from "lucide-react";
import { useState } from "react";
import { MoveBackDialog, RecordAnswerDialog } from "./condition-answer-dialogs";
import { ConditionDetailSheet } from "./condition-detail-sheet";
import { ImportedConditions } from "./imported-conditions";
import { RoundDetailsSheet } from "./round-details-sheet";
import { RoundStrip } from "./round-strip";

/**
 * Our track in order, which is what makes a move "backward" — the client's copy of the backend's
 * `_PREP_RANK`.
 *
 * `review` IS ABSENT HERE FOR THE SAME REASON IT IS ABSENT THERE (default A4): it stays in the
 * database, no control offers it, and it has no rank. A move involving an unranked status is not
 * judged here at all — it is sent, and the server's own refusal is what the processor reads.
 */
const PREP_RANK: Partial<Record<ConditionPrepStatus, number>> = {
  to_do: 0,
  waiting: 1,
  ready: 2,
  with_underwriter: 3,
};

/**
 * The file's conditions after at least one round has been imported (S1-05, S1-08).
 *
 * THIS BRANCH DID NOT EXIST, AND ITS ABSENCE WAS A REAL DEFECT. An imported round fell through
 * the dashboard's `parsing` / `parse_failed` / empty-draft checks straight into `RoundReview` — so
 * importing put a processor back on a review screen, editing and re-importing rows that are no
 * longer drafts at all. `draft_rows` is CLEARED on import, so the screen would have shown nothing to
 * review while offering to import it.
 *
 * THE STRIP SHOWS EVERY ROUND, INCLUDING DISCARDED ONES. The dashboard filters those out of "what
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

  // THE ID, NOT THE ROUND. This held the round OBJECT, captured from `rounds` at the moment it was
  // opened — and on the one path S1-09 exists for, that moment is an attach's `onSuccess`, BEFORE
  // the invalidation refetches. So the sheet opened on the pre-attach round: chips without
  // `PDF upload`, "A paste has no letter…", every expiry "—", directly under a callout saying the
  // PDF had just filled them (seen in a browser, LP-909 §5; the strip behind it was already fresh).
  // Deriving from the live list each render means the sheet shows what the server now says.
  const [openRoundId, setOpenRoundId] = useState<string | null>(null);
  const openRound = rounds.find((round) => round.id === openRoundId) ?? null;
  const [enrichment, setEnrichment] = useState<ConditionEnrichResult | null>(null);

  const newest = rounds.find((round) => round.status === "imported") ?? rounds[0];

  // --- LP-916: the detail sheet and the two dialogs it opens --------------------------------- //

  const [openConditionId, setOpenConditionId] = useState<string | null>(null);
  // S3-03 (LP-919): the condition whose reading she is confirming, opened from the detail sheet.
  // S3-01's "Add an item" (LP-920).
  const addItem = useAddItem(fileId);
  const [confirmReadingId, setConfirmReadingId] = useState<string | null>(null);
  const [answerFor, setAnswerFor] = useState<Condition | null>(null);
  const [moveBack, setMoveBack] = useState<{
    condition: Condition;
    to: ConditionPrepStatus | null;
    mode: "move-back" | "reopen";
  } | null>(null);
  // The SERVER'S sentence, held while a dialog is open so it appears beside the field that caused it
  // rather than as a toast that outlives the dialog (spec §6 rule 5: shown as-is, never paraphrased).
  const [refusal, setRefusal] = useState<string | null>(null);

  const prepStatus = usePrepStatus(fileId);
  const owner = useOwner(fileId);
  const verdict = useVerdict(fileId);
  const reopen = useReopen(fileId);

  // `.rows`, because the hook returns a PAGE now: the list plus whether the server hit its 500-row
  // ceiling (LP-911's review — a capped list used to render as a complete one).
  const rows = conditions.data?.rows ?? [];

  /** Every write echoes the `updated_at` it read, so a stale one is refused rather than winning. */
  const movePrep = (condition: Condition, to: ConditionPrepStatus) => {
    const from = PREP_RANK[condition.prep_status];
    const target = PREP_RANK[to];
    if (from !== undefined && target !== undefined && target < from) {
      // BACKWARD MOVES GO THROUGH S2-05, because the server refuses one without a reason and the
      // dialog is where the reason comes from. Sending it first would mean showing a processor a
      // refusal for something the screen could have asked them for.
      setRefusal(null);
      setMoveBack({ condition, to, mode: "move-back" });
      return;
    }
    prepStatus.mutate(
      {
        conditionId: condition.id,
        to,
        // "Waiting" WITH NOBODY NAMED IS REFUSED, and the row already knows who it is waiting on —
        // S2-03 draws the control as "Waiting on Borrower" for exactly that reason. The owner comes
        // from the row rather than a second prompt.
        waiting_on: to === "waiting" ? condition.effective_owner : null,
        expected_updated_at: condition.updated_at,
      },
      {
        onError: (error) =>
          notifyError({
            title: "That status could not be changed",
            whatToDo: getErrorMessage(error),
          }),
      },
    );
  };

  const setConditionOwner = (condition: Condition, next: OwnerHint | null) =>
    owner.mutate(
      { conditionId: condition.id, owner: next, expected_updated_at: condition.updated_at },
      {
        onError: (error) =>
          notifyError({
            title: "The owner could not be changed",
            whatToDo: getErrorMessage(error),
          }),
      },
    );

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
        total={rows.length}
        // The round being attached to is the mutation's own argument. `openRound` is null while an
        // attach runs from the strip, so the card it was clicked on never showed as busy.
        busyRoundId={attach.isPending ? (attach.variables?.roundId ?? null) : null}
        onOpenDetails={(round) => {
          // A round opened from the strip shows no enrich callout — that belongs to an attach that
          // just happened, not to every visit.
          setEnrichment(null);
          setOpenRoundId(round.id);
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
                setOpenRoundId(result.round_id);
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

      {/* THE SENTENCE IS THE DESIGN'S, VERBATIM, AND IT IS STILL TRUE IN STAGE 2. Nothing in this
          list is marked cleared or removed, and only the lender clears a condition.

          ITS REASONING CHANGED WITH LP-916 AND THIS COMMENT USED TO STATE THE OLD ONE — "which is
          why the imported list has no status control of any kind". The LIST still has none, but a
          row now opens the detail sheet, and that sheet has both status controls. The promise the
          sentence makes is unaffected: `cleared` and `waived` are reachable only through a recorded
          verdict naming who said so and where (ADR-404), which is a stronger guarantee than a screen
          simply not offering a control. */}
      <p className="flex items-start gap-2 rounded-md border border-input bg-muted/40 p-2.5 text-xs text-muted-foreground">
        <Info className="mt-0.5 h-3.5 w-3.5 shrink-0" aria-hidden />
        This is the lender’s list exactly as issued. Only the lender clears a condition — nothing
        here is marked cleared or removed.
      </p>

      {newest && newest.completeness === "partial" && newest.status === "imported" ? (
        // S1-08: a round pasted as "just some" leaves everything it did not mention alone, and the
        // screen says so rather than letting absence read as removal.
        //
        // AN INFO CALLOUT, NOT A GREY LINE (S1-08 Must-match, LP-909 §5). This is the sentence
        // that stops a reader concluding the lender withdrew everything the round omitted — the same
        // job as the callout eight lines above — and it was drawn as the faintest text on the screen.
        // Matching that sibling's markup rather than inventing a third treatment.
        <p className="flex items-start gap-2 rounded-md border border-input bg-muted/40 p-2.5 text-xs text-muted-foreground">
          <Info className="mt-0.5 h-3.5 w-3.5 shrink-0" aria-hidden />
          <span>
            Round {newest.round_number} was{" "}
            {newest.sources.some((s) => s.kind === "paste") ? "pasted" : "read"} as just some.
            Conditions that weren’t in it were left as they are — nothing is removed or cleared.
          </span>
        </p>
      ) : null}

      {conditions.isPending ? (
        <div className="flex flex-col gap-2" aria-busy>
          <Skeleton className="h-24 w-full" />
          <Skeleton className="h-24 w-full" />
        </div>
      ) : (
        <ImportedConditions conditions={rows} onOpen={setOpenConditionId} />
      )}

      <RoundDetailsSheet
        round={openRound}
        enrichment={enrichment}
        open={openRound !== null}
        onOpenChange={(next) => {
          if (!next) {
            setOpenRoundId(null);
            setEnrichment(null);
          }
        }}
      />

      {/* THE SHEET IS GIVEN THE ROWS THE LIST IS RENDERING, IN THAT ORDER. That is how Previous and
          Next "follow the list's current filter and sort" without the sheet knowing what either is —
          and when LP-913 adds the filter row, they follow it with no change here. */}
      <ConditionDetailSheet
        conditions={rows}
        openId={openConditionId}
        onOpenChange={(next) => {
          if (!next) setOpenConditionId(null);
        }}
        onSelect={setOpenConditionId}
        onMovePrepStatus={movePrep}
        onSetOwner={setConditionOwner}
        onRecordAnswer={(condition) => {
          setRefusal(null);
          setAnswerFor(condition);
        }}
        onReopen={(condition) => {
          setRefusal(null);
          setMoveBack({ condition, to: null, mode: "reopen" });
        }}
        onConfirmReading={(condition) => setConfirmReadingId(condition.id)}
        onAddItem={(condition, name, performer) =>
          addItem.mutate({ conditionId: condition.id, name, performers: [performer] })
        }
      />
      <ConfirmReadingFor
        fileId={fileId}
        conditions={rows}
        conditionId={confirmReadingId}
        onClose={() => setConfirmReadingId(null)}
      />

      <RecordAnswerDialog
        conditions={answerFor ? [answerFor] : []}
        open={answerFor !== null}
        onOpenChange={(next) => {
          if (!next) setAnswerFor(null);
        }}
        refusal={refusal}
        pending={verdict.isPending}
        onSubmit={(values) => {
          if (!answerFor) return;
          setRefusal(null);
          verdict.mutate(
            { conditionId: answerFor.id, ...values, expected_updated_at: answerFor.updated_at },
            {
              onSuccess: () => setAnswerFor(null),
              // THE SERVER'S WORDS, IN THE DIALOG. A toast would be dismissed with the dialog still
              // open on the values that caused it.
              onError: (error) => setRefusal(getErrorMessage(error)),
            },
          );
        }}
      />

      <MoveBackDialog
        condition={moveBack?.condition ?? null}
        to={moveBack?.to ?? null}
        mode={moveBack?.mode ?? "move-back"}
        open={moveBack !== null}
        onOpenChange={(next) => {
          if (!next) setMoveBack(null);
        }}
        refusal={refusal}
        pending={prepStatus.isPending || reopen.isPending}
        onSubmit={(reason) => {
          if (!moveBack) return;
          setRefusal(null);
          const { condition, to, mode } = moveBack;
          const settle = {
            onSuccess: () => setMoveBack(null),
            onError: (error: unknown) => setRefusal(getErrorMessage(error)),
          };
          if (mode === "reopen") {
            reopen.mutate(
              {
                conditionId: condition.id,
                reason,
                expected_updated_at: condition.updated_at,
              },
              settle,
            );
          } else if (to) {
            prepStatus.mutate(
              {
                conditionId: condition.id,
                to,
                reason,
                waiting_on: to === "waiting" ? condition.effective_owner : null,
                expected_updated_at: condition.updated_at,
              },
              settle,
            );
          }
        }}
      />
    </div>
  );
}
