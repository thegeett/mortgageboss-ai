/**
 * LP-826 — what a request tells a processor it did.
 *
 * The reported gap: clicking "Request" gave no sign a draft existed. The persistent half is
 * `DraftBadge`, derived from the draft's contents. This is the half a count cannot express — a
 * request for an appraisal is deliberately left out of an email addressed to the borrower, and on
 * the draft's count that is indistinguishable from a click that did nothing.
 */
import { requestConsequence } from "@/components/file/verification/findings-list";
import type { VerificationStatus } from "@/lib/types/verification";
import { describe, expect, it } from "vitest";

function status(added: number, elsewhere: number): VerificationStatus {
  return {
    document_request: { added_to_draft: added, not_borrower_facing: elsewhere },
  } as unknown as VerificationStatus;
}

describe("requestConsequence", () => {
  it("says how many joined the email", () => {
    expect(requestConsequence(status(2, 0))).toContain(
      "2 documents were added to the file's email draft",
    );
  });

  it("singular reads as English, not as a count of one", () => {
    expect(requestConsequence(status(1, 0))).toContain("1 document was added");
  });

  it("says where a non-borrower request went instead", () => {
    // THE CASE THE BADGE CANNOT SHOW. Without this sentence the draft count stays where it was and
    // the processor is left to guess whether the click worked.
    const message = requestConsequence(status(0, 1));

    expect(message).toContain("not the borrower's to send");
    expect(message).toContain("needs list");
    // And it must NOT claim the email gained anything.
    expect(message).not.toContain("added to the file's email draft");
  });

  it("reports both halves of a mixed request", () => {
    const message = requestConsequence(status(2, 1));

    expect(message).toContain("2 documents were added");
    expect(message).toContain("1 is not the borrower's to send");
  });

  it("a second click on the same row says so rather than claiming an addition", () => {
    // Already present: `add_needs_to_draft` is idempotent per need, so nothing was added and
    // nothing was skipped. "Added" would be false; silence would read as a broken button.
    const message = requestConsequence(status(0, 0));

    expect(message).toContain("already");
    expect(message).not.toContain("were added");
  });

  it("does not claim the draft holds it, because on this outcome it may not exist", () => {
    // LP-826 REVIEW. This branch used to say "already on the needs list AND in the file's email
    // draft". Measured on PR-3 — a rule whose only document is the lender's appraisal — the second
    // click returns {added: 0, elsewhere: 0} on a file with NO draft at all, so the sentence
    // asserted membership of an email that does not exist. It is the same confusion this ticket
    // exists to remove, arriving one click later.
    const message = requestConsequence(status(0, 0));

    expect(message).not.toContain("draft");
    // The control: the sentence still says something. An empty string would satisfy the line above.
    expect(message.length).toBeGreaterThan(20);
    expect(message).toContain("The finding stays open");
  });

  it("falls back to the hedge when the server did not say", () => {
    // A version skew is not a reason to claim something specific and be wrong about it.
    const message = requestConsequence({} as unknown as VerificationStatus);

    expect(message).toContain("whatever the borrower can send");
  });
});
