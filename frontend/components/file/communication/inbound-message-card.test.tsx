// @vitest-environment jsdom
/**
 * LP-807 — the triage card, and the two things it must not get wrong.
 *
 * A CARD IS THE END OF THE REDACTION. LP-806's review measured one company receiving another
 * company's borrower's personal address and a subject naming the borrower and the property, and the
 * server now returns those as null on an unclaimed message. Nulls are only half a fix: a UI that
 * renders them as blanks tells a processor the sender is unknown, and a UI that renders them as
 * "—" tells them nothing at all. This asserts the card says WHY they are missing, and — the part
 * that matters — that it offers no action on a message nobody owns.
 *
 * And `GRAY` IS NOT `PASS`. §2.3 calls that subtlety out because SES returns GRAY most often when a
 * message is signed by a domain that does not match `From:` — the spoofing case. A badge that
 * treats "not FAIL" as verified puts a green tick on exactly that message.
 */
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, render, screen } from "@testing-library/react";
import type { ReactNode } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";

const mockAccept = vi.fn();
const mockReject = vi.fn();

vi.mock("@/lib/api/inbound", async () => {
  const actual = await vi.importActual<typeof import("@/lib/api/inbound")>("@/lib/api/inbound");
  return {
    // The REAL `unclaimed`. It is what decides everything below, and a mocked one would leave these
    // tests asserting that a stub returns what it was told to.
    unclaimed: actual.unclaimed,
    useAcceptAttachment: () => ({ mutate: mockAccept, isPending: false, isError: false }),
    useRejectAttachment: () => ({ mutate: mockReject, isPending: false, isError: false }),
    useAttachmentPreview: () => ({ data: null, isPending: false }),
  };
});

import { InboundMessageCard, SIGNAL_LABEL } from "./inbound-message-card";

function wrapper({ children }: { children: ReactNode }) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
}

const ATTACHMENT = {
  id: "att-1",
  filename_original: "Jane_2024_tax_return.pdf",
  filename_normalized: "Jane_2024_tax_return.pdf",
  declared_content_type: "application/pdf",
  sniffed_content_type: "application/pdf",
  size_bytes: 2048,
  safety_state: "safe" as const,
  safety_reason: null,
  disposition: "pending" as const,
  nesting_depth: 0,
};

const ROUTED = {
  id: "msg-1",
  loan_file_id: "file-1",
  routing_state: "routed" as const,
  routing_signal: "inbox_token",
  routing_confidence: 1,
  is_dsn: false,
  is_auto_reply: false,
  from_address: "jane.borrower@personal-email.com",
  subject: "Docs for 42 Maple Ave - Jane Borrower",
  received_at: "2026-09-07T10:00:00Z",
  auth_verdicts: { dmarcVerdict: "PASS" },
  attachments: [ATTACHMENT],
};

/** The shape the server returns to a company that does not own the message. */
const UNCLAIMED = {
  ...ROUTED,
  id: "msg-2",
  loan_file_id: null,
  routing_state: "unrouted" as const,
  routing_signal: null,
  routing_confidence: null,
  from_address: null,
  subject: null,
  attachments: [{ ...ATTACHMENT, filename_original: null, filename_normalized: null }],
};

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

describe("a message on its own file", () => {
  it("shows what the sender wrote and offers the three decisions", () => {
    render(<InboundMessageCard message={ROUTED} fileId="file-1" />, { wrapper });

    expect(screen.getByText("jane.borrower@personal-email.com")).toBeDefined();
    expect(screen.getByText("Docs for 42 Maple Ave - Jane Borrower")).toBeDefined();
    expect(screen.getByText("Jane_2024_tax_return.pdf")).toBeDefined();
    expect(screen.getByRole("button", { name: "Accept" })).toBeDefined();
    expect(screen.getByRole("button", { name: "Correspondence" })).toBeDefined();
    expect(screen.getByRole("button", { name: "Reject" })).toBeDefined();
  });

  it("names the rung it matched on, not the confidence", () => {
    render(<InboundMessageCard message={ROUTED} fileId="file-1" />, { wrapper });
    expect(screen.getByText("Sent to this file's address")).toBeDefined();
  });
});

describe("a message nobody owns", () => {
  it("says the sender and subject are hidden rather than leaving them blank", () => {
    render(<InboundMessageCard message={UNCLAIMED} fileId={null} />, { wrapper });

    expect(screen.getByText("Sender hidden until claimed")).toBeDefined();
    expect(screen.getByText("Subject hidden until claimed")).toBeDefined();
    expect(screen.getByText("Name hidden until claimed")).toBeDefined();
    // The sender's words are not on the page under any element.
    expect(screen.queryByText(/personal-email\.com/)).toBeNull();
    expect(screen.queryByText(/42 Maple Ave/)).toBeNull();
  });

  it("offers no decision, because there is no file to accept into", () => {
    render(<InboundMessageCard message={UNCLAIMED} fileId={null} />, { wrapper });

    expect(screen.queryByRole("button", { name: "Accept" })).toBeNull();
    expect(screen.queryByRole("button", { name: "Reject" })).toBeNull();
  });

  it("stays visible, with our own assessment of the bytes", () => {
    // §2.2 — "confidence gates auto-acceptance, never visibility". The size and the safety state are
    // ours, not the sender's, and they are what deciding whether to claim it actually requires.
    render(<InboundMessageCard message={UNCLAIMED} fileId={null} />, { wrapper });
    expect(screen.getByText(/2 KB/)).toBeDefined();
    expect(screen.getByText("Not matched to a file")).toBeDefined();
  });
});

describe("the authentication badge", () => {
  it("verifies a DMARC pass", () => {
    render(<InboundMessageCard message={ROUTED} fileId="file-1" />, { wrapper });
    expect(screen.getByText("Sender verified")).toBeDefined();
  });

  it("does not verify GRAY", () => {
    // The one §2.3 calls out: GRAY usually means signed by a domain that is not the From domain.
    const gray = { ...ROUTED, auth_verdicts: { dmarcVerdict: "GRAY" } };
    render(<InboundMessageCard message={gray} fileId="file-1" />, { wrapper });

    expect(screen.queryByText("Sender verified")).toBeNull();
    expect(screen.getByText("Not verified (GRAY)")).toBeDefined();
  });

  it("does not verify a message with no verdict at all", () => {
    const none = { ...ROUTED, auth_verdicts: {} };
    render(<InboundMessageCard message={none} fileId="file-1" />, { wrapper });
    expect(screen.getByText("Not verified")).toBeDefined();
  });
});

describe("an attachment that is not safe", () => {
  it("shows the reason and offers nothing", () => {
    const quarantined = {
      ...ROUTED,
      attachments: [
        {
          ...ATTACHMENT,
          safety_state: "quarantined" as const,
          safety_reason: "Archives are not accepted. Ask for the file itself rather than a zip.",
        },
      ],
    };
    render(<InboundMessageCard message={quarantined} fileId="file-1" />, { wrapper });

    expect(screen.getByText(/Archives are not accepted/)).toBeDefined();
    expect(screen.queryByRole("button", { name: "Accept" })).toBeNull();
  });
});

describe("the routing signal labels", () => {
  it("covers exactly the rungs LP-805 built", () => {
    // The first draft of this map had five entries — copy for rungs 3 to 6, which no message can
    // carry — and spelled rung 2 `references` rather than `thread_reference`, so the one real
    // rung-2 message fell through to the fallback while the map looked complete.
    expect(Object.keys(SIGNAL_LABEL).sort()).toEqual(["inbox_token", "thread_reference"]);
  });

  it("falls back rather than printing a raw enum value for a rung added later", () => {
    const future = { ...ROUTED, routing_signal: "some_future_rung" };
    render(<InboundMessageCard message={future} fileId="file-1" />, { wrapper });

    expect(screen.getByText("Matched to this file")).toBeDefined();
    expect(screen.queryByText(/some_future_rung/)).toBeNull();
  });
});
