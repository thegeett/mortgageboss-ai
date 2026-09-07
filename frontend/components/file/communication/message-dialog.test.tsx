// @vitest-environment jsdom
/**
 * LP-829 — the dialog reads a message; it never edits one.
 *
 * The two things worth protecting are the ones a screenshot would not show: the dialog becoming a
 * second editor for a draft the panel above already owns, and a borrower's own text being rendered
 * as anything other than the characters they typed.
 */
import { MessageDialog } from "@/components/file/communication/message-dialog";
import type { MessageDetail } from "@/lib/types/communication";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const mockUseMessageDetail = vi.fn();
const mockSend = vi.fn();
const sendState = { mutate: mockSend, isPending: false, isError: false };
vi.mock("@/lib/api/communications", () => ({
  useMessageDetail: (...args: unknown[]) => mockUseMessageDetail(...args),
  useSendDraft: () => sendState,
}));

afterEach(cleanup);

// LP-831 — CLEARED BETWEEN TESTS, and this was a real defect in the tests rather than a precaution.
// `mockSend` accumulates across cases, so `mock.calls[0]` in the party-draft test was reading the
// call the BORROWER-draft test made a moment earlier: it passed alone and failed in the suite, which
// is the wrong way round for a test to be wrong.
beforeEach(() => {
  vi.clearAllMocks();
  sendState.isPending = false;
  sendState.isError = false;
});

function detail(overrides: Partial<MessageDetail> = {}): { data: MessageDetail } {
  return {
    data: {
      id: "m1",
      direction: "outbound",
      status: "sent",
      subject: "Documents we need",
      body: "Hello Sarah,\n\nPlease send the bank statements.\n\nDana Reyes",
      counterparty: "sarah@example.com",
      template_key: "initial_documentation_request",
      template_version: "v3",
      created_at: "2026-09-07T10:00:00Z",
      sent_at: "2026-09-07T11:00:00Z",
      read_at: null,
      is_important: false,
      error_detail: null,
      documents: ["Bank statements"],
      attachments: [],
      is_open_draft: false,
      is_editable: false,
      suggested_recipient: null,
      ...overrides,
    } as MessageDetail,
  };
}

function state(over: Record<string, unknown>) {
  return { data: undefined, isPending: false, isError: false, ...over };
}

describe("MessageDialog", () => {
  it("shows the words that went out", () => {
    // The state this exists for: before LP-829 a sent message's body was readable nowhere.
    mockUseMessageDetail.mockReturnValue(state(detail()));
    render(<MessageDialog fileId="LF-JR4T" messageId="m1" onClose={vi.fn()} />);

    expect(screen.getByText(/Please send the bank statements/)).toBeTruthy();
    expect(screen.getByText("Bank statements")).toBeTruthy();
  });

  it("offers no way to change a SENT message", () => {
    // LP-821 — the evidence record must not change after the fact. LP-831 made this dialog the one
    // editor, so "there is no editor here" stopped being true of the COMPONENT and became true of
    // this STATE, which is the thing that actually has to hold.
    mockUseMessageDetail.mockReturnValue(state(detail({ is_editable: false })));
    render(<MessageDialog fileId="LF-JR4T" messageId="m1" onClose={vi.fn()} />);

    // LP-829 REVIEW — THE POSITIVE HALF, IN THIS TEST. Both assertions below are absences, and a
    // dialog that rendered nothing at all would satisfy them. "Renders nothing when no message is
    // open" is a different state and cannot close this one: it proves the empty case is empty, not
    // that THIS case is populated.
    expect(screen.getByText(/Please send the bank statements/)).toBeTruthy();

    expect(screen.queryByRole("textbox")).toBeNull();
    expect(screen.queryByRole("button", { name: /Mark as sent/ })).toBeNull();
  });

  it("edits and sends a draft", () => {
    mockUseMessageDetail.mockReturnValue(
      state(detail({ is_editable: true, is_open_draft: true, status: "draft" })),
    );
    render(<MessageDialog fileId="LF-JR4T" messageId="m1" onClose={vi.fn()} />);

    const message = screen.getByRole("textbox", { name: "Message" }) as HTMLTextAreaElement;
    fireEvent.change(message, { target: { value: "Edited by the processor." } });
    fireEvent.click(screen.getByRole("button", { name: /Mark as sent/ }));

    expect(mockSend).toHaveBeenCalledTimes(1);
    expect(mockSend.mock.calls[0]?.[0]).toMatchObject({
      draftId: "m1",
      body: "Edited by the processor.",
    });
  });

  it("sends a PARTY draft, which no screen could do before", () => {
    // THE ESCALATED LP-820 DEFECT. A party request is a draft under its own template key;
    // `get_open_draft` filters on the borrower's, so the old panel never showed one — while the
    // party panel told a processor to "send it from the document request above", which is the
    // BORROWER's draft. `is_editable` comes from the server and does not care which template
    // rendered the body.
    mockUseMessageDetail.mockReturnValue(
      state(
        detail({
          is_editable: true,
          is_open_draft: false,
          status: "draft",
          template_key: "title_document_request",
          counterparty: "t@title.example",
        }),
      ),
    );
    render(<MessageDialog fileId="LF-JR4T" messageId="m1" onClose={vi.fn()} />);

    expect((screen.getByRole("textbox", { name: "Send to" }) as HTMLInputElement).value).toBe(
      "t@title.example",
    );
    fireEvent.click(screen.getByRole("button", { name: /Mark as sent/ }));
    expect(mockSend.mock.calls[0]?.[0]).toMatchObject({ recipient: "t@title.example" });
  });

  it("seeds the borrower's address when nobody has been addressed yet", () => {
    mockUseMessageDetail.mockReturnValue(
      state(
        detail({
          is_editable: true,
          status: "draft",
          counterparty: null,
          suggested_recipient: "sarah@example.com",
        }),
      ),
    );
    render(<MessageDialog fileId="LF-JR4T" messageId="m1" onClose={vi.fn()} />);

    expect((screen.getByRole("textbox", { name: "Send to" }) as HTMLInputElement).value).toBe(
      "sarah@example.com",
    );
  });

  it("refuses to send with no recipient", () => {
    mockUseMessageDetail.mockReturnValue(
      state(detail({ is_editable: true, status: "draft", counterparty: null })),
    );
    render(<MessageDialog fileId="LF-JR4T" messageId="m1" onClose={vi.fn()} />);

    expect(
      (screen.getByRole("button", { name: /Mark as sent/ }) as HTMLButtonElement).disabled,
    ).toBe(true);
  });

  it("renders a borrower's text as text", () => {
    // A borrower's sentence is not markup, and a dollar sign in it is a dollar sign. This is the
    // one place a message body is shown in full, so it is the one place that could get it wrong.
    mockUseMessageDetail.mockReturnValue(
      state(
        detail({
          direction: "inbound",
          body: "Who is $processor_name? I paid $10,000 <b>in cash</b>.",
        }),
      ),
    );
    render(<MessageDialog fileId="LF-JR4T" messageId="m1" onClose={vi.fn()} />);

    expect(screen.getByText("Who is $processor_name? I paid $10,000 <b>in cash</b>.")).toBeTruthy();
  });

  it("shows what arrived, and what became of it", () => {
    mockUseMessageDetail.mockReturnValue(
      state(
        detail({
          direction: "inbound",
          attachments: [
            { name: "March_statement.pdf", disposition: "accepted" },
            { name: "selfie.heic", disposition: "not_yet_accepted" },
          ],
        }),
      ),
    );
    render(<MessageDialog fileId="LF-JR4T" messageId="m1" onClose={vi.fn()} />);

    expect(screen.getByText(/March_statement\.pdf · accepted/)).toBeTruthy();
    expect(screen.getByText(/selfie\.heic · not yet accepted/)).toBeTruthy();
  });

  it("says a failed send failed", () => {
    mockUseMessageDetail.mockReturnValue(
      state(detail({ status: "failed", error_detail: "550 5.1.1 user unknown" })),
    );
    render(<MessageDialog fileId="LF-JR4T" messageId="m1" onClose={vi.fn()} />);

    expect(screen.getByText(/550 5\.1\.1 user unknown/)).toBeTruthy();
  });

  it("renders nothing when no message is open", () => {
    // THE CONTROL. A dialog that rendered its content regardless would satisfy every assertion
    // above and sit permanently over the timeline.
    mockUseMessageDetail.mockReturnValue(state({ data: undefined }));
    render(<MessageDialog fileId="LF-JR4T" messageId={null} onClose={vi.fn()} />);

    expect(screen.queryByText(/Please send the bank statements/)).toBeNull();
  });
});
