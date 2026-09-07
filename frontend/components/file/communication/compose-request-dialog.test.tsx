// @vitest-environment jsdom
/**
 * LP-833 — asking for documents nothing flagged.
 *
 * WHAT SHIPS IS "PICK DOCUMENTS, GET A DRAFT". `email_draft_enabled` is off in every environment, so
 * the model writes nothing today and a processor gets LP-817's template — a complete email, not a
 * degraded one. The thing that must not be false is the sentence the screen says about which kind of
 * email it just made.
 */
import { ComposeRequestDialog } from "@/components/file/communication/compose-request-dialog";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const mockCompose = vi.fn();
vi.mock("@/lib/api/communications", () => ({
  useComposeRequest: () => ({ mutate: mockCompose, isPending: false }),
}));

const mockTypes = vi.fn();
vi.mock("@/lib/api/documents", () => ({
  useDocumentTypes: () => mockTypes(),
}));

const mockNeeds = vi.fn();
vi.mock("@/lib/api/needs", () => ({
  useNeeds: () => mockNeeds(),
}));

const notifySuccess = vi.fn();
vi.mock("@/lib/toast", () => ({
  notifySuccess: (...args: unknown[]) => notifySuccess(...args),
  notifyError: vi.fn(),
}));

afterEach(cleanup);
beforeEach(() => {
  vi.clearAllMocks();
  mockTypes.mockReturnValue({
    data: [
      { value: "w2", label: "W-2", category: "income", extracts: true },
      { value: "bank_statement", label: "Bank statement", category: "assets", extracts: true },
      { value: "pay_stub", label: "Pay stub", category: "income", extracts: true },
    ],
  });
  mockNeeds.mockReturnValue({ data: [] });
});

function open() {
  render(<ComposeRequestDialog fileId="LF-JR4T" open onOpenChange={vi.fn()} />);
}

describe("ComposeRequestDialog", () => {
  it("sends the picked types", () => {
    open();
    fireEvent.click(screen.getByLabelText(/W-2/));
    fireEvent.click(screen.getByLabelText(/Pay stub/));
    fireEvent.click(screen.getByRole("button", { name: "Generate email" }));

    expect(mockCompose.mock.calls[0]?.[0]).toEqual(["w2", "pay_stub"]);
  });

  it("refuses to generate with nothing picked", () => {
    // A click that meant nothing must not mint a draft — the same rule LP-809's review applied to a
    // request the borrower has no part in.
    open();

    expect(
      (screen.getByRole("button", { name: "Generate email" }) as HTMLButtonElement).disabled,
    ).toBe(true);
  });

  it("puts the file's outstanding needs first", () => {
    // 166 document types alphabetically is a list nobody reads, and the ones this file is waiting on
    // are the likely answer. ORDERED, not filtered — the rest of the catalog is what this is for.
    mockNeeds.mockReturnValue({ data: [{ id: "n1", needs_type: "pay_stub" }] });
    open();

    const labels = screen.getAllByRole("checkbox").map((box) => box.closest("label")?.textContent);
    expect(labels[0]).toContain("Pay stub");
    expect(labels).toHaveLength(3);
  });

  it("says which types are already requested, before they are picked", () => {
    // LP-826 built the after-the-fact answer. Saying it at selection is cheaper for everybody, and
    // asking twice for one document is the mistake it prevents.
    mockNeeds.mockReturnValue({ data: [{ id: "n1", needs_type: "pay_stub" }] });
    open();

    expect(screen.getByText("already requested")).toBeTruthy();
  });

  it("searches the catalog", () => {
    open();
    fireEvent.change(screen.getByLabelText("Search documents"), { target: { value: "bank" } });

    expect(screen.getAllByRole("checkbox")).toHaveLength(1);
    expect(screen.getByLabelText(/Bank statement/)).toBeTruthy();
  });

  it("does not claim the model wrote it when the model did not", () => {
    // THE SENTENCE THAT WOULD BE FALSE EVERY TIME. `email_draft_enabled` is off in every
    // environment, so `composed_by_model` is false and the words are the template's. A toast saying
    // otherwise would be the untrue half of this feature's own headline.
    open();
    fireEvent.click(screen.getByLabelText(/W-2/));
    fireEvent.click(screen.getByRole("button", { name: "Generate email" }));
    const onSuccess = mockCompose.mock.calls[0]?.[1]?.onSuccess as (r: unknown) => void;
    onSuccess({ draft_id: "d1", needs_added: 1, composed_by_model: false });

    const said = notifySuccess.mock.calls[0]?.[0] as { consequence: string };
    expect(said.consequence).toContain("standard wording");
  });

  it("says so when the model DID write it", () => {
    // THE CONTROL on the sentence above: a toast hardcoded to "standard wording" would satisfy it
    // and be wrong the day somebody turns the flag on.
    open();
    fireEvent.click(screen.getByLabelText(/W-2/));
    fireEvent.click(screen.getByRole("button", { name: "Generate email" }));
    const onSuccess = mockCompose.mock.calls[0]?.[1]?.onSuccess as (r: unknown) => void;
    onSuccess({ draft_id: "d1", needs_added: 1, composed_by_model: true });

    const said = notifySuccess.mock.calls[0]?.[0] as { consequence: string };
    expect(said.consequence).toContain("drafted for this file");
  });
});
