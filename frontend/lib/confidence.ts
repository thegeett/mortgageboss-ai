/**
 * How much scrutiny an extracted field asks for (LP-UI-032).
 *
 * Four tiers, and the fourth is the one the ticket did not have. Measured over the
 * 90 current extractions in the corpus: **190 of 734 valued fields carry a
 * confidence at all** — the other 544 have no `confidence` key, because the model
 * was never asked for one or did not return one. A field with no rating is not
 * "confident"; rendering it with no chrome, exactly like a rated 0.99, would show
 * the ABSENCE of a rating as a positive one. That is the same error the ticket
 * exists to prevent, one level up.
 *
 * The number itself belongs in a hover beside the grounding excerpt, never in the
 * default view: a processor reading twelve decimals down a column is doing
 * arithmetic instead of reviewing.
 */

import type { FieldScrutiny } from "@/lib/types/document";

/**
 * Ordinary fields are checked below this. Mirrors `--confidence-standard` in
 * `app/globals.css`; `confidence.test.ts` fails if the two ever disagree.
 */
export const CONFIDENCE_STANDARD = 0.85;

/**
 * The critical threshold, mirroring `--confidence-critical`.
 *
 * IT DOES NOT GATE ANYTHING, and that is a finding rather than an oversight. The
 * ticket asks for two thresholds AND for criticality to override confidence, and
 * the second rule swallows the first: if a critical field is checked whatever its
 * number, there is no number at which 0.97 decides anything. The AC's own sentence
 * — "a 0.97 loan amount, note rate, SSN or income figure still gets flagged" — is
 * the explicit half, so it wins.
 *
 * Kept, exported and tested for parity with the stylesheet so the tension is
 * visible in the code rather than resolved silently by deleting one side of it.
 */
export const CONFIDENCE_CRITICAL = 0.97;

export type FieldTier =
  /** A person confirmed this value. No producer exists yet — see the ticket. */
  | "verified"
  /** Rated, above its threshold, nothing else to say. Gets NO chrome at all. */
  | "confident"
  /** Read this one: critical, or under threshold, or a known-bad extractor field. */
  | "check"
  /** No confidence was reported. Not a judgement, and not silence either. */
  | "unrated"
  /** A person read this and said it is wrong. Their finding, not the model's doubt. */
  | "rejected";

export interface TierInput {
  /** The model's self-rating in [0,1], or null when it gave none. */
  confidence: number | null;
  /** Money, a rate, or an identity — resolved by the backend against the schema specs. */
  critical: boolean;
  /** Why this field has a confirmed wrong value in the corpus (LP-508), or null. */
  distrustedReason: string | null;
  /** Whether a person has confirmed this value (accepted it, or corrected it). */
  humanConfirmed?: boolean;
  /** Whether a person read this value and said it is wrong. */
  rejected?: boolean;
}

/**
 * The tier for one field.
 *
 * ORDER MATTERS and it is the ticket's rule: **criticality overrides confidence**.
 * A 0.99 loan amount is still checked, because the expensive errors are the
 * confident ones — a hallucinated licence expiry arrives at 0.99 (LP-508). So a
 * high number can never talk a critical field out of being read.
 */
export function tierFor({
  confidence,
  critical,
  distrustedReason,
  humanConfirmed = false,
  rejected = false,
}: TierInput): FieldTier {
  // A person looked at it. Nothing the model reports can downgrade that.
  if (humanConfirmed) return "verified";

  // AND NEITHER CAN A HIGH NUMBER ERASE A REJECTION. Setting `humanConfirmed:
  // false` for a rejection is right — "I could not verify this" is not "this is
  // right" — but false only returns the field to the ordinary path, where a
  // non-critical field rated above the standard threshold is `confident` and
  // renders nothing at all. A processor would reject a value and watch their own
  // decision vanish from the row. A rejection outranks every model signal for the
  // same reason a confirmation does: a person looked.
  if (rejected) return "rejected";

  // A field the system already knows this extractor gets wrong. Independent of the
  // number, because the whole point of the distrust list is that the number lied.
  if (distrustedReason) return "check";

  // Criticality first, and absolutely: an unrated critical field is still critical,
  // and asking for the number before deciding would let a missing rating buy it a
  // pass. Note what this means for CONFIDENCE_CRITICAL — see its comment.
  if (critical) return "check";

  if (confidence === null) return "unrated";
  return confidence >= CONFIDENCE_STANDARD ? "confident" : "check";
}

/** The words for a tier. Neutral, and never an accusation — the model is not on trial. */
export const TIER_LABEL: Record<FieldTier, string> = {
  verified: "Verified",
  confident: "Confident",
  check: "Check this",
  unrated: "Not rated",
  rejected: "Rejected",
};

/**
 * Read the tier inputs for one field out of an extraction entry + the backend's
 * scrutiny.
 *
 * THE ONE PLACE THIS IS DERIVED. It shipped without the verdict in LP-UI-032
 * (there were no verdicts yet) and the review queue grew its own copy in
 * LP-UI-033 — so a field could be accepted, drop out of the keyboard loop, and go
 * on rendering "Check this" beside it. Two computations of one fact, disagreeing.
 * Both callers use this now.
 */
export function tierInputFor(
  confidence: number | null,
  scrutiny: FieldScrutiny | undefined,
): TierInput {
  return {
    confidence,
    critical: scrutiny?.critical ?? false,
    distrustedReason: scrutiny?.distrusted_reason ?? null,
    // A rejection is NOT confirmation — "I could not verify this" is the opposite
    // of "this is right", and it must keep its mark.
    humanConfirmed: scrutiny?.verdict === "accepted" || scrutiny?.verdict === "corrected",
    rejected: scrutiny?.verdict === "rejected",
  };
}
