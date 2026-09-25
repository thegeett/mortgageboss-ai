"use client";

import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";
import { BUCKET_KIND_LABEL } from "@/lib/types/conditions";
import type { DraftRow, OwnerHint, OwnerHintSource, UnderwriterNote } from "@/lib/types/conditions";
import { cn } from "@/lib/utils";
import { Pencil, Sparkles, X } from "lucide-react";
import { useState } from "react";

/**
 * Who probably has to act. A HINT, never a decision (Stage 3 decides).
 *
 * ⚠️ `unknown` IS "Owner not known", NOT "Unknown". The chip sits where a name goes, and a bare
 * "Unknown" reads as a party called Unknown rather than as an absence of evidence.
 */
const OWNER_LABEL: Record<OwnerHint, string> = {
  borrower: "Borrower",
  title: "Title",
  insurance: "Insurance",
  lender: "Lender",
  broker: "Broker",
  processor: "Processor",
  unknown: "Owner not known",
};

/**
 * Where the hint came from, in the design's words (S1-04).
 *
 * ⚠️ WRITTEN, NOT DERIVED FROM THE VALUE. De-snaking gives "code map" and "prefix" — and "prefix"
 * alone says nothing, where `from "TC:" prefix` names the evidence the lender actually typed. The
 * whole point of carrying the source is that the hints are not equally good, so the weak one and
 * the strong one must not read alike.
 */
const SOURCE_LABEL: Record<OwnerHintSource, string> = {
  prefix: "from “TC:” prefix",
  bucket: "from bucket",
  code_map: "from code map",
  none: "",
};

/** Anything at or above this is a row the rules read; below it needs checking before import. */
export const FLAGGED_BELOW = 0.8;

/** `2026-08-28` → `8/28`, the short form the note chips use. */
function noteDate(value: string | null): string | null {
  if (!value) return null;
  const [, month, day] = value.split("-");
  return month && day ? `${Number(month)}/${Number(day)}` : value;
}

/**
 * A dated note the underwriter appended inside the condition's text.
 *
 * ⚠️ A CHIP, NEVER MERGED INTO THE WORDING (design rule 5). The lender wrote one string and the
 * reader carried the note out of it as structure; putting it back into the serif block would make
 * the underwriter's aside indistinguishable from the condition itself.
 */
function NoteChip({ note }: { note: UnderwriterNote }) {
  const when = noteDate(note.date);
  return (
    <span className="inline-flex items-center gap-1.5 rounded-md border-l-2 border-warning bg-muted px-1.5 py-0.5 text-xs">
      {when ? <span className="font-mono text-muted-foreground">{when}</span> : null}
      <span className="text-foreground-2">{note.text}</span>
    </span>
  );
}

/**
 * One draft row, editable in place (S1-04, S1-10).
 *
 * ⚠️ THE EDITED TEXT IS WHAT IMPORTS, which is why editing happens here rather than in a dialog.
 * The fingerprint is taken of what a processor leaves behind, so an edited row may match a different
 * condition or none — correct rather than unfortunate, and the spec's own frontend test is "editing
 * a row and importing sends the edited text".
 */
function Row({
  row,
  onChange,
  onRemove,
}: {
  row: DraftRow;
  onChange: (verbatim: string) => void;
  onRemove: () => void;
}) {
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState(row.verbatim_text);
  const bySplit = row.confidence < 1;
  const flagged = row.confidence < FLAGGED_BELOW;

  return (
    <div
      className={cn(
        "grid grid-cols-[4rem_7rem_1fr_11rem] items-start gap-3 border-t border-input px-3 py-2.5 first:border-t-0",
        // Design rule 4: AI is always marked, in the --ai violet, with a 2px left stripe.
        bySplit && "border-l-2 border-l-ai",
      )}
    >
      <div className="font-mono text-xs text-foreground-2">{row.lender_code ?? "—"}</div>
      <div className="text-xs text-muted-foreground">{row.lender_category ?? "—"}</div>

      <div className="flex min-w-0 flex-col gap-1.5">
        {editing ? (
          <>
            <Textarea
              value={draft}
              onChange={(event) => setDraft(event.target.value)}
              className="min-h-[5rem] font-serif text-sm"
              aria-label="The lender's wording"
            />
            <p className="text-xs text-muted-foreground">
              Only fix what the reader got wrong — this is stored as the lender’s words.
            </p>
            <div className="flex gap-2">
              <Button
                size="sm"
                onClick={() => {
                  onChange(draft);
                  setEditing(false);
                }}
              >
                Save wording
              </Button>
              <Button
                variant="ghost"
                size="sm"
                onClick={() => {
                  setDraft(row.verbatim_text);
                  setEditing(false);
                }}
              >
                Cancel
              </Button>
            </div>
          </>
        ) : (
          <p className="max-w-prose font-serif text-sm text-foreground">{row.verbatim_text}</p>
        )}

        {row.underwriter_notes.length > 0 ? (
          <div className="flex flex-wrap gap-1.5">
            {row.underwriter_notes.map((note, index) => (
              <NoteChip key={`${note.date}-${index}`} note={note} />
            ))}
          </div>
        ) : null}

        {bySplit ? (
          <span className="inline-flex w-fit items-center gap-1 rounded-md bg-ai/10 px-1.5 py-0.5 text-xs text-ai">
            <Sparkles className="h-3 w-3" aria-hidden />
            Split by AI · {row.confidence.toFixed(2)}
          </span>
        ) : null}
      </div>

      <div className="flex items-start justify-between gap-1">
        <div className="flex min-w-0 flex-col">
          <span className="text-xs text-foreground-2">{OWNER_LABEL[row.owner_hint]}</span>
          {/* ⚠️ THE PROVENANCE, BECAUSE THE HINTS ARE NOT EQUALLY GOOD. A `TC:` the lender typed is
              far stronger than a default from the code map, and showing them identically would
              invite trusting the weak one — the reason the column exists at all. */}
          {SOURCE_LABEL[row.owner_hint_source] ? (
            <span className="text-xs text-muted-foreground">
              {SOURCE_LABEL[row.owner_hint_source]}
            </span>
          ) : null}
        </div>
        {!editing ? (
          <div className="flex shrink-0 gap-0.5">
            <Button
              variant="ghost"
              size="sm"
              className="h-6 w-6 p-0"
              onClick={() => setEditing(true)}
              title="Edit the wording"
            >
              <Pencil className="h-3 w-3" aria-hidden />
              <span className="sr-only">Edit the wording</span>
            </Button>
            <Button
              variant="ghost"
              size="sm"
              className="h-6 w-6 p-0 text-destructive"
              onClick={onRemove}
              title="Remove this row"
            >
              <X className="h-3 w-3" aria-hidden />
              <span className="sr-only">Remove this row</span>
            </Button>
          </div>
        ) : null}
      </div>

      {flagged ? <span className="sr-only">Needs checking before import</span> : null}
    </div>
  );
}

/**
 * The draft rows, grouped by the lender's own heading (S1-04).
 *
 * ⚠️ GROUPED BY `bucket_heading`, IN SHEET ORDER, AND THE HEADING IS THE LENDER'S STRING. Not by
 * `bucket_kind`: the kind is WHEN a condition is due, the heading is WHAT THE LENDER PRINTED, and
 * grouping by the kind would silently merge two differently-worded lender sections that happen to
 * mean the same timing — redrawing the lender's own document.
 *
 * ⚠️ ROWS UNDER 0.80 COME FIRST WITHIN THEIR GROUP (S1-10), which is a sort the processor's
 * attention needs rather than one the sheet has. The sheet order survives everywhere else, and
 * within a group the sequence still decides ties, so the reordering is bounded and reversible.
 */
export function ReviewRows({
  rows,
  onChange,
}: {
  rows: DraftRow[];
  onChange: (rows: DraftRow[]) => void;
}) {
  const groups: { heading: string; kind: DraftRow["bucket_kind"]; rows: DraftRow[] }[] = [];
  for (const row of rows) {
    const last = groups.at(-1);
    if (last && last.heading === row.bucket_heading) last.rows.push(row);
    else groups.push({ heading: row.bucket_heading, kind: row.bucket_kind, rows: [row] });
  }

  function replace(sequence: number, next: Partial<DraftRow> | null) {
    onChange(
      next === null
        ? rows.filter((row) => row.sequence !== sequence)
        : rows.map((row) => (row.sequence === sequence ? { ...row, ...next } : row)),
    );
  }

  return (
    <div className="flex flex-col gap-2">
      {groups.map((group) => {
        const label = BUCKET_KIND_LABEL[group.kind];
        // No chip when the kind adds nothing the heading has not already said.
        const showChip = label.toLowerCase() !== group.heading.toLowerCase();
        const ordered = [...group.rows].sort((left, right) => {
          const leftFlagged = left.confidence < FLAGGED_BELOW ? 0 : 1;
          const rightFlagged = right.confidence < FLAGGED_BELOW ? 0 : 1;
          return leftFlagged - rightFlagged || left.sequence - right.sequence;
        });

        return (
          <div
            key={group.heading}
            className="overflow-hidden rounded-lg border border-input bg-card"
          >
            <div className="flex items-center gap-2 border-b border-input bg-muted/40 px-3 py-2">
              <span className="text-sm font-semibold text-foreground">{group.heading}</span>
              {showChip ? (
                <span className="rounded-md border border-input px-1.5 py-0.5 text-xs text-muted-foreground">
                  {label}
                </span>
              ) : null}
              <span className="ml-auto text-xs text-muted-foreground">{group.rows.length}</span>
            </div>
            {ordered.map((row) => (
              <Row
                key={row.sequence}
                row={row}
                onChange={(verbatim) => replace(row.sequence, { verbatim_text: verbatim })}
                onRemove={() => replace(row.sequence, null)}
              />
            ))}
          </div>
        );
      })}
    </div>
  );
}
