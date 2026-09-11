import type { VerificationStatus } from "@/lib/types/verification";
/**
 * LP-826 — what a request tells a processor it did.
 *
 * The reported gap: clicking "Request" gave no sign a draft existed. The persistent half is
 * `DraftBadge`, derived from the draft's contents. This is the half a count cannot express — a
 * request for an appraisal is deliberately left out of an email addressed to the borrower, and on
 * the draft's count that is indistinguishable from a click that did nothing.
 */
import { requestConsequence } from "@/lib/verification/request-consequence";
import { describe, expect, it } from "vitest";

function status(added: number, elsewhere: Record<string, number> = {}): VerificationStatus {
  return {
    document_request: { added_to_draft: added, routed_elsewhere: elsewhere },
  } as unknown as VerificationStatus;
}

describe("requestConsequence", () => {
  it("says how many joined the email", () => {
    expect(requestConsequence(status(2))).toContain(
      "2 documents were added to the borrower's email draft",
    );
  });

  it("singular reads as English, not as a count of one", () => {
    expect(requestConsequence(status(1))).toContain("1 document was added");
  });

  it("names the party a non-borrower request went to", () => {
    // THE CASE THE BADGE CANNOT SHOW. The borrower's draft count stays where it was, and without
    // this sentence a processor cannot tell that from a click that did nothing.
    //
    // LP-841 — IT NAMES WHO. This asserted "not the borrower's to send" and "needs list", which was
    // true while those documents were dropped from every draft. They go to the party who holds them
    // now, and that sentence would tell a processor their request reached nobody.
    const message = requestConsequence(status(0, { lender: 1 }));

    expect(message).toContain("draft for the lender");
    expect(message).not.toContain("needs list only");
    // And it must NOT claim the BORROWER's email gained anything.
    expect(message).not.toContain("added to the borrower's email draft");
  });

  it("says the title company, not the catalog's key for it", () => {
    // `title` is a slug. "a draft for the title" is not a sentence a processor would write.
    expect(requestConsequence(status(0, { title: 1 }))).toContain("draft for the title company");
  });

  it("names each party separately when one request went to two", () => {
    // A single finding can want a credit report (lender) and a VOE (employer). Summing them into
    // "2 went elsewhere" loses the only part a processor can act on.
    const message = requestConsequence(status(0, { lender: 1, employer: 2 }));

    expect(message).toContain("1 went to a draft for the lender");
    expect(message).toContain("2 went to a draft for the employer");
  });

  it("reports both halves of a mixed request", () => {
    const message = requestConsequence(status(2, { lender: 1 }));

    expect(message).toContain("2 documents were added");
    expect(message).toContain("1 went to a draft for the lender");
  });

  it("a second click on the same row says so rather than claiming an addition", () => {
    // Already present: `add_needs_to_draft` is idempotent per need, so nothing was added and
    // nothing was skipped. "Added" would be false; silence would read as a broken button.
    const message = requestConsequence(status(0));

    expect(message).toContain("already");
    expect(message).not.toContain("were added");
  });

  it("does not claim the draft holds it, because on this outcome it may not exist", () => {
    // LP-826 REVIEW. This branch used to say "already on the needs list AND in the file's email
    // draft". Measured on PR-3 — a rule whose only document is the lender's appraisal — the second
    // click returns {added: 0, elsewhere: 0} on a file with NO draft at all, so the sentence
    // asserted membership of an email that does not exist. It is the same confusion this ticket
    // exists to remove, arriving one click later.
    const message = requestConsequence(status(0));

    expect(message).not.toContain("draft");
    // The control: the sentence still says something. An empty string would satisfy the line above.
    expect(message.length).toBeGreaterThan(20);
    expect(message).toContain("The finding stays open");
  });

  it("does not throw when there is no status at all", () => {
    // It runs in two mutation handlers now. A toast that throws takes the confirmation with it and
    // leaves a processor with a request that worked and no sign it did.
    expect(requestConsequence(undefined)).toContain("whatever the borrower can send");
  });

  it("falls back to the hedge when the server did not say", () => {
    // A version skew is not a reason to claim something specific and be wrong about it.
    const message = requestConsequence({} as unknown as VerificationStatus);

    expect(message).toContain("whatever the borrower can send");
  });
});
