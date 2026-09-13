// @vitest-environment jsdom
/**
 * LP-858 §7 and §8 — Delete, and the two confirms that are not the same question.
 *
 * THE BUTTON WAS SPECIFIED AND NEVER BUILT. `comm-v1-draft-only-spec.md` §6 listed it, and a
 * comment in this pane described the exact row it belongs to — the comment shipped, the button did
 * not. That is the failure the design contract's §6 rule exists to stop, so these cases press a
 * button rather than checking that one is described.
 */
import type { MessageDetail } from "@/lib/types/communication";
import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const mockUseMessageDetail = vi.fn();
const mockDelete = vi.fn();
const mockSave = vi.fn();

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
  useSendDraft: () => ({ mutate: vi.fn(), isPending: false, isError: false }),
  useAttachUploadLink: () => ({ mutate: vi.fn(), isPending: false, isError: false }),
  useSaveDraftBody: () => ({ mutate: mockSave, isPending: false, isError: false }),
  usePolishDraft: () => ({ mutate: vi.fn(), isPending: false }),
  useDeleteDraft: () => ({ mutate: mockDelete, isPending: false }),
}));
vi.mock("@/lib/toast", () => ({ notifySuccess: vi.fn(), notifyError: vi.fn() }));
vi.mock("@/components/file/communication/message-editor", () => ({
  MessageEditor: () => <div data-testid="editor" />,
}));

import { DraftPane } from "./message-dialog";

afterEach(cleanup);
beforeEach(() => vi.clearAllMocks());

function draft(overrides: Partial<MessageDetail> = {}): { data: MessageDetail } {
  return {
    data: {
      id: "m1",
      direction: "outbound",
      status: "draft",
      subject: "Documents we need",
      body: "Hi Sarah,\n\nPlease send the March statement.\n\nDana",
      body_format: "plain",
      counterparty: "sarah@example.com",
      template_key: "initial_documentation_request",
      template_version: "v4",
      created_at: "2026-09-13T10:00:00Z",
      sent_at: null,
      read_at: null,
      is_important: false,
      error_detail: null,
      documents: ["Bank statements"],
      attachments: [],
      is_open_draft: true,
      is_editable: true,
      suggested_bcc: "lf-abc@imbox.example.test",
      mailto_available: true,
      mailto_max_chars: 1800,
      suggested_recipient: null,
      party: "borrower",
      ...overrides,
    } as MessageDetail,
  };
}

async function open(detail = draft(), onDeleted = vi.fn(), onClose = vi.fn()) {
  mockUseMessageDetail.mockReturnValue({ ...detail, isPending: false, isError: false });
  render(<DraftPane fileId="LF-JR4T" messageId="m1" onClose={onClose} onDeleted={onDeleted} />);
  await screen.findByTestId("editor");
  return { onDeleted, onClose };
}

const CONFIRM = /Delete this draft\?/i;

describe("Delete", () => {
  it("is in the button row", async () => {
    // §4 — after a spacer, quiet, danger text. The POSITIVE CONTROL for everything below: a button
    // that does not exist cannot be pressed, and every other case here presses it.
    await open();

    expect(screen.getByRole("button", { name: /Delete/ })).toBeTruthy();
  });

  it("deletes an unedited draft without asking", async () => {
    // §7 — NO CONFIRM WHEN `body_edited` IS FALSE. An unedited draft is template output: deleting
    // it destroys nothing a person wrote, and a confirm on every delete is the dialog people learn
    // to dismiss without reading, which makes the one that matters useless too.
    const { onDeleted } = await open();

    fireEvent.click(screen.getByRole("button", { name: /Delete/ }));

    expect(screen.queryByText(CONFIRM)).toBeNull();
    expect(mockDelete).toHaveBeenCalledTimes(1);
    // SOFT — no `discard`. The processor asked for this one; §8's hard delete is the other case.
    expect(mockDelete.mock.calls[0]?.[0]).toEqual({ draftId: "m1" });

    const opts = mockDelete.mock.calls[0]?.[1] as { onSuccess: () => void };
    opts.onSuccess();
    // §2.1 rule 6 — the page is told, so the selection moves off a row that is gone.
    await waitFor(() => expect(onDeleted).toHaveBeenCalledWith("m1"));
  });

  it("confirms before deleting an edited draft, and quotes the edit", async () => {
    // §7 — the same pattern LP-851 uses for the append warning. "You have unsaved changes" is a
    // sentence about a category; the processor's own first line is the thing they can recognise.
    await open(
      draft({
        body_format: "html",
        body: "<p>Hi Sarah — the March statement only, please.</p><p>Dana</p>",
      }),
    );

    fireEvent.click(screen.getByRole("button", { name: /Delete/ }));

    expect(screen.getByText(CONFIRM)).toBeTruthy();
    expect(screen.getByText(/the March statement only, please/)).toBeTruthy();
    // AND NOTHING IS DELETED UNTIL THEY SAY SO.
    expect(mockDelete).not.toHaveBeenCalled();
  });

  it("keeps the draft when the confirm is declined", async () => {
    await open(draft({ body_format: "html", body: "<p>Mine.</p>" }));
    fireEvent.click(screen.getByRole("button", { name: /Delete/ }));

    fireEvent.click(screen.getByRole("button", { name: "Keep it" }));

    expect(screen.queryByText(CONFIRM)).toBeNull();
    expect(mockDelete).not.toHaveBeenCalled();
  });

  it("deletes once the confirm is accepted", async () => {
    // THE POSITIVE CONTROL on the two not-called assertions above.
    const { onDeleted } = await open(draft({ body_format: "html", body: "<p>Mine.</p>" }));
    fireEvent.click(screen.getByRole("button", { name: /Delete/ }));

    // THE CONFIRM'S Delete, not the row's — both are buttons reading "Delete", which is correct on
    // screen (the confirm repeats the verb it is confirming) and ambiguous to a query. Scoped to
    // the dialog rather than picked by index, so a re-ordered button row cannot silently make this
    // press the wrong one.
    const confirm = screen.getByRole("dialog");
    fireEvent.click(within(confirm).getByRole("button", { name: "Delete" }));

    expect(mockDelete).toHaveBeenCalledTimes(1);
    expect(mockDelete.mock.calls[0]?.[0]).toEqual({ draftId: "m1" });
    (mockDelete.mock.calls[0]?.[1] as { onSuccess: () => void }).onSuccess();
    await waitFor(() => expect(onDeleted).toHaveBeenCalledWith("m1"));
  });
});

describe("closing a compose draft", () => {
  /** §8's case: a composed draft, nothing in it, nothing typed. */
  const untouched = () =>
    draft({
      template_key: null,
      template_version: null,
      subject: null,
      body: "",
      counterparty: null,
      suggested_recipient: null,
      documents: [],
      party: null,
    });

  it("removes the row entirely when nothing was modified", async () => {
    // §8 — HARD, because it never held anything. A `deleted_at` row for a message with no words in
    // it is litter with a timestamp on it.
    const { onDeleted, onClose } = await open(untouched());

    fireEvent.click(screen.getByRole("button", { name: "Close" }));

    expect(mockDelete).toHaveBeenCalledWith({ draftId: "m1", discard: true }, expect.anything());
    // AND IT SAVES NOTHING ON THE WAY OUT. A flush here would write `body_format = html` onto a row
    // about to be removed.
    expect(mockSave).not.toHaveBeenCalled();
    expect(onClose).toHaveBeenCalled();
    (mockDelete.mock.calls[0]?.[1] as { onSuccess: () => void }).onSuccess();
    await waitFor(() => expect(onDeleted).toHaveBeenCalledWith("m1"));
  });

  it("keeps a compose draft with only a recipient typed", async () => {
    // §8 — *"A processor who typed a recipient and stopped has done work; do not destroy it."*
    await open(untouched());
    fireEvent.change(screen.getByLabelText("Send to"), {
      target: { value: "jane@borrower.example" },
    });

    fireEvent.click(screen.getByRole("button", { name: "Close" }));

    expect(mockDelete).not.toHaveBeenCalled();
  });

  it("keeps a compose draft with only a subject typed", async () => {
    // The other two thirds of "no modification", asserted separately: a single condition covering
    // all three would pass with two of them dropped.
    await open(untouched());
    fireEvent.change(screen.getByLabelText("Subject"), { target: { value: "An update" } });

    fireEvent.click(screen.getByRole("button", { name: "Close" }));

    expect(mockDelete).not.toHaveBeenCalled();
  });

  it("does not discard a generated draft, however empty it looks", async () => {
    // A TEMPLATE KEY IS NOT A COMPOSE DRAFT. An emptied request still carries the record that
    // documents were asked for, and the server refuses this too — but asking for it at all would
    // mean the client's idea of "compose" had drifted from the server's.
    const { onClose } = await open(
      draft({ subject: null, body: "", counterparty: null, suggested_recipient: null }),
    );

    fireEvent.click(screen.getByRole("button", { name: "Close" }));

    expect(mockDelete).not.toHaveBeenCalled();
    expect(onClose).toHaveBeenCalled();
  });

  it("does not discard a draft the file suggested an address for", async () => {
    // SEEDED IS NOT TYPED, and the comparison is against what the pane OPENED with rather than
    // against emptiness. A draft carrying the file's own suggestion has had nothing done to it —
    // but the "all three are empty" half of the rule is what stops it being discarded, since
    // removing a row the file addressed would lose a suggestion nobody re-derives.
    await open(
      draft({
        template_key: null,
        subject: null,
        body: "",
        counterparty: null,
        suggested_recipient: "jane@borrower.example",
        documents: [],
        party: null,
      }),
    );

    fireEvent.click(screen.getByRole("button", { name: "Close" }));

    expect(mockDelete).not.toHaveBeenCalled();
  });
});
