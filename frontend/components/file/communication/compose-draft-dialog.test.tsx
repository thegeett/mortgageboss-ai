// @vitest-environment jsdom
/**
 * LP-856 — Compose, the dialog's half of acceptance 1 and 5.
 *
 * ACCEPTANCE 5 IS ASSERTED ON THE SERVER (`tests/api/test_compose_draft_lp856.py`) because that is
 * where a participant row would be written. What this file can add is the half a server test cannot
 * see: the address is TYPED here, seeded from a read of the borrower, and the dialog sends exactly
 * the three fields — nothing that could become a party address on the way.
 */
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const mockCompose = vi.fn();
const mockBorrowers = vi.fn();

vi.mock("@/lib/api/messages", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/lib/api/messages")>()),
  useComposeDraft: () => ({ mutate: mockCompose, isPending: false }),
}));

vi.mock("@/lib/api/loan-files", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/lib/api/loan-files")>()),
  useLoanFileBorrowers: () => mockBorrowers(),
}));

vi.mock("@/lib/toast", () => ({ notifySuccess: vi.fn(), notifyError: vi.fn() }));

import { ComposeDraftButton } from "./compose-draft-dialog";

afterEach(cleanup);
beforeEach(() => {
  vi.clearAllMocks();
  mockBorrowers.mockReturnValue({
    data: [
      { id: "b2", email: "co@borrower.example", is_primary: false },
      { id: "b1", email: "jane@borrower.example", is_primary: true },
    ],
  });
});

function openDialog() {
  render(<ComposeDraftButton fileId="LF-JR4T" />);
  fireEvent.click(screen.getByRole("button", { name: "Compose" }));
}

describe("Compose", () => {
  it("does not fetch the borrower until the dialog is opened", async () => {
    // LP-856 REVIEW — A BORROWER'S ADDRESS IS NOT FETCHED TO SUPPLY A DEFAULT NOBODY ASKED FOR.
    // `useLoanFileBorrowers` is enabled on the identifier alone, so the only thing keeping it off
    // the page load is that the component calling it is mounted behind `open`. Hoisting the hook
    // into `ComposeDraftButton` is the obvious tidy-up and would make every file screen request
    // `BorrowerDetail` — the payload whose own docstring explains why the loan-file view omits the
    // email — for a button nobody has pressed.
    render(<ComposeDraftButton fileId="LF-JR4T" />);

    expect(mockBorrowers).not.toHaveBeenCalled();

    // THE CONTROL: it is called once the dialog is open, so "not called" above is about the gate
    // rather than about a mock that is never reached at all.
    fireEvent.click(screen.getByRole("button", { name: "Compose" }));
    await screen.findByLabelText("To");
    expect(mockBorrowers).toHaveBeenCalled();
  });

  it("seeds To from the PRIMARY borrower, not the first one", async () => {
    // ORDER IS NOT PRIMACY. The fixture lists the co-borrower first on purpose — a `[0]` would
    // agree with a `find(is_primary)` on any fixture where they happen to coincide, and would put a
    // message meant for the borrower in front of the co-borrower on a file where they do not.
    openDialog();
    const to = (await screen.findByLabelText("To")) as HTMLInputElement;
    expect(to.value).toBe("jane@borrower.example");
  });

  it("leaves To empty when the borrower has no address, rather than showing a guess", async () => {
    mockBorrowers.mockReturnValue({ data: [{ id: "b1", email: null, is_primary: true }] });
    openDialog();
    const to = (await screen.findByLabelText("To")) as HTMLInputElement;
    expect(to.value).toBe("");
  });

  it("will not start a draft without all three fields", async () => {
    openDialog();
    // To is seeded, so the missing ones are subject and body — and the control is below.
    expect(
      (screen.getByRole("button", { name: /Start the draft/ }) as HTMLButtonElement).disabled,
    ).toBe(true);
    fireEvent.change(screen.getByLabelText("Subject"), { target: { value: "An update" } });
    expect(
      (screen.getByRole("button", { name: /Start the draft/ }) as HTMLButtonElement).disabled,
    ).toBe(true);
  });

  it("sends the three typed fields and nothing else", async () => {
    // THE POSITIVE CONTROL for the disabled assertions above, and the shape claim for acceptance 5:
    // a payload carrying a role, a party or a participant id is how an address typed for one
    // message would become a fact about the file.
    openDialog();
    fireEvent.change(screen.getByLabelText("Subject"), { target: { value: "  An update  " } });
    fireEvent.change(screen.getByLabelText("Message"), {
      target: { value: "Your file went to underwriting." },
    });
    fireEvent.click(screen.getByRole("button", { name: /Start the draft/ }));

    await waitFor(() => expect(mockCompose).toHaveBeenCalledTimes(1));
    const payload = mockCompose.mock.calls[0]?.[0] as Record<string, unknown>;
    expect(Object.keys(payload).sort()).toEqual(["body", "recipient", "subject"]);
    expect(payload.recipient).toBe("jane@borrower.example");
    // Trimmed, because a subject with a leading space is a subject line that looks broken in every
    // mail client; the BODY is not, because whitespace there is the processor's own layout.
    expect(payload.subject).toBe("An update");
    expect(payload.body).toBe("Your file went to underwriting.");
  });
});
