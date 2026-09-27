import type { OwnerHint } from "@/lib/types/conditions";

/**
 * Who probably has to act, as a word. A HINT, never a decision (Stage 3 decides).
 *
 * `unknown` IS "Owner not known", NOT "Unknown". The chip sits where a name goes, and a bare
 * "Unknown" reads as a party called Unknown rather than as an absence of evidence.
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
  unknown: "Owner not known",
};
