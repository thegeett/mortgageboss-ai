"use client";

import { Button } from "@/components/ui/button";
import type { ConditionRound } from "@/lib/types/conditions";
import { cn } from "@/lib/utils";
import { useRef } from "react";

/** `2026-08-28` → `08/28/2026`. */
function usDate(value: string | null): string {
  if (!value) return "—";
  const [year, month, day] = value.split("-");
  return year && month && day ? `${month}/${day}/${year}` : value;
}

/**
 * Whether any arrival on this round stored bytes.
 *
 * ⚠️ IT ASKS THE SERVER'S OWN QUESTION NOW, AND IT USED TO ASK A PROXY (LP-909 review). The authority
 * is `_has_pdf_source` in `condition_enrich.py`, which keys on `storage_path` and says why: "it is
 * the BYTES that make a second attach meaningless. `kind` would need a list of three values kept in
 * step with the enum." This function WAS that list, and could not be anything else while
 * `ConditionSourcePublic` did not serialise the path — the client was structurally unable to ask the
 * real question, so it asked the nearest one it could see.
 *
 * It held only because every bytes-carrying source happens to be written as `pdf_upload` or `email`.
 * That is a fact about the current writers rather than a rule binding them: a fourth kind that
 * stores bytes, or a bytes-less forward, split the two answers apart silently, and the failure was a
 * button offered for a merge the server refuses.
 *
 * `has_bytes` is now on every source — a boolean rather than the path itself, because
 * `_storage_path` is server-controlled precisely so a sender's filename never shapes the storage
 * layout, and shipping it would export that layout to answer yes or no.
 *
 * Still read across the LIST, because `sources` is a list: a paste that gained a PDF carries both
 * arrivals, and the question is whether bytes are present anywhere, not how the round began.
 */
export function hasPdf(round: ConditionRound): boolean {
  return round.sources.some((source) => source.has_bytes);
}

/**
 * Whether the server would accept a PDF for this round.
 *
 * ⚠️ THE SERVER REFUSES ON TWO COUNTS AND THE STRIP CHECKED ONE (LP-909 review).
 * `enrich_round_with_pdf` raises `RoundNotEnrichable` when the status is outside `ENRICHABLE`
 * (`draft` or `imported`) AND when the round already has stored bytes. Gating on the second alone
 * offered "Attach the lender's PDF" on a `discarded` round — which this strip renders deliberately,
 * at `opacity-60`, so the button appeared on it — and on a `parse_failed` one. Both answer 409.
 *
 * A control that offers what the server refuses is the same defect as a label promising what its
 * handler cannot do; this stage has corrected that three times already.
 */
export function canAttachPdf(round: ConditionRound): boolean {
  const enrichable = round.status === "draft" || round.status === "imported";
  return enrichable && !hasPdf(round);
}

const SOURCE_LABEL: Record<string, string> = {
  pdf_upload: "PDF upload",
  email: "Forwarded PDF",
  paste: "Pasted",
  manual: "Typed",
};

/**
 * The round strip above the imported list (S1-05, S1-08).
 *
 * ⚠️ DISCARDED ROUNDS ARE HERE ON PURPOSE. A processor who threw a draft away should see that they
 * did; a round silently vanishing reads as data loss. The dashboard filters them out of "what am I
 * working on", which is a different question from "what has happened to this file".
 *
 * ⚠️ "Attach the lender's PDF" APPEARS ONLY ON A ROUND WITH NO PDF, and that is the whole of LP-907's
 * merge surfaced: it fills the letter details into THAT round and creates no second one. Offering it
 * on a round that already has a PDF would promise a merge the server refuses with "this round
 * already has the lender's PDF".
 */
export function RoundStrip({
  rounds,
  total,
  onAttachPdf,
  onOpenDetails,
  busyRoundId,
}: {
  rounds: ConditionRound[];
  total: number;
  onAttachPdf: (roundId: string, file: File) => void;
  onOpenDetails: (round: ConditionRound) => void;
  busyRoundId?: string | null;
}) {
  const inputs = useRef<Record<string, HTMLInputElement | null>>({});

  return (
    <div className="flex flex-wrap items-stretch gap-2">
      <div className="flex min-w-[8rem] flex-col justify-center rounded-lg border border-input bg-card px-3 py-2">
        <span className="text-xs text-muted-foreground">All rounds</span>
        <span className="text-sm font-semibold text-foreground">
          {total} {total === 1 ? "condition" : "conditions"}
        </span>
      </div>

      {rounds.map((round) => {
        const attachable = canAttachPdf(round);
        return (
          <div
            key={round.id}
            className={cn(
              "flex min-w-[13rem] flex-col gap-1 rounded-lg border border-input bg-card px-3 py-2",
              round.status === "discarded" && "opacity-60",
            )}
          >
            <div className="flex items-baseline gap-2">
              <span className="text-sm font-semibold text-foreground">
                {/* A draft has no number — it is assigned on import — so the card says so rather
                    than printing "Round null". */}
                {round.round_number === null ? "Not imported yet" : `Round ${round.round_number}`}
              </span>
              <span className="text-xs text-muted-foreground">{usDate(round.round_date)}</span>
            </div>

            <div className="flex flex-wrap gap-1">
              {round.sources.map((source) => (
                <span
                  key={`${source.kind}-${source.at ?? ""}`}
                  className="rounded-md border border-input px-1 py-0.5 text-xs text-muted-foreground"
                >
                  {SOURCE_LABEL[source.kind] ?? source.kind}
                </span>
              ))}
              <span className="rounded-md border border-input px-1 py-0.5 text-xs text-muted-foreground">
                {round.completeness === "full" ? "Full list" : "Just some"}
              </span>
            </div>

            <span className="text-xs text-muted-foreground">
              {round.condition_count} on sheet
              {round.status === "discarded" ? " · discarded" : null}
            </span>

            <div className="flex flex-wrap items-center gap-2">
              <button
                type="button"
                className="text-xs text-primary underline-offset-2 hover:underline"
                onClick={() => onOpenDetails(round)}
              >
                Letter details →
              </button>

              {attachable ? (
                <>
                  <input
                    ref={(element) => {
                      inputs.current[round.id] = element;
                    }}
                    type="file"
                    accept="application/pdf"
                    className="hidden"
                    onChange={(event) => {
                      const file = event.target.files?.[0];
                      // Cleared so choosing the same file twice fires `change` again — otherwise a
                      // second attempt after a refusal is a dead button.
                      event.target.value = "";
                      if (file) onAttachPdf(round.id, file);
                    }}
                  />
                  <Button
                    variant="outline"
                    size="sm"
                    className="h-6 px-2 text-xs"
                    disabled={busyRoundId === round.id}
                    onClick={() => inputs.current[round.id]?.click()}
                  >
                    Attach the lender’s PDF
                  </Button>
                </>
              ) : null}
            </div>
          </div>
        );
      })}
    </div>
  );
}
