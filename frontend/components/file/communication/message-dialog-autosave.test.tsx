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
import { emailBodyToHtml } from "@/lib/markdown/email-body";
import type { MessageDetail } from "@/lib/types/communication";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const mockUseMessageDetail = vi.fn();
const mockSave = vi.fn();
const mockSend = vi.fn();

// LP-855 — the mail-client preference. Mocked like the rest of the data layer: these cases are
// about the DIALOG, and `usePreferences` is a query that would otherwise need a provider.
// `mail_client: "gmail"` means the picker has been answered, so it does not open over the cases
// below; `the mail-client picker` describes the unanswered state explicitly.
const mockPreferences = vi.fn(() => ({
  data: {
    mail_client: "gmail",
    suggested_mail_client: "gmail",
    mail_client_suggestion_reason: "you sign in as priya@gmail.com",
  },
}));
const mockSavePreferences = { mutate: vi.fn(), isPending: false };
vi.mock("@/lib/api/preferences", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/lib/api/preferences")>()),
  usePreferences: () => mockPreferences(),
  useUpdatePreferences: () => mockSavePreferences,
}));

// LP-857 — the dialog asks whether this version can receive, to decide whether to offer the
// secure-link button. `false` is the product's default and the restrictive answer; the button's
// two states are asserted in `message-dialog-address.test.tsx`.
vi.mock("@/lib/api/capabilities", () => ({
  useCapabilities: () => ({ data: { receiving: false } }),
}));
const mockDeleteState = { mutate: vi.fn(), isPending: false };
vi.mock("@/lib/api/communications", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/lib/api/communications")>()),
  useMessageDetail: (...args: unknown[]) => mockUseMessageDetail(...args),
  useSendDraft: () => ({ mutate: mockSend, isPending: false, isError: false }),
  useAttachUploadLink: () => ({ mutate: vi.fn(), isPending: false, isError: false }),
  // LP-856 — the dialog now holds a polish mutation, and an unmocked one reaches for a
  // QueryClient this tree does not have. `isPending: false` keeps the ✦ button in its resting
  // state; what the button DOES is asserted in `message-dialog-polish.test.tsx`.
  usePolishDraft: () => ({ mutate: vi.fn(), isPending: false }),
  // LP-858 §7 — the pane holds a delete mutation, and an unmocked one reaches for a QueryClient
  // this tree does not have. What delete DOES is asserted in `message-dialog-delete.test.tsx`.
  useDeleteDraft: () => mockDeleteState,
  useSaveDraftBody: () => ({ mutate: mockSave, isPending: false, isError: false }),
}));

// THE STUB. One button, which calls `onChange` with a body a processor could have typed — the
// editor's whole contract as far as this dialog is concerned. `next/dynamic` resolves through the
// module registry, so mocking the module is enough.
vi.mock("@/components/file/communication/message-editor", () => ({
  MessageEditor: ({
    value,
    format,
    onChange,
  }: { value: string; format?: "plain" | "html"; onChange: (html: string) => void }) => (
    <>
      <button type="button" onClick={() => onChange("<p>March statement only.</p>")}>
        simulate-typing
      </button>
      {/* UNDO, which is `onChange` with the DOCUMENT the editor holds — the exact case the
          `openedAs` comparison in `message-dialog.tsx` says it covers.

          LP-859 §1 — AND THE STUB HAD TO LEARN THE CONVERSION, because the caller stopped doing it.
          `onChange` is "called with HTML, always" (the editor's own prop contract), and the real
          editor converts a plain body on the way in. This stub echoed `value` untouched, which was
          HTML only because the caller was pre-converting — the double conversion that was §1's
          defect. So the stub was accidentally correct, and correct BECAUSE of the bug: with the
          caller fixed it started reporting a plain body as an edit, and this test caught it.

          LP-859 REVIEW — AND IT IS STILL ONE STEP SHORT OF THE REAL EDITOR, WHICH BOUNDS WHAT THIS
          TEST CAN SAY. The real editor emits `getHTML()` — ProseMirror's re-serialisation of the
          document it built — not the string it was seeded with. Measured against the real
          `EXTENSIONS`: seeding `emailBodyToHtml(body)` and reading `getHTML()` back differs by the
          newline block joiner AND structurally, because `<li>text</li>` is re-serialised as
          `<li><p>text</p></li>`. So a whitespace-tolerant comparison would not close the gap either.

          WHAT THAT MEANS FOR THIS TEST: it catches a caller that pre-converts again (§1's defect
          returning — verified by mutation, it goes red), and it CANNOT catch the mismatch between
          `openedAs` and what the editor actually reports, because the stub's output equals
          `openedAs` by construction. That mismatch is real and is recorded against
          `message-dialog.tsx:154`; the honest fix is for the editor to report its own normalised
          HTML once, which is a change to `message-editor.tsx` rather than to this stub. Making the
          stub faithful without that fix would turn this red rather than green, which is a true
          signal about the product and a broken suite — so the claim is written down here instead. */}
      <button
        type="button"
        onClick={() => onChange(format === "html" ? value : emailBodyToHtml(value))}
      >
        simulate-undo
      </button>
    </>
  ),
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
    render(<DraftPane fileId="LF-JR4T" messageId="m1" onClose={onClose} />);
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

  it("does not save a draft typed in and then undone back to where it started", async () => {
    // The `openedAs` comparison in `message-dialog.tsx` says this is what it covers: "a processor
    // undoing back to where they started". `dirtyRef` is only ever set TRUE, never cleared when the
    // text returns to `openedAs`, so the flag survives the undo and the flush saves an unchanged
    // body — flipping `body_format` to html, freezing the draft against `_regenerate`, and making
    // LP-851 warn about losing changes that do not exist.
    const { typing } = await open(draft());
    const undo = await screen.findByRole("button", { name: "simulate-undo" });
    vi.useFakeTimers();

    fireEvent.click(typing);
    fireEvent.click(undo);
    await vi.advanceTimersByTimeAsync(1000);
    vi.useRealTimers();

    expect(mockSave).not.toHaveBeenCalled();
  });

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

  it("flushes the last edit when the pane closes", async () => {
    // The debounce is 800ms; a processor who types and immediately closes must not lose the
    // sentence they just wrote.
    //
    // LP-858 §2/§3 — CLOSED BY THE PANE'S OWN ✕, not by Escape. This was a Radix modal, which
    // handled Escape for free; a pane has no scrim and no key handler, so the button IS the close
    // path and testing the old one would assert against a route nothing takes.
    const { typing, onClose } = await open(draft());
    vi.useFakeTimers();

    fireEvent.click(typing);
    // Closed well before the debounce would have fired.
    fireEvent.click(screen.getByRole("button", { name: "Close" }));
    vi.useRealTimers();

    expect(mockSave).toHaveBeenCalledTimes(1);
    expect(onClose).toHaveBeenCalled();
  });

  it("closing a draft nobody typed in saves nothing", async () => {
    await open(draft());
    vi.useFakeTimers();

    fireEvent.click(screen.getByRole("button", { name: "Close" }));
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
