"use client";

import { Button } from "@/components/ui/button";
import { canAttachPdf } from "@/lib/api/conditions";
import { COMPLETENESS_CHIP } from "@/lib/types/conditions";
import type { ConditionRound } from "@/lib/types/conditions";
import { cn } from "@/lib/utils";
import { useRef } from "react";

/** `2026-08-28` → `08/28/2026`. */
function usDate(value: string | null): string {
  if (!value) return "—";
  const [year, month, day] = value.split("-");
  return year && month && day ? `${month}/${day}/${year}` : value;
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

      {/* ⚠️ REVERSED HERE RATHER THAN BY THE CALLER, AND THAT IS THE WHOLE CARE OF THIS FIX (S1-08).
          The design's strip runs Round 1 → Round 2 left to right; the server sends `created_at DESC`
          and `imported-view.tsx` documents the prop as "Every round on the file, newest first", then
          derives `newest = rounds.find(imported) ?? rounds[0]` from that order. Reversing the ARRAY
          before passing it in would silently redefine `newest`, and `newest` is what decides whether
          the "left as they are" sentence appears and which round number it names.
          So the display order is reversed inside the render and the prop contract is untouched. */}
      {[...rounds].reverse().map((round) => {
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
                {COMPLETENESS_CHIP[round.completeness]}
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
