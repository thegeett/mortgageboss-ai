// @vitest-environment jsdom
/**
 * LP-853 — the autosave, and the thing it must not do.
 *
 * A SEPARATE FILE BECAUSE THE EDITOR IS STUBBED HERE. `message-dialog.test.tsx` mounts the real
 * Tiptap editor, which is what proves the dynamic import is wired at all — and a real ProseMirror
 * document cannot be edited reliably from jsdom, so a test that tried would be testing the
 * simulation. What this file asserts is the DIALOG's half of the contract: what it does when the
 * editor reports a change, and what it does when nothing changes.
 *
 * EVERY "IT DOES NOT SAVE" HERE HAS ITS CONTROL IN THE SAME FILE. `expect(mockSave).not.toHaveBeen
 * Called()` passes against a dialog with no autosave at all, against a broken import, and against
 * a stub that never fires — so "an edit IS saved" is asserted first, through the same stub.
 */
import type { MessageDetail } from "@/lib/types/communication";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const mockUseMessageDetail = vi.fn();
const mockSave = vi.fn();
const mockSend = vi.fn();

vi.mock("@/lib/api/communications", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/lib/api/communications")>()),
  useMessageDetail: (...args: unknown[]) => mockUseMessageDetail(...args),
  useSendDraft: () => ({ mutate: mockSend, isPending: false, isError: false }),
  useAttachUploadLink: () => ({ mutate: vi.fn(), isPending: false, isError: false }),
  useSaveDraftBody: () => ({ mutate: mockSave, isPending: false, isError: false }),
}));

// THE STUB. One button, which calls `onChange` with a body a processor could have typed — the
// editor's whole contract as far as this dialog is concerned. `next/dynamic` resolves through the
// module registry, so mocking the module is enough.
vi.mock("@/components/file/communication/message-editor", () => ({
  MessageEditor: ({ onChange }: { onChange: (html: string) => void }) => (
    <button type="button" onClick={() => onChange("<p>March statement only.</p>")}>
      simulate-typing
    </button>
  ),
}));

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
      body: "Hello Sarah,\n\nPlease send the bank statements.\n\nDana Reyes",
      body_format: "plain",
      counterparty: "sarah@example.com",
      template_key: "initial_documentation_request",
      template_version: "v3",
      created_at: "2026-09-07T10:00:00Z",
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
      ...overrides,
    } as MessageDetail,
  };
}

describe("the autosave", () => {
  /**
   * Render, and WAIT FOR THE STUB TO ARRIVE before anything else.
   *
   * `next/dynamic` with `ssr: false` resolves asynchronously, so the editor — real or stubbed — is
   * not in the tree on the first paint. Every "it does not save" case below is an assertion that a
   * function was never called, and all five of them passed against a tree where the button simply
   * did not exist yet. The positive control is what caught it; this is what fixes it.
   *
   * Real timers for the wait, fake ones afterwards for the debounce — a fake clock never resolves
   * the import.
   */
  async function open(detail: { data: MessageDetail }, onClose = vi.fn()) {
    mockUseMessageDetail.mockReturnValue({ ...detail, isPending: false, isError: false });
    render(<MessageDialog fileId="LF-JR4T" messageId="m1" onClose={onClose} />);
    const typing = await screen.findByRole("button", { name: "simulate-typing" });
    return { typing, onClose };
  }

  it("saves what the processor typed, as HTML", async () => {
    // THE POSITIVE CONTROL FOR EVERY not-called ASSERTION BELOW.
    const { typing } = await open(draft());
    vi.useFakeTimers();

    fireEvent.click(typing);
    await vi.advanceTimersByTimeAsync(1000);
    vi.useRealTimers();

    expect(mockSave).toHaveBeenCalledTimes(1);
    const saved = mockSave.mock.calls[0]?.[0] as { draftId: string; body: string };
    expect(saved.draftId).toBe("m1");
    expect(saved.body).toBe("<p>March statement only.</p>");
  });

  // "The editor reports the body it was handed" has NO TEST HERE, deliberately. React bails out of
  // a state update that sets the same string, so a stub re-emitting the seed never reaches the
  // debounce at all — the assertion passed with the comparison deleted, which makes it a test that
  // cannot fail. The guarantee it was reaching for is that Tiptap does not report without a
  // document change, and that is asserted against the REAL editor in `message-editor.test.tsx`.

  it("does not save a draft nobody typed in", async () => {
    // ACCEPTANCE 2 — FOCUS IS NOT AN EDIT, on the side that can actually keep it.
    //
    // The server cannot tell the difference: a save IS the edit, which is why
    // `SaveDraftBodyRequest` carries no `body_format` field. A dialog that posted on open would
    // flip every draft a processor merely LOOKED at to `html`, `_regenerate` would then refuse it,
    // and LP-851 would warn about losing changes nobody made.
    await open(draft());
    vi.useFakeTimers();
    // The clock runs well past the debounce, with a focusable editor on screen and nothing typed.
    vi.advanceTimersByTime(5000);
    vi.useRealTimers();

    expect(mockSave).not.toHaveBeenCalled();
  });

  it("flushes the last edit when the dialog closes", async () => {
    // The debounce is 800ms; a processor who types and immediately closes must not lose the
    // sentence they just wrote.
    const { typing, onClose } = await open(draft());
    vi.useFakeTimers();

    fireEvent.click(typing);
    // Closed well before the debounce would have fired.
    fireEvent.keyDown(document.body, { key: "Escape" });
    vi.useRealTimers();

    expect(mockSave).toHaveBeenCalledTimes(1);
    expect(onClose).toHaveBeenCalled();
  });

  it("closing a draft nobody typed in saves nothing", async () => {
    await open(draft());
    vi.useFakeTimers();

    fireEvent.keyDown(document.body, { key: "Escape" });
    vi.useRealTimers();

    expect(mockSave).not.toHaveBeenCalled();
  });

  it("saves once for a burst of keystrokes, not once each", async () => {
    const { typing } = await open(draft());
    vi.useFakeTimers();

    fireEvent.click(typing);
    vi.advanceTimersByTime(100);
    fireEvent.click(typing);
    vi.advanceTimersByTime(100);
    fireEvent.click(typing);
    vi.advanceTimersByTime(2000);
    vi.useRealTimers();

    expect(mockSave).toHaveBeenCalledTimes(1);
  });
});
