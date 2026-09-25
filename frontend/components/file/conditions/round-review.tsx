"use client";

import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Spinner } from "@/components/ui/spinner";
import { useImportRound, useUpdateDraft } from "@/lib/api/conditions";
import { getErrorMessage } from "@/lib/errors/api-error";
import { notifyError, notifySuccess } from "@/lib/toast";
import type {
  ConditionRound,
  ConditionSheetFormat,
  ConditionSourceKind,
  DraftRow,
} from "@/lib/types/conditions";
import { CircleCheck, Sparkles, TriangleAlert } from "lucide-react";
import { useId, useState } from "react";
import { FLAGGED_BELOW, ReviewRows } from "./review-rows";
import { ReviewSidePanel } from "./review-side-panel";

/** Which layout the reader recognised, in the words S1-04 and S1-10 print. */
const FORMAT_LABEL: Record<ConditionSheetFormat, string> = {
  uwm_approval_letter: "UWM · Loan Approval Conditions",
  champions_certificate: "Champions · Conditional Approval",
  generic: "Unrecognised layout",
  pasted_text: "Plain text · no lender layout found",
};

const SOURCE_LABEL: Record<ConditionSourceKind, string> = {
  pdf_upload: "PDF upload",
  email: "Forwarded PDF",
  paste: "Pasted",
  manual: "Typed",
};

/** `2026-08-28` → `08/28/2026`. */
function usDate(value: string | null): string | null {
  if (!value) return null;
  const [year, month, day] = value.split("-");
  return year && month && day ? `${month}/${day}/${year}` : value;
}

/**
 * How the reader describes itself, for the line under the format (S1-04, S1-10).
 *
 * ⚠️ THE AI CASE IS NOT "reader: split". `parse_report.reader` is "split" after an AI split and the
 * version is `SPLIT_VERSION`, and the design says "Split by AI (split v1) · rules found no rows" —
 * which names both what ran AND what the rules managed, because a processor reading "split v1"
 * alone cannot tell whether the rules contributed anything.
 */
function readerLine(round: ConditionRound): string {
  const { reader, reader_version, ai_used } = round.parse_report;
  if (!reader) return "No reader ran";
  if (ai_used)
    return `Split by AI (${reader} ${reader_version ?? ""}) · rules found no rows`.trim();
  return `Read by rules (${reader} ${reader_version ?? ""}) — no AI`.replace(" )", ")");
}

/**
 * The review screen — a draft round before anything is saved (S1-04, S1-07, S1-10, S1-11).
 *
 * ⚠️ THE ROWS ARE LOCAL STATE UNTIL SAVED, AND THAT IS THE WHOLE POINT OF THE SCREEN. Nothing a
 * processor edits touches the file until they import; the two sentences in the sticky bar promise
 * exactly that, and they are the design's rule 6 rather than reassurance we invented.
 *
 * ⚠️ IMPORT SENDS THE EDITED TEXT, WHICH IS THE SPEC'S OWN ACCEPTANCE TEST. The draft is PUT before
 * the import POST, so the fingerprint is taken of what the processor left behind — meaning an edited
 * row may match a different condition or none. Correct rather than unfortunate: the fingerprint is
 * of what is imported, not of what was read.
 *
 * ⚠️ THE FLAGGED-ROWS CHECKBOX GATES IMPORT (S1-10), and it appears only when there is something to
 * check — a row the AI split below 0.80, or a line the reader could not assign. A checkbox that is
 * always present is one a processor learns to tick without reading, which is worse than none.
 */
export function RoundReview({
  round,
  fileId,
  onDiscard,
}: {
  round: ConditionRound;
  fileId: string;
  onDiscard: () => void;
}) {
  const checkboxId = useId();
  const [rows, setRows] = useState<DraftRow[]>(round.draft_rows ?? []);
  /**
   * ⚠️ THE TOKEN FOR THE ROWS WE ARE HOLDING, CAPTURED FROM THE SAME SNAPSHOT (LP-909 review).
   *
   * Sending `round.updated_at` instead read the LIVE prop while `rows` stayed the snapshot `useState`
   * seeded from — and the dashboard renders this component with no `key`, so a refetch swaps the
   * prop under a mounted component without resetting the rows. The PUT then carried a FRESH token
   * with STALE rows: `update_draft` compares the token, finds it current, and writes. The 409 that
   * exists for exactly this case could never fire, so the guard was bypassed rather than tripped —
   * a silent overwrite of whatever the other writer had just done.
   *
   * Frozen here, the pair travels together: stale rows arrive with the stale token that produced
   * them, `update_draft` refuses with 409, and the processor is told rather than the other writer's
   * work disappearing. That is the behaviour the endpoint already implements — it was simply never
   * handed a token old enough to trip it.
   *
   * ⚠️ AND `importNow` SAVES UNCONDITIONALLY, WHICH MAKES THIS FIRE ON EVERY IMPORT RATHER THAN
   * RARELY. A processor who edits nothing, leaves the screen open across an enrich, and presses
   * Import would otherwise overwrite the enriched rows with the pre-enrich copy. Both behaviours are
   * right; together they need this token to be honest.
   */
  const [baseUpdatedAt] = useState(round.updated_at);
  const [checked, setChecked] = useState(false);
  const save = useUpdateDraft(fileId);
  const importRound = useImportRound(fileId);

  const report = round.parse_report;
  const unassigned = report.unassigned_lines ?? [];
  const flaggedRows = rows.filter((row) => row.confidence < FLAGGED_BELOW).length;
  const needsCheck = flaggedRows > 0 || unassigned.length > 0;
  const headings = new Set(rows.map((row) => row.bucket_heading)).size;
  const withNotes = rows.filter((row) => row.underwriter_notes.length > 0).length;
  const busy = save.isPending || importRound.isPending;

  function importNow() {
    // ⚠️ SAVE FIRST, ALWAYS — not "if dirty". The import reads `draft_rows` from the ROW, so an
    // unsaved edit would import the text the reader produced rather than the text on screen, and the
    // processor would have no way to tell. One extra PUT is cheaper than that silence.
    save.mutate(
      {
        roundId: round.id,
        draft_rows: rows,
        expected_updated_at: baseUpdatedAt,
      },
      {
        onSuccess: () =>
          importRound.mutate(round.id, {
            onSuccess: (result) =>
              notifySuccess({
                title: `Conditions imported · Round ${result.round_number}`,
                consequence: `${result.created} new, ${result.seen_again} seen again. Import never removes or clears a condition.`,
              }),
            onError: (error) =>
              notifyError({
                title: "Those conditions could not be imported",
                whatToDo: getErrorMessage(error),
              }),
          }),
        onError: (error) =>
          notifyError({
            title: "Your edits could not be saved, so nothing was imported",
            whatToDo: getErrorMessage(error),
          }),
      },
    );
  }

  return (
    <div className="flex flex-col gap-3 pb-20">
      <Card>
        <CardContent className="flex flex-col gap-2 p-3.5">
          <div className="flex flex-wrap items-start justify-between gap-3">
            <div className="flex min-w-0 flex-col gap-1">
              <span className="text-xs font-medium uppercase tracking-wide text-warning">
                Review · not imported yet
              </span>
              <p className="text-base font-semibold text-foreground">
                {FORMAT_LABEL[round.sheet_format]}
              </p>
              <div className="flex flex-wrap items-center gap-1.5">
                {round.sources.map((source) => (
                  <span
                    key={`${source.kind}-${source.at ?? ""}`}
                    className="rounded-md border border-input px-1.5 py-0.5 text-xs text-muted-foreground"
                  >
                    {SOURCE_LABEL[source.kind]}
                  </span>
                ))}
                {/* ⚠️ NO "Date printed" CHIP FOR A PASTE OR A HEADERLESS SHEET (S1-07, S1-11). The
                    letter carries the date; a paste has no letter, and the page-break fixture has no
                    header at all. An empty chip would claim the field exists and is blank. */}
                {round.date_printed ? (
                  <span className="rounded-md border border-input px-1.5 py-0.5 text-xs text-muted-foreground">
                    Date printed {usDate(round.date_printed)}
                  </span>
                ) : null}
                <span className="text-xs text-muted-foreground">{readerLine(round)}</span>
              </div>
            </div>
            <div className="flex shrink-0 flex-col items-end gap-1 text-xs text-muted-foreground">
              <span>
                This sheet is{" "}
                <span className="font-medium text-foreground-2">
                  {round.completeness === "full"
                    ? "the lender’s full list"
                    : "just some conditions"}
                </span>
              </span>
              <span>Round date {usDate(round.round_date)}</span>
            </div>
          </div>

          <div className="mt-1 flex flex-wrap items-center gap-x-2 gap-y-1 border-t border-input pt-2 text-xs text-foreground-2">
            <span className="font-medium">{rows.length} conditions</span>
            <span>·</span>
            <span>
              {headings} {headings === 1 ? "heading" : "headings"}
            </span>
            {withNotes > 0 ? (
              <>
                <span>·</span>
                <span className="flex items-center gap-1 text-warning">
                  <TriangleAlert className="h-3 w-3" aria-hidden />
                  {withNotes} with underwriter notes
                </span>
              </>
            ) : null}
            {flaggedRows > 0 ? (
              <>
                <span>·</span>
                <span className="flex items-center gap-1 text-ai">
                  <Sparkles className="h-3 w-3" aria-hidden />
                  {flaggedRows} split by AI
                </span>
              </>
            ) : null}
            <span>·</span>
            <span
              className={
                report.warnings.length + unassigned.length + report.duplicates_dropped === 0
                  ? "flex items-center gap-1 text-success"
                  : "flex items-center gap-1 text-warning"
              }
            >
              {report.warnings.length + unassigned.length + report.duplicates_dropped === 0 ? (
                <CircleCheck className="h-3 w-3" aria-hidden />
              ) : (
                <TriangleAlert className="h-3 w-3" aria-hidden />
              )}
              {report.warnings.length} warnings · {unassigned.length} lines left over ·{" "}
              {report.duplicates_dropped} duplicates
            </span>
          </div>
        </CardContent>
      </Card>

      {needsCheck || report.warnings.length > 0 ? (
        <Card className="border-warning/40">
          <CardContent className="flex flex-col gap-2 p-3.5">
            <p className="text-sm font-semibold text-foreground">Check before importing</p>

            {report.ai_used ? (
              <p className="max-w-prose rounded-md border-l-2 border-l-ai bg-ai/5 p-2 text-xs text-foreground-2">
                The AI only SPLIT this text into rows — it did not write, summarise or reword any of
                it. Every row was checked to be text that appears in what you pasted, and anything
                that was not is thrown away rather than shown.
              </p>
            ) : null}

            {report.warnings.map((warning) => (
              <p key={warning} className="text-xs text-muted-foreground">
                {warning}
              </p>
            ))}

            {unassigned.map((line) => (
              <div key={line} className="flex flex-wrap items-start gap-2 rounded-md bg-muted p-2">
                <p className="min-w-0 flex-1 font-serif text-sm text-foreground">{line}</p>
                {/* ⚠️ "Ignore this line" IS NOT OFFERED, AND ITS ABSENCE IS DELIBERATE. S1-10 draws
                    it, but nothing in the schema can REMEMBER a dismissal — there is no column for
                    it — so the button would clear on reload and quietly re-raise the line. Recorded
                    against LP-909 rather than faked. The line is already non-blocking: it never
                    becomes a condition unless somebody adds it. */}
                <Button variant="outline" size="sm" disabled title="Add this line as a condition">
                  Add as a condition
                </Button>
              </div>
            ))}
          </CardContent>
        </Card>
      ) : null}

      <div className="grid grid-cols-1 items-start gap-3 xl:grid-cols-[1fr_330px]">
        <ReviewRows rows={rows} onChange={setRows} />
        <ReviewSidePanel round={round} />
      </div>

      <div className="fixed inset-x-0 bottom-0 z-10 flex flex-wrap items-center gap-3 border-t border-input bg-background/95 px-4 py-2.5 backdrop-blur">
        {/* Design rule 6, verbatim — the two sentences that make the screen trustworthy. */}
        <span className="text-xs text-muted-foreground">
          Nothing is saved to the file until you import. Import never removes or clears a condition.
        </span>

        {needsCheck ? (
          <label className="flex cursor-pointer items-center gap-1.5 text-xs text-foreground-2">
            <input
              id={checkboxId}
              type="checkbox"
              checked={checked}
              onChange={(event) => setChecked(event.target.checked)}
              className="accent-primary"
            />
            I checked the flagged rows
          </label>
        ) : null}

        <div className="ml-auto flex items-center gap-2">
          <Button variant="ghost" size="sm" className="text-destructive" onClick={onDiscard}>
            Discard
          </Button>
          <Button size="sm" onClick={importNow} disabled={busy || (needsCheck && !checked)}>
            {busy && <Spinner className="mr-2 h-4 w-4" />}
            Import {rows.length} conditions
          </Button>
        </div>
      </div>
    </div>
  );
}
