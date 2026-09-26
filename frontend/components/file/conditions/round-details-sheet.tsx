"use client";

import { Sheet, SheetContent, SheetHeader, SheetTitle } from "@/components/ui/sheet";
import { Skeleton } from "@/components/ui/skeleton";
import { useRoundEvents } from "@/lib/api/conditions";
import { COMPLETENESS_CHIP, FORMAT_LABEL } from "@/lib/types/conditions";
import type { ConditionEnrichResult, ConditionEvent, ConditionRound } from "@/lib/types/conditions";
import { CircleCheck } from "lucide-react";
import { LetterDetails } from "./review-side-panel";

const SOURCE_LABEL: Record<string, string> = {
  pdf_upload: "PDF upload",
  email: "Forwarded PDF",
  paste: "Pasted",
  manual: "Typed",
};

/** `2026-09-10` → `09/10/2026`. */
function usDate(value: string | null): string {
  if (!value) return "—";
  const [year, month, day] = value.split("-");
  return year && month && day ? `${month}/${day}/${year}` : value;
}

/**
 * What attaching the lender's PDF actually did, in the round's own numbers (S1-09).
 *
 * ⚠️ BUILT FROM THE RESULT, NEVER A FIXED SENTENCE. The design shows "Filled the letter details, the
 * expiry dates and the codes on the 6 pasted conditions" — but an enrich can fill some of those and
 * not others, so a hardcoded sentence would claim work that did not happen. `ConditionEnrichResult`
 * carries `filled_header`, `filled_expiry`, `filled_date_printed` and `matched` precisely so the
 * screen can say what was true this time.
 *
 * ⚠️ AND THE LAST CLAUSE IS THE ONE THAT MATTERS MOST. "No new conditions, no second round" is the
 * whole promise of LP-907's merge: a processor forwarding the PDF of a round they already pasted
 * needs to know it did not duplicate their work. It is stated unconditionally because the merge
 * path cannot create either — `added` is asserted zero by the endpoint's own tests.
 */
function enrichSummary(result: ConditionEnrichResult): string {
  const filled: string[] = [];
  if (result.filled_header) filled.push("the letter details");
  if (result.filled_expiry) filled.push("the expiry dates");
  if (result.filled_date_printed) filled.push("the date printed");

  // ⚠️ `matched` IS NOT SOMETHING FILLED, AND IT WAS IN THE FILLED LIST (LP-909 review). It counts
  // the pasted rows the PDF recognised — `_merge_conditions` increments it when a row MATCHES, and
  // separately fills fields on it. So a PDF that matched six conditions and filled no letter details
  // read "Filled the codes on the 6 pasted conditions", claiming work the result does not report.
  // Worse, it made the zero case unreachable whenever matching happened: "Nothing new was found in
  // it" could not fire for an attach that filled nothing but recognised rows, which is the ordinary
  // outcome of re-attaching a sheet already pasted in full.
  const matched =
    result.matched > 0
      ? ` It matched ${result.matched} pasted ${result.matched === 1 ? "condition" : "conditions"}.`
      : "";

  const what =
    filled.length === 0
      ? "Nothing new was found in it"
      : `Filled ${filled.length === 1 ? filled[0] : `${filled.slice(0, -1).join(", ")} and ${filled.at(-1)}`}`;
  return `Lender’s PDF attached. ${what}.${matched} No new conditions, no second round.`;
}

/**
 * The round-details sheet (S1-09) — "Letter details →" from the round strip.
 *
 * ⚠️ ITS CHIPS ARE THE ROUND'S SOURCES IN ORDER, WHICH IS HOW A MERGE SHOWS ITSELF. A round pasted
 * and later enriched reads `Pasted` then `PDF upload`, because `sources` is a LIST and the enrich
 * appends rather than replaces. That ordering is the visible evidence that one round gained a
 * second arrival instead of a second round being created.
 *
 * ⚠️ THE HISTORY SECTION EXISTS NOW, AND THIS COMMENT USED TO EXPLAIN WHY IT COULD NOT. It said
 * there was no endpoint — true when written: `ConditionEvent` appeared nowhere in the API or the
 * schemas, and no service read events for a round, while LP-904 had built
 * `ix_condition_events_round_occurred` FOR this screen and paid a write on every event insert to
 * serve a query nobody made. `GET /condition-rounds/{id}/events` is that query, and the index
 * finally has its first reader.
 *
 * ⚠️ EVERY LINE IS COMPOSED FROM NAMED SCALARS, NEVER FROM `detail`. That column is NPI-classified —
 * "what changed, which is the lender's text" — and the readonly layer drops it whole, so the server
 * projects an allow-list and the sentences are built here from counts and identifiers. A history
 * panel is not a reason to open a door the readonly layer deliberately closed.
 */
export function RoundDetailsSheet({
  round,
  enrichment,
  open,
  onOpenChange,
}: {
  round: ConditionRound | null;
  /** The result of the attach that just happened, when the sheet was opened by one. */
  enrichment?: ConditionEnrichResult | null;
  open: boolean;
  onOpenChange: (open: boolean) => void;
}) {
  if (!round) return null;

  return (
    <Sheet open={open} onOpenChange={onOpenChange}>
      <SheetContent className="w-full overflow-y-auto sm:max-w-md">
        <SheetHeader>
          <SheetTitle>
            {round.round_number === null ? "Not imported yet" : `Round ${round.round_number}`} ·{" "}
            {usDate(round.round_date)}
          </SheetTitle>
        </SheetHeader>

        {/* ⚠️ THE BODY CARRIES ITS OWN GUTTER. `SheetContent` has no padding and `SheetHeader` brings
            its own `px-4`, so without this the chips, the letter and the history sat flush against
            the sheet's edge while the title above them was inset (LP-909 §5, S1-09). */}
        <div className="px-4 pb-6">
          <div className="mt-3 flex flex-wrap gap-1.5">
            {round.sources.map((source) => (
              <span
                key={`${source.kind}-${source.at ?? ""}`}
                className="rounded-md border border-input px-1.5 py-0.5 text-xs text-muted-foreground"
              >
                {SOURCE_LABEL[source.kind] ?? source.kind}
              </span>
            ))}
            <span className="rounded-md border border-input px-1.5 py-0.5 text-xs text-muted-foreground">
              {COMPLETENESS_CHIP[round.completeness]}
            </span>
            <span className="rounded-md border border-input px-1.5 py-0.5 text-xs text-muted-foreground">
              {FORMAT_LABEL[round.sheet_format] ?? round.sheet_format}
            </span>
          </div>

          {enrichment ? (
            <p className="mt-3 flex items-start gap-2 rounded-lg border border-success/40 bg-success/5 p-2 text-xs text-foreground-2">
              <CircleCheck className="mt-0.5 h-3.5 w-3.5 shrink-0 text-success" aria-hidden />
              {enrichSummary(enrichment)}
            </p>
          ) : null}

          <div className="mt-3">
            <LetterDetails round={round} />
          </div>

          <RoundHistory roundId={round.id} />
        </div>
      </SheetContent>
    </Sheet>
  );
}

/** `2026-09-10T16:31:00Z` → `09/10 4:31 PM`, the form S1-09's history lines use. */
function historyStamp(iso: string): string {
  const when = new Date(iso);
  if (Number.isNaN(when.getTime())) return iso;
  const month = `${when.getMonth() + 1}`.padStart(2, "0");
  const day = `${when.getDate()}`.padStart(2, "0");
  const time = when.toLocaleTimeString("en-US", { hour: "numeric", minute: "2-digit" });
  return `${month}/${day} ${time}`;
}

/**
 * One history line, in the processor's words (S1-09).
 *
 * ⚠️ COMPOSED FROM SCALARS, WHICH IS WHY EACH KIND GETS ITS OWN SENTENCE RATHER THAN A LABEL MAP. The
 * design's lines carry the numbers — "Imported: 0 new, 6 seen again", "Pasted (just some) · 6
 * conditions read" — and those come from `created`/`seen_again` and `source_kind`/`rows`. A map of
 * kind → string could not say them.
 *
 * ⚠️ EVERY FIELD IS OPTIONAL AND THE FALLBACK IS THE BARE EVENT, NOT A GUESS. The server projects
 * only what a writer actually stored, and `_as_int` returns null rather than coercing — so a count
 * can legitimately be absent, and the line says what happened without inventing a number for it.
 */
function historyLine(event: ConditionEvent): string {
  const { kind, rows, created, seen_again, reader, from_status } = event;

  switch (kind) {
    case "round_received":
      // ⚠️ FOUR SOURCES, AND "a sheet was received" IS FALSE FOR TWO OF THEM (LP-909 review). A
      // MANUAL round is a condition somebody typed; nothing arrived. A paste is text, not a sheet.
      // The old version said "Condition sheet received" for both, which is the class of statement
      // this stage keeps deleting.
      //
      // ⚠️ AND NO ROW COUNT HERE. The paste writer stores `{source_kind, bytes}` — never `rows` — so
      // the old `rows === null ? "" : …` arm was dead code that could not run, and the design's
      // "6 conditions read" comes from the following `ROUND_PARSED`.
      switch (event.source_kind) {
        case "paste":
          return "Pasted";
        case "manual":
          return "Typed by hand";
        case "email":
          return "Condition sheet forwarded";
        default:
          return "Condition sheet received";
      }
    case "round_parsed":
      return reader === "split"
        ? `Split by AI${rows === null ? "" : ` · ${rows} rows`}`
        : `Read by the rules${reader ? ` (${reader})` : ""}${rows === null ? "" : ` · ${rows} rows`}`;
    case "round_parse_failed":
      return "Could not be read";
    case "round_reparse_requested":
      return `Read again${from_status ? ` (was ${from_status.replace(/_/g, " ")})` : ""}`;
    case "round_imported":
      // No "as round N": the sheet's own title already says which round this is, and the design's
      // line is "Imported: 0 new, 6 seen again".
      return `Imported${
        created === null && seen_again === null
          ? ""
          : `: ${created ?? 0} new, ${seen_again ?? 0} seen again`
      }`;
    case "round_discarded":
      return "Discarded";
    case "round_enriched": {
      // ⚠️ IT USED TO CLAIM "letter details filled" UNCONDITIONALLY (LP-909 review). An enrich fills
      // only what the round was missing — `if header and not round_.header` — so attaching a PDF to a
      // paste that already carried its own letterhead fills nothing, and the line asserted otherwise.
      // The same defect as `enrichSummary` counting a match as a fill, one panel over.
      const filled = [
        event.filled_header ? "letter details" : null,
        event.filled_expiry ? "expiry dates" : null,
      ].filter((part): part is string => part !== null);
      const matched =
        event.matched && event.matched > 0
          ? ` · matched ${event.matched} condition${event.matched === 1 ? "" : "s"}`
          : "";
      return filled.length > 0
        ? `PDF attached — ${filled.join(" and ")} filled${matched}`
        : `PDF attached — nothing new to fill${matched}`;
    }
    case "condition_created":
      return "A condition was added";
    case "condition_seen_again":
      return "A condition was seen again";
    case "condition_note_added":
      return "An underwriter note was added";
    case "condition_edited":
      return "A condition was edited";
    default:
      // ⚠️ A KIND THIS BUNDLE HAS NOT HEARD OF DEGRADES TO SOMETHING HONEST rather than rendering
      // `undefined`. The enum mirror guard makes drift unlikely in CI; it cannot guard a browser tab
      // running against a backend one deploy ahead.
      return "Something happened to this round";
  }
}

/**
 * The round's history (S1-09).
 *
 * ⚠️ AN EMPTY LIST AND A FAILED FETCH SAY DIFFERENT THINGS, AND NEITHER IS SILENCE. A round always
 * has at least its `ROUND_RECEIVED` event, so "no history" is not a real state — if the list comes
 * back empty something is wrong, and saying nothing would make a broken endpoint look like a quiet
 * round.
 */
function RoundHistory({ roundId }: { roundId: string }) {
  const events = useRoundEvents(roundId);

  return (
    <div className="mt-3">
      <p className="text-xs font-medium uppercase tracking-wide text-muted-foreground">History</p>

      {events.isPending ? (
        <div className="mt-1 flex flex-col gap-1" aria-busy>
          <Skeleton className="h-3 w-3/4" />
          <Skeleton className="h-3 w-2/3" />
        </div>
      ) : events.isError ? (
        <p className="mt-1 text-xs text-muted-foreground">
          The history couldn’t be loaded. Nothing about the round has changed.
        </p>
      ) : (
        <ol className="mt-1 flex flex-col gap-1">
          {(events.data ?? []).map((event, index) => (
            <li
              key={`${event.kind}-${event.occurred_at}-${index}`}
              className="flex flex-wrap gap-1.5 text-xs text-foreground-2"
            >
              <span className="font-mono text-muted-foreground">
                {historyStamp(event.occurred_at)}
              </span>
              <span>·</span>
              <span>{historyLine(event)}</span>
            </li>
          ))}
        </ol>
      )}
    </div>
  );
}
