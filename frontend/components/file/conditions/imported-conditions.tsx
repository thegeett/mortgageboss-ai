"use client";

import { displayWording } from "@/lib/conditions/wording";
import type { Condition } from "@/lib/types/conditions";
import { BUCKET_KIND_CHIP } from "@/lib/types/conditions";
import { OwnerCell } from "./owner-cell";

/** `2026-08-28` → `8/28`, the short form the note chips use. */
function noteDate(value: string | null): string | null {
  if (!value) return null;
  const [, month, day] = value.split("-");
  return month && day ? `${Number(month)}/${Number(day)}` : value;
}

/**
 * The file's imported conditions, grouped by the lender's own heading (S1-05, S1-08).
 *
 * READ-ONLY, AND THE ABSENCE OF CONTROLS IS THE FEATURE. No edit, no remove, and above all no
 * status control of any kind — design rule 3: nothing in Stage 1 says cleared, done, satisfied, open
 * or to do. The review screen is where a processor changes what a round says; once imported it is
 * the lender's record of what they asked for, and only the lender clears a condition.
 *
 * THE `R1 R2` CHIPS COME FROM `round_numbers`, WHICH IS DERIVED FROM EVENTS SERVER-SIDE. Not from
 * `first_round_id` / `last_seen_round_id`: two columns cannot express "appeared on R1 and R3 but not
 * R2", and that is exactly what the chips are for. A condition on one round shows one chip and is
 * NOT marked missing, removed or cleared for the rounds it is absent from (S1-08).
 */
export function ImportedConditions({
  conditions,
  onOpen,
}: {
  conditions: Condition[];
  /** Opens the S2-03 detail sheet on this condition. Optional so S1-era callers are unchanged. */
  onOpen?: (conditionId: string) => void;
}) {
  const groups: { heading: string; kind: Condition["bucket_kind"]; rows: Condition[] }[] = [];
  for (const condition of [...conditions].sort((a, b) => a.sequence - b.sequence)) {
    const last = groups.at(-1);
    if (last && last.heading === condition.bucket_heading) last.rows.push(condition);
    else
      groups.push({
        heading: condition.bucket_heading,
        kind: condition.bucket_kind,
        rows: [condition],
      });
  }

  return (
    <div className="flex flex-col gap-2">
      {groups.map((group, index) => {
        // The chip form, for the reason given at the same line of `review-rows.tsx`: the select's
        // long label can never equal a lender heading, so the "kind adds nothing" test needs this one.
        const label = BUCKET_KIND_CHIP[group.kind];
        const showChip = label.toLowerCase() !== group.heading.toLowerCase();
        return (
          <div
            // A GROUP IS A RUN OF ROWS, NOT A HEADING, so one heading can own two runs — a
            // full round that leaves some conditions behind, or two hand-typed ones with no heading
            // around a printed one. Keyed by heading alone, S1-08 raised a React duplicate-key
            // error per repeat in a browser (LP-909 §5).
            key={`${index}-${group.heading || "no-heading"}`}
            className="overflow-hidden rounded-lg border border-input bg-card"
          >
            <div className="flex items-center gap-2 border-b border-input bg-muted/40 px-3 py-2">
              {/* An empty heading is what a hand-typed condition carries — the server declines to
                  invent one, so the list says so rather than printing a blank. */}
              <span className="text-sm font-semibold text-foreground">
                {group.heading || "No heading given"}
              </span>
              {showChip && group.heading ? (
                <span className="rounded-md border border-input px-1.5 py-0.5 text-xs text-muted-foreground">
                  {label}
                </span>
              ) : null}
              <span className="ml-auto text-xs text-muted-foreground">{group.rows.length}</span>
            </div>

            {group.rows.map((condition) => (
              // CLICKING A ROW OPENS THE DETAIL SHEET (spec §LP-913: "the list stays in place and
              // the row is highlighted").
              //
              // A REAL `<button>`, NOT A DIV WITH `role="button"`. The first version was the div,
              // reasoning that the row IS a grid and a button would collapse its four columns — true
              // of the OUTER element, and irrelevant once the grid moves inside. Biome's
              // `useSemanticElements` was right: the button gets focus order, Enter/Space, the
              // disabled semantics and the screen-reader role for free, where the div had me
              // reimplementing three of them and forgetting the fourth.
              //
              // `text-left` and `w-full` because a button centres and shrinks its content by default,
              // which would undo the column alignment the header depends on.
              <button
                key={condition.id}
                type="button"
                onClick={() => onOpen?.(condition.id)}
                className="grid w-full cursor-pointer grid-cols-[4rem_7rem_1fr_9rem] items-start gap-3 border-t border-input px-3 py-2.5 text-left first:border-t-0 hover:bg-muted/40 focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-primary"
              >
                <div className="font-mono text-xs text-foreground-2">
                  {condition.lender_code ?? "—"}
                </div>
                <div className="text-xs text-muted-foreground">
                  {condition.lender_category ?? "—"}
                </div>

                <div className="flex min-w-0 flex-col gap-1.5">
                  {/* The note renders as a chip below, not inside the wording (design rule 5).
                      `verbatim_text` still holds it — this cut is display only. */}
                  <p className="max-w-prose font-serif text-sm text-foreground">
                    {displayWording(condition.verbatim_text, condition.underwriter_notes.length)}
                  </p>
                  {condition.underwriter_notes.length > 0 ? (
                    <div className="flex flex-wrap gap-1.5">
                      {condition.underwriter_notes.map((note, index) => {
                        const when = noteDate(note.date);
                        return (
                          <span
                            key={`${note.date}-${index}`}
                            className="inline-flex items-center gap-1.5 rounded-md border-l-2 border-warning bg-muted px-1.5 py-0.5 text-xs"
                          >
                            {when ? (
                              <span className="font-mono text-muted-foreground">{when}</span>
                            ) : null}
                            <span className="text-foreground-2">{note.text}</span>
                          </span>
                        );
                      })}
                    </div>
                  ) : null}
                </div>

                <div className="flex min-w-0 flex-col items-end gap-1">
                  {/* The design draws owner chips on this screen too — 10 in the S1-05 mock and 10
                      in S1-08 — so the cell is shared rather than reimplemented here.

                      THE EFFECTIVE OWNER, NOT THE HINT (LP-912 review Q1). This rendered
                      `owner_hint` / `owner_hint_source`, which was harmless while nothing could
                      override them — and LP-916 is what changes that: the detail sheet's Owner
                      select writes `owner_override`, so with the hint pair here a processor
                      reassigns a condition to Title and the row behind the sheet still shows what
                      the code map guessed. The override would have been invisible on the one screen
                      it exists to change. `effective_owner` already coalesces the two, server-side
                      and in SQL, so the row and the filter agree. */}
                  <OwnerCell
                    hint={condition.effective_owner}
                    source={condition.effective_owner_source}
                  />
                  <div className="flex flex-wrap justify-end gap-1">
                    {condition.round_numbers.map((number) => (
                      <span
                        key={number}
                        className="rounded-md border border-input px-1 py-0.5 font-mono text-xs text-muted-foreground"
                      >
                        R{number}
                      </span>
                    ))}
                  </div>
                </div>
              </button>
            ))}
          </div>
        );
      })}
    </div>
  );
}
