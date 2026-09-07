// @vitest-environment jsdom
/**
 * LP-835 — writing to somebody who is not the borrower.
 *
 * What this closes is a DEFECT rather than a gap. Party drafts have existed since LP-820 and until
 * LP-831 no screen could send one; the panel this replaces told a processor, on success, to "Send it
 * from the document request above" — where the draft above is the BORROWER's. Following that
 * instruction emailed the borrower while believing the title company had been contacted.
 */
import { PartyRequestDialog } from "@/components/file/communication/party-request-dialog";
import type { PartyRequest } from "@/lib/types/party-request";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const mockRequests = vi.fn();
const mockBuild = vi.fn();
const mockAddAddress = vi.fn();
vi.mock("@/lib/api/party-requests", () => ({
  usePartyRequests: (...args: unknown[]) => mockRequests(...args),
  useBuildPartyDraft: () => ({ mutate: mockBuild, isPending: false }),
  useAddPartyAddress: () => ({ mutate: mockAddAddress, isPending: false }),
}));

const notifySuccess = vi.fn();
vi.mock("@/lib/toast", () => ({
  notifySuccess: (...args: unknown[]) => notifySuccess(...args),
  notifyError: vi.fn(),
}));

afterEach(cleanup);
beforeEach(() => vi.clearAllMocks());

function request(over: Partial<PartyRequest> = {}): PartyRequest {
  return {
    party: "title",
    name: "Acme Title",
    address: "closings@titleco.com",
    reachable: true,
    needs: [{ id: "n1", title: "Title commitment" }],
    ...over,
  } as PartyRequest;
}

function loaded(requests: PartyRequest[]) {
  mockRequests.mockReturnValue({ data: requests, isPending: false, isError: false });
}

describe("PartyRequestDialog", () => {
  it("does not tell a processor to send from the borrower's draft", () => {
    // THE SENTENCE THAT MAILED THE WRONG PERSON. Asserted as a literal so a revert reads as a
    // failure rather than as a rewording nobody notices.
    loaded([request()]);
    render(<PartyRequestDialog fileId="LF-JR4T" open onOpenChange={vi.fn()} />);

    fireEvent.click(screen.getByRole("button", { name: "Create draft" }));
    const onSuccess = mockBuild.mock.calls[0]?.[1]?.onSuccess as (d: unknown) => void;
    onSuccess({ needs_count: 1 });

    const said = notifySuccess.mock.calls[0]?.[0] as { consequence: string };
    expect(said.consequence).not.toContain("document request above");
    expect(said.consequence).toContain("drafts");
  });

  it("leaves the borrower out", () => {
    // Their requests are the file's own draft, which the mailbox already carries. Offering them here
    // would be a second route to the same email.
    loaded([request(), request({ party: "borrower", name: "Sarah" })]);
    render(<PartyRequestDialog fileId="LF-JR4T" open onOpenChange={vi.fn()} />);

    expect(screen.queryByText("Borrower")).toBeNull();
    expect(screen.getByText("Title company")).toBeTruthy();
  });

  it("says what is stuck when a party has no address", () => {
    // LP-820 MEASURED THIS: of 166 document types, 13 across title, agent, CPA, insurer and employer
    // had no address anywhere in the schema. The blocker was never "no way to compose".
    loaded([request({ reachable: false, address: null, name: null })]);
    render(<PartyRequestDialog fileId="LF-JR4T" open onOpenChange={vi.fn()} />);

    expect(screen.getByText(/No address yet/)).toBeTruthy();
    expect(screen.queryByRole("button", { name: "Create draft" })).toBeNull();
    expect(screen.getByRole("button", { name: "Save address" })).toBeTruthy();
  });

  it("still shows what an unreachable party is owed", () => {
    // LISTED RATHER THAN HIDDEN. A screen showing only what it can send renders a stuck file as
    // having nothing to do, which is the failure LP-820 named.
    loaded([request({ reachable: false, address: null })]);
    render(<PartyRequestDialog fileId="LF-JR4T" open onOpenChange={vi.fn()} />);

    expect(screen.getByText("Title commitment")).toBeTruthy();
  });

  it("saves an address under the party's own role", () => {
    loaded([request({ reachable: false, address: null })]);
    render(<PartyRequestDialog fileId="LF-JR4T" open onOpenChange={vi.fn()} />);

    fireEvent.change(screen.getByLabelText(/email/i), {
      target: { value: "closings@titleco.com" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Save address" }));

    expect(mockAddAddress.mock.calls[0]?.[0]).toMatchObject({
      role: "title",
      email: "closings@titleco.com",
    });
  });

  it("says so when nobody but the borrower is waiting", () => {
    // THE CONTROL on the filter above: a dialog that rendered an empty list would look broken, and
    // one that showed the borrower would offer a second route to the same email.
    loaded([request({ party: "borrower" })]);
    render(<PartyRequestDialog fileId="LF-JR4T" open onOpenChange={vi.fn()} />);

    expect(screen.getByText(/waiting on anybody but the borrower/)).toBeTruthy();
  });
});
