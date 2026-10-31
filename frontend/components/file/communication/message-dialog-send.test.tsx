// @vitest-environment jsdom
/**
 * LP-997 — the Send button. A draft the app can send (`can_send`: file address, company switched on
 * for sending, a mail sender, not a condition draft) gets Send From the file address (`suggested_bcc`)
 * instead of copy / mail app / "Mark as sent"; any other keeps them.
 */
import { DraftPane } from "@/components/file/communication/message-dialog";
import type { MessageDetail } from "@/lib/types/communication";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { AxiosError, type AxiosResponse } from "axios";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const mockUseMessageDetail = vi.fn();
const mockSend = vi.fn();
const sendState: { mutate: typeof mockSend; isPending: boolean; isError: boolean; error: unknown } =
  { mutate: mockSend, isPending: false, isError: false, error: null };

vi.mock("@/lib/api/preferences", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/lib/api/preferences")>()),
  usePreferences: () => ({ data: { mail_client: "gmail", suggested_mail_client: "gmail" } }),
  useUpdatePreferences: () => ({ mutate: vi.fn(), isPending: false }),
}));
vi.mock("@/lib/api/capabilities", () => ({
  useCapabilities: () => ({ data: { receiving: false, polish: false } }),
}));
vi.mock("@/lib/api/communications", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/lib/api/communications")>()),
  useMessageDetail: (...args: unknown[]) => mockUseMessageDetail(...args),
  useSendDraft: () => sendState,
  useAttachUploadLink: () => ({ mutate: vi.fn(), isPending: false, isError: false }),
  usePolishDraft: () => ({ mutate: vi.fn(), isPending: false }),
  useDeleteDraft: () => ({ mutate: vi.fn(), isPending: false }),
  useSaveDraftBody: () => ({ mutate: vi.fn(), isPending: false, isError: false }),
}));

afterEach(cleanup);
beforeEach(() => {
  vi.clearAllMocks();
  sendState.isPending = false;
  sendState.isError = false;
  sendState.error = null;
});

const ADDRESS = "lf-ab12@mb-mail.localhost";

function draft(overrides: Partial<MessageDetail> = {}) {
  return {
    data: {
      id: "m1",
      direction: "outbound",
      status: "draft",
      subject: "Documents we need",
      body: "Hello Sarah,\n\nPlease send the pay stubs.\n\nDana Reyes",
      body_format: "plain",
      counterparty: "sarah@example.com",
      template_key: "initial_documentation_request",
      template_version: "v3",
      created_at: "2026-09-07T10:00:00Z",
      sent_at: null,
      read_at: null,
      is_important: false,
      error_detail: null,
      documents: ["Pay stubs"],
      attachments: [],
      is_open_draft: true,
      is_editable: true,
      suggested_bcc: ADDRESS,
      can_send: true,
      send_requested_at: null,
      mailto_available: true,
      mailto_max_chars: 1800,
      suggested_recipient: null,
      party: "borrower",
      ...overrides,
    } as MessageDetail,
    isPending: false,
    isError: false,
  };
}

/** A 409 as the API sends it: a string detail becomes `{"error": {"type", "message"}}`. */
function conflict(message: string): AxiosError {
  return new AxiosError("Request failed with status code 409", "ERR_BAD_REQUEST", undefined, null, {
    status: 409,
    data: { error: { type: "conflict", message } },
  } as AxiosResponse);
}

describe("message dialog: Send (LP-997)", () => {
  it("offers Send, From the file address with CC, instead of the copy and mark-sent buttons", () => {
    mockUseMessageDetail.mockReturnValue(draft());
    const onClose = vi.fn();
    render(<DraftPane fileId="LF-AB12" messageId="m1" onClose={onClose} />);

    expect(screen.getByText(`From ${ADDRESS} · CC you`)).toBeTruthy();
    expect(screen.queryByRole("button", { name: /Mark as sent/ })).toBeNull();
    expect(screen.queryByRole("button", { name: /Copy message/ })).toBeNull();
    expect(screen.queryByRole("button", { name: /Copy & open/ })).toBeNull();
    expect(screen.queryByText(/Formatting survives/)).toBeNull();

    fireEvent.click(screen.getByRole("button", { name: /^Send$/ }));
    expect(mockSend).toHaveBeenCalledTimes(1);
    const [input, options] = mockSend.mock.calls[0] as [
      { draftId: string; recipient: string; body: string; transmit?: boolean },
      { onSuccess: () => void },
    ];
    expect(input.transmit).toBe(true);
    expect(input.draftId).toBe("m1");
    expect(input.recipient).toBe("sarah@example.com");
    expect(input.body).toContain("Please send the pay stubs.");
    // Success closes the dialog, the way "Mark as sent" already did.
    options.onSuccess();
    expect(onClose).toHaveBeenCalledTimes(1);
  });

  it.each([
    ["sending is not switched on for the company", { can_send: false }],
    ["the file has no address", { can_send: false, suggested_bcc: null }],
  ])("keeps the old buttons, and posts no transmit, when %s", (_, over) => {
    // The first case is the flag: the file HAS an address (`suggested_bcc`), and still no Send.
    mockUseMessageDetail.mockReturnValue(draft(over));
    render(<DraftPane fileId="LF-AB12" messageId="m1" onClose={vi.fn()} />);

    expect(screen.queryByRole("button", { name: /^Send$/ })).toBeNull();
    expect(screen.queryByText(/CC you/)).toBeNull();
    expect(screen.getByRole("button", { name: /Copy message/ })).toBeTruthy();
    expect(screen.getByText(/Formatting survives/)).toBeTruthy();
    expect(
      screen.getByText("Records that you sent it. Nothing is transmitted from here."),
    ).toBeTruthy();

    fireEvent.click(screen.getByRole("button", { name: /Mark as sent/ }));
    const [input] = mockSend.mock.calls[0] as [{ transmit?: boolean }];
    expect(input.transmit).toBeUndefined();
  });

  it("shows the server's reason when Send is refused, and stays open", () => {
    const reason =
      "sarah@example.com is blocked: an earlier email to it bounced or was marked as spam.";
    sendState.isError = true;
    sendState.error = conflict(reason);
    mockUseMessageDetail.mockReturnValue(draft());
    const onClose = vi.fn();
    render(<DraftPane fileId="LF-AB12" messageId="m1" onClose={onClose} />);

    fireEvent.click(screen.getByRole("button", { name: /^Send$/ }));
    expect(screen.getByText(reason)).toBeTruthy();
    expect(screen.queryByText(/was not recorded as sent/)).toBeNull();
    expect(onClose).not.toHaveBeenCalled();
  });

  it("disables Send while the request is in flight", () => {
    sendState.isPending = true;
    mockUseMessageDetail.mockReturnValue(draft());
    render(<DraftPane fileId="LF-AB12" messageId="m1" onClose={vi.fn()} />);

    const button = screen.getByRole("button", { name: /Sending…/ }) as HTMLButtonElement;
    expect(button.disabled).toBe(true);
    fireEvent.click(button);
    expect(mockSend).not.toHaveBeenCalled();
  });

  it.each([
    ["queued", null, "Queued"],
    ["sending", null, "Sending"],
    ["sent", null, "Sent"],
    ["delivered", null, "Delivered"],
    ["failed", "smtp; 550 5.1.1 user unknown", "Failed: smtp; 550 5.1.1 user unknown"],
    ["sending", "Not confirmed: TimeoutError", "Not confirmed: check before sending again"],
  ])("labels a %s Send in plain words", (status, errorDetail, label) => {
    mockUseMessageDetail.mockReturnValue(
      draft({
        status,
        error_detail: errorDetail,
        // Pressed a few seconds ago: a Send from the app, inside the 1.5-minute window.
        send_requested_at: new Date(Date.now() - 5_000).toISOString(),
        is_editable: false,
        is_open_draft: false,
      }),
    );
    render(<DraftPane fileId="LF-AB12" messageId="m1" onClose={vi.fn()} />);
    expect(screen.getByText(label)).toBeTruthy();
  });

  it.each([
    ["sent", null, "Marked sent"],
    ["delivered", null, "Marked sent"],
    ["failed", "ConnectionRefusedError: [Errno 61]", "Failed"],
  ])(
    "keeps a %s email that was not sent from the app in its own words",
    (status, errorDetail, label) => {
      // REVIEW FINDING 2 — "Mark as sent" is her claim; the timeline says "Marked sent by …", and the
      // open message must not say "Sent" as though the app sent it. A failed row with no Send behind it
      // reads "Failed", not a raw error.
      mockUseMessageDetail.mockReturnValue(
        draft({
          status,
          error_detail: errorDetail,
          send_requested_at: null,
          is_editable: false,
          is_open_draft: false,
        }),
      );
      render(<DraftPane fileId="LF-AB12" messageId="m1" onClose={vi.fn()} />);
      expect(screen.getByText(label)).toBeTruthy();
      expect(screen.queryByText(/^Sent$/)).toBeNull();
      expect(screen.queryByText(/Errno/)).toBeNull();
    },
  );

  it("says Not confirmed for a Send still queued 1.5 minutes after it was pressed", () => {
    const pressed = new Date(Date.now() - 91_000).toISOString();
    mockUseMessageDetail.mockReturnValue(
      draft({ status: "queued", send_requested_at: pressed, is_editable: false }),
    );
    render(<DraftPane fileId="LF-AB12" messageId="m1" onClose={vi.fn()} />);
    expect(screen.getByText("Not confirmed: check before sending again")).toBeTruthy();
  });
});
