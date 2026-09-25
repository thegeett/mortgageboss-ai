"use client";

import type { Condition, OwnerHint, OwnerHintSource } from "@/lib/types/conditions";
import { BUCKET_KIND_LABEL } from "@/lib/types/conditions";

/** Who probably has to act — the same vocabulary the review screen uses. */
const OWNER_LABEL: Record<OwnerHint, string> = {
  borrower: "Borrower",
  title: "Title",
  insurance: "Insurance",
  lender: "Lender",
  broker: "Broker",
  processor: "Processor",
  unknown: "Owner not known",
};

const SOURCE_LABEL: Record<OwnerHintSource, string> = {
  prefix: "from “TC:” prefix",
  bucket: "from bucket",
  code_map: "from code map",
  none: "",
};

/** `2026-08-28` → `8/28`, the short form the note chips use. */
function noteDate(value: string | null): string | null {
  if (!value) return null;
  const [, month, day] = value.split("-");
  return month && day ? `${Number(month)}/${Number(day)}` : value;
}

/**
 * The file's imported conditions, grouped by the lender's own heading (S1-05, S1-08).
 *
 * ⚠️ READ-ONLY, AND THE ABSENCE OF CONTROLS IS THE FEATURE. No edit, no remove, and above all no
 * status control of any kind — design rule 3: nothing in Stage 1 says cleared, done, satisfied, open
 * or to do. The review screen is where a processor changes what a round says; once imported it is
 * the lender's record of what they asked for, and only the lender clears a condition.
 *
 * ⚠️ THE `R1 R2` CHIPS COME FROM `round_numbers`, WHICH IS DERIVED FROM EVENTS SERVER-SIDE. Not from
 * `first_round_id` / `last_seen_round_id`: two columns cannot express "appeared on R1 and R3 but not
 * R2", and that is exactly what the chips are for. A condition on one round shows one chip and is
 * NOT marked missing, removed or cleared for the rounds it is absent from (S1-08).
 */
export function ImportedConditions({ conditions }: { conditions: Condition[] }) {
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
      {groups.map((group) => {
        const label = BUCKET_KIND_LABEL[group.kind];
        const showChip = label.toLowerCase() !== group.heading.toLowerCase();
        return (
          <div
            key={group.heading || "no-heading"}
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
              <div
                key={condition.id}
                className="grid grid-cols-[4rem_7rem_1fr_9rem] items-start gap-3 border-t border-input px-3 py-2.5 first:border-t-0"
              >
                <div className="font-mono text-xs text-foreground-2">
                  {condition.lender_code ?? "—"}
                </div>
                <div className="text-xs text-muted-foreground">
                  {condition.lender_category ?? "—"}
                </div>

                <div className="flex min-w-0 flex-col gap-1.5">
                  <p className="max-w-prose font-serif text-sm text-foreground">
                    {condition.verbatim_text}
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
                  <span className="text-xs text-foreground-2">
                    {OWNER_LABEL[condition.owner_hint]}
                  </span>
                  {SOURCE_LABEL[condition.owner_hint_source] ? (
                    <span className="text-xs text-muted-foreground">
                      {SOURCE_LABEL[condition.owner_hint_source]}
                    </span>
                  ) : null}
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
              </div>
            ))}
          </div>
        );
      })}
    </div>
  );
}
