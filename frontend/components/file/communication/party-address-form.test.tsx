// @vitest-environment jsdom
/**
 * LP-857 — the address form, where it lives now.
 *
 * LIFTED FROM `party-request-dialog.test.tsx`, which went with its dialog. Two of these cases are
 * that file's, unchanged in substance: an address is saved under the party's OWN role, and the
 * screen names what is stuck rather than shrugging. They were the only part of "Write to another
 * party" that this version keeps, and they are what LP-820's measurement is about — of 166 document
 * types, 13 across title, agent, CPA, insurer and employer had no address anywhere in the schema.
 *
 * The cases that did NOT come across are listed at the bottom of this file, with why.
 */
import { PartyAddressForm } from "@/components/file/communication/party-address-form";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const mockAddAddress = vi.fn();
vi.mock("@/lib/api/party-requests", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/lib/api/party-requests")>()),
  useAddPartyAddress: () => ({ mutate: mockAddAddress, isPending: false }),
}));
vi.mock("@/lib/toast", () => ({ notifySuccess: vi.fn(), notifyError: vi.fn() }));

afterEach(cleanup);
beforeEach(() => vi.clearAllMocks());

describe("PartyAddressForm", () => {
  it("names what is stuck, in the party's own words", () => {
    render(<PartyAddressForm fileId="LF-JR4T" party="title" onSaved={vi.fn()} />);

    // "title company", not "title". The enum value is an internal identifier and a processor should
    // never read one.
    expect(screen.getByText(/No address on file for the title company/i)).toBeTruthy();
    expect(screen.getByText(/Who are they, and where do we write\?/)).toBeTruthy();
  });

  it("saves the address under the party's own role", () => {
    render(<PartyAddressForm fileId="LF-JR4T" party="lender" onSaved={vi.fn()} />);

    fireEvent.change(screen.getByLabelText(/email/i), {
      target: { value: " ops@lender.example " },
    });
    fireEvent.click(screen.getByRole("button", { name: "Save address" }));

    // THE ROLE IS THE PROP, never derived from anything on screen. A lender's address filed under
    // the title company is a message to the wrong company that nothing else would catch.
    expect(mockAddAddress.mock.calls[0]?.[0]).toMatchObject({
      role: "lender",
      email: "ops@lender.example",
    });
  });

  it("does not save an empty address, and does not send a blank name", () => {
    render(<PartyAddressForm fileId="LF-JR4T" party="title" onSaved={vi.fn()} />);
    const save = screen.getByRole("button", { name: "Save address" }) as HTMLButtonElement;

    expect(save.disabled).toBe(true);

    fireEvent.change(screen.getByLabelText(/email/i), { target: { value: "a@b.example" } });
    expect(save.disabled).toBe(false);
    fireEvent.click(save);

    // `undefined`, NOT "". An empty string is a name somebody typed and then deleted; the column is
    // nullable so the participant can simply have no name.
    expect(mockAddAddress.mock.calls[0]?.[0]).toMatchObject({ name: undefined });
  });

  it("hands the saved address back, so the draft is sendable without being reopened", () => {
    // ACCEPTANCE 3's client half. The server has it either way — `suggested_recipient` resolves it
    // on the next read — and this is what stops a processor closing the modal to see the effect of
    // the thing they just did inside it.
    const onSaved = vi.fn();
    render(<PartyAddressForm fileId="LF-JR4T" party="title" onSaved={onSaved} />);

    fireEvent.change(screen.getByLabelText(/email/i), {
      target: { value: "closings@acmetitle.example" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Save address" }));
    expect(onSaved).not.toHaveBeenCalled(); // not before the server agreed

    const opts = mockAddAddress.mock.calls[0]?.[1] as { onSuccess: () => void };
    opts.onSuccess();

    expect(onSaved).toHaveBeenCalledWith("closings@acmetitle.example");
  });

  it("says the address outlives this message", () => {
    // THE SENTENCE IS THE CONTRACT. Typing into "Send to" sends one email and loses the address;
    // this writes a participant, and the copy is what tells a processor which of the two they did.
    render(<PartyAddressForm fileId="LF-JR4T" party="title" onSaved={vi.fn()} />);

    expect(screen.getByText(/used for every future message to this party/i)).toBeTruthy();
  });
});

/**
 * WHAT DID NOT COME ACROSS FROM `party-request-dialog.test.tsx`, and why.
 *
 * • "does not tell a processor to send from the borrower's draft" — asserted a toast that no longer
 *   exists. The defect it guarded (a success message naming the wrong draft) cannot recur through a
 *   dialog that is gone; the surviving path is `compose-request-dialog`, whose own toast is covered
 *   there and goes through `draftToastTitle`.
 * • "leaves the borrower out" / "says so when nobody but the borrower is waiting" — both about the
 *   deleted dialog's LIST of parties. There is no list any more: the draft already exists and knows
 *   whose it is.
 * • "still shows what an unreachable party is owed" — the draft's own "What it asks for" block does
 *   this now, and the modal shows it for every draft rather than only for stuck ones.
 */
