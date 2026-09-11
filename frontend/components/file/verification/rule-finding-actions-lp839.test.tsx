// @vitest-environment jsdom
/**
 * LP-839 — the row says what the last request did, and where it went.
 *
 * THE FIXTURE IS A NON-BORROWER DOCUMENT THROUGHOUT, because that is the case that produced the
 * report and the one an obvious implementation gets wrong. Of the 43 documents any rule can put
 * behind a Request button, 16 are somebody else's to send — the credit report, the appraisal, the
 * title commitment, the purchase agreement, the VOE. Every one is correctly kept out of an email
 * addressed to the borrower, and every one used to look identical to a request that landed in it.
 */
import { RuleFindingActions } from "@/components/file/verification/rule-finding-actions";
import type { RuleFinding } from "@/lib/types/verification";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

afterEach(cleanup);

function finding(over: Partial<RuleFinding> = {}): RuleFinding {
  return {
    id: "f1",
    rule_id: "IN-8",
    evaluation_outcome: "couldnt_check",
    resolution_status: "open",
    missing_documents: ["verification of employment"],
    documents_requested: false,
    documents_other_party: {},
    can_apply: false,
    ratification_pending: false,
    ...over,
  } as unknown as RuleFinding;
}

describe("before a request", () => {
  it("offers Request, and says where it goes", () => {
    render(<RuleFindingActions finding={finding()} onAct={vi.fn()} />);

    const button = screen.getByRole("button", { name: /^Request verification of employment$/ });
    expect(button.getAttribute("title")).toBe(
      "This will be added to the latest communication draft.",
    );
  });

  it("says so when the document is NOT the borrower's to send", () => {
    // The tooltip must not promise the draft for a document that will never enter it. This is the
    // VOE case: `voe`'s responsible party is the EMPLOYER.
    render(
      <RuleFindingActions
        finding={finding({ documents_other_party: { "verification of employment": "employer" } })}
        onAct={vi.fn()}
      />,
    );

    expect(screen.getByRole("button", { name: /Request/ }).getAttribute("title")).toMatch(
      /not the borrower's to send/i,
    );
  });
});

describe("after a request", () => {
  it("the button becomes Re-request", () => {
    // The row gated on `missing_documents` alone and never read `docs_requested`, which LP-801 has
    // written at request time since that ticket. So a finding already acted on offered an identical
    // button, and a processor could not tell it apart from a fresh one.
    render(<RuleFindingActions finding={finding({ documents_requested: true })} onAct={vi.fn()} />);

    expect(screen.getByRole("button", { name: /^Re-request/ })).toBeTruthy();
    expect(screen.queryByRole("button", { name: /^Request verification/ })).toBeNull();
  });

  it("says it is in the draft when it is", () => {
    render(
      <RuleFindingActions
        finding={finding({ documents_requested: true, missing_documents: ["bank statement"] })}
        onAct={vi.fn()}
      />,
    );

    expect(screen.getByText(/in the latest draft/)).toBeTruthy();
  });

  it("names the party whose draft took it, when it was not the borrower's", () => {
    // THE REPORTED CASE. "Requested" and "in the BORROWER's draft" are different claims, and for 16
    // of 43 documents only the first is true — a row that said "in the latest draft" for a VOE
    // would be the same untrue confirmation, moved from a toast onto the page.
    //
    // LP-841 — AND THE OPPOSITE SENTENCE IS NOW THE FALSE ONE. This asserted "not the borrower's to
    // send", which read as "so nobody was asked". The VOE is in a draft to the employer.
    render(
      <RuleFindingActions
        finding={finding({
          documents_requested: true,
          documents_other_party: { "verification of employment": "employer" },
        })}
        onAct={vi.fn()}
      />,
    );

    expect(screen.getByText(/in a draft for the employer/)).toBeTruthy();
    expect(screen.queryByText(/in the latest draft/)).toBeNull();
  });

  it("says both when a finding wants one of each", () => {
    // A rule can want a document from the borrower AND one from the lender — CR-6 wants a credit
    // report and a closing disclosure, both the lender's; IN-8 mixes. A single sentence would be
    // wrong about half of it.
    render(
      <RuleFindingActions
        finding={finding({
          documents_requested: true,
          missing_documents: ["pay stub", "verification of employment"],
          documents_other_party: { "verification of employment": "employer" },
        })}
        onAct={vi.fn()}
      />,
    );

    expect(screen.getByText(/in the latest draft/)).toBeTruthy();
    expect(screen.getByText(/in a draft for the employer/)).toBeTruthy();
  });

  it("says nothing about a request that has not happened", () => {
    // THE CONTROL. A row that always rendered the line would satisfy every assertion above and tell
    // a processor a fresh finding had already been actioned.
    render(<RuleFindingActions finding={finding()} onAct={vi.fn()} />);

    expect(screen.queryByText(/in the latest draft/)).toBeNull();
    expect(screen.queryByText(/needs list/)).toBeNull();
  });
});

describe("the note", () => {
  it("says who reads it", () => {
    // It asked "anything to add to the request?", stored the answer in NeedsItem.description, and
    // nothing rendered it — the draft body came from the catalog's guidance or the title. The label
    // now names the borrower because the note now reaches them.
    render(<RuleFindingActions finding={finding()} onAct={vi.fn()} />);
    fireEvent.click(screen.getByRole("button", { name: /Request/ }));

    expect(screen.getByText("Anything to add for the borrower?")).toBeTruthy();
  });
});
