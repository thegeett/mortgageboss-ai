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
};

function draftState(overrides: Partial<typeof DRAFT> | null = {}) {
  return {
    data: overrides === null ? null : { ...DRAFT, ...overrides },
    isPending: false,
    isError: false,
  };
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
    mockUseOutboundDraft.mockReturnValue(draftState());
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
