import type { OwnerHint, OwnerHintSource } from "@/lib/types/conditions";
import { Building2, ClipboardList, type LucideIcon, ShieldCheck, User } from "lucide-react";

/**
 * Who probably has to act. A HINT, never a decision (Stage 3 decides).
 *
 * ⚠️ `unknown` IS "Owner not known", NOT "Unknown". The chip sits where a name goes, and a bare
 * "Unknown" reads as a party called Unknown rather than as an absence of evidence.
 */
const OWNER_LABEL: Record<OwnerHint, string> = {
  borrower: "Borrower",
  title: "Title",
  insurance: "Insurance",
  lender: "Lender",
  broker: "Broker",
  processor: "Processor",
  unknown: "Owner not known",
};

/**
 * Where the hint came from, in the design's words (S1-04).
 *
 * ⚠️ WRITTEN, NOT DERIVED FROM THE VALUE. De-snaking gives "code map" and "prefix" — and "prefix"
 * alone says nothing, where `from "TC:" prefix` names the evidence the lender actually typed. The
 * whole point of carrying the source is that the hints are not equally good, so the weak one and
 * the strong one must not read alike.
 */
const SOURCE_LABEL: Record<OwnerHintSource, string> = {
  prefix: "from “TC:” prefix",
  bucket: "from bucket",
  code_map: "from code map",
  none: "",
};

/**
 * The glyph beside each owner, matched to the design pack's own markup (S1-04, S1-11).
 *
 * ⚠️ `unknown` IS `null`, AND THAT IS THE DESIGN RATHER THAN AN OMISSION. Every other owner draws as
 * a bordered chip; "Owner not known" draws as plain muted text with no chip and no icon. A chip says
 * "here is who acts", and putting an absence of evidence in the same container as a named party is
 * the same mistake as labelling it "Unknown", one layer up.
 *
 * ⚠️ TWO PAIRS SHARE A GLYPH ON PURPOSE. Borrower and Broker are both `User`, Title and Lender both
 * `Building2`, exactly as the mock draws them — not a gap to fill with two more distinct icons. The
 * icon is a category cue and the LABEL is the identification, which is why S1-04's "May differ" list
 * names icons explicitly.
 */
const OWNER_ICON: Record<OwnerHint, LucideIcon | null> = {
  borrower: User,
  title: Building2,
  insurance: ShieldCheck,
  lender: Building2,
  broker: User,
  processor: ClipboardList,
  unknown: null,
};

/**
 * The owner hint and where it came from — one cell, shared by the review screen and the imported
 * list (S1-04, S1-05, S1-08, S1-11).
 *
 * ⚠️ ONE COPY, BECAUSE THERE WERE ALREADY TWO AND ICONS WOULD HAVE MADE THREE. `review-rows.tsx` and
 * `imported-conditions.tsx` each carried their own `OWNER_LABEL` and `SOURCE_LABEL`, byte-identical,
 * with the second file's comment even saying "the same vocabulary the review screen uses" — a
 * statement that was true only until somebody edited one of them. The design draws owner chips on
 * BOTH screens (10 in the S1-05 mock, 10 in S1-08), so the treatment had to land in both places
 * regardless; sharing the cell is what stops the two drifting the first time an owner is added.
 */
export function OwnerCell({ hint, source }: { hint: OwnerHint; source: OwnerHintSource }) {
  const Icon = OWNER_ICON[hint];
  return (
    <div className="flex min-w-0 flex-col items-end gap-0.5">
      {Icon ? (
        <span className="inline-flex items-center gap-1 rounded-md border border-input px-1.5 py-0.5 text-xs text-foreground-2">
          <Icon className="h-3 w-3 shrink-0" aria-hidden />
          {OWNER_LABEL[hint]}
        </span>
      ) : (
        <span className="text-xs text-muted-foreground">{OWNER_LABEL[hint]}</span>
      )}
      {/* ⚠️ THE PROVENANCE, BECAUSE THE HINTS ARE NOT EQUALLY GOOD. A `TC:` the lender typed is far
          stronger than a default from the code map, and showing them identically would invite
          trusting the weak one — the reason the column exists at all. */}
      {SOURCE_LABEL[source] ? (
        <span className="text-[10.5px] text-muted-foreground">{SOURCE_LABEL[source]}</span>
      ) : null}
    </div>
  );
}
