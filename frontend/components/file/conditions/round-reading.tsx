"use client";

import { StatusToken } from "@/components/status-token";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { isStranded } from "@/lib/api/conditions";
import { CONDITION_ROUND_STATUS, resolveStatus } from "@/lib/status";
import type { ConditionRound, ConditionSource } from "@/lib/types/conditions";
import { cn } from "@/lib/utils";
import { CircleCheckBig, CircleDashed } from "lucide-react";

/**
 * The four steps, in the order the task does them (screen S1-02).
 *
 * ⚠️ TIMED ON THE CLIENT, AND THE DESIGN ALLOWS IT. S1-02's *May differ* says "whether the steps
 * come from the server or are timed on the client", and the server sends no progress — a round is
 * `parsing` until it is not. So these are a description of the work, not a report of it, and the
 * screen must never claim a step has FINISHED when it only knows the round is still going.
 *
 * That is why every step past the first renders as pending rather than complete: "Stored" is the one
 * thing the round's existence actually proves.
 */
const STEPS = ["Stored", "Finding conditions", "Reading the letter details", "Ready to review"];

/** The filename this round arrived as, if any source carried one. */
function sourceLabel(sources: ConditionSource[]): string | null {
  const upload = sources.find((s) => s.kind === "pdf_upload" || s.kind === "email");
  return upload ? (upload.kind === "email" ? "Forwarded PDF" : "PDF upload") : null;
}

/**
 * A round the server is still reading (screen S1-02).
 *
 * ⚠️ NO SPINNER OVER THE WHOLE PAGE — the design says so outright, and the reason is that a page
 * that blanks cannot tell a processor what it is waiting for. The card names the sheet, the steps
 * name the work, and the skeleton rows show the shape of what is coming.
 *
 * ⚠️ IT ALSO RENDERS THE STATE THE DESIGN HAS NO SCREEN FOR. A round is committed `parsing` BEFORE
 * its task is enqueued, so a broker that is down strands it forever — `_enqueue_split_or_fail`
 * documents that the upload and forward doors are deliberately unmitigated. S1-02 says "poll until
 * DRAFT or PARSE_FAILED", which does not contemplate never. Past the stranded window the polling
 * stops (see `isStranded`) and this says so, because a progress card that never resolves is the same
 * dead end as a spinner with no exit.
 *
 * ⚠️ IT NOW OFFERS THE RETRY IT USED TO EXPLAIN AWAY. This paragraph said "there is no route that
 * re-reads an existing round — `parse_condition_round.delay()` is called from creation paths only",
 * and that was true when written. `POST /condition-rounds/{id}/reparse` is that route, so the
 * dashboard passes `onRetry` and the button under the stranded copy is live.
 *
 * ⚠️ THE BUTTON APPEARS ONLY IN THE STRANDED BRANCH, WHICH IS NOT MERELY TIDY. The server REFUSES a
 * reparse on a round it is still reading, so a Try again offered during a healthy parse would 409
 * with "this sheet is still being read". Both sides now use the same bound — `STRANDED_AFTER_MS`
 * here is `STRANDED_AFTER_SECONDS` there, pinned by `test_condition_type_mirror.py` — so what this
 * screen shows and what the server will accept cannot drift apart.
 */
export function RoundReading({
  round,
  onRetry,
}: {
  round: ConditionRound;
  onRetry?: () => void;
}) {
  const stranded = isStranded(round);
  const source = sourceLabel(round.sources);

  return (
    <Card>
      <CardContent className="flex flex-col gap-3 p-4">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <div className="flex min-w-0 flex-col gap-1">
            <h2 className="text-base font-semibold text-foreground">
              {stranded ? "Still reading the condition sheet" : "Reading the condition sheet…"}
            </h2>
            <p className="text-xs text-muted-foreground">
              {source ? <span className="font-mono">{source}</span> : null}
              {source ? " · " : null}
              {stranded ? "This is taking much longer than it should." : "usually under 30 seconds"}
            </p>
          </div>
          {/* ⚠️ THROUGH `resolveStatus`, NOT A DIRECT INDEX. Indexing is compile-time safe — the map
              is typed to the union, so all five keys are forced — but the case the helper exists for
              is not a compile-time case. A backend one deploy ahead of this bundle sends a sixth
              status, the index returns `undefined`, and `StatusToken` evaluates `GLYPH[meta.tone]`:
              a TypeError that takes the card down instead of degrading to an honest unknown label.
              The enum-mirror guard makes that drift unlikely in CI; it cannot guard a browser tab. */}
          <StatusToken meta={resolveStatus(CONDITION_ROUND_STATUS, round.status)} />
        </div>

        <ol className="flex flex-wrap items-center gap-x-3 gap-y-1">
          {STEPS.map((step, index) => (
            <li key={step} className="flex items-center gap-1.5 text-xs">
              {/* Only the first is complete: the round existing proves it was stored and proves
                  nothing else. Marking later steps done would report progress nobody measured. */}
              {index === 0 ? (
                <CircleCheckBig className="h-3.5 w-3.5 text-success" aria-hidden />
              ) : (
                <CircleDashed className="h-3.5 w-3.5 text-muted-foreground" aria-hidden />
              )}
              <span className={cn(index === 0 ? "text-foreground-2" : "text-muted-foreground")}>
                {step}
              </span>
            </li>
          ))}
        </ol>

        {stranded ? (
          <div className="flex flex-col gap-2">
            {/* ⚠️ THIS SENTENCE ONCE PROMISED A ROUTE THAT DID NOT EXIST — "you can try reading it
                again", when nothing re-read an existing round. It was rewritten to stop promising
                it, and is now rewritten again because the route arrived: the reparse endpoint hands
                the stored PDF back to the reader. A paragraph and a button that finally agree. */}
            <p className="max-w-prose text-sm text-muted-foreground">
              Nothing has come back from the reader. The sheet is stored and nothing was lost — you
              can hand it back to the reader, or bring the conditions in another way.
            </p>
            {onRetry ? (
              <div>
                <Button size="sm" onClick={onRetry}>
                  Try again
                </Button>
              </div>
            ) : null}
          </div>
        ) : (
          <>
            <div className="flex flex-col gap-2" aria-hidden>
              {[0, 1, 2].map((row) => (
                <Skeleton key={row} className="h-8 w-full" />
              ))}
            </div>
            <p className="text-xs text-muted-foreground">
              You can leave this page. The file’s timeline will show “Condition sheet received”, and
              the sheet waits here for review.
            </p>
          </>
        )}
      </CardContent>
    </Card>
  );
}
