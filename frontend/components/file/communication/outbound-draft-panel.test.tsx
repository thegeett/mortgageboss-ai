// @vitest-environment jsdom
/**
 * LP-811b — the panel a processor sends from.
 *
 * The behaviours worth protecting are the ones that fail silently in a browser: a `mailto:` link
 * offered for a message too long to survive it, and a regenerating draft overwriting text somebody
 * is in the middle of typing. Neither throws; both lose work or send half an email.
 */
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const mockUseOutboundDraft = vi.fn();
const mockMutate = vi.fn();
const mockSendState = {
  mutate: mockMutate,
  isPending: false,
  isError: false,
  isSuccess: false,
  data: undefined as { needs_items_requested: number } | undefined,
};

vi.mock("@/lib/api/communications", async () => {
  const actual = await vi.importActual<typeof import("@/lib/api/communications")>(
    "@/lib/api/communications",
  );
  return {
    // `mailtoUrl` is deliberately the REAL one. It is the function under test in two of these
    // cases, and mocking it would leave them asserting that a mock returns what it was told to.
    mailtoUrl: actual.mailtoUrl,
    useOutboundDraft: (...args: unknown[]) => mockUseOutboundDraft(...args),
    useSendDraft: () => mockSendState,
  };
});

import { OutboundDraftPanel } from "./outbound-draft-panel";

function wrapper({ children }: { children: ReactNode }) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
}

const DRAFT = {
  id: "draft-1",
  subject: "Documents we need for your loan (LF-6T3N)",
  body: "Hello,\n\nPlease send these.\n\n[LF-6T3N]",
  reply_to: "lf-token@inbox.example.com",
  suggested_bcc: "lf-token@inbox.example.com",
  mailto_available: true,
  mailto_max_chars: 1800,
  needs_item_count: 2,
  suggested_recipient: "sarah@example.com" as string | null,
};

function draftState(overrides: Partial<typeof DRAFT> | null = {}) {
  return {
    data: overrides === null ? null : { ...DRAFT, ...overrides },
    isPending: false,
    isError: false,
  };
}

/** The To: input. Read through its value rather than a jest-dom matcher — this suite does not
 * load one, and `toHaveValue` fails as an unknown Chai property rather than as a wrong value. */
function toBox(): HTMLInputElement {
  return screen.getByPlaceholderText("borrower@example.com") as HTMLInputElement;
}

afterEach(cleanup);

beforeEach(() => {
  vi.clearAllMocks();
  mockSendState.isPending = false;
  mockSendState.isError = false;
  mockSendState.isSuccess = false;
  mockSendState.data = undefined;
});

describe("OutboundDraftPanel", () => {
  it("seeds the To: field from the borrower's address (LP-823)", () => {
    // The box used to start empty and every send was retyped by hand. The address is on the
    // application; the panel had no field to read it from.
    mockUseOutboundDraft.mockReturnValue(draftState());
    render(<OutboundDraftPanel fileId="LF-6T3N" />, { wrapper });

    expect(toBox().value).toBe("sarah@example.com");
  });

  it("leaves To: empty when the file has no borrower address", () => {
    // `borrowers.email` is nullable, so this file is ordinary rather than broken. An empty box is
    // the honest render; anything else would be a suggestion that is not an address.
    mockUseOutboundDraft.mockReturnValue(draftState({ suggested_recipient: null }));
    render(<OutboundDraftPanel fileId="LF-6T3N" />, { wrapper });

    expect(toBox().value).toBe("");
  });

  it("does not overwrite an address the processor corrected", () => {
    // The seed is keyed on the draft's IDENTITY, like the body. A processor who types a
    // co-borrower's address must not have it replaced under them when the draft regenerates.
    mockUseOutboundDraft.mockReturnValue(draftState());
    const { rerender } = render(<OutboundDraftPanel fileId="LF-6T3N" />, { wrapper });

    fireEvent.change(toBox(), { target: { value: "cosigner@example.com" } });
    mockUseOutboundDraft.mockReturnValue(
      draftState({ body: "Hello,\n\nRegenerated.\n\n[LF-6T3N]" }),
    );
    rerender(<OutboundDraftPanel fileId="LF-6T3N" />);

    expect(toBox().value).toBe("cosigner@example.com");
  });

  it("shows the draft, the reply-to and the bcc suggestion", () => {
    mockUseOutboundDraft.mockReturnValue(draftState());
    render(<OutboundDraftPanel fileId="f1" />, { wrapper });

    expect(screen.getByDisplayValue(/Please send these/)).toBeDefined();
    expect(screen.getAllByText(/lf-token@inbox.example.com/).length).toBeGreaterThan(0);
    expect(screen.getByText(/2 documents are included/)).toBeDefined();
  });

  it("tells a processor there is nothing to request rather than showing an empty form", () => {
    // The empty state is ORDINARY — a file in good order has no outstanding documents. An empty
    // textarea with a Send button under it would read as a broken page.
    mockUseOutboundDraft.mockReturnValue(draftState(null));
    render(<OutboundDraftPanel fileId="f1" />, { wrapper });

    expect(screen.getByText("Nothing to request")).toBeDefined();
    expect(screen.queryByRole("button", { name: /Mark as sent/ })).toBeNull();
  });

  it("offers the mail client for a short message", () => {
    mockUseOutboundDraft.mockReturnValue(draftState());
    render(<OutboundDraftPanel fileId="f1" />, { wrapper });
    fireEvent.change(screen.getByPlaceholderText("borrower@example.com"), {
      target: { value: "b@example.com" },
    });

    expect(
      screen.getByRole("link", { name: /Open in mail client/ }).getAttribute("href"),
    ).toContain("mailto:");
  });

  it("withholds the mail client link when the message is too long, and says why", () => {
    // `mailto:` does not FAIL when it is over the client's limit — it opens a compose window with
    // part of the message in it. A disabled button with no explanation gets worked around; the
    // reason is what stops a processor pasting a truncated draft anyway.
    mockUseOutboundDraft.mockReturnValue(draftState({ mailto_available: false }));
    render(<OutboundDraftPanel fileId="f1" />, { wrapper });

    expect(screen.queryByRole("link", { name: /Open in mail client/ })).toBeNull();
    expect(screen.getByText(/too long to open in a mail client/)).toBeDefined();
    expect(screen.getByText(/1800 characters/)).toBeDefined();
  });

  it("cannot be sent without a recipient", () => {
    // LP-823 — the file with NO borrower address, which is now the only way the box starts empty.
    // Left as an explicit case rather than deleted: "send is refused with no recipient" is still
    // the rule, and a seeded default must not be allowed to hide it.
    mockUseOutboundDraft.mockReturnValue(draftState({ suggested_recipient: null }));
    render(<OutboundDraftPanel fileId="f1" />, { wrapper });

    expect(
      (screen.getByRole("button", { name: /Mark as sent/ }) as HTMLButtonElement).disabled,
    ).toBe(true);
  });

  it("sends the processor's edited body, not the draft as composed", async () => {
    // The record of an outbound message must be what went out. Sending `draft.body` while the
    // processor had rewritten the textarea would file a message nobody sent.
    mockUseOutboundDraft.mockReturnValue(draftState());
    render(<OutboundDraftPanel fileId="f1" />, { wrapper });

    fireEvent.change(screen.getByPlaceholderText("borrower@example.com"), {
      target: { value: "b@example.com" },
    });
    fireEvent.change(screen.getByRole("textbox", { name: /Message/ }), {
      target: { value: "I rewrote this entirely." },
    });
    fireEvent.click(screen.getByRole("button", { name: /Mark as sent/ }));

    await waitFor(() =>
      expect(mockMutate).toHaveBeenCalledWith({
        draftId: "draft-1",
        recipient: "b@example.com",
        body: "I rewrote this entirely.",
      }),
    );
  });

  it("does not overwrite an edit when the same draft re-renders", () => {
    // LP-809 REGENERATES the draft on every add and remove, so the query returns a new object
    // frequently. Re-seeding from it would throw away a processor's edits mid-sentence — the
    // failure this component's seeding rule exists to prevent, and one nothing would report.
    mockUseOutboundDraft.mockReturnValue(draftState());
    const { rerender } = render(<OutboundDraftPanel fileId="f1" />, { wrapper });

    fireEvent.change(screen.getByRole("textbox", { name: /Message/ }), {
      target: { value: "half a sentence I am still" },
    });
    mockUseOutboundDraft.mockReturnValue(draftState({ body: "a regenerated body" }));
    rerender(<OutboundDraftPanel fileId="f1" />);

    expect(screen.getByDisplayValue("half a sentence I am still")).toBeDefined();
  });

  it("does seed from a different draft", () => {
    // The control for the test above. A component that never seeded would satisfy it and would show
    // an empty box for every draft.
    mockUseOutboundDraft.mockReturnValue(draftState());
    const { rerender } = render(<OutboundDraftPanel fileId="f1" />, { wrapper });
    expect(screen.getByDisplayValue(/Please send these/)).toBeDefined();

    mockUseOutboundDraft.mockReturnValue(draftState({ id: "draft-2", body: "A different draft." }));
    rerender(<OutboundDraftPanel fileId="f1" />);

    expect(screen.getByDisplayValue("A different draft.")).toBeDefined();
  });

  it("explains a refused send instead of failing silently", () => {
    mockUseOutboundDraft.mockReturnValue(draftState());
    mockSendState.isError = true;
    render(<OutboundDraftPanel fileId="f1" />, { wrapper });

    expect(screen.getByText(/was not recorded as sent/)).toBeDefined();
  });

  it("confirms how many documents moved to requested", () => {
    mockUseOutboundDraft.mockReturnValue(draftState());
    mockSendState.isSuccess = true;
    mockSendState.data = { needs_items_requested: 2 };
    render(<OutboundDraftPanel fileId="f1" />, { wrapper });

    expect(screen.getByText(/2 documents moved to requested/)).toBeDefined();
  });
});

describe("the mail-client link and the processor's edit", () => {
  it("carries the EDITED body, not the composed one", () => {
    // Measured before this was fixed: the link was built from `draft.body`, so a processor who
    // edited the message and opened their mail client sent the composed text — while "Mark as
    // sent" recorded their edit. The borrower receives one version and the record stores the
    // other, which is the one divergence an evidence record cannot survive.
    mockUseOutboundDraft.mockReturnValue(draftState({ body: "COMPOSED BODY" }));
    render(<OutboundDraftPanel fileId="f1" />, { wrapper });

    fireEvent.change(screen.getByRole("textbox", { name: /message/i }), {
      target: { value: "EDITED BY THE PROCESSOR" },
    });

    const link = screen.getByRole("link", { name: /open in mail client/i }) as HTMLAnchorElement;
    // `URLSearchParams` writes spaces as `+`, which `decodeURIComponent` does not undo.
    const href = decodeURIComponent(link.href).replace(/\+/g, " ");
    expect(href).toContain("EDITED BY THE PROCESSOR");
    expect(href).not.toContain("COMPOSED BODY");
  });

  it("withdraws the link when an EDIT runs past the length limit", () => {
    // The gate was the server's verdict on the COMPOSED body, so an edit could run past the limit
    // and still be offered a link that truncates silently. The limit is still the server's; only
    // the measurement is of the text actually being sent.
    mockUseOutboundDraft.mockReturnValue(draftState({ body: "Short.", mailto_max_chars: 100 }));
    render(<OutboundDraftPanel fileId="f1" />, { wrapper });

    expect(screen.getByRole("link", { name: /open in mail client/i })).toBeTruthy();

    fireEvent.change(screen.getByRole("textbox", { name: /message/i }), {
      target: { value: "x".repeat(500) },
    });

    expect(screen.queryByRole("link", { name: /open in mail client/i })).toBeNull();
    expect(screen.getByText(/too long to open in a mail client/i)).toBeTruthy();
  });

  it("still offers the link for a short edit — the control", () => {
    // A fix that simply never returned a link would satisfy both cases above.
    mockUseOutboundDraft.mockReturnValue(draftState({ mailto_max_chars: 2000 }));
    render(<OutboundDraftPanel fileId="f1" />, { wrapper });

    fireEvent.change(screen.getByRole("textbox", { name: /message/i }), {
      target: { value: "A short edit." },
    });

    const link = screen.getByRole("link", { name: /open in mail client/i }) as HTMLAnchorElement;
    expect(decodeURIComponent(link.href).replace(/\+/g, " ")).toContain("A short edit.");
  });
});
