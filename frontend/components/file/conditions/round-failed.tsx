"use client";

import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import type { ConditionRound } from "@/lib/types/conditions";
import { TriangleAlert } from "lucide-react";

/**
 * What each failure kind means, in the processor's words.
 *
 * ⚠️ THESE ARE THE KINDS THE BACKEND CAN ACTUALLY WRITE, and the list came from the code rather than
 * from the mockup: `unreadable`, `no_text`, `bytes_unavailable`, `ai_unavailable`, `enqueue_failed`,
 * and the base `parse_failed`. S1-03's example shows `NO_CONDITIONS_FOUND`, which does not exist —
 * see the deviation recorded in the ticket.
 *
 * The headline is ours; `failure_detail` is the server's sentence and is shown beneath it, because
 * "the file is no longer in storage", "this PDF cannot be opened" and "the sheet is empty" lead a
 * processor to three different next actions (spec §9.8).
 */
const HEADLINE: Record<string, string> = {
  unreadable: "We couldn’t open this PDF",
  no_text: "This PDF has no text we can read",
  bytes_unavailable: "The stored file couldn’t be fetched",
  ai_unavailable: "The reader couldn’t finish this one",
  enqueue_failed: "This sheet was never queued for reading",
  parse_failed: "We couldn’t read conditions from this PDF",
};

/** The typed line, in mono — only from what `parse_report` actually carries. */
function reasonLine(round: ConditionRound): string {
  const report = round.parse_report;
  const parts = [`reason: ${report.failure_kind ?? "unknown"}`];
  // ⚠️ ONE READER, NOT A LIST. The mockup shows "reader uwm v1, champions v1, generic v1" — the
  // readers that were TRIED — and nothing records that: `parse_report.reader` is singular and is
  // written `None` on the failure path. Rendering a list here would be inventing provenance, which
  // is a worse failure than showing less.
  if (report.reader) {
    parts.push(
      `reader ${report.reader}${report.reader_version ? ` ${report.reader_version}` : ""}`,
    );
  }
  return parts.join(" · ");
}

/**
 * A round the reader could not turn into conditions (screen S1-03).
 *
 * ⚠️ BUILT FOR THE FAILURES THAT EXIST, WHICH IS A DEVIATION FROM THE REFERENCE SCREEN AND WAS
 * APPROVED AS ONE. S1-03 depicts a PDF that "has text, but no condition rows or lender headings" —
 * but that case does not fail: the parse task settles unconditionally to `DRAFT` with whatever rows
 * it found, so a non-condition PDF becomes a draft holding ZERO rows. The screen therefore shows a
 * state the system never produces, with a reason code and a readers-tried list it never records.
 *
 * So this renders the real kinds, and the zero-row draft is handled where it actually occurs.
 */
export function RoundFailed({
  round,
  onRetry,
  onUploadAnother,
  onPaste,
  onDiscard,
}: {
  round: ConditionRound;
  onRetry?: () => void;
  onUploadAnother: () => void;
  onPaste: () => void;
  onDiscard: () => void;
}) {
  const kind = round.parse_report.failure_kind ?? "parse_failed";
  const detail = round.parse_report.failure_detail;

  return (
    <Card className="border-destructive/40">
      <CardContent className="flex flex-col gap-3 p-4">
        <div className="flex items-start gap-2">
          <TriangleAlert className="mt-0.5 h-4 w-4 shrink-0 text-destructive" aria-hidden />
          <div className="flex min-w-0 flex-col gap-1">
            <h2 className="text-base font-semibold text-foreground">
              {HEADLINE[kind] ?? HEADLINE.parse_failed}
            </h2>
            {detail ? <p className="max-w-prose text-sm text-muted-foreground">{detail}</p> : null}
          </div>
        </div>

        <code className="w-fit max-w-full truncate rounded-md border border-border bg-muted px-2 py-1 font-mono text-xs text-foreground-2">
          {reasonLine(round)}
        </code>

        <div className="flex flex-wrap items-center gap-2">
          {/* `Try again` is primary and only offered when re-reading is possible — and what makes it
              possible changed. It used to be nothing: no route re-read an existing round at all.
              `POST /condition-rounds/{id}/reparse` is that route now, so the caller passes this.

              It stays OPTIONAL because the server still refuses some rounds, and the sharpest case
              is a pasted one: `parse_round` reads the sheet from storage, and a paste has no stored
              PDF — its text IS the source. The refusal says so in those words rather than settling
              `bytes_unavailable` and blaming storage for something that was never there. */}
          {onRetry ? (
            <Button size="sm" onClick={onRetry}>
              Try again
            </Button>
          ) : null}
          <Button variant="outline" size="sm" onClick={onUploadAnother}>
            Upload a different PDF
          </Button>
          <Button variant="outline" size="sm" onClick={onPaste}>
            Paste instead
          </Button>
          <Button variant="ghost" size="sm" className="text-destructive" onClick={onDiscard}>
            Discard
          </Button>
        </div>
      </CardContent>
    </Card>
  );
}
