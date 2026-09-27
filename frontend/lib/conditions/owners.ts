import type { OwnerHint } from "@/lib/types/conditions";

/**
 * Who probably has to act, as a word. A HINT, never a decision (Stage 3 decides).
 *
 * `unknown` IS "Not known", NOT "Unknown" — and NOT "Owner not known", which is what it said until
 * LP-913. A bare "Unknown" reads as a party called Unknown rather than as an absence of evidence, so
 * the longer form was written to avoid that; but "Not known" is what S2-01, S2-02 and S2-03 all draw,
 * on the one screen element this label reaches as a standalone owner.
 *
 * THE STAGE 1 PACK DRAWS THE LONG FORM, AND ONE LIVE SCREEN STILL NEEDS IT (LP-913 review). An
 * earlier version of this comment said the Stage 1 pack never drew an unknown owner. It does, seven
 * times: "Owner not known" on S1-04 to S1-09 and S1-12. Most of those draw it in the old imported
 * list, which the Stage 2 list replaced, so "Not known" is right there. But the DRAFT REVIEW rows
 * (S1-04, S1-07) are still live, so `review-rows.tsx` passes `OWNER_NOT_KNOWN_LONG` to `OwnerCell`.
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

/** The Stage 1 review screens' wording for an unknown owner (S1-04, S1-07). See above. */
export const OWNER_NOT_KNOWN_LONG = "Owner not known";
