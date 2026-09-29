"use client";

import type { ConditionListUrlState } from "@/lib/conditions/list-url";
import { CONDITION_LENDER_STATUS, resolveStatus } from "@/lib/status";
import type { ConditionSummary } from "@/lib/types/conditions";
import { cn } from "@/lib/utils";

/**
 * The seven numbers above the list (S2-01, S2-02).
 *
 * THE NUMBERS DESCRIBE THE FILE, NOT THE VIEW, and that is why they come from `/conditions/summary`
 * rather than from the rows on screen. Each one is a filter a processor clicks, so recomputing them
 * under the current filter would make "Open 6" change the moment you clicked it — the number would
 * describe its own consequence.
 *
 * A ZERO IS NEVER COLOURED (S2-01 Must-match). "Cleared 5" is worth a verified green; "Cleared 0" in
 * green is a claim of achievement about an empty set, and five greens on a fresh import would make the
 * colour mean nothing on the screen where it has to mean something.
 *
 * THE LABELS ARE THE DESIGN'S AND THEY AGREE WITH THE CHIPS. "Came back", not "Not cleared" — the same
 * word `CONDITION_LENDER_STATUS` gives the row chip and S2-04 gives its radio, so the bar, the row and
 * the dialog cannot call one state three things.
 */

/** Which filter a number applies, or `null` for the two that are counts rather than filters. */
type Cell = {
  label: string;
  value: number;
  /** The filter this number sets. `null` means clicking does nothing (see `open_prior_to_*`). */
  filter: Partial<ConditionListUrlState> | null;
  tone?: "verified" | "attention" | "progress";
};

const OPEN: Partial<ConditionListUrlState> = { lenderStatus: ["open", "not_cleared"] };

export function ConditionsSummaryBar({
  summary,
  state,
  onFilter,
}: {
  summary: ConditionSummary;
  state: ConditionListUrlState;
  onFilter: (next: ConditionListUrlState) => void;
}) {
  const cells: Cell[] = summary.has_plan ? planCells(summary) : stageTwoCells(summary);

  return (
    <div className="flex flex-wrap items-stretch overflow-hidden rounded-lg border border-input bg-card">
      {cells.map((cell) => (
        <SummaryCell key={cell.label} cell={cell} state={state} onFilter={onFilter} />
      ))}
    </div>
  );
}

/**
 * S3-12's numbers, on a file with a plan (LP-921). THE NUMBERS OVERLAP, as the screen says: a
 * condition waiting on the borrower can also have failed a check. Each one is a filter, and the count
 * is the server's own predicate for that filter, so clicking "Your tasks 2" shows two rows.
 *
 * "Failed a check" arrives with its data in LP-923; a cell that could only ever read 0 would be a claim
 * with nothing behind it.
 */
function planCells(summary: ConditionSummary): Cell[] {
  return [
    { label: "Open", value: summary.open, filter: OPEN },
    {
      label: "Waiting on others",
      value: summary.waiting_on_others,
      filter: { ...OPEN, prepStatus: ["waiting"] },
      tone: "progress",
    },
    { label: "Your tasks", value: summary.your_tasks, filter: { ...OPEN, step: ["i_will_do_it"] } },
    {
      label: "Ready to send",
      value: summary.ready_to_send,
      filter: { ...OPEN, prepStatus: ["ready"] },
      tone: "verified",
    },
    {
      label: "Prior to docs open",
      value: summary.open_prior_to_docs,
      filter: { ...OPEN, bucketKind: ["prior_to_docs"] },
    },
    {
      label: "Prior to funding open",
      value: summary.open_prior_to_funding,
      filter: { ...OPEN, bucketKind: ["prior_to_funding"] },
    },
  ];
}

/** Stage 2's seven (S2-01, S2-02), unchanged on a file with no plan. */
function stageTwoCells(summary: ConditionSummary): Cell[] {
  return [
    // OPEN MEANS OPEN OR CAME BACK, AS THE NUMBER DOES (LP-913 review). `summary.open` is LP-911's
    // `is_open` — `open` or `not_cleared` — so a filter of `open` alone showed fewer rows than the
    // number it was clicked from, and dropped every came-back condition from "Open".
    { label: "Open", value: summary.open, filter: { lenderStatus: ["open", "not_cleared"] } },
    {
      label: resolveStatus(CONDITION_LENDER_STATUS, "not_cleared").label,
      value: summary.not_cleared,
      filter: { lenderStatus: ["not_cleared"] },
      tone: "attention",
    },
    {
      label: "Cleared",
      value: summary.cleared,
      filter: { lenderStatus: ["cleared"] },
      tone: "verified",
    },
    { label: "Waived", value: summary.waived, filter: { lenderStatus: ["waived"] } },
    // "Information", not "Information only": the bar has seven cells across and the longer form is
    // the SECTION heading below the list. Both are the design's own wording for their own place.
    { label: "Information", value: summary.info_only, filter: null },
    {
      label: "Prior to docs open",
      value: summary.open_prior_to_docs,
      filter: { lenderStatus: ["open", "not_cleared"], bucketKind: ["prior_to_docs"] },
    },
    {
      label: "Prior to funding open",
      value: summary.open_prior_to_funding,
      filter: { lenderStatus: ["open", "not_cleared"], bucketKind: ["prior_to_funding"] },
    },
  ];
}

/** Every filter a cell may set, cleared together so one click never stacks on another. */
const CLEARED: Partial<ConditionListUrlState> = {
  lenderStatus: [],
  bucketKind: [],
  prepStatus: [],
  step: [],
};

function SummaryCell({
  cell,
  state,
  onFilter,
}: {
  cell: Cell;
  state: ConditionListUrlState;
  onFilter: (next: ConditionListUrlState) => void;
}) {
  const active = isActive(cell, state);
  const content = (
    <>
      <span className="text-xs font-medium uppercase tracking-wide text-muted-foreground">
        {cell.label}
      </span>
      <span
        className={cn(
          "text-lg font-semibold tabular-nums",
          // The tone applies to the NUMBER and only when there is something to describe.
          cell.value > 0 && cell.tone === "verified" && "text-success",
          cell.value > 0 && cell.tone === "attention" && "text-warning",
          cell.value > 0 && cell.tone === "progress" && "text-info",
        )}
      >
        {cell.value}
      </span>
    </>
  );

  // A cell with no filter is not a button. A control that looks clickable and does nothing is
  // the same defect as a label promising what its handler cannot do.
  if (cell.filter === null) {
    return (
      <div className="flex min-w-[5.75rem] flex-col gap-0.5 border-r border-input px-3.5 py-2 last:border-r-0">
        {content}
      </div>
    );
  }

  return (
    <button
      type="button"
      aria-pressed={active}
      onClick={() =>
        // CLICKING AN ACTIVE NUMBER CLEARS IT. A filter you cannot undo with the control that
        // set it sends a processor hunting for a Clear button to escape one click.
        onFilter(active ? { ...state, ...CLEARED } : { ...state, ...CLEARED, ...cell.filter })
      }
      className={cn(
        "flex min-w-[5.75rem] flex-col gap-0.5 border-r border-input px-3.5 py-2 text-left last:border-r-0 hover:bg-muted/40",
        "focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-primary",
        active && "shadow-[inset_0_-2px_0_hsl(var(--primary))]",
      )}
    >
      {content}
    </button>
  );
}

/**
 * Whether this cell's filter is the one currently applied.
 *
 * EXACT, NOT OVERLAPPING. "Prior to docs open" sets lender `open` AND heading `prior_to_docs`, so a
 * looser test would light BOTH it and "Open" while only one of them describes the view — and clicking
 * the lit "Open" would then not clear what a processor could see was applied.
 */
function isActive(cell: Cell, state: ConditionListUrlState): boolean {
  if (cell.filter === null) return false;
  return (
    sameSet(state.lenderStatus, cell.filter.lenderStatus ?? []) &&
    sameSet(state.bucketKind, cell.filter.bucketKind ?? []) &&
    sameSet(state.prepStatus, cell.filter.prepStatus ?? []) &&
    sameSet(state.step, cell.filter.step ?? []) &&
    state.owner.length === 0
  );
}

function sameSet(a: readonly string[], b: readonly string[]): boolean {
  return a.length === b.length && a.every((value) => b.includes(value));
}
