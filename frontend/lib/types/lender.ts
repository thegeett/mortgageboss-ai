/** A lender as returned by `GET /lenders` (LP-32) — for the intake dropdown. */
export interface LenderSummary {
  id: string;
  name: string;
  supported_programs: string[];
}
