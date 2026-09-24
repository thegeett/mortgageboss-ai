"use client";

import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { ErrorState } from "@/components/ui/error-state";
import { Skeleton } from "@/components/ui/skeleton";
import { useConditionRounds } from "@/lib/api/conditions";
import type { ConditionRound } from "@/lib/types/conditions";
import { TriangleAlert } from "lucide-react";
import { ConditionsEmpty } from "./conditions-empty";
import { RoundFailed } from "./round-failed";
import { RoundReading } from "./round-reading";

/**
 * A round that is no longer in play. Discarded rounds stay in the list deliberately — a processor
 * who threw a draft away should see that they did — so "is there anything to work on" has to exclude
 * them explicitly rather than take the newest row.
 */
function isSettledAway(round: ConditionRound): boolean {
  return round.status === "discarded";
}

/**
 * ⚠️ A ROUND WHOSE READER ASKED FOR AI THAT NOTHING WILL EVER RUN.
 *
 * `needs_ai: true` with `ai_used: false` is the pair LP-904's schema calls "waiting for the split
 * task". On the PASTE door that is true — `_enqueue_split_or_fail` queues the split there. On the
 * upload and forward doors nothing does: `split_condition_round.delay()` is called from exactly one
 * site, inside `paste_conditions`. So on two of three doors this state is permanent.
 *
 * Recorded against LP-908, whose own section row scopes it to "a `needs_ai` PASTE". Rendered here as
 * abandoned rather than waiting, because a screen that says "waiting for AI" about work nothing will
 * do is the stranded-round failure again in a different costume.
 */
function isAbandonedByAi(round: ConditionRound): boolean {
  if (round.status !== "draft") return false;
  const { needs_ai, ai_used } = round.parse_report;
  if (!needs_ai || ai_used) return false;
  return !round.sources.some((source) => source.kind === "paste");
}

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
 * ⚠️ NO `onRetry` IS PASSED ANYWHERE, and that is a fact about the API rather than an omission.
 * `parse_condition_round.delay()` is called from creation paths only, so there is no route that
 * re-reads an existing round. Both child screens take the callback optionally so the day one exists
 * they need no change; until then a button that cannot work is worse than an absent one.
 */
export function ConditionsDashboard({
  fileId,
  onPaste,
  onAddByHand,
  onUploadAnother,
  onDiscard,
}: {
  fileId: string;
  onPaste: () => void;
  onAddByHand: () => void;
  onUploadAnother: () => void;
  onDiscard: (roundId: string) => void;
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
    return <RoundReading round={current} />;
  }

  if (current.status === "parse_failed") {
    return (
      <RoundFailed
        round={current}
        onUploadAnother={onUploadAnother}
        onPaste={onPaste}
        onDiscard={() => onDiscard(current.id)}
      />
    );
  }

  if (isAbandonedByAi(current)) {
    return (
      <Notice
        title="This sheet is waiting for a reader that will not come"
        actions={
          <>
            <Button variant="outline" size="sm" onClick={onUploadAnother}>
              Upload it again
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
        The rules could not tell where one condition ended and the next began, so this sheet needs
        the AI split — and nothing will run it for a sheet that arrived this way. Pasting the text
        starts that split; uploading again will not.
      </Notice>
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

  // ⚠️ INTERIM, AND IT SAYS SO. The review screen is §4; until then a draft with rows would
  // otherwise render as a blank tab, which reads as a broken feature rather than as unfinished work.
  return (
    <Card>
      <CardContent className="flex flex-col gap-2 p-4">
        <h2 className="text-base font-semibold text-foreground">
          {(current.draft_rows ?? []).length} conditions read, awaiting review
        </h2>
        <p className="max-w-prose text-sm text-muted-foreground">
          Nothing is saved to the file until you import. The review screen is not built yet — it
          arrives with the rest of this ticket.
        </p>
      </CardContent>
    </Card>
  );
}
