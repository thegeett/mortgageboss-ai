"use client";

import { Button } from "@/components/ui/button";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { OWNER_LABEL } from "@/lib/conditions/owners";
import { CONDITION_PREP_STATUS } from "@/lib/status";
import type { Condition, ConditionPrepStatus, OwnerHint } from "@/lib/types/conditions";
import { ChevronDown, X } from "lucide-react";

/**
 * The bulk bar (S2-02), shown while any row is selected.
 *
 * "3 selected · 1582 · 0006 · 0007" — THE CODES, NOT JUST THE COUNT. A processor about to record the
 * lender's answer on three conditions needs to see WHICH three, on the control that will do it; a
 * bare count is the shape that lets somebody clear a row they did not mean to touch.
 *
 * **Record lender's answer** IS THE EMPHASISED ONE (S2-02 Must-match) because it is the action this
 * screen exists for. It opens the same S2-04 dialog the detail sheet opens, with every selected row
 * listed — one dialog for the set, not one per row.
 *
 * WHAT THIS BAR DOES NOT DO IS DECIDE ANYTHING. Every action here goes to the same service the
 * single-row writes use, so a rule enforced on one row is enforced on eleven — the hole LP-912's
 * `test_bulk_goes_through_the_same_service_as_one_row` exists to keep shut. A bulk action is not a
 * way round a guard.
 */

/** The four our-track steps a processor may set. `review` is in the database and offered nowhere. */
const OFFERED_PREP: ConditionPrepStatus[] = ["to_do", "waiting", "ready", "with_underwriter"];

const OFFERED_OWNERS: OwnerHint[] = [
  "borrower",
  "title",
  "insurance",
  "lender",
  "broker",
  "processor",
  "unknown",
];

export function ConditionsBulkBar({
  selected,
  onClear,
  onSetPrepStatus,
  onSetOwner,
  onRecordAnswer,
  pending,
}: {
  /** The selected conditions, in the list's order, so the codes read as they do on screen. */
  selected: Condition[];
  onClear: () => void;
  onSetPrepStatus: (to: ConditionPrepStatus) => void;
  onSetOwner: (owner: OwnerHint) => void;
  onRecordAnswer: () => void;
  pending: boolean;
}) {
  if (selected.length === 0) return null;

  const codes = selected.map((condition) => condition.lender_code ?? "—");
  // A LONG SELECTION IS SUMMARISED RATHER THAN ALLOWED TO PUSH THE BUTTONS OFF SCREEN. Eleven codes
  // is still readable; fifty is a wall that hides the controls the bar exists to offer.
  const shown =
    codes.length > 12
      ? `${codes.slice(0, 12).join(" · ")} +${codes.length - 12}`
      : codes.join(" · ");

  return (
    <section
      // A `<section>` WITH A LABEL, NOT A DIV CLAIMING `role="region"`. Biome's `useSemanticElements`,
      // and it is the same correction it made about the list row: an element that IS the thing beats
      // an attribute asserting it, and a labelled section is a region by definition.
      //
      // Pinned at the bottom of the list (S2-02). "May differ: the bulk bar's colours … its position
      // may be the top of the list instead" — so the placement is a choice, and the bottom is the
      // design's own, nearest the rows a processor just ticked.
      className="sticky bottom-3 z-10 flex flex-wrap items-center gap-2 rounded-lg bg-foreground px-3 py-2 text-background shadow-lg"
      aria-label="Actions for the selected conditions"
    >
      <span className="text-sm font-medium tabular-nums">{selected.length} selected</span>
      <span className="min-w-0 truncate font-mono text-xs opacity-80">{shown}</span>

      <span className="flex-1" />

      <DropdownMenu>
        <DropdownMenuTrigger asChild>
          <Button
            variant="outline"
            size="sm"
            disabled={pending}
            className="border-background/25 bg-transparent text-background hover:bg-background/10"
          >
            Set status
            <ChevronDown className="h-3 w-3" aria-hidden />
          </Button>
        </DropdownMenuTrigger>
        <DropdownMenuContent align="end" className="w-48">
          {OFFERED_PREP.map((value) => (
            <DropdownMenuItem key={value} onSelect={() => onSetPrepStatus(value)}>
              {CONDITION_PREP_STATUS[value].label}
            </DropdownMenuItem>
          ))}
        </DropdownMenuContent>
      </DropdownMenu>

      <DropdownMenu>
        <DropdownMenuTrigger asChild>
          <Button
            variant="outline"
            size="sm"
            disabled={pending}
            className="border-background/25 bg-transparent text-background hover:bg-background/10"
          >
            Owner
            <ChevronDown className="h-3 w-3" aria-hidden />
          </Button>
        </DropdownMenuTrigger>
        <DropdownMenuContent align="end" className="w-48">
          {OFFERED_OWNERS.map((value) => (
            <DropdownMenuItem key={value} onSelect={() => onSetOwner(value)}>
              {OWNER_LABEL[value]}
            </DropdownMenuItem>
          ))}
        </DropdownMenuContent>
      </DropdownMenu>

      {/* THE EMPHASISED CONTROL. It opens S2-04 once for the whole selection. */}
      <Button size="sm" disabled={pending} onClick={onRecordAnswer}>
        Record lender’s answer
      </Button>

      <Button
        variant="ghost"
        size="icon-sm"
        aria-label="Clear the selection"
        onClick={onClear}
        className="text-background hover:bg-background/10"
      >
        <X className="h-3.5 w-3.5" aria-hidden />
      </Button>
    </section>
  );
}

/**
 * "4 updated · 1 skipped: information only" — what a bulk write actually did (spec §LP-913).
 *
 * IT READS THE REFUSAL **CODE**, NOT THE SENTENCE, AND THAT IS WHY IT CAN GROUP AT ALL. The bulk
 * endpoint answers 200 with `{applied, refused: [{condition_id, code, message}]}` — refusals are
 * DATA, because partial success is the expected outcome and a 409 would throw away the rows that
 * worked. So the codes arrive in the body and never through the error envelope, which is why this
 * needed no change to `lib/errors/api-error.ts` (recorded as an open question in the survey; this is
 * the answer).
 *
 * THE SENTENCE IS STILL WHAT A SINGLE REFUSAL SHOWS. Grouping needs a code; explaining needs the
 * server's words, and the dialogs show those as-is (spec §6 rule 5).
 */
export function bulkResultSummary(result: {
  applied: string[];
  refused: { code: string; message: string }[];
}): string {
  const applied = `${result.applied.length} updated`;
  if (result.refused.length === 0) return applied;

  // GROUPED BY CODE, so eleven rows refused for one reason read as one clause rather than eleven.
  const byCode = new Map<string, number>();
  for (const refusal of result.refused) {
    byCode.set(refusal.code, (byCode.get(refusal.code) ?? 0) + 1);
  }
  const skipped = [...byCode.entries()]
    .map(([code, count]) => `${count} skipped: ${REFUSAL_SUMMARY[code] ?? "not allowed"}`)
    .join(" · ");
  return `${applied} · ${skipped}`;
}

/**
 * The short reason a row was skipped, for the summary line only.
 *
 * SHORT FORMS, NOT THE SERVER'S SENTENCES. "This line is information from the lender — there is
 * nothing to track." is the right thing to show a processor who asked about ONE condition; in a
 * summary listing four outcomes it is a paragraph. The server's full sentence stays the only thing
 * shown when a single write is refused.
 *
 * A code with no entry falls back to "not allowed" rather than printing the raw code — an
 * unrecognised value in front of a processor is what the closed vocabularies exist to prevent.
 */
const REFUSAL_SUMMARY: Record<string, string> = {
  info_only_has_no_status: "information only",
  backward_move_needs_reason: "needs a reason",
  waiting_needs_owner: "no owner named",
  nothing_to_reopen: "nothing to reopen",
  verdict_needs_source: "needs a source",
  verdict_needs_round: "needs a round",
  status_not_offered: "status not offered",
  stale: "changed by someone else",
};
