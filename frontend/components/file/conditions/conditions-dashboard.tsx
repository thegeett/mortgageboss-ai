"use client";

import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { ErrorState } from "@/components/ui/error-state";
import { Skeleton } from "@/components/ui/skeleton";
import { useConditionRounds } from "@/lib/api/conditions";
import type { ConditionRound } from "@/lib/types/conditions";
import { TriangleAlert } from "lucide-react";
import { ConditionsEmpty } from "./conditions-empty";
import { ImportedView } from "./imported-view";
import { RoundFailed } from "./round-failed";
import { RoundReading } from "./round-reading";
import { RoundReview } from "./round-review";

/**
 * A round that is no longer in play. Discarded rounds stay in the list deliberately — a processor
 * who threw a draft away should see that they did — so "is there anything to work on" has to exclude
 * them explicitly rather than take the newest row.
 */
function isSettledAway(round: ConditionRound): boolean {
  return round.status === "discarded";
}

/**
 * ⚠️ THERE IS NO "ABANDONED BY AI" SCREEN ANY MORE, AND ITS REMOVAL IS THE FIX RATHER THAN A LOSS.
 *
 * This file used to carry a notice — "this sheet is waiting for a reader that will not come" — for a
 * non-paste round whose reader asked for the AI. It was accurate when written: `split_condition_round`
 * was reachable only from `paste_conditions`, so an uploaded or forwarded sheet that needed splitting
 * waited forever.
 *
 * `parse_round` now queues the split for every door and leaves such a round `PARSING` while it runs,
 * so the state that notice described is unreachable. A screen for an unreachable state is the same
 * class of defect as a comment promising a route that does not exist: it looks maintained while
 * describing a bug that is gone, and the next reader trusts it.
 *
 * A split that genuinely FAILS is a different thing and already has a home — `split_round` settles
 * `PARSE_FAILED` with `failure_kind: "ai_unavailable"`, which `RoundFailed` renders as "The reader
 * couldn't finish this one".
 */

/** A sheet that was read successfully and yielded nothing. */
function isEmptyDraft(round: ConditionRound): boolean {
  return round.status === "draft" && (round.draft_rows ?? []).length === 0;
}

function Notice({
  title,
  children,
  actions,
}: {
  title: string;
  children: React.ReactNode;
  actions: React.ReactNode;
}) {
  return (
    <Card className="border-warning/40">
      <CardContent className="flex flex-col gap-3 p-4">
        <div className="flex items-start gap-2">
          <TriangleAlert className="mt-0.5 h-4 w-4 shrink-0 text-warning" aria-hidden />
          <div className="flex min-w-0 flex-col gap-1">
            <h2 className="text-base font-semibold text-foreground">{title}</h2>
            <p className="max-w-prose text-sm text-muted-foreground">{children}</p>
          </div>
        </div>
        <div className="flex flex-wrap items-center gap-2">{actions}</div>
      </CardContent>
    </Card>
  );
}

/**
 * The Conditions tab (LP-909 §3).
 *
 * ⚠️ IT CHOOSES ON `status`, NEVER ON THE PRESENCE OF ROWS. A `parsing` round carries the
 * rules-read rows too, so "has rows" would show a sheet as reviewable while the split was still
 * running — the trap `ConditionRound.draft_rows` warns about in its own comment.
 *
 * ⚠️ `onRetry` NOW EXISTS, AND THIS PARAGRAPH USED TO EXPLAIN WHY IT COULD NOT. It said no route
 * re-read an existing round — true then, because `parse_condition_round.delay()` was called from
 * creation paths only — and concluded that "a button that cannot work is worse than an absent one".
 * `POST /condition-rounds/{id}/reparse` is that route, so both child screens are finally passed the
 * callback they have always accepted, and the copy on them that promised it stops being a dead
 * button wearing prose.
 *
 * ⚠️ NOT THE SAME THING AS THE `ErrorState` RETRY BELOW. That one refetches the LIST when the tab
 * itself failed to load; this one asks the SERVER to read a stored sheet again. They read alike at
 * a glance and mean entirely different things, which is why the handler names differ.
 */
export function ConditionsDashboard({
  fileId,
  onPaste,
  onAddByHand,
  onUploadAnother,
  onDiscard,
  onRetry,
}: {
  fileId: string;
  onPaste: () => void;
  onAddByHand: () => void;
  onUploadAnother: () => void;
  onDiscard: (roundId: string) => void;
  /** Ask the server to read this round's stored sheet again (S1-02 stranded, S1-03 "Try again"). */
  onRetry: (roundId: string) => void;
}) {
  const rounds = useConditionRounds(fileId);

  if (rounds.isPending) {
    return (
      <div className="flex flex-col gap-2" aria-busy>
        <Skeleton className="h-24 w-full" />
        <Skeleton className="h-8 w-full" />
      </div>
    );
  }

  // `message` is REQUIRED by design rather than by accident: `ErrorState`'s own docstring records
  // that its old optional defaults were "Something went wrong" / "We couldn't load this" — an
  // apology and an instruction, telling a processor nothing they can act on — and that making it
  // required is what stops a screen falling back into saying nothing. So this says what the failure
  // means for their work instead of that something failed.
  if (rounds.isError) {
    return (
      <ErrorState
        title="The conditions couldn’t be loaded"
        message="Nothing was changed, and no sheet was lost. Try again in a moment."
        onRetry={() => void rounds.refetch()}
      />
    );
  }

  const live = (rounds.data ?? []).filter((round) => !isSettledAway(round));
  if (live.length === 0) {
    return <ConditionsEmpty fileId={fileId} onPaste={onPaste} onAddByHand={onAddByHand} />;
  }

  // Newest first is the server's order, so the round a processor is working on is the first one.
  const current = live[0] as ConditionRound;

  if (current.status === "parsing") {
    // ⚠️ THE RETRY IS OFFERED ONLY ONCE THE ROUND IS STRANDED, which `RoundReading` decides for
    // itself — it renders the button only in that branch. Passing the callback unconditionally is
    // correct: the server refuses a round it is still reading, so a button shown too early would
    // 409 with "this sheet is still being read", and the screen already knows not to show it.
    return <RoundReading round={current} onRetry={() => onRetry(current.id)} />;
  }

  if (current.status === "parse_failed") {
    return (
      <RoundFailed
        round={current}
        onRetry={() => onRetry(current.id)}
        onUploadAnother={onUploadAnother}
        onPaste={onPaste}
        onDiscard={() => onDiscard(current.id)}
      />
    );
  }

  // ⚠️ AN IMPORTED ROUND USED TO FALL THROUGH TO `RoundReview`, WHICH IS A SCREEN IT CANNOT USE.
  // `draft_rows` is CLEARED on import, so a processor who imported a sheet was put back on a review
  // screen with nothing to review and an "Import 0 conditions" button — the same class as a control
  // whose label promises what its handler cannot do.
  //
  // ⚠️ THE STRIP GETS EVERY ROUND, NOT `live`. Discarded rounds are filtered out of "what am I
  // working on" and belong in "what has happened to this file"; a round vanishing from the history
  // reads as data loss.
  if (current.status === "imported") {
    return (
      <ImportedView
        fileId={fileId}
        rounds={rounds.data ?? []}
        onPaste={onPaste}
        onAddByHand={onAddByHand}
        onUploadAnother={onUploadAnother}
      />
    );
  }

  if (isEmptyDraft(current)) {
    return (
      <Notice
        title="We read this sheet and found no conditions in it"
        actions={
          <>
            <Button variant="outline" size="sm" onClick={onUploadAnother}>
              Upload a different PDF
            </Button>
            <Button variant="outline" size="sm" onClick={onPaste}>
              Paste instead
            </Button>
            <Button
              variant="ghost"
              size="sm"
              className="text-destructive"
              onClick={() => onDiscard(current.id)}
            >
              Discard
            </Button>
          </>
        }
      >
        The file was read without trouble — it simply has no condition rows or lender headings in
        it. That usually means it is not a condition sheet.
      </Notice>
    );
  }

  // The draft a processor reviews and imports (S1-04/07/10/11). This branch used to be an interim
  // card saying the review screen was not built yet; it is now the screen.
  return <RoundReview round={current} fileId={fileId} onDiscard={() => onDiscard(current.id)} />;
}
