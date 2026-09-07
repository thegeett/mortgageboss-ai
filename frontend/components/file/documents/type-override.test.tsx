// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

const { mutate, types, toasts } = vi.hoisted(() => ({
  mutate: vi.fn(),
  types: {
    data: [
      {
        value: "closing_disclosure",
        label: "Closing disclosure",
        category: "property",
        extracts: true,
      },
      { value: "pay_stub", label: "Pay stub", category: "income", extracts: true },
      { value: "hoa_statement", label: "HOA statement", category: "property", extracts: false },
    ] as unknown,
    isPending: false,
    isError: false,
  },
  toasts: { success: vi.fn(), error: vi.fn() },
}));

vi.mock("@/lib/api/documents", () => ({
  useOverrideDocumentType: () => ({ mutate, isPending: false }),
  useDocumentTypes: () => types,
  useReprocessDocument: () => ({ mutate: vi.fn(), isPending: false }),
}));
vi.mock("sonner", () => ({ toast: toasts }));

import type { DocumentResponse, DocumentStatus } from "@/lib/types/document";
import { TypeOverride } from "./type-override";

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
  types.isPending = false;
  types.isError = false;
});

function doc(over: Partial<DocumentResponse> = {}): DocumentResponse {
  return {
    id: "d1",
    document_type: "pay_stub",
    status: "completed" as DocumentStatus,
    ...over,
  } as DocumentResponse;
}

function view(document: DocumentResponse) {
  render(<TypeOverride summary={document} fileId="f1" onPickerOpenChange={vi.fn()} />);
  return screen.getByRole("button", { name: /Apply|Confirm/ }) as HTMLButtonElement;
}

describe("TypeOverride — confirming (LP-638 review)", () => {
  it("lets a processor confirm a needs_review document whose type is already right", () => {
    // THE LITERAL COMPLAINT, still live after the commit that quoted it: "there is no way to
    // confirm in drawer". The picker half was fixed and the confirm half was not — Apply was
    // disabled whenever the selection equalled the current type, which IS the confirm case, while
    // the banner directly above told the processor to "confirm or correct the type below".
    //
    // The PATCH is the confirmation: it sets classification_confidence = 1.0 and clears the review
    // state, which is what takes the document out of the queue.
    const button = view(doc({ status: "needs_review" as DocumentStatus }));

    expect(button.disabled).toBe(false);
    expect(button.textContent).toContain("Confirm");

    fireEvent.click(button);
    expect(mutate).toHaveBeenCalledTimes(1);
    expect(mutate.mock.calls[0]?.[0]).toBe("pay_stub");
  });

  it("says it confirmed rather than claiming it changed something", () => {
    view(doc({ status: "needs_review" as DocumentStatus }));
    fireEvent.click(screen.getByRole("button", { name: /Confirm/ }));
    mutate.mock.calls[0]?.[1].onSuccess();

    expect(toasts.success.mock.calls[0]?.[0]).toBe("Confirmed as Pay stub");
  });

  it("will not confirm a type the server would reject", () => {
    // The retired-slug fallback keeps a non-catalog type VISIBLE so the document still reads
    // correctly, and the endpoint now 422s anything not in the catalog. Allowing confirmation
    // without this check turns `unknown` — the exact cohort needing correction — into a guaranteed
    // error the moment someone presses the button.
    const button = view(
      doc({ document_type: "unknown", status: "needs_review" as DocumentStatus }),
    );

    expect(button.disabled).toBe(true);
  });

  it("stays disabled for a healthy document nobody has changed", () => {
    // Confirming is for a flagged document. A completed one with the right type needs no action,
    // and an enabled button there invites a pointless model call.
    expect(view(doc()).disabled).toBe(true);
  });
});

describe("TypeOverride — claims it must not make", () => {
  it("does not assert extraction behaviour before the catalog is known", () => {
    types.data = undefined as unknown as typeof types.data;
    types.isPending = true;
    render(<TypeOverride summary={doc()} fileId="f1" onPickerOpenChange={vi.fn()} />);

    expect(screen.getByText(/Checking whether this type is extracted/)).toBeDefined();
    expect(screen.queryByText(/no data is extracted/)).toBeNull();
    types.data = [
      { value: "pay_stub", label: "Pay stub", category: "income", extracts: true },
    ] as unknown as typeof types.data;
  });

  it("says so when the type list could not be loaded", () => {
    // `catalog` is undefined whether the request is in flight or failed, and `isPending` goes false
    // on error — so without this the picker simply offers nothing and the processor is left to
    // conclude the control is broken, on the one control this ticket exists to restore.
    types.isError = true;
    render(<TypeOverride summary={doc()} fileId="f1" onPickerOpenChange={vi.fn()} />);

    expect(screen.getByText(/Couldn’t load the document types/)).toBeDefined();
  });
});
