"use client";

import { Sheet, SheetContent, SheetHeader, SheetTitle } from "@/components/ui/sheet";
import type { ConditionEnrichResult, ConditionRound } from "@/lib/types/conditions";
import { CircleCheck } from "lucide-react";
import { LetterDetails } from "./review-side-panel";

const SOURCE_LABEL: Record<string, string> = {
  pdf_upload: "PDF upload",
  email: "Forwarded PDF",
  paste: "Pasted",
  manual: "Typed",
};

const FORMAT_LABEL: Record<string, string> = {
  uwm_approval_letter: "UWM · Loan Approval Conditions",
  champions_certificate: "Champions · Conditional Approval",
  generic: "Unrecognised layout",
  pasted_text: "Plain text · no lender layout found",
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
 * ⚠️ NO HISTORY SECTION, AND ITS ABSENCE IS RECORDED RATHER THAN STUBBED. The design shows three
 * entries built from the round's `condition_events` — "PDF attached — letter details filled",
 * "Imported: 0 new, 6 seen again", "Pasted (just some) · 6 conditions read". There is no endpoint:
 * `ConditionEvent` appears nowhere in `app/api/conditions.py` or `app/schemas/condition.py`, and no
 * service reads events for a round. LP-904 built `ix_condition_events_round_occurred` FOR this
 * screen — its comment says "the shape the round-details sheet reads (S1-09)" — so the index is
 * paying write cost on every event insert for a reader that was never written.
 *
 * Rendering an empty History panel would make a missing endpoint look like a round with no history,
 * which is a different and false statement. It arrives with `GET /condition-rounds/{id}/events`.
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
            {round.completeness === "full" ? "Full list" : "Just some"}
          </span>
          <span className="rounded-md border border-input px-1.5 py-0.5 text-xs text-muted-foreground">
            {FORMAT_LABEL[round.sheet_format] ?? round.sheet_format}
          </span>
        </div>

        {enrichment ? (
          <p className="mt-3 flex items-start gap-2 rounded-md border border-success/40 bg-success/5 p-2 text-xs text-foreground-2">
            <CircleCheck className="mt-0.5 h-3.5 w-3.5 shrink-0 text-success" aria-hidden />
            {enrichSummary(enrichment)}
          </p>
        ) : null}

        <div className="mt-3">
          <LetterDetails round={round} />
        </div>
      </SheetContent>
    </Sheet>
  );
}
