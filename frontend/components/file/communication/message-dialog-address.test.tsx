// @vitest-environment jsdom
/**
 * LP-857 — the address is asked inside the draft that is blocked on it. Acceptance 2 and 3.
 *
 * THE GATE IS THE SUBJECT HERE, not the form — `party-address-form.test.tsx` covers what the form
 * does. What this asserts is WHEN it appears, and every condition on that gate is load-bearing in a
 * way a screenshot would not show: showing it on a borrower draft files the address as a
 * participant rather than on the borrower record, and showing it on a draft the file already has an
 * address for is how a second title company ends up on a loan.
 */
import type { MessageDetail } from "@/lib/types/communication";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const mockUseMessageDetail = vi.fn();
const mockAddAddress = vi.fn();

vi.mock("@/lib/api/preferences", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/lib/api/preferences")>()),
  usePreferences: () => ({ data: { mail_client: "gmail", suggested_mail_client: "gmail" } }),
  useUpdatePreferences: () => ({ mutate: vi.fn(), isPending: false }),
}));
vi.mock("@/lib/api/communications", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/lib/api/communications")>()),
  useMessageDetail: (...args: unknown[]) => mockUseMessageDetail(...args),
  useSendDraft: () => ({ mutate: vi.fn(), isPending: false, isError: false }),
  useAttachUploadLink: () => ({ mutate: vi.fn(), isPending: false, isError: false }),
  useSaveDraftBody: () => ({ mutate: vi.fn(), isPending: false, isError: false }),
  usePolishDraft: () => ({ mutate: vi.fn(), isPending: false }),
}));
vi.mock("@/lib/api/party-requests", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/lib/api/party-requests")>()),
  useAddPartyAddress: () => ({ mutate: mockAddAddress, isPending: false }),
}));
vi.mock("@/components/file/communication/message-editor", () => ({
  MessageEditor: () => <div data-testid="editor" />,
}));
const mockCapabilities = vi.fn(() => ({ data: { receiving: false } }));
vi.mock("@/lib/api/capabilities", () => ({ useCapabilities: () => mockCapabilities() }));

import { MessageDialog } from "./message-dialog";

afterEach(cleanup);
beforeEach(() => vi.clearAllMocks());

function draft(overrides: Partial<MessageDetail> = {}): { data: MessageDetail } {
  return {
    data: {
      id: "m1",
      direction: "outbound",
      status: "draft",
      subject: "Documents we need",
      body: "Please send the title commitment.",
      body_format: "plain",
      counterparty: null,
      template_key: "document_request_third_party",
      template_version: "v1",
      created_at: "2026-09-12T10:00:00Z",
      sent_at: null,
      read_at: null,
      is_important: false,
      error_detail: null,
      documents: ["Title commitment"],
      attachments: [],
      is_open_draft: false,
      is_editable: true,
      suggested_bcc: "lf-abc@imbox.example.test",
      mailto_available: true,
      mailto_max_chars: 1800,
      suggested_recipient: null,
      party: "title",
      ...overrides,
    } as MessageDetail,
  };
}

async function open(detail = draft()) {
  mockUseMessageDetail.mockReturnValue({ ...detail, isPending: false, isError: false });
  render(<MessageDialog fileId="LF-JR4T" messageId="m1" onClose={vi.fn()} />);
  // WAIT FOR THE DIALOG'S CONTENT, not for the editor. `next/dynamic` resolves after the first
  // paint, so asserting straight away reads an empty tree — but a SENT message has no editor at
  // all, and waiting for one there would time out rather than fail on the property.
  await screen.findByText("Documents we need");
}

const FORM = /No address on file for the/i;

describe("the secure upload link", () => {
  const LINK = /secure upload link/i;

  it("is not offered while the version cannot receive", async () => {
    // ACCEPTANCE 5's other half, on the client. This button MINTS a link and writes it into the
    // body — leaving it would put a live upload link in a message on a version that can receive
    // nothing through it, which is acceptance 5 broken by a click rather than by a template. The
    // server refuses the same call; this is the half a processor sees.
    await open();

    expect(screen.queryByText(LINK)).toBeNull();
  });

  it("comes back when the version can receive", async () => {
    // THE POSITIVE CONTROL. Without it the absence above passes against a dialog that never had
    // the button, and against LP-834 having been deleted rather than flagged.
    mockCapabilities.mockReturnValue({ data: { receiving: true } });
    await open();

    expect(screen.getByText(LINK)).toBeTruthy();
  });
});

describe("the address form inside a blocked draft", () => {
  it("appears on a party draft the file has no address for", async () => {
    // ACCEPTANCE 2's client half, and the POSITIVE CONTROL for every absence below.
    await open();

    expect(screen.getByText(FORM)).toBeTruthy();
    expect(screen.getByText(/No address on file for the title company/i)).toBeTruthy();
    // NOT INSTEAD OF "Send to". The box below still sends this one message; the form adds the
    // option to record the address as a fact about the file.
    expect(screen.getByLabelText("Send to")).toBeTruthy();
  });

  it("does not appear on the borrower's draft", async () => {
    // A borrower's address is a borrower record, not a participant row — `add_party_address` would
    // file it under the wrong thing, and nothing downstream would notice.
    await open(draft({ party: "borrower", template_key: "initial_documentation_request" }));

    expect(screen.queryByText(FORM)).toBeNull();
  });

  it("does not appear when the file already knows the address", async () => {
    // Asking again for something already recorded is how a second title company ends up on a file.
    await open(draft({ suggested_recipient: "known@title.example" }));

    expect(screen.queryByText(FORM)).toBeNull();
  });

  it("does not appear on a draft somebody has already addressed", async () => {
    await open(draft({ counterparty: "typed@title.example" }));

    expect(screen.queryByText(FORM)).toBeNull();
  });

  it("stays away when the processor clears a box the file has an address for", async () => {
    // THE CASE THAT SEPARATES THE GATE FROM `recipient === ""`.
    //
    // At open time those two agree: an addressed draft seeds the box, so an empty box already means
    // nobody is addressed. They part company the moment a processor deletes what is in it — and
    // "No address on file for the title company" would then be FALSE, because the file has one and
    // is offering it. Measured: without `!data.counterparty && !data.suggested_recipient` on the
    // gate, every assertion in this file still passed.
    await open(draft({ suggested_recipient: "known@title.example" }));
    const box = screen.getByLabelText("Send to") as HTMLInputElement;
    expect(box.value).toBe("known@title.example");

    fireEvent.change(box, { target: { value: "" } });

    await waitFor(() =>
      expect((screen.getByLabelText("Send to") as HTMLInputElement).value).toBe(""),
    );
    expect(screen.queryByText(FORM)).toBeNull();
  });

  it("stays away when the processor clears an address somebody already typed", async () => {
    await open(draft({ counterparty: "typed@title.example" }));

    fireEvent.change(screen.getByLabelText("Send to"), { target: { value: "" } });

    await waitFor(() =>
      expect((screen.getByLabelText("Send to") as HTMLInputElement).value).toBe(""),
    );
    expect(screen.queryByText(FORM)).toBeNull();
  });

  it("does not appear on a sent message", async () => {
    // Nothing on a sent message is editable, and an address form on the evidence record would be a
    // control that cannot change what went out.
    await open(draft({ status: "sent", is_editable: false, counterparty: null }));

    expect(screen.queryByText(FORM)).toBeNull();
  });

  it("does not appear when the payload has no party field at all", async () => {
    // NOT THE SAME AS `party: null`. An older or partial payload simply omits the key, and
    // `undefined !== null` — the gate was written that way and rendered the form with no role to
    // save against, which is an address filed under nothing from a control that looked ordinary.
    const detail = draft();
    // biome-ignore lint/performance/noDelete: the point is a payload where the key is ABSENT
    delete (detail.data as Partial<MessageDetail>).party;
    await open(detail);

    expect(screen.queryByText(FORM)).toBeNull();
  });

  it("does not appear on a draft whose party the server could not name", async () => {
    // `party: null` is a real answer (a reply, a free draft). There is no role to file an address
    // under, and guessing one would put an address on somebody else's record.
    await open(draft({ party: null, template_key: null }));

    expect(screen.queryByText(FORM)).toBeNull();
  });

  it("fills Send to when the address is saved, and puts the form away", async () => {
    // ACCEPTANCE 3 at the layer a processor sees it: the draft is sendable without being reopened.
    await open();

    fireEvent.change(screen.getByLabelText(/title company's email/i), {
      target: { value: "closings@acmetitle.example" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Save address" }));
    (mockAddAddress.mock.calls[0]?.[1] as { onSuccess: () => void }).onSuccess();

    await waitFor(() =>
      expect((screen.getByLabelText("Send to") as HTMLInputElement).value).toBe(
        "closings@acmetitle.example",
      ),
    );
    // AND THE QUESTION STOPS BEING ASKED. A form still sitting there after it was answered reads
    // as "that did not work".
    expect(screen.queryByText(FORM)).toBeNull();
  });
});
