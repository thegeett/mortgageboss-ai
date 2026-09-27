"use client";

import { StatusToken } from "@/components/status-token";
import { Button } from "@/components/ui/button";
import { displayWording } from "@/lib/conditions/wording";
import { CONDITION_PREP_STATUS } from "@/lib/status";
import { CONDITION_LENDER_STATUS, resolveStatus } from "@/lib/status";
import type { Condition, ConditionRound, LetterChange } from "@/lib/types/conditions";
import { cn } from "@/lib/utils";
import { ChevronRight, Info } from "lucide-react";
import { useEffect, useState } from "react";

/**
 * "What changed in round N" — the comparison panel (S2-06, S2-07, S2-08, S2-10), LP-915.
 *
 * IT DRAWS A QUESTION, NEVER A STATUS (design rule 4). "Probably cleared" is a list with a button and
 * every row in it is still `open`; the only thing that turns one into *Cleared* is the processor
 * pressing **Confirm N as cleared**, which records a verdict naming the sheet that showed it (ADR-404).
 * Nothing here writes a status by itself, and the panel says so on screen twice.
 *
 * EVERY LIST IS IDS, RESOLVED HERE. The saved comparison holds condition ids and no wording at all —
 * that is what keeps the lender's text out of the column — so this panel looks each id up in the rows
 * it was given. An id that is not among them is skipped rather than half-drawn, which is the honest
 * outcome for a condition outside the current page.
 *
 * THE SERVER'S SENTENCES ARE SHOWN AS-IS. `no_suggestions_reason` is the server's wording for why
 * nothing is suggested, and a refusal is the server's wording for why a click did not take effect
 * (spec §6 rule 5). Neither is reworded here.
 *
 * WHAT IS NOT DRAWN, AND WHY — both recorded in `docs/tickets/LP-915.md` rather than left as silent
 * gaps:
 *   - S2-08's came-back line ends "· our status moved from Sent to lender back to To do". That clause
 *     lives in the `condition_came_back` event's `prep_status_from` / `prep_status_to`, and reading it
 *     would mean a history fetch per came-back condition from inside this panel. The line states the
 *     half it can prove: which dated note set it.
 *   - S2-06's "line naming what didn't change" needs the full set of letter facts. The comparison
 *     deliberately stores only the values that MOVED, so the unchanged ones are not available to name.
 */

/** `2026-08-28` → `08/28/2026`. */
function usDate(value: string | null): string {
  if (!value) return "—";
  const [year, month, day] = value.split("-");
  return year && month && day ? `${month}/${day}/${year}` : value;
}

/** `2026-08-28` → `08/28` — the form the suggestion rows and note chips use. */
function shortDate(value: string | null): string {
  if (!value) return "—";
  const [, month, day] = value.split("-");
  return month && day ? `${month}/${day}` : value;
}

/**
 * The server's label as the table prints it: "note rate" → "Note rate", "close by expiry" → "Expiry ·
 * Close by".
 *
 * PRESENTATION, NOT DATA. The stored labels are the tickets file's own prose, and the design's table
 * capitalises them and moves the word "expiry" to the front. Rewriting the stored values to match the
 * table would make the saved comparison a rendering of one screen rather than a record of what moved.
 */
function letterLabel(label: string): string {
  if (label === "rate lock expiry") return "Rate lock expires";
  if (label.endsWith(" expiry")) {
    const subject = label.slice(0, -" expiry".length);
    return `Expiry · ${subject.charAt(0).toUpperCase()}${subject.slice(1)}`;
  }
  if (label === "UW team") return label;
  return `${label.charAt(0).toUpperCase()}${label.slice(1)}`;
}

export function RoundComparisonPanel({
  round,
  previousRoundNumber,
  conditions,
  rounds,
  pending,
  refusal,
  onConfirm,
  onNotNow,
  onResolveReworded,
  onSwitchToFull,
  onHide,
}: {
  /** The round this panel is about. Rendered only when it carries a comparison. */
  round: ConditionRound;
  /** The imported round before it, for "Letter changes since round N". */
  previousRoundNumber: number | null;
  /** Rows to resolve ids against — the UNFILTERED list, so a filter cannot empty the panel. */
  conditions: Condition[];
  /** Every round, for "last on round 1 · 08/28". */
  rounds: ConditionRound[];
  pending: boolean;
  /** The server's sentence when a click was refused, shown as-is. */
  refusal: string | null;
  onConfirm: (conditionIds: string[]) => void;
  onNotNow: () => void;
  onResolveReworded: (oldId: string, newId: string, same: boolean) => void;
  onSwitchToFull: () => void;
  onHide: () => void;
}) {
  const comparison = round.comparison;
  const suggested = comparison?.probably_cleared ?? [];

  // ALL TICKED TO START (S2-06), and re-synced when the round's suggestions change — after a confirm
  // the list empties, and a stale selection would leave the button counting ids that are gone.
  const [ticked, setTicked] = useState<ReadonlySet<string>>(() => new Set(suggested));
  // S2-08's Probably cleared starts collapsed behind **Review**; opening it is per visit.
  const [reviewing, setReviewing] = useState(false);
  const signature = suggested.join(",");
  useEffect(() => {
    setTicked(new Set(signature === "" ? [] : signature.split(",")));
  }, [signature]);

  if (!comparison) return null;

  const byId = new Map(conditions.map((row) => [row.id, row]));
  const roundDateByNumber = new Map(
    rounds
      .filter((row) => row.round_number !== null)
      .map((row) => [row.round_number as number, row.date_printed ?? row.round_date]),
  );

  const codesOf = (ids: string[]) =>
    ids.map((id) => byId.get(id)?.lender_code ?? "—").filter((code) => code !== "—");

  /** The date each verdict will carry — the SHEET's date, never today's. */
  const sheetDate = round.date_printed ?? round.round_date;
  const suggestionsOffered = comparison.no_suggestions_reason === null;
  const tickedIds = suggested.filter((id) => ticked.has(id));
  const untickedCodes = codesOf(suggested.filter((id) => !ticked.has(id)));

  // ONE RULE FOR BOTH SCREENS (LP-915 review). S2-06 puts Probably cleared first; S2-08 puts Came
  // back, Reworded and New first and draws Probably cleared collapsed with **Review**. They agree once
  // read as: the sheet's own news comes first when there is any, and the question about what is
  // missing waits behind it. S2-06 has no news (all three are 0), so its question leads.
  const attentionFirst =
    comparison.came_back.length + comparison.reworded.length + comparison.new.length > 0;
  const probablyBlock =
    suggested.length > 0 ? (
      <div className="flex flex-col gap-2">
        <div>
          <p className="text-sm font-semibold text-foreground">
            Probably cleared — not on the lender’s full list
          </p>
          <p className="text-xs text-muted-foreground">
            Nothing changes until you confirm. Each one is recorded as{" "}
            <span className="font-medium text-foreground-2">
              Cleared · round {comparison.round_number} comparison · {usDate(sheetDate)}
            </span>
            .
          </p>
        </div>

        <ul className="flex flex-col">
          {suggested.map((id) => {
            const condition = byId.get(id);
            if (!condition) return null;
            const lastOn = condition.round_numbers
              .filter((number) => number !== comparison.round_number)
              .at(-1);
            return (
              <li
                key={id}
                className="flex items-start gap-3 border-b border-input py-2 last:border-b-0"
              >
                <label className="flex cursor-pointer items-center pt-0.5">
                  <input
                    type="checkbox"
                    className="accent-primary"
                    checked={ticked.has(id)}
                    onChange={() => {
                      const next = new Set(ticked);
                      if (next.has(id)) next.delete(id);
                      else next.add(id);
                      setTicked(next);
                    }}
                    aria-label={`Confirm ${condition.lender_code ?? "condition"} as cleared`}
                  />
                </label>
                <span className="w-10 shrink-0 font-mono text-xs font-medium text-foreground-2">
                  {condition.lender_code ?? "—"}
                </span>
                <span className="line-clamp-2 min-w-0 flex-1 font-serif text-xs text-foreground">
                  {displayWording(condition.verbatim_text, condition.underwriter_notes.length)}
                </span>
                <span className="w-28 shrink-0 text-right text-xs text-muted-foreground">
                  {lastOn === undefined
                    ? "—"
                    : `last on round ${lastOn} · ${shortDate(roundDateByNumber.get(lastOn) ?? null)}`}
                </span>
              </li>
            );
          })}
        </ul>

        {/* S2-07: the unticked ones are named, and what happens to them is spelled out. */}
        {untickedCodes.length > 0 ? (
          <p className="text-xs text-muted-foreground">
            <span className="font-mono text-foreground-2">{untickedCodes.join(", ")}</span>{" "}
            {untickedCodes.length === 1 ? "stays" : "stay"} Open and{" "}
            {untickedCodes.length === 1 ? "loses" : "lose"} the suggestion. You can still record the
            lender’s answer on {untickedCodes.length === 1 ? "it" : "them"} by hand.
          </p>
        ) : null}

        <div className="flex flex-wrap items-center gap-2">
          {/* THE COUNT IS LIVE (S2-07's Must-match). Disabled at zero: confirming nothing would
                withdraw every suggestion and record no verdict, which the server also refuses. */}
          <Button
            size="sm"
            disabled={pending || tickedIds.length === 0}
            onClick={() => onConfirm(tickedIds)}
          >
            Confirm {tickedIds.length} as cleared
          </Button>
          <Button variant="outline" size="sm" disabled={pending} onClick={onNotNow}>
            Not now
          </Button>
          <span className="text-xs text-muted-foreground">
            “Not now” keeps them open with a “probably cleared — review” mark.
          </span>
        </div>
      </div>
    ) : null;

  return (
    <section className="flex flex-col gap-3 rounded-lg border border-primary/35 bg-card p-4">
      <div className="flex items-start justify-between gap-4">
        <div className="flex flex-col gap-0.5">
          <span className="text-xs font-semibold uppercase tracking-wide text-primary">
            What changed in round {comparison.round_number}
          </span>
          <span className="text-sm font-semibold text-foreground">
            Round {comparison.round_number}
            {round.date_printed ? ` · printed ${usDate(round.date_printed)}` : ""}
            {` · ${round.completeness === "full" ? "Full list" : "Just some"}`}
          </span>
          {/* A FACT ABOUT THE PAST, and it does not shrink as those conditions are answered — which
              is why the server computes it once and saves it. */}
          <span className="text-xs text-muted-foreground">
            Compared with the {comparison.compared_with}{" "}
            {comparison.compared_with === 1 ? "condition" : "conditions"} that{" "}
            {comparison.compared_with === 1 ? "was" : "were"} open before it.
          </span>
        </div>
        <Button variant="ghost" size="sm" onClick={onHide}>
          Hide
        </Button>
      </div>

      {/* THE PILL ORDER FOLLOWS THE SECTIONS (LP-915 review): S2-06's order when the sheet has no
          news, S2-08's when it does — see `attentionFirst`. The Probably cleared pill is absent
          entirely when nothing could be suggested, which is S2-10's Must-match. */}
      <div className="flex flex-wrap gap-2">
        {suggestionsOffered && !attentionFirst ? (
          <CountPill label="Probably cleared" count={suggested.length} />
        ) : null}
        <CountPill label="Came back" count={comparison.came_back.length} />
        <CountPill label="Reworded" count={comparison.reworded.length} />
        <CountPill label="New" count={comparison.new.length} />
        {suggestionsOffered && attentionFirst ? (
          <CountPill label="Probably cleared" count={suggested.length} />
        ) : null}
        <CountPill label="Still open" count={comparison.still_open.length} />
      </div>

      {refusal ? (
        <p className="flex items-start gap-2 rounded-md border border-warning/40 bg-warning/5 p-2.5 text-xs text-foreground-2">
          <Info className="mt-0.5 h-3.5 w-3.5 shrink-0 text-warning" aria-hidden />
          {refusal}
        </p>
      ) : null}

      {/* --- why nothing is suggested (S2-10) ---------------------------------------------- */}
      {comparison.no_suggestions_reason ? (
        <div className="flex flex-col gap-2 rounded-md border border-primary/30 bg-primary/5 p-3">
          <p className="flex items-start gap-2 text-xs text-foreground-2">
            <Info className="mt-0.5 h-3.5 w-3.5 shrink-0 text-primary" aria-hidden />
            <span>
              {/* THE SERVER'S SENTENCE, WORD FOR WORD. */}
              {comparison.no_suggestions_reason} The conditions that weren’t in it stay exactly as
              they are — nothing is removed or cleared.
            </span>
          </p>
          {round.completeness === "partial" ? (
            <div className="flex flex-wrap items-center gap-2">
              <Button size="sm" disabled={pending} onClick={onSwitchToFull}>
                Switch to Full list
              </Button>
              {/* "Attach the lender's PDF" is the round strip's own button on this same round, so it
                  is not repeated here — offering one action from two places is how the two come to
                  disagree about when it is allowed. */}
            </div>
          ) : null}
        </div>
      ) : null}

      {/* --- probably cleared (S2-06, S2-07): FIRST only when nothing else needs attention --- */}
      {attentionFirst ? null : probablyBlock}

      {/* --- came back (S2-08) ------------------------------------------------------------ */}
      {comparison.came_back.length > 0 ? (
        <div className="flex flex-col gap-2">
          <p className="text-sm font-semibold text-foreground">
            Came back — a new note from the underwriter
          </p>
          {comparison.came_back.map((id) => {
            const condition = byId.get(id);
            if (!condition) return null;
            return (
              <div key={id} className="relative rounded-md border border-input p-3 pl-4">
                <span className="absolute left-0 top-0 bottom-0 w-0.5 bg-warning" aria-hidden />
                <div className="flex flex-wrap items-center gap-2">
                  <span className="font-mono text-xs font-medium text-foreground-2">
                    {condition.lender_code ?? "—"}
                  </span>
                  {condition.round_numbers.map((number) => (
                    <span
                      key={number}
                      className="rounded-md border border-input px-1 py-0.5 font-mono text-[10.5px] text-muted-foreground"
                    >
                      R{number}
                    </span>
                  ))}
                  <StatusToken
                    meta={resolveStatus(CONDITION_LENDER_STATUS, condition.lender_status)}
                  />
                </div>
                <p className="mt-1.5 line-clamp-2 font-serif text-xs text-foreground">
                  {displayWording(condition.verbatim_text, condition.underwriter_notes.length)}
                </p>
                {condition.latest_note ? (
                  <p className="mt-1.5 inline-flex w-fit items-baseline gap-1.5 rounded-md border-l-2 border-warning bg-muted px-1.5 py-0.5 text-xs">
                    {condition.latest_note.date ? (
                      <span className="font-mono text-warning">
                        {shortDate(condition.latest_note.date)}
                      </span>
                    ) : null}
                    <span className="text-foreground-2">{condition.latest_note.text}</span>
                  </p>
                ) : null}
                {condition.latest_note?.date ? (
                  <p className="mt-1.5 text-xs text-muted-foreground">
                    set by the lender’s {shortDate(condition.latest_note.date)} note
                    {/* S2-08's second clause (LP-915 review), from the came-back event's own pair. */}
                    {(() => {
                      const move = comparison.came_back_moves?.find((m) => m.condition_id === id);
                      return move
                        ? ` · our status moved from ${CONDITION_PREP_STATUS[move.prep_status_from].label} back to ${CONDITION_PREP_STATUS[move.prep_status_to].label}`
                        : "";
                    })()}
                  </p>
                ) : null}
              </div>
            );
          })}
        </div>
      ) : null}

      {/* --- reworded? (S2-08) ----------------------------------------------------------- */}
      {comparison.reworded.map((pair) => {
        const oldOne = byId.get(pair.old_id);
        const newOne = byId.get(pair.new_id);
        if (!oldOne || !newOne) return null;
        const wasRounds = oldOne.round_numbers;
        return (
          <div
            key={`${pair.old_id}-${pair.new_id}`}
            className="flex flex-col gap-2 rounded-md border border-input p-3"
          >
            <div className="flex flex-wrap items-baseline gap-2">
              <span className="text-sm font-semibold text-foreground">Reworded?</span>
              <span className="font-mono text-xs font-medium text-foreground-2">
                {newOne.lender_code ?? "—"}
              </span>
              <span className="text-xs text-muted-foreground">Same code, different wording</span>
            </div>
            <p className="text-xs text-foreground-2">Is this the same condition?</p>

            <div className="flex flex-col gap-1">
              <span className="text-xs text-muted-foreground">
                Was · R{wasRounds.length > 1 ? `${wasRounds[0]}–${wasRounds.at(-1)}` : wasRounds[0]}
              </span>
              <p className="line-clamp-3 font-serif text-xs text-muted-foreground">
                {displayWording(oldOne.verbatim_text, oldOne.underwriter_notes.length)}
              </p>
            </div>
            <div className="flex flex-col gap-1">
              <span className="text-xs text-muted-foreground">
                Now · R{comparison.round_number}
              </span>
              <p className="line-clamp-3 font-serif text-xs text-foreground">
                {displayWording(newOne.verbatim_text, newOne.underwriter_notes.length)}
              </p>
            </div>

            <div className="flex flex-wrap items-center gap-2">
              <Button
                size="sm"
                disabled={pending}
                onClick={() => onResolveReworded(pair.old_id, pair.new_id, true)}
              >
                Same condition — replace the old one
              </Button>
              <Button
                variant="outline"
                size="sm"
                disabled={pending}
                onClick={() => onResolveReworded(pair.old_id, pair.new_id, false)}
              >
                Different conditions — keep both
              </Button>
            </div>
            <p className="text-xs text-muted-foreground">
              “Same” marks the old one Replaced and links the history. Nothing happens until you
              choose.
            </p>
          </div>
        );
      })}

      {/* --- new (S2-08) ----------------------------------------------------------------- */}
      {comparison.new.length > 0 ? (
        <div className="flex flex-col gap-2">
          <p className="text-sm font-semibold text-foreground">New</p>
          {comparison.new.map((id) => {
            const condition = byId.get(id);
            if (!condition) return null;
            return (
              <div key={id} className="rounded-md border border-input p-3">
                <div className="flex flex-wrap items-center gap-2">
                  <span className="font-mono text-xs font-medium text-foreground-2">
                    {condition.lender_code ?? "—"}
                  </span>
                  {condition.round_numbers.map((number) => (
                    <span
                      key={number}
                      className="rounded-md border border-input px-1 py-0.5 font-mono text-[10.5px] text-muted-foreground"
                    >
                      R{number}
                    </span>
                  ))}
                  <StatusToken
                    meta={resolveStatus(CONDITION_LENDER_STATUS, condition.lender_status)}
                  />
                </div>
                <p className="mt-1.5 line-clamp-2 font-serif text-xs text-foreground">
                  {displayWording(condition.verbatim_text, condition.underwriter_notes.length)}
                </p>
                <p className="mt-1.5 text-xs text-muted-foreground">
                  {condition.bucket_heading ?? "—"}
                </p>
              </div>
            );
          })}
        </div>
      ) : null}

      {/* --- probably cleared AFTER came back / reworded / new, collapsed with Review (S2-08) --- */}
      {attentionFirst && suggested.length > 0 ? (
        reviewing ? (
          probablyBlock
        ) : (
          <div className="flex items-center gap-2 rounded-md border border-input px-3 py-2">
            <span className="text-sm font-semibold text-foreground">
              Probably cleared ({suggested.length}: {codesOf(suggested).join(", ")})
            </span>
            <Button
              variant="outline"
              size="sm"
              className="ml-auto"
              onClick={() => setReviewing(true)}
            >
              Review
            </Button>
          </div>
        )
      ) : null}

      {/* --- letter changes (S2-06) ------------------------------------------------------ */}
      <LetterChanges
        changes={comparison.letter_changes}
        roundNumber={comparison.round_number}
        previousRoundNumber={previousRoundNumber}
        hasHeader={round.header !== null}
      />

      {/* --- still open, collapsed (S2-06) ----------------------------------------------- */}
      {comparison.still_open.length > 0 ? (
        <Collapsed
          title="Still open"
          summary={`${comparison.still_open.length} · ${codesOf(comparison.still_open).join(", ")}`}
        />
      ) : null}
    </section>
  );
}

function CountPill({ label, count }: { label: string; count: number }) {
  return (
    <span className="inline-flex items-center gap-1.5 rounded-full border border-input bg-card px-2.5 py-0.5 text-xs text-foreground-2">
      {label} <span className="font-medium tabular-nums text-foreground">{count}</span>
    </span>
  );
}

/**
 * "Letter changes since round 1" — only the values that MOVED, old struck through → new.
 *
 * WHEN THERE IS NOTHING TO COMPARE THE PANEL SAYS SO, and which sentence it says depends on WHY. A
 * paste carries no letter at all, so there is nothing to compare rather than nothing that changed —
 * two different facts, and S2-10 and S2-08 word them differently on purpose.
 */
function LetterChanges({
  changes,
  roundNumber,
  previousRoundNumber,
  hasHeader,
}: {
  changes: LetterChange[];
  roundNumber: number | null;
  previousRoundNumber: number | null;
  hasHeader: boolean;
}) {
  if (changes.length === 0) {
    return (
      <p className="text-xs text-muted-foreground">
        {hasHeader
          ? `No changes on the letter since round ${previousRoundNumber ?? (roundNumber ?? 1) - 1}.`
          : "A paste has no letter details, so there are no letter changes to show."}
      </p>
    );
  }

  return (
    <div className="flex flex-col gap-1.5">
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <span className="text-sm font-semibold text-foreground">
          Letter changes since round {previousRoundNumber ?? (roundNumber ?? 1) - 1}
        </span>
        <span className="text-xs text-muted-foreground">Only values that changed</span>
      </div>
      {/* The table is the one thing here allowed its own horizontal scroll on a narrow screen. */}
      <div className="overflow-x-auto">
        <table className="w-full border-collapse text-xs">
          <thead>
            <tr className="border-b border-input text-left">
              <th className="py-1 pr-2 font-semibold uppercase tracking-wide text-muted-foreground">
                Field
              </th>
              <th className="py-1 pr-2 font-semibold uppercase tracking-wide text-muted-foreground">
                Round {previousRoundNumber ?? (roundNumber ?? 1) - 1}
              </th>
              <th className="py-1 pr-2" />
              <th className="py-1 font-semibold uppercase tracking-wide text-muted-foreground">
                Round {roundNumber}
              </th>
            </tr>
          </thead>
          <tbody>
            {changes.map((change) => (
              <tr key={change.label} className="border-b border-input last:border-b-0">
                <td className="py-1 pr-2 text-foreground-2">{letterLabel(change.label)}</td>
                {/* MISSING IS "—" AND IS NEVER GUESSED: round 1's rate lock was genuinely blank. */}
                <td className="py-1 pr-2 tabular-nums text-muted-foreground line-through">
                  {change.old ?? "—"}
                </td>
                <td className="py-1 pr-2 text-muted-foreground" aria-hidden>
                  →
                </td>
                <td className="py-1 font-medium tabular-nums text-foreground">
                  {change.new ?? "—"}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

/** A collapsed line with its codes — "Still open · 6 · 1228, 1947, …" (S2-06). */
function Collapsed({ title, summary }: { title: string; summary: string }) {
  const [open, setOpen] = useState(false);
  return (
    <button
      type="button"
      onClick={() => setOpen((was) => !was)}
      aria-expanded={open}
      className="flex items-center gap-2 rounded-md border border-input px-3 py-2 text-left hover:bg-muted/40 focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-primary"
    >
      <ChevronRight
        className={cn(
          "h-3.5 w-3.5 text-muted-foreground transition-transform",
          open && "rotate-90",
        )}
        aria-hidden
      />
      <span className="text-sm font-semibold text-foreground">{title}</span>
      <span className="text-xs text-muted-foreground">{summary}</span>
    </button>
  );
}
