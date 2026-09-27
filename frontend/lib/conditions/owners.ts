import type { OwnerHint } from "@/lib/types/conditions";

/**
 * Who probably has to act, as a word. A HINT, never a decision (Stage 3 decides).
 *
 * `unknown` IS "Not known", NOT "Unknown" — and NOT "Owner not known", which is what it said until
 * LP-913. A bare "Unknown" reads as a party called Unknown rather than as an absence of evidence, so
 * the longer form was written to avoid that; but "Not known" is what S2-01, S2-02 and S2-03 all draw,
 * on the one screen element this label reaches as a standalone owner.
 *
 * WHY THE LONGER FORM SURVIVED AS LONG AS IT DID: the Stage 1 design pack never draws an unknown
 * owner at all, so it was authored rather than taken from a screen, and LP-909's visual check records
 * "owner chips" without pinning the wording. Stage 2 draws it three times and agrees with itself.
 *
 * IT IS SAFE TO SHORTEN BECAUSE THE SENTENCE THAT WOULD SUFFER ALREADY GUARDS THE CASE.
 * `history.ts` never interpolates this for `unknown` — "Moved to Waiting on someone" is its own
 * wording — and `OWNER_ICON.unknown` is `null`, so `owner-cell.tsx` renders this value only through
 * its plain-text branch, which is exactly the chip the design labels "Not known".
 *
 * MOVED HERE FROM `owner-cell.tsx` (LP-916 review) so the owner chip and the history line
 * ("Moved to Waiting on Borrower") read one copy, not two.
 */
export const OWNER_LABEL: Record<OwnerHint, string> = {
  borrower: "Borrower",
  title: "Title",
  insurance: "Insurance",
  lender: "Lender",
  broker: "Broker",
  processor: "Processor",
  unknown: "Not known",
};
