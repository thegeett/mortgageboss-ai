/**
 * The words Stage 3 plans conditions in, as the screens print them (LP-919 onwards).
 *
 * ONE COPY, like `OWNER_LABEL`: the detail sheet, the plan panel, the confirm dialog and the list all
 * read these, so "Ask a third party" cannot be spelled two ways. The wording is the Stage 3 screens'
 * (S3-01, S3-02, S3-03, S3-12), which win for wording (LP-934).
 */
import type { Performer, PlanOption } from "@/lib/types/conditions";

export const PERFORMER_LABEL: Record<Performer, string> = {
  borrower: "Borrower",
  lo: "LO",
  processor: "You",
  lender: "Lender",
  title: "Title / escrow",
  attorney: "Attorney",
  insurance: "Insurance agent",
  hoa: "HOA",
  employer: "Employer",
  appraiser: "Appraiser",
  other_party: "Other party",
};

export const OPTION_LABEL: Record<PlanOption, string> = {
  ask_borrower: "Ask the borrower",
  ask_third_party: "Ask a third party",
  i_will_do_it: "I’ll do it",
  already_in_file: "Already in the file",
  ask_underwriter: "Ask the underwriter",
  push_back: "Push back",
  lender_doing_it: "Lender is doing it",
  information_only: "Information only",
};

/** `Borrower + LO` — how S3-02 and S3-03 name an item two people act on. */
export function performersLabel(performers: readonly Performer[]): string {
  return performers.map((performer) => PERFORMER_LABEL[performer]).join(" + ");
}

const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];

/** `2026-07` → `Jul 2026`, as S3-01's item lines print a statement month. */
export function monthLabel(month: string | null): string | null {
  if (!month) return null;
  const [year, number] = month.split("-");
  const name = MONTHS[Number(number) - 1];
  return year && name ? `${name} ${year}` : null;
}
