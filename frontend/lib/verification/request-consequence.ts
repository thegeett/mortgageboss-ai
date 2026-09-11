import type { VerificationStatus } from "@/lib/types/verification";

/**
 * What a request actually did, in the borrower's terms rather than the system's (LP-826).
 *
 * THE COUNT ALONE CANNOT SAY IT. A request for an appraisal, a title commitment or an employer's
 * VOE is deliberately left out of an email addressed to the borrower — it goes on the needs list
 * and LP-820 owns chasing the other party. On the draft's count that is indistinguishable from a
 * click that did nothing, and the previous copy hedged ("whatever the borrower can send") because
 * nothing told the client which had happened.
 *
 * FALLS BACK TO THE HEDGE rather than to silence: an older server that does not send the field is a
 * version skew, not a reason to claim something specific and be wrong about it.
 *
 * LP-839 — MOVED HERE FROM `findings-list.tsx`, WHICH IS HALF THE SCREENS THAT REQUEST.
 *
 * It was written for the LEGACY AI-sweep rows and the GOVERNED §8 rows — where the Request button a
 * processor actually clicks lives — kept their own sentence: "whatever the borrower can send is in
 * the file's email draft". True, unfalsifiable, and identical whether the draft gained a line or
 * not. A processor requesting a VOE saw success and an unchanged draft, and 16 of the 43 documents
 * a rule can put behind that button are somebody else's to send.
 *
 * One module so a third surface cannot invent a third sentence.
 */
/** The party names as a processor says them, not as the catalog keys them. */
const PARTY_NOUN: Record<string, string> = {
  borrower: "borrower",
  employer: "employer",
  lender: "lender",
  title: "title company",
  cpa: "accountant",
  agent: "agent",
  insurer: "insurer",
};

export function requestConsequence(status: VerificationStatus | undefined): string {
  // TOLERATES NO STATUS AT ALL, which is not defensiveness for its own sake: this now runs in two
  // mutation handlers, and a toast that throws takes the confirmation with it — leaving a processor
  // with a request that worked and no sign it did. The hedge below is already the right answer to
  // "the server did not say", and "there was no response object" is the same question.
  const outcome = status?.document_request;
  if (!outcome) {
    return "On the needs list, and whatever the borrower can send is in the file's email draft. The finding stays open until it is met.";
  }
  const { added_to_draft: added, routed_elsewhere: elsewhere } = outcome;
  const parts: string[] = [];
  if (added > 0) {
    parts.push(
      added === 1
        ? "1 document was added to the borrower's email draft"
        : `${added} documents were added to the borrower's email draft`,
    );
  }
  // LP-841 — NAMES WHO, because there is now a who. This said "N are not the borrower's to send, so
  // they are on the needs list only", which was true while those documents were dropped from the
  // draft and put nowhere. They go to the party who holds them now, and the old sentence tells a
  // processor their request reached nobody in exactly the case where it reached somebody.
  for (const [party, count] of Object.entries(elsewhere ?? {})) {
    parts.push(
      count === 1
        ? `1 went to a draft for the ${PARTY_NOUN[party] ?? party}`
        : `${count} went to a draft for the ${PARTY_NOUN[party] ?? party}`,
    );
  }
  if (parts.length === 0) {
    // A second click on a row that is already requested. LP-826 REVIEW — THIS MUST NOT CLAIM THE
    // DRAFT. It used to say "already on the needs list AND in the file's email draft", and measured
    // on PR-3 — a rule whose only document is the lender's appraisal — the second click returns
    // {added: 0, elsewhere: 0} on a file that has NO draft at all. The sentence asserted membership
    // of an email that does not exist, in exactly the case this ticket exists to distinguish.
    //
    // Where it went is already answered: it was said on the first click, and the badge shows what
    // the draft holds now. This says only what this click did.
    return "It had already been requested — nothing new was added. The finding stays open until it is met.";
  }
  return `${parts.join(". ")}. The finding stays open until it is met.`;
}
