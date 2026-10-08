"use client";

import { StatusToken } from "@/components/status-token";
import { Button } from "@/components/ui/button";
import { EmptyState } from "@/components/ui/empty-state";
import { Select } from "@/components/ui/select";
import { groupConditions } from "@/lib/conditions/grouping";
import type { ConditionGroupBy, ConditionListUrlState } from "@/lib/conditions/list-url";
import { describeConditionFilters } from "@/lib/conditions/list-url";
import { lenderAnswerLabel } from "@/lib/conditions/next-action";
import { isDisplayOnly, waitingLabel } from "@/lib/conditions/next-step";
import { OWNER_LABEL } from "@/lib/conditions/owners";
import { displayWording } from "@/lib/conditions/wording";
import { CONDITION_LENDER_STATUS, CONDITION_PREP_STATUS, resolveStatus } from "@/lib/status";
import type { Condition, ConditionPrepStatus } from "@/lib/types/conditions";
import { BUCKET_KIND_CHIP } from "@/lib/types/conditions";
import { cn } from "@/lib/utils";
import { ChevronRight, Info, Landmark } from "lucide-react";
import { useRef, useState } from "react";
import { NextStepCell } from "./next-step-cell";

/**
 * The conditions list (S2-01, S2-02, S2-09) — the processor's main screen for conditions.
 *
 * WHAT IS IN THE GROUPS IS ONLY WHAT IS STILL OPEN (S2-02 Must-match: "Only open conditions are in
 * the groups. The heading with none left open isn't shown."). Everything settled moves to a collapsed
 * section at the bottom — **and moves, never disappears** (spec §6 rule 3). A processor needs to say
 * "that was cleared on the 12th" long after it stopped being work.
 *
 * THE ROW NEVER SAYS "CLEARED" ON ITS OWN. The chip reads `CONDITION_LENDER_STATUS`, and that status
 * only leaves `open` through a recorded verdict naming who said so and where (ADR-404) — so the word
 * on screen is always backed by one. The list invents no status of its own.
 *
 * SHEET ORDER INSIDE EVERY GROUP, WHATEVER THE GROUPING. `sequence` is the order the lender printed
 * them, which is the order the processor sees in the lender's own portal; regrouping changes which
 * rows sit together, never their order within a group.
 */

/** Which bottom section a condition belongs to, or `null` while it is still live work. */
function settledSection(condition: Condition): string | null {
  // ORDER IS PRECEDENCE, AND INFORMATION WINS. An information-only line asks for nothing, so it is
  // never "cleared" — it had no status to clear (LP-912's `info_only_has_no_status`).
  if (condition.info_only) return "Information only";
  if (condition.lender_status === "superseded") return "Replaced";
  if (condition.lender_status === "cleared" || condition.lender_status === "waived") {
    return "Cleared";
  }
  // The lender is doing this one; it is not our work, but it is not settled either.
  if (condition.bucket_kind === "lender_to_clear") return "Lender is doing it";
  return null;
}

const OFFERED_PREP: ConditionPrepStatus[] = ["to_do", "waiting", "ready", "with_underwriter"];

export function ConditionsList({
  conditions,
  settledFrom,
  state,
  search,
  capped,
  selected,
  onSelectedChange,
  onOpen,
  onMovePrepStatus,
  onOpenDraft,
  onRecordAnswer,
  onClearFilters,
  suggestedIds,
  suggestedRoundNumber,
  unplannedIds,
}: {
  /** The rows the server returned for the CURRENT filters. Grouped here, in sheet order. */
  conditions: Condition[];
  /**
   * Every row on the file, UNFILTERED — the source for the collapsed sections at the bottom.
   *
   * THE SETTLED SECTIONS MUST SURVIVE THE FILTERS. S2-09 says so in as many words: with filters that
   * match nothing, "the Cleared section is still shown below". Deriving those sections from the
   * filtered rows would make them vanish exactly when a processor is most likely to be looking for
   * one — "that was cleared on the 12th" is a question asked while hunting for something else.
   *
   * Defaults to the filtered rows so a caller with nothing else to give still renders sensibly.
   */
  settledFrom?: Condition[];
  state: ConditionListUrlState;
  search: string;
  /** True when the server stopped at its 500-row ceiling. */
  capped: boolean;
  selected: ReadonlySet<string>;
  onSelectedChange: (next: ReadonlySet<string>) => void;
  onOpen: (conditionId: string) => void;
  onMovePrepStatus: (condition: Condition, to: ConditionPrepStatus) => void;
  /** LP-922 — opens a draft email from its Next step token. */
  onOpenDraft?: (draftId: string) => void;
  /** LP-958 — the row's "Record" beside "Not cleared yet": opens S2-04 for that one condition. */
  onRecordAnswer?: (condition: Condition) => void;
  onClearFilters: () => void;
  /**
   * LP-964 — conditions whose round's plan is not confirmed yet. Their Next step reads "Plan not
   * confirmed yet" instead of the AI's proposal, which would otherwise look decided. Only reachable
   * when she opens the list early with "Show them now"; once the plan is confirmed this is empty.
   */
  unplannedIds?: ReadonlySet<string>;
  /**
   * Conditions a round's comparison suggests probably cleared (LP-915, S2-06).
   *
   * THE ROW SAYS "REVIEW", NOT "CLEARED". These rows are still `open` and their status chip still
   * reads Open — the line is a pointer to the panel's question, and it disappears the moment she
   * answers it either way.
   */
  suggestedIds?: ReadonlySet<string>;
  /** Which round suggested them — "Probably cleared in round 2 — review". */
  suggestedRoundNumber?: number | null;
}) {
  // SHEET ORDER, WHATEVER THE GROUPING. `sequence` is the order the lender printed them, which is
  // the order the processor sees in the lender's own portal.
  const bySequence = [...conditions].sort((a, b) => a.sequence - b.sequence);

  // THE GROUPS COME FROM THE FILTERED ROWS; THE SECTIONS COME FROM ALL OF THEM. Two sources, because
  // they answer two questions — "what matches what I asked for" and "what has already been settled
  // on this file" — and only the first one is a filter's business.
  const live = bySequence.filter((condition) => settledSection(condition) === null);

  const settled = new Map<string, Condition[]>();
  for (const condition of [...(settledFrom ?? conditions)].sort(
    (a, b) => a.sequence - b.sequence,
  )) {
    const section = settledSection(condition);
    if (section === null) continue;
    const rows = settled.get(section) ?? [];
    rows.push(condition);
    settled.set(section, rows);
  }

  // Runs by heading, one group per value by owner or status — see `groupConditions`.
  const groups = groupConditions(live, state.groupBy);

  const filtered = describeConditionFilters(state, search);

  function toggle(id: string) {
    const next = new Set(selected);
    if (next.has(id)) next.delete(id);
    else next.add(id);
    onSelectedChange(next);
  }

  const container = useRef<HTMLDivElement>(null);

  /**
   * "↑ ↓ to move, Enter to open, `x` to select" (spec §LP-913).
   *
   * ENTER IS NOT HANDLED HERE because it already works: every row is a real `<button>`, so Enter and
   * Space activate it natively. That is the payoff for making the row a button rather than a div
   * with `role="button"` — three keyboard behaviours arrive for free and none of them can drift.
   *
   * A SELECT SWALLOWS THE ARROWS, DELIBERATELY. The inline status control is inside each row, and
   * ↑ ↓ inside an open select must change the option under the cursor, not jump to another condition.
   * Same exclusion the detail sheet makes, for the same reason.
   */
  function onKeyDown(event: React.KeyboardEvent<HTMLDivElement>) {
    const { key } = event;
    if (key !== "ArrowUp" && key !== "ArrowDown" && key.toLowerCase() !== "x") return;

    const target = event.target as HTMLElement;
    const tag = target.tagName;
    if (tag === "INPUT" || tag === "TEXTAREA" || tag === "SELECT" || target.isContentEditable) {
      return;
    }

    const rows = Array.from(
      container.current?.querySelectorAll<HTMLElement>("[data-condition-row]") ?? [],
    );
    if (rows.length === 0) return;
    const current = rows.findIndex((row) => row.contains(target));

    if (key.toLowerCase() === "x") {
      // `x` TOGGLES THE ROW THE PROCESSOR IS ON, and does nothing when focus is not on a row —
      // rather than guessing at "the first one", which would tick a condition nobody was looking at.
      const id = current >= 0 ? rows[current]?.dataset.conditionRow : undefined;
      if (id) {
        event.preventDefault();
        toggle(id);
      }
      return;
    }

    event.preventDefault();
    // From outside the list, either arrow enters at the first row. Clamped at both ends rather than
    // wrapping: wrapping from the last row to the first reads as the list having jumped.
    const next =
      key === "ArrowDown" ? Math.min(current + 1, rows.length - 1) : Math.max(current - 1, 0);
    rows[next]?.focus();
  }

  return (
    // THE HANDLER IS ON THE CONTAINER BECAUSE IT MOVES BETWEEN ROWS. Each row is already a real
    // button handling its own Enter and Space; putting this on every row would give each one a copy
    // of the list's navigation. Keydown bubbles, so the container sees keys pressed on any row.
    <div ref={container} onKeyDown={onKeyDown} className="flex flex-col gap-2">
      {capped ? (
        // THE CAP IS SAID OUT LOUD, because a truncated list that looks complete is the failure the
        // cap exists to prevent — the server reports it in a header precisely so this can be said.
        <p className="flex items-start gap-2 rounded-md border border-warning/40 bg-warning/5 p-2.5 text-xs text-foreground-2">
          <Info className="mt-0.5 h-3.5 w-3.5 shrink-0 text-warning" aria-hidden />
          This file has more conditions than one page shows. Narrow the filters to see the rest —
          nothing is missing from the file, only from this view.
        </p>
      ) : null}

      {live.length === 0 ? (
        filtered.length > 0 ? (
          <EmptyState
            kind="filtered"
            title={`No condition matches ${filtered.join(" · ")}`}
            action={
              <Button variant="outline" size="sm" onClick={onClearFilters}>
                Clear filters
              </Button>
            }
          >
            {/* The settled rows are still below, so "nothing here" would be untrue as well as
                unhelpful — say where they went. */}
            {settled.size > 0
              ? "Conditions that are cleared, replaced or information-only are in the sections below."
              : "Nothing on this file matches those filters."}
          </EmptyState>
        ) : (
          <EmptyState kind="structural" title="Nothing open on this file">
            Every condition has been answered. They are in the sections below, with the lender’s
            answer and where it came from on each.
          </EmptyState>
        )
      ) : (
        groups.map((group, index) => (
          <ConditionGroup
            key={`${index}-${group.key}`}
            heading={group.key}
            groupBy={state.groupBy}
            rows={group.rows}
            selected={selected}
            onToggle={toggle}
            onOpen={onOpen}
            onMovePrepStatus={onMovePrepStatus}
            onOpenDraft={onOpenDraft}
            onRecordAnswer={onRecordAnswer}
            suggestedIds={suggestedIds}
            suggestedRoundNumber={suggestedRoundNumber}
            unplannedIds={unplannedIds}
          />
        ))
      )}

      {[...settled.entries()].map(([section, rows]) => (
        <SettledSection
          key={section}
          title={section}
          rows={rows}
          selected={selected}
          onToggle={toggle}
          onOpen={onOpen}
        />
      ))}
    </div>
  );
}

function ConditionGroup({
  heading,
  groupBy,
  rows,
  selected,
  onToggle,
  onOpen,
  onMovePrepStatus,
  onOpenDraft,
  onRecordAnswer,
  suggestedIds,
  suggestedRoundNumber,
  unplannedIds,
}: {
  heading: string;
  groupBy: ConditionGroupBy;
  rows: Condition[];
  selected: ReadonlySet<string>;
  onToggle: (id: string) => void;
  onOpen: (id: string) => void;
  onMovePrepStatus: (condition: Condition, to: ConditionPrepStatus) => void;
  /** LP-922 — opens a draft email from its Next step token. */
  onOpenDraft?: (draftId: string) => void;
  onRecordAnswer?: (condition: Condition) => void;
  suggestedIds?: ReadonlySet<string>;
  suggestedRoundNumber?: number | null;
  unplannedIds?: ReadonlySet<string>;
}) {
  const first = rows[0];
  // The kind chip belongs to a LENDER HEADING. Grouped by owner or status the heading is ours, and a
  // bucket chip beside it would attach the lender's vocabulary to our own grouping.
  const chip = groupBy === "heading" && first ? BUCKET_KIND_CHIP[first.bucket_kind] : null;
  const showChip = chip !== null && chip.toLowerCase() !== heading.toLowerCase();

  return (
    <div className="overflow-hidden rounded-lg border border-input bg-card">
      <div className="flex items-center gap-2 border-b border-input bg-muted/40 px-3 py-2">
        <span className="text-sm font-semibold text-foreground">{heading}</span>
        {showChip ? (
          <span className="rounded-md border border-input px-1.5 py-0.5 text-xs text-muted-foreground">
            {chip}
          </span>
        ) : null}
        <span className="ml-auto text-xs text-muted-foreground">{rows.length}</span>
      </div>

      <div className="grid grid-cols-[1.5rem_3.5rem_minmax(0,1fr)_14rem_10.5rem_9.5rem] gap-3 border-b border-input px-3 py-1.5 text-xs font-medium uppercase tracking-wide text-muted-foreground">
        <span />
        <span>Code</span>
        <span>Lender’s words</span>
        {/* NEXT STEP WHERE OWNER WAS (S3-12, LP-934 M3). The owner stays in the Owner filter and on
            the detail sheet. */}
        <span>Next step</span>
        <span>Our status</span>
        {/* LP-958 — "Lender" read as a state of ours ("What is that Open last column for?"). */}
        <span>Lender’s answer</span>
      </div>

      {rows.map((condition) => (
        <ConditionRow
          key={condition.id}
          condition={condition}
          checked={selected.has(condition.id)}
          onToggle={() => onToggle(condition.id)}
          onOpen={() => onOpen(condition.id)}
          onMovePrepStatus={onMovePrepStatus}
          onOpenDraft={onOpenDraft}
          onRecordAnswer={onRecordAnswer ? () => onRecordAnswer(condition) : undefined}
          suggestedInRound={suggestedIds?.has(condition.id) ? (suggestedRoundNumber ?? null) : null}
          unplanned={unplannedIds?.has(condition.id) ?? false}
        />
      ))}
    </div>
  );
}

function ConditionRow({
  condition,
  checked,
  onToggle,
  onOpen,
  onMovePrepStatus,
  onOpenDraft,
  onRecordAnswer,
  suggestedInRound,
  unplanned,
}: {
  condition: Condition;
  checked: boolean;
  onToggle: () => void;
  onOpen: () => void;
  onMovePrepStatus: (condition: Condition, to: ConditionPrepStatus) => void;
  /** LP-922 — opens a draft email from its Next step token. */
  onOpenDraft?: (draftId: string) => void;
  onRecordAnswer?: () => void;
  /** LP-964 — its round's plan is not confirmed yet. */
  unplanned: boolean;
  /** The round that suggests this one probably cleared, or null when none does. */
  suggestedInRound?: number | null;
}) {
  const lenderMeta = resolveStatus(CONDITION_LENDER_STATUS, condition.lender_status);

  return (
    <div
      className={cn(
        "relative grid grid-cols-[1.5rem_3.5rem_minmax(0,1fr)_14rem_10.5rem_9.5rem] items-start gap-3 border-b border-input px-3 py-2.5 last:border-b-0",
        checked && "bg-primary/5",
      )}
    >
      {/* THE AMBER RAIL FOR A CAME-BACK (S2-08). Only for the note-driven case, which is what
          `came_back` means — a `not_cleared` recorded by phone is not one. */}
      {condition.came_back ? (
        <span className="absolute left-0 top-0 bottom-0 w-0.5 bg-warning" aria-hidden />
      ) : null}

      {/* A NATIVE CHECKBOX, the pattern this feature already uses (`round-review.tsx`). It is OUTSIDE
          the row button: nesting an input inside a button is invalid, and clicking to select must not
          also open the sheet. */}
      <label className="flex cursor-pointer items-center pt-0.5">
        <input
          type="checkbox"
          className="accent-primary"
          checked={checked}
          onChange={onToggle}
          aria-label={`Select ${condition.lender_code ?? "condition"}`}
        />
      </label>

      <button
        type="button"
        onClick={onOpen}
        // The list's ↑ ↓ / `x` handler finds rows by this attribute and reads the id from it, so
        // navigation follows the DOM order — which is the order on screen, whatever the grouping.
        data-condition-row={condition.id}
        className="col-span-2 grid grid-cols-[3.5rem_minmax(0,1fr)] items-start gap-3 text-left focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-primary"
      >
        <span className="flex flex-col gap-1">
          <span className="font-mono text-xs font-medium text-foreground-2">
            {condition.lender_code ?? "—"}
          </span>
          <span className="flex flex-wrap gap-1">
            {condition.round_numbers.map((number) => (
              <span
                key={number}
                className="rounded-md border border-input px-1 py-0.5 font-mono text-[10.5px] text-muted-foreground"
              >
                R{number}
              </span>
            ))}
          </span>
        </span>

        <span className="flex min-w-0 flex-col gap-1.5">
          {/* CLAMPED TO TWO LINES (S2-01), full wording in the detail sheet. The note is cut from the
              display only — `verbatim_text` still holds it, and Copy text copies the whole thing. */}
          <span className="line-clamp-2 max-w-prose font-serif text-sm text-foreground">
            {displayWording(condition.verbatim_text, condition.underwriter_notes.length)}
          </span>
          {condition.latest_note ? (
            <span className="inline-flex w-fit items-baseline gap-1.5 rounded-md border-l-2 border-warning bg-muted px-1.5 py-0.5 text-xs">
              {condition.latest_note.date ? (
                <span className="font-mono text-warning">
                  {condition.latest_note.date.slice(5).replace("-", "/")}
                </span>
              ) : null}
              <span className="line-clamp-1 text-foreground-2">{condition.latest_note.text}</span>
            </span>
          ) : null}
          {/* "Probably cleared in round 2 — review" (S2-06). A QUESTION ON THE ROW, and the status
              column beside it still reads Open — which is the whole distinction between a suggestion
              and a verdict (design rule 4). */}
          {suggestedInRound !== null && suggestedInRound !== undefined ? (
            <span className="inline-flex w-fit items-center gap-1 text-xs font-medium text-primary">
              Probably cleared in round {suggestedInRound} — review
            </span>
          ) : null}
        </span>
      </button>

      <NextStepCell condition={condition} onOpenDraft={onOpenDraft} unplanned={unplanned} />

      {/* A DISPLAY-ONLY STEP HAS NO STATUS OF ITS OWN (S3-12, LP-934 M4): "Lender is doing it" stays in
          its heading group, neutral, with no select — it is not ours to move. */}
      {isDisplayOnly(condition) ? (
        <span className="inline-flex items-center gap-1.5 pt-0.5 text-sm text-muted-foreground">
          {condition.next_step === "lender_doing_it" ? (
            <Landmark className="h-3.5 w-3.5" aria-hidden />
          ) : (
            <Info className="h-3.5 w-3.5" aria-hidden />
          )}
          {condition.next_step === "lender_doing_it" ? "Lender is doing it" : "Information only"}
        </span>
      ) : (
        /* INLINE, AND IT UPDATES STRAIGHT AWAY. A backward move opens S2-05 instead, because the
           server refuses one without a reason and the dialog is where the reason comes from. */
        <Select
          aria-label={`Our status for ${condition.lender_code ?? "this condition"}`}
          value={condition.prep_status}
          onChange={(event) => {
            const to = event.target.value as ConditionPrepStatus;
            if (to !== condition.prep_status) onMovePrepStatus(condition, to);
          }}
        >
          {(OFFERED_PREP.includes(condition.prep_status)
            ? OFFERED_PREP
            : [condition.prep_status, ...OFFERED_PREP]
          ).map((value) => (
            <option key={value} value={value}>
              {/* "Waiting on Borrower", not "Waiting on someone", once we know who (S3-12). */}
              {value === "waiting" && condition.waiting_on
                ? `Waiting on ${waitingLabel(condition.waiting_on)}`
                : CONDITION_PREP_STATUS[value].label}
            </option>
          ))}
        </Select>
      )}

      <span className="flex flex-wrap items-center gap-x-2 gap-y-0.5 pt-0.5">
        <StatusToken
          meta={{
            ...lenderMeta,
            label: lenderAnswerLabel(condition.lender_status, lenderMeta.label),
          }}
        />
        {/* Only while the lender still owes an answer and the row takes writes (not a replaced one). */}
        {onRecordAnswer &&
        condition.superseded_by_id === null &&
        (condition.lender_status === "open" || condition.lender_status === "not_cleared") ? (
          <button
            type="button"
            onClick={onRecordAnswer}
            aria-label={`Record the lender’s answer for ${condition.lender_code ?? "this condition"}`}
            className="text-xs text-primary hover:underline"
          >
            Record
          </button>
        ) : null}
      </span>
    </div>
  );
}

/**
 * "Cleared (5)", "Information only (1)", "Lender is doing it (4)", "Replaced (1)" — collapsed.
 *
 * COLLAPSED, NOT HIDDEN (spec §6 rule 3). These rows are out of the way because they are not work
 * any more, and present because a processor still needs to say what the lender answered and when.
 */
function SettledSection({
  title,
  rows,
  selected,
  onToggle,
  onOpen,
}: {
  title: string;
  rows: Condition[];
  selected: ReadonlySet<string>;
  onToggle: (id: string) => void;
  onOpen: (id: string) => void;
}) {
  const [open, setOpen] = useState(false);

  return (
    <div className="overflow-hidden rounded-lg border border-input bg-card">
      <button
        type="button"
        onClick={() => setOpen((was) => !was)}
        aria-expanded={open}
        className="flex w-full items-center gap-2 px-3 py-2 text-left hover:bg-muted/40 focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-primary"
      >
        <ChevronRight
          className={cn(
            "h-3.5 w-3.5 text-muted-foreground transition-transform",
            open && "rotate-90",
          )}
          aria-hidden
        />
        <span className="text-sm font-semibold text-foreground">{title}</span>
        <span className="text-xs text-muted-foreground">
          {rows.length} · {rows.map((row) => row.lender_code ?? "—").join(", ")}
        </span>
        {title === "Cleared" ? (
          <span className="ml-auto text-xs text-muted-foreground">
            Kept for the record — the lender’s answer and where it came from on each
          </span>
        ) : null}
      </button>

      {open
        ? rows.map((condition) => (
            <div
              key={condition.id}
              className="grid grid-cols-[1.5rem_3.5rem_minmax(0,1fr)_7.5rem] items-start gap-3 border-t border-input px-3 py-2"
            >
              <label className="flex cursor-pointer items-center pt-0.5">
                <input
                  type="checkbox"
                  className="accent-primary"
                  checked={selected.has(condition.id)}
                  onChange={() => onToggle(condition.id)}
                  aria-label={`Select ${condition.lender_code ?? "condition"}`}
                />
              </label>
              <button
                type="button"
                onClick={() => onOpen(condition.id)}
                className="col-span-2 grid grid-cols-[3.5rem_minmax(0,1fr)] items-start gap-3 text-left focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-primary"
              >
                <span className="font-mono text-xs font-medium text-foreground-2">
                  {condition.lender_code ?? "—"}
                </span>
                <span className="line-clamp-1 font-serif text-sm text-foreground-2">
                  {displayWording(condition.verbatim_text, condition.underwriter_notes.length)}
                </span>
              </button>
              <StatusToken meta={resolveStatus(CONDITION_LENDER_STATUS, condition.lender_status)} />
            </div>
          ))
        : null}
    </div>
  );
}
