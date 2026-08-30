"use client";

import { StatusToken } from "@/components/status-token";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import { type FieldTier, TIER_LABEL, type TierInput, tierFor } from "@/lib/confidence";
import type { Tone } from "@/lib/status";

/**
 * How much scrutiny one field asks for (LP-UI-032).
 *
 * A CONFIDENT FIELD RENDERS NOTHING. Not a green tick, not a quiet label —
 * nothing. Chrome on the fields that are fine is chrome on almost every field, and
 * a mark that appears everywhere stops being a mark. The ones worth a second look
 * are the ones that get ink.
 *
 * `check` is `attention`, never `blocking`: the field is worth reading, not wrong.
 * The system does not know it is wrong — if it did, that would be a finding.
 */
const TONE: Record<Exclude<FieldTier, "confident">, Tone> = {
  verified: "verified",
  check: "attention",
  // Neutral, deliberately. "Nobody rated this" is not a warning, and colouring it
  // as one would put three-quarters of every document in amber.
  unrated: "neutral",
};

/** Why this field is being flagged, in the processor's terms rather than the model's. */
function reason(input: TierInput, tier: FieldTier): string | null {
  if (tier === "verified") return "Confirmed by a person.";
  if (input.distrustedReason) {
    return `This extractor has read this field wrong before, so it is always checked. ${input.distrustedReason}`;
  }
  if (tier === "check" && input.critical) {
    return "A money figure, a rate or an identity — always checked, however sure the model is.";
  }
  if (tier === "check") return "The model was not confident in this value.";
  if (tier === "unrated") return "The model reported no confidence for this field.";
  return null;
}

export function ScrutinyMark({ input }: { input: TierInput }) {
  const tier = tierFor(input);
  // The whole point of the tier: the good case is invisible.
  if (tier === "confident") return null;

  const note = reason(input, tier);
  const rating =
    input.confidence === null
      ? "No confidence reported"
      : // The NUMBER lives here and only here. A column of decimals turns reviewing
        // into arithmetic, and the decimal is the least useful thing on the row.
        `Model confidence ${(input.confidence * 100).toFixed(0)}%`;

  return (
    <Tooltip>
      <TooltipTrigger asChild>
        {/* A BUTTON, not a span with a tabIndex. The reason a field is flagged
            exists only inside this hover, so it has to be reachable — and putting
            a tab stop on a non-interactive element announces something focusable
            that answers nothing to a screen reader. */}
        <button type="button" className="mt-1 inline-flex cursor-help rounded-sm">
          <StatusToken meta={{ tone: TONE[tier], label: TIER_LABEL[tier] }} className="text-xs" />
        </button>
      </TooltipTrigger>
      <TooltipContent side="left" className="max-w-64">
        <p className="font-medium">{TIER_LABEL[tier]}</p>
        {note ? <p className="mt-1 text-xs">{note}</p> : null}
        <p className="mt-1 text-xs opacity-80">{rating}</p>
      </TooltipContent>
    </Tooltip>
  );
}
