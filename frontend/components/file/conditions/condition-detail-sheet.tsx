"use client";

import { ReadingBox, ReadingItems } from "@/components/file/conditions/reading-box";
import { StatusToken } from "@/components/status-token";
import { Button } from "@/components/ui/button";
import { Select } from "@/components/ui/select";
import { Sheet, SheetContent, SheetHeader, SheetTitle } from "@/components/ui/sheet";
import { Skeleton } from "@/components/ui/skeleton";
import { useCondition, useConditionEvents } from "@/lib/api/conditions";
import { conditionHistoryLine } from "@/lib/conditions/history";
import { becomes, stepOptions, waitingLabel } from "@/lib/conditions/next-step";
import { OWNER_LABEL } from "@/lib/conditions/owners";
import { OPTION_LABEL } from "@/lib/conditions/plan-words";
import { CONDITION_LENDER_STATUS, CONDITION_PREP_STATUS, resolveStatus } from "@/lib/status";
import type {
  Condition,
  ConditionItem,
  ConditionPrepStatus,
  OwnerHint,
  Performer,
  PlanOption,
  UnderwriterNote,
  Verdict,
} from "@/lib/types/conditions";
import { BUCKET_KIND_CHIP } from "@/lib/types/conditions";
import { cn } from "@/lib/utils";
import { Check, ChevronDown, ChevronUp, Copy, Minus, Undo2 } from "lucide-react";
import { useCallback, useEffect } from "react";
import { OwnerCell } from "./owner-cell";

/** `2026-09-12` → `09/12`. The app's short form; the full date is in the callout. */
function shortDate(iso: string | null): string {
  if (!iso) return "—";
  const [, month, day] = iso.split("-");
  return month && day ? `${month}/${day}` : iso;
}

/** `2026-09-12` → `09/12/2026`, the form the verdict callout prints. */
function usDate(iso: string | null): string {
  if (!iso) return "—";
  const [year, month, day] = iso.split("-");
  return year && month && day ? `${month}/${day}/${year}` : iso;
}

/** `2026-09-10T16:31:00Z` → `09/10 4:31 PM`, the stamp each history line carries. */
function historyStamp(iso: string): string {
  const when = new Date(iso);
  if (Number.isNaN(when.getTime())) return iso;
  const month = `${when.getMonth() + 1}`.padStart(2, "0");
  const day = `${when.getDate()}`.padStart(2, "0");
  return `${month}/${day} ${when.toLocaleTimeString("en-US", { hour: "numeric", minute: "2-digit" })}`;
}

/** The four steps a processor may choose. `review` is deliberately absent (default A4). */
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

/**
 * What the lender said, and where — the callout S2-03 draws under the status block.
 *
 * **NOTHING MAY SHOW "Cleared" WITHOUT ONE** (ADR-404). That is the whole reason this renders beside
 * the status rather than behind a second request: a screen saying "Cleared" has to be able to say who
 * said so, on the same screen, without another click.
 *
 * `source_date` IS THE LENDER'S AND `recorded_at` IS OURS, and keeping both visible is the point —
 * "cleared on the 12th, recorded on the 14th" is a different fact from either date alone.
 */
function VerdictCallout({ verdict }: { verdict: Verdict }) {
  const meta = resolveStatus(CONDITION_LENDER_STATUS, verdict.status);

  return (
    <div className="mt-2 flex items-start gap-2 rounded-md border border-success/30 bg-success/5 p-2 text-xs text-foreground-2">
      <StatusToken meta={meta} variant="dot" className="mt-0.5" />
      <div className="min-w-0">
        <p className="font-medium text-foreground">
          {meta.label} · {verdict.source_kind.replace(/_/g, " ")} · {usDate(verdict.source_date)}
        </p>
        {/* The processor's own note about the verdict, never the lender's words. */}
        {verdict.note ? <p className="mt-0.5">{verdict.note}</p> : null}
      </div>
    </div>
  );
}

/** A dated note chip, showing the round it arrived in (S2-03's Underwriter notes). */
/** The chips S3-01 offers beside the ones already chosen. */
const ALSO_OFFERED: PlanOption[] = ["already_in_file", "ask_underwriter"];

/**
 * S3-01's Next step chips: every step the condition has, selected, plus "Already in the file" and
 * "Ask the underwriter". A chip that is the condition's OWN step toggles it; a step that comes from an
 * item is changed on the item (the plan panel's select), so its chip is shown selected and inert.
 */
function NextStepChips({
  condition,
  disabled,
  onChoose,
}: {
  condition: Condition;
  disabled: boolean;
  onChoose?: (option: PlanOption | null) => void;
}) {
  const chosen = stepOptions(condition);
  const offered = [...chosen, ...ALSO_OFFERED.filter((option) => !chosen.includes(option))];
  return (
    <section className="flex flex-col gap-1.5">
      <p className="text-xs font-medium uppercase tracking-wide text-muted-foreground">Next step</p>
      <div className="flex flex-wrap gap-1.5">
        {offered.map((option) => {
          const selected = chosen.includes(option);
          const own = condition.next_step === option;
          const inert = disabled || !onChoose || (selected && !own);
          return (
            <button
              key={option}
              type="button"
              aria-pressed={selected}
              disabled={inert}
              title={selected && !own ? "Change it on the item" : undefined}
              onClick={() => onChoose?.(own ? null : option)}
              className={cn(
                "inline-flex items-center gap-1 rounded-md border px-2 py-1 text-xs",
                selected
                  ? "border-primary/50 bg-primary/10 font-medium text-primary"
                  : "border-input text-foreground-2 hover:bg-muted/60",
                inert && !selected && "opacity-60",
              )}
            >
              {selected ? <Check className="h-3 w-3" aria-hidden /> : null}
              {OPTION_LABEL[option]}
            </button>
          );
        })}
      </div>
    </section>
  );
}

function NoteChip({ note, roundLabel }: { note: UnderwriterNote; roundLabel: string | null }) {
  return (
    <span className="inline-flex items-baseline gap-1.5 rounded-md border-l-2 border-warning bg-muted px-1.5 py-0.5 text-xs">
      {note.date ? <span className="font-mono text-warning">{shortDate(note.date)}</span> : null}
      <span className="text-foreground-2">{note.text}</span>
      {roundLabel ? <span className="text-muted-foreground">{roundLabel}</span> : null}
    </span>
  );
}

/**
 * Everything about one condition, opened from any row (S2-03, LP-916).
 *
 * PREVIOUS / NEXT STEP THROUGH THE CALLER'S OWN ARRAY, which is how they "follow the list's current
 * filter and sort" without this component knowing what those are. The list passes the conditions it
 * is already rendering, in the order it is rendering them; the sheet moves an index. Holding its own
 * id list, or re-querying, would be a second source of order — and the two would disagree the moment
 * LP-913 adds the filter row.
 *
 * THE ROW IS THE FALLBACK AND THE DETAIL IS THE UPGRADE. `useCondition` fetches the rounds this
 * condition did and did not appear on, which the list does not carry — but the sheet renders
 * immediately from the row the caller already has, so opening it never shows an empty panel while a
 * request is in flight.
 *
 * NO ACTION BUTTONS FOR STAGE 3 WORK. No "email borrower", no "request document". The ticket is
 * explicit: leave the space empty rather than show disabled buttons that promise work the app cannot
 * do yet.
 */
export function ConditionDetailSheet({
  conditions,
  openId,
  onOpenChange,
  onSelect,
  onMovePrepStatus,
  onSetOwner,
  onRecordAnswer,
  onReopen,
  suggestedIds,
  suggestedRoundNumber,
  onConfirmSuggestion,
  onConfirmReading,
  onAddItem,
  onSetNextStep,
  onMarkItemDone,
}: {
  /** The list's rows, in the list's order — the filter and sort come with them. */
  conditions: Condition[];
  openId: string | null;
  onOpenChange: (open: boolean) => void;
  onSelect: (conditionId: string) => void;
  /** Opens S2-05 when the move is backward; the caller owns the refusal wording. */
  onMovePrepStatus: (condition: Condition, to: ConditionPrepStatus) => void;
  onSetOwner: (condition: Condition, owner: OwnerHint | null) => void;
  onRecordAnswer: (condition: Condition) => void;
  onReopen: (condition: Condition) => void;
  /**
   * Conditions the newest comparison suggests probably cleared (LP-915).
   *
   * LP-916 LEFT THIS BLOCK OUT ON PURPOSE and said why: `pending_suggestion` had no producer, so the
   * block would have been a branch nobody could reach. LP-915 is the producer, so it arrives with it.
   */
  suggestedIds?: ReadonlySet<string>;
  suggestedRoundNumber?: number | null;
  /** Confirm this ONE condition — the spec's "she can also confirm one from the detail sheet". */
  onConfirmSuggestion?: (condition: Condition) => void;
  /** Opens S3-03 for a reading that needs her (LP-919). The caller owns the dialog. */
  onConfirmReading?: (condition: Condition) => void;
  /** S3-01's "Add an item" (LP-920). */
  onAddItem?: (condition: Condition, name: string, performer: Performer) => void;
  /** S3-01's next-step chips (LP-921): the condition's own step, or null to clear it. */
  onSetNextStep?: (condition: Condition, option: PlanOption | null) => void;
  /** LP-921 — her own task done or not. */
  onMarkItemDone?: (condition: Condition, item: ConditionItem, done: boolean) => void;
}) {
  const index = conditions.findIndex((row) => row.id === openId);
  const row = index >= 0 ? conditions[index] : undefined;

  const step = useCallback(
    (delta: number) => {
      if (index < 0) return;
      const next = conditions[index + delta];
      if (next) onSelect(next.id);
    },
    [conditions, index, onSelect],
  );

  // ↑ AND ↓ MOVE THROUGH THE LIST, which the ticket asks for by name so a processor can work a
  // filtered set without closing the sheet between rows. Bound while the sheet is open only, and
  // ignored while a field has focus so the keys still move a caret inside the reason box or a select.
  useEffect(() => {
    if (!row) return;
    const onKey = (event: KeyboardEvent) => {
      if (event.key !== "ArrowUp" && event.key !== "ArrowDown") return;
      const target = event.target as HTMLElement | null;
      const tag = target?.tagName;
      if (tag === "INPUT" || tag === "TEXTAREA" || tag === "SELECT" || target?.isContentEditable) {
        return;
      }
      // NOT WHILE A DIALOG IS OPEN ON TOP (LP-916 review). The sheet is itself a dialog, so a second
      // one is S2-04 or S2-05 over it. The first version stepped the sheet underneath when an arrow
      // key was pressed on the dialog's Portal / Email / Phone buttons: the answer still went to the
      // right row, but the sheet behind it showed a different condition when the dialog closed.
      if (document.querySelectorAll('[role="dialog"]').length > 1) return;
      event.preventDefault();
      step(event.key === "ArrowUp" ? -1 : 1);
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [row, step]);

  return (
    <Sheet open={row !== undefined} onOpenChange={onOpenChange}>
      <SheetContent className="w-full overflow-y-auto sm:max-w-[38.75rem]">
        {row ? (
          <SheetBody
            row={row}
            conditions={conditions}
            hasPrevious={index > 0}
            hasNext={index >= 0 && index < conditions.length - 1}
            onStep={step}
            onMovePrepStatus={onMovePrepStatus}
            onSetOwner={onSetOwner}
            onRecordAnswer={onRecordAnswer}
            onReopen={onReopen}
            onSelect={onSelect}
            suggestedInRound={suggestedIds?.has(row.id) ? (suggestedRoundNumber ?? null) : null}
            onConfirmSuggestion={onConfirmSuggestion}
            onConfirmReading={onConfirmReading}
            onAddItem={onAddItem}
            onSetNextStep={onSetNextStep}
            onMarkItemDone={onMarkItemDone}
          />
        ) : null}
      </SheetContent>
    </Sheet>
  );
}

function SheetBody({
  row,
  hasPrevious,
  hasNext,
  onStep,
  onMovePrepStatus,
  onSetOwner,
  onRecordAnswer,
  onReopen,
  onSelect,
  suggestedInRound,
  onConfirmSuggestion,
  onConfirmReading,
  onAddItem,
  onSetNextStep,
  onMarkItemDone,
  conditions,
}: {
  row: Condition;
  /** The list's rows — used to resolve the replaced/replaces pair without a second request. */
  conditions: Condition[];
  hasPrevious: boolean;
  hasNext: boolean;
  onStep: (delta: number) => void;
  onMovePrepStatus: (condition: Condition, to: ConditionPrepStatus) => void;
  onSetOwner: (condition: Condition, owner: OwnerHint | null) => void;
  onRecordAnswer: (condition: Condition) => void;
  onReopen: (condition: Condition) => void;
  onSelect: (conditionId: string) => void;
  suggestedInRound?: number | null;
  onConfirmSuggestion?: (condition: Condition) => void;
  onConfirmReading?: (condition: Condition) => void;
  onAddItem?: (condition: Condition, name: string, performer: Performer) => void;
  onSetNextStep?: (condition: Condition, option: PlanOption | null) => void;
  onMarkItemDone?: (condition: Condition, item: ConditionItem, done: boolean) => void;
}) {
  const detail = useCondition(row.id);
  const events = useConditionEvents(row.id);
  // The row the list already has, upgraded by the detail once it lands — so the sheet is never empty.
  const condition = detail.data ?? row;

  const prepMeta = resolveStatus(CONDITION_PREP_STATUS, condition.prep_status);
  const becomesLine = becomes(condition);
  const lenderMeta = resolveStatus(CONDITION_LENDER_STATUS, condition.lender_status);
  const kindChip = BUCKET_KIND_CHIP[condition.bucket_kind];
  const reopenable = condition.lender_status === "cleared" || condition.lender_status === "waived";
  const roundById = new Map((detail.data?.rounds ?? []).map((r) => [r.round_id, r]));

  /**
   * A REPLACED CONDITION TAKES NO WRITES, so this screen must not offer any (LP-915).
   *
   * The server refuses every one of them with `condition_was_replaced` — a status move, a verdict, a
   * reopen and an owner change alike — because the successor carries the work from the moment a
   * reworded pair is confirmed. Leaving the selects live would put four controls on screen whose only
   * possible outcome is a 409, which is the same dead-branch trade LP-916 refused for this sheet's
   * unreachable blocks. What replaces them is the link to the row that DOES take the work.
   *
   * Read from `superseded_by_id` rather than from the status, for the reason the service guard gives:
   * the pointer is the fact, and `lender_status == superseded` is a rendering of it.
   */
  const replacedById = condition.superseded_by_id;
  // THE REVERSE DIRECTION, out of the rows the list already handed over: the condition THIS one
  // replaced is the one pointing at it. No extra request, and it is the same pair read from the other
  // end — `superseded_by_id` is the single fact, so the two directions cannot disagree.
  const replaces = conditions.filter((other) => other.superseded_by_id === condition.id);
  // The link is offered only when the successor is among those rows. A filter can hide it, and a
  // button that opens nothing is worse than the sentence beside it.
  const successorKnown =
    replacedById !== null && conditions.some((other) => other.id === replacedById);

  return (
    <>
      <SheetHeader>
        {/* `pr-8` KEEPS ↑ ↓ CLEAR OF THE SHEET'S ×, which is absolutely positioned at the top right.
            Without it the × sat on top of ↓ (LP-919's S3-01 check; the header is Stage 2's). */}
        <div className="flex items-center justify-between gap-2 pr-8">
          <SheetTitle className="flex min-w-0 items-baseline gap-2">
            <span className="font-mono text-sm">{condition.lender_code ?? "No code"}</span>
            <span className="truncate text-xs font-normal text-muted-foreground">
              {[condition.lender_category, condition.bucket_heading].filter(Boolean).join(" · ") ||
                "No heading given"}
            </span>
          </SheetTitle>
          <div className="flex shrink-0 items-center gap-1">
            <Button
              variant="outline"
              size="icon-sm"
              title="Previous (↑)"
              aria-label="Previous condition"
              disabled={!hasPrevious}
              onClick={() => onStep(-1)}
            >
              <ChevronUp className="h-3.5 w-3.5" aria-hidden />
            </Button>
            <Button
              variant="outline"
              size="icon-sm"
              title="Next (↓)"
              aria-label="Next condition"
              disabled={!hasNext}
              onClick={() => onStep(1)}
            >
              <ChevronDown className="h-3.5 w-3.5" aria-hidden />
            </Button>
          </div>
        </div>
      </SheetHeader>

      {/* `SheetContent` brings no padding and `SheetHeader` carries its own, so the body supplies its
          gutter — the same correction S1-09 needed (LP-909 §5). */}
      <div className="flex flex-col gap-3 px-4 pb-6">
        <section>
          <div className="flex items-center justify-between">
            <p className="text-xs font-medium uppercase tracking-wide text-muted-foreground">
              Lender’s words
            </p>
            <Button
              variant="ghost"
              size="sm"
              // COPIES THE SAVED WORDING EXACTLY — a Done-when. `verbatim_text` is what the lender
              // wrote, including any note inside it; the chips below are a display cut, never a
              // rewrite, so what lands on the clipboard is what the sheet says.
              onClick={() => void navigator.clipboard?.writeText(condition.verbatim_text)}
            >
              <Copy className="h-3 w-3" aria-hidden />
              Copy text
            </Button>
          </div>
          <p className="mt-1 max-w-prose font-serif text-sm leading-relaxed text-foreground">
            {condition.verbatim_text}
          </p>
          <div className="mt-2 flex flex-wrap items-center gap-1.5">
            <span className="rounded-md border border-input px-1.5 py-0.5 text-xs text-muted-foreground">
              {kindChip}
            </span>
            {condition.info_only ? (
              <span className="rounded-md border border-input px-1.5 py-0.5 text-xs text-muted-foreground">
                Information only
              </span>
            ) : null}
            {condition.bucket_kind === "lender_to_clear" ? (
              <span className="rounded-md border border-input px-1.5 py-0.5 text-xs text-muted-foreground">
                Lender is doing it
              </span>
            ) : null}
            {/* THE EFFECTIVE OWNER, NEVER THE RAW HINT — a manual override must be visible here. */}
            <OwnerCell hint={condition.effective_owner} source={condition.effective_owner_source} />
          </div>
        </section>

        <ReadingBox
          condition={condition}
          onConfirm={onConfirmReading ? () => onConfirmReading(condition) : undefined}
        />
        {condition.items.length > 0 || condition.next_step !== null ? (
          <ReadingItems
            items={condition.items}
            onAdd={
              onAddItem ? (name, performer) => onAddItem(condition, name, performer) : undefined
            }
            onMarkDone={
              onMarkItemDone ? (item, done) => onMarkItemDone(condition, item, done) : undefined
            }
          />
        ) : condition.reading ? (
          <ReadingItems items={condition.reading.items} />
        ) : null}
        {condition.items.length > 0 || condition.next_step !== null ? (
          <NextStepChips
            condition={condition}
            disabled={replacedById !== null}
            onChoose={onSetNextStep ? (option) => onSetNextStep(condition, option) : undefined}
          />
        ) : null}

        <section className="rounded-lg border border-input bg-card p-3">
          <div className="grid grid-cols-[6rem_1fr] items-center gap-y-2">
            <span className="text-xs font-medium uppercase tracking-wide text-muted-foreground">
              Our status
            </span>
            <Select
              aria-label="Our status"
              disabled={replacedById !== null}
              value={condition.prep_status}
              // `review` is not offered (A4), so a row already carrying it keeps it as an extra
              // option rather than being silently rewritten by the control that renders it.
              onChange={(event) => {
                // A RE-SELECTION OF THE CURRENT VALUE IS NOT A MOVE. The server already treats it as
                // a no-op (LP-912 review R7: a "move" to the status a row already has wrote an event
                // and restarted `prep_status_changed_at`), and sending it from here would ask a
                // processor for a reason to move a condition to where it already is.
                const to = event.target.value as ConditionPrepStatus;
                if (to !== condition.prep_status) onMovePrepStatus(condition, to);
              }}
            >
              {(OFFERED_PREP.includes(condition.prep_status)
                ? OFFERED_PREP
                : [condition.prep_status, ...OFFERED_PREP]
              ).map((value) => (
                <option key={value} value={value}>
                  {value === "waiting" && condition.waiting_on
                    ? `Waiting on ${waitingLabel(condition.waiting_on)}`
                    : CONDITION_PREP_STATUS[value].label}
                </option>
              ))}
            </Select>
            {becomesLine ? (
              <p className="col-start-2 text-xs text-muted-foreground">
                Becomes <b className="font-semibold text-foreground">{becomesLine.status}</b> when{" "}
                {becomesLine.when}.
              </p>
            ) : null}

            <span className="text-xs font-medium uppercase tracking-wide text-muted-foreground">
              Owner
            </span>
            <div className="flex items-center gap-2">
              <Select
                aria-label="Owner"
                disabled={replacedById !== null}
                value={condition.effective_owner}
                onChange={(event) => onSetOwner(condition, event.target.value as OwnerHint)}
              >
                {OFFERED_OWNERS.map((value) => (
                  <option key={value} value={value}>
                    {/* THE SHARED LABEL, NOT A CAPITALISED ENUM VALUE. This built its own words —
                        agreeing with `OWNER_LABEL` only by coincidence once LP-913 shortened
                        `unknown` to "Not known", and diverging silently the next time an owner is
                        added or reworded. The reviewer consolidated this vocabulary one ticket ago
                        so the chip and the history line read one copy; the select is the third
                        reader and was quietly a fourth copy. */}
                    {OWNER_LABEL[value]}
                  </option>
                ))}
              </Select>
              {/* "suggested" WHEN NOBODY CHOSE IT. S2-03 marks the select this way so a code-map
                  guess and a person's decision are not read as the same claim. */}
              {condition.effective_owner_source !== "manual" ? (
                <span className="shrink-0 text-xs text-muted-foreground">suggested</span>
              ) : (
                <Button variant="ghost" size="sm" onClick={() => onSetOwner(condition, null)}>
                  Clear
                </Button>
              )}
            </div>

            <span className="text-xs font-medium uppercase tracking-wide text-muted-foreground">
              Lender
            </span>
            <div className="flex items-center justify-between gap-2">
              <StatusToken meta={lenderMeta} />
              {replacedById !== null ? null : reopenable ? (
                <Button variant="outline" size="sm" onClick={() => onReopen(condition)}>
                  <Undo2 className="h-3 w-3" aria-hidden />
                  Reopen
                </Button>
              ) : (
                <Button variant="outline" size="sm" onClick={() => onRecordAnswer(condition)}>
                  Record lender’s answer
                </Button>
              )}
            </div>
          </div>

          {condition.verdict ? <VerdictCallout verdict={condition.verdict} /> : null}

          {/* REPLACED: WHERE THE WORK WENT (S2-03's content list, item 8). Nothing disappeared — this
              row and its whole history are still here — but the next action is on the other one, so
              the screen points at it instead of offering writes that cannot succeed. */}
          {replacedById !== null ? (
            <div className="mt-2 flex flex-wrap items-center gap-2 rounded-md border border-input bg-muted/40 p-2 text-xs text-foreground-2">
              <span>
                This condition was replaced by a later one. Nothing was deleted — the work moved.
              </span>
              <Button
                variant="outline"
                size="sm"
                // Navigable only when the successor is among the rows the list handed over; a filter
                // can hide it, and a button that opens nothing is worse than a sentence.
                disabled={!successorKnown}
                onClick={() => onSelect(replacedById)}
              >
                Open the one that replaced it
              </Button>
            </div>
          ) : null}
          {replaces.length > 0 ? (
            <p className="mt-2 text-xs text-muted-foreground">
              Replaces {replaces.map((row) => row.lender_code ?? "a condition").join(", ")}.
            </p>
          ) : null}
        </section>

        {/* PENDING SUGGESTION (S2-03's content list, item 6) — the per-condition half of S2-06's
            panel. A QUESTION WITH A BUTTON, never a status: the Lender row above still reads Open,
            and it is this click that records the verdict. */}
        {suggestedInRound !== null && suggestedInRound !== undefined ? (
          <section className="flex flex-col gap-2 rounded-lg border border-primary/35 bg-primary/5 p-3">
            <p className="text-sm font-medium text-foreground">
              Round {suggestedInRound} suggests this probably cleared
            </p>
            <p className="text-xs text-foreground-2">
              It was open before round {suggestedInRound} and is not on that sheet, which was the
              lender’s full list. Nothing changes until you confirm.
            </p>
            <div className="flex flex-wrap items-center gap-2">
              <Button
                size="sm"
                disabled={onConfirmSuggestion === undefined}
                onClick={() => onConfirmSuggestion?.(condition)}
              >
                Confirm as cleared
              </Button>
              {/* NO "Keep open" BUTTON. Keeping it open is what happens if she does nothing, and a
                  button that dismisses the question would withdraw a suggestion from this one row
                  while the panel still offers it — two places disagreeing about one question. */}
              <span className="text-xs text-muted-foreground">
                Or leave it — it stays Open until you decide.
              </span>
            </div>
          </section>
        ) : null}

        {condition.underwriter_notes.length > 0 ? (
          <section>
            <p className="text-xs font-medium uppercase tracking-wide text-muted-foreground">
              Underwriter notes
            </p>
            <div className="mt-1 flex flex-col items-start gap-1">
              {condition.underwriter_notes.map((note, i) => {
                const round = note.first_seen_round_id
                  ? roundById.get(note.first_seen_round_id)
                  : undefined;
                return (
                  <NoteChip
                    key={`${note.date}-${i}`}
                    note={note}
                    roundLabel={round?.round_number ? `round ${round.round_number}` : null}
                  />
                );
              })}
            </div>
            {/* What the note means, read by CODE from a fixed list (LP-919), never guessed. */}
            {condition.reading?.note_meaning ? (
              <p className="mt-1 text-xs text-muted-foreground">{condition.reading.note_meaning}</p>
            ) : null}
          </section>
        ) : null}

        <section>
          <p className="text-xs font-medium uppercase tracking-wide text-muted-foreground">
            Rounds
          </p>
          {detail.isPending ? (
            <Skeleton className="mt-1 h-5 w-48" />
          ) : (
            <div className="mt-1 flex flex-wrap gap-1.5">
              {(detail.data?.rounds ?? []).map((round) => (
                <span
                  key={round.round_id}
                  className="inline-flex items-center gap-1.5 rounded-full border border-input px-2 py-0.5 text-xs text-foreground-2"
                >
                  <b className="font-mono font-medium">R{round.round_number ?? "—"}</b>
                  <span className="tabular-nums">{shortDate(round.round_date)}</span>
                  {/* THREE STATES, NOT TWO (ADR-404). Absent from a FULL round is genuinely absent;
                      absent from a PARTIAL one says nothing at all, because the processor pasted some
                      lines and never claimed the rest were gone. */}
                  {round.on_sheet ? (
                    <span className="inline-flex items-center gap-1 text-success">
                      on the sheet <Check className="h-3 w-3" aria-hidden />
                    </span>
                  ) : round.completeness === "full" ? (
                    <span className="inline-flex items-center gap-1 text-muted-foreground">
                      full list · not on it <Minus className="h-3 w-3" aria-hidden />
                    </span>
                  ) : (
                    <span className="text-muted-foreground">just some · not comparable</span>
                  )}
                </span>
              ))}
            </div>
          )}
        </section>

        <section>
          <p className="text-xs font-medium uppercase tracking-wide text-muted-foreground">
            History
          </p>
          {events.isPending ? (
            <div className="mt-1 flex flex-col gap-1" aria-busy>
              <Skeleton className="h-3 w-3/4" />
              <Skeleton className="h-3 w-2/3" />
            </div>
          ) : events.isError ? (
            // An empty list and a failed fetch say different things, and neither is silence: a
            // condition always has at least its `CONDITION_CREATED` event.
            <p className="mt-1 text-xs text-muted-foreground">
              The history couldn’t be loaded. Nothing about this condition has changed.
            </p>
          ) : (
            <ol className="mt-1 flex flex-col gap-1">
              {(events.data ?? []).map((event, i) => (
                <li
                  key={`${event.kind}-${event.occurred_at}-${i}`}
                  className="grid grid-cols-[6.5rem_1fr] gap-2 border-b border-dashed border-input pb-1 text-xs text-foreground-2 last:border-b-0"
                >
                  <span className="font-mono tabular-nums text-muted-foreground">
                    {historyStamp(event.occurred_at)}
                  </span>
                  <span>{conditionHistoryLine(event, detail.data?.rounds ?? [])}</span>
                </li>
              ))}
            </ol>
          )}
        </section>
      </div>
    </>
  );
}
