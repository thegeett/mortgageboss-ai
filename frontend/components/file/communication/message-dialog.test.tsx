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
const mockAttach = vi.fn();
const attachState = { mutate: mockAttach, isPending: false, isError: false };
// LP-853 — the autosave. Held here so a case can assert WHAT was saved, and WHETHER anything was:
// "focus is not an edit" is an assertion that this was never called.
const mockSave = vi.fn();
const saveState = { mutate: mockSave, isPending: false, isError: false };
// LP-831 REVIEW — THE REAL `messageMailtoUrl`, not a stub. What the "Open in mail client" link
// carries is the assertion; a mocked builder would let the button exist while the link was wrong.
// Only the two hooks are replaced.
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
const mockCapabilities = vi.fn(() => ({ data: { receiving: false } }));
vi.mock("@/lib/api/capabilities", () => ({ useCapabilities: () => mockCapabilities() }));
vi.mock("@/lib/api/communications", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/lib/api/communications")>()),
  useMessageDetail: (...args: unknown[]) => mockUseMessageDetail(...args),
  useSendDraft: () => sendState,
  useAttachUploadLink: () => attachState,
  // LP-856 — the dialog now holds a polish mutation, and an unmocked one reaches for a
  // QueryClient this tree does not have. `isPending: false` keeps the ✦ button in its resting
  // state; what the button DOES is asserted in `message-dialog-polish.test.tsx`.
  usePolishDraft: () => ({ mutate: vi.fn(), isPending: false }),
  useSaveDraftBody: () => saveState,
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
  // LP-855 — RESET, or `unanswered()` in one case leaks into the next and the picker opens over
  // tests that are about something else. `vi.clearAllMocks` clears CALLS, not a `mockReturnValue`.
  mockPreferences.mockReturnValue({
    data: {
      mail_client: "gmail",
      suggested_mail_client: "gmail",
      mail_client_suggestion_reason: "you sign in as priya@gmail.com",
    },
  });
});

function detail(overrides: Partial<MessageDetail> = {}): { data: MessageDetail } {
  return {
    data: {
      id: "m1",
      direction: "outbound",
      status: "sent",
      subject: "Documents we need",
      body: "Hello Sarah,\n\nPlease send the bank statements.\n\nDana Reyes",
      // LP-853 — every generated draft is plain; a case that wants the authored path overrides it.
      body_format: "plain",
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
      suggested_bcc: "lf-abc@imbox.example.test",
      mailto_available: true,
      mailto_max_chars: 1800,
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

    // LP-849 — WHAT THE SEND RECEIVES IS PLAIN TEXT, and that is the property worth pinning here.
    //
    // The message field is a rich editor now, so "edit" is a ProseMirror document change rather
    // than a `value` assignment — `fireEvent.change` on a contenteditable does nothing, and a
    // version of this test that kept using it would have asserted that the UNEDITED body was sent
    // while appearing to test an edit. Simulating keystrokes through ProseMirror in jsdom is
    // unreliable enough that it would test the simulation.
    //
    // The integration risk is not "can a processor type" — it is whether HTML leaks into the
    // record of what went out, because the editor speaks HTML and the column stores plain text.
    // That is what this asserts. The conversion itself is a fixed point over 13 shapes in
    // `round-trip.test.ts`, and the editor's own suite covers the toolbar and what is displayed.
    fireEvent.click(screen.getByRole("button", { name: /Mark as sent/ }));

    expect(mockSend).toHaveBeenCalledTimes(1);
    const sent = mockSend.mock.calls[0]?.[0] as { draftId: string; body: string };
    expect(sent.draftId).toBe("m1");
    // LP-853 — STILL PLAIN, BECAUSE NOBODY TYPED. `body_format` is `plain` on this fixture, so the
    // send posts the plain derivation and the record of what went out is byte-for-byte what LP-849
    // stored. HTML reaches the send only once a processor has actually written into the draft.
    expect(sent.body).not.toContain("<p>");
    expect(sent.body).not.toContain("<strong>");
    expect(sent.body).toContain("Please send the bank statements.");
  });

  // ------------------------------------------------------------------------------------------- //
  // LP-853 — the body becomes HTML the moment a person touches it
  // ------------------------------------------------------------------------------------------- //
  // The autosave — whether an edit is saved and a non-edit is not — needs the editor replaced by a
  // stub that can emit a change on demand, so it lives in `message-dialog-autosave.test.tsx`. This
  // file keeps the REAL editor, which is what "gives the processor the rich editor" asserts.

  it("loads an authored body as HTML rather than escaping it into view", () => {
    // THE READER HALF. An `html` body is already markup; running it through `emailBodyToHtml` would
    // escape the processor's own tags, so the message they wrote would read back as source. What
    // makes showing it safe is the server's allowlist, not this component.
    mockUseMessageDetail.mockReturnValue(
      state(
        detail({
          is_editable: false,
          body_format: "html",
          body: "<p>March statement <strong>only</strong>, not February.</p>",
        }),
      ),
    );
    render(<MessageDialog fileId="LF-JR4T" messageId="m1" onClose={vi.fn()} />);

    // The word is bold, not surrounded by visible tags.
    const bold = screen.getByText("only");
    expect(bold.tagName).toBe("STRONG");
    expect(screen.queryByText(/&lt;strong&gt;/)).toBeNull();
    expect(screen.queryByText(/<strong>/)).toBeNull();
  });

  it("sends the HTML once the draft is authored", () => {
    // THE CONTROL FOR "still plain, because nobody typed" above. Same button, same assertions
    // inverted — without this, a dialog that posted plain text forever would pass both.
    mockUseMessageDetail.mockReturnValue(
      state(
        detail({
          is_editable: true,
          is_open_draft: true,
          status: "draft",
          body_format: "html",
          body: "<p>March statement <strong>only</strong>.</p>",
        }),
      ),
    );
    render(<MessageDialog fileId="LF-JR4T" messageId="m1" onClose={vi.fn()} />);

    fireEvent.click(screen.getByRole("button", { name: /Mark as sent/ }));

    const sent = mockSend.mock.calls[0]?.[0] as { body: string };
    expect(sent.body).toContain("<strong>");
    expect(sent.body).toContain("March statement");
  });

  it("gives the processor the rich editor, not a textarea", async () => {
    // THE WIRING, and it is the fifth time in this run that something was built correctly and
    // nothing asserted it was connected. Every other test in this file reads `body` from the seeded
    // detail, so all of them pass whether the editor mounts or not — and `next/dynamic` with
    // `ssr: false` is exactly the kind of thing that silently renders a placeholder forever.
    mockUseMessageDetail.mockReturnValue(
      state(detail({ is_editable: true, is_open_draft: true, status: "draft" })),
    );
    render(<MessageDialog fileId="LF-JR4T" messageId="m1" onClose={vi.fn()} />);

    await vi.waitFor(() => expect(document.querySelector(".ProseMirror")).not.toBeNull());
    // And the notepad it replaced is gone, rather than both being present.
    expect(document.querySelector("textarea")).toBeNull();
    // LP-844's Markdown affordances went with it: a WYSIWYG IS the preview, and telling a processor
    // to type `**bold**` into a box where bold is a button is the report this ticket came from.
    expect(screen.queryByText(/\*\*bold\*\*/)).toBeNull();
    expect(screen.queryByRole("button", { name: /^Preview$/ })).toBeNull();
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

  it("can be marked sent with NO recipient", () => {
    // LP-847 — THE REPORTED BUG, and it was two of our own decisions contradicting. LP-843 gives a
    // party with no contact on file a draft with an empty To, deliberately ("processor mostly worry
    // about a message"); this button required one, so every such draft was permanently grey with
    // nothing saying why.
    //
    // Nothing here transmits. Marking sent records that a PROCESSOR sent it from their own mail
    // client, possibly to an address they know and have never typed into this system, so refusing
    // the record for want of our own bookkeeping is refusing to believe them.
    mockUseMessageDetail.mockReturnValue(
      state(detail({ is_editable: true, status: "draft", counterparty: null })),
    );
    render(<MessageDialog fileId="LF-JR4T" messageId="m1" onClose={vi.fn()} />);

    expect(
      (screen.getByRole("button", { name: /Mark as sent/ }) as HTMLButtonElement).disabled,
    ).toBe(false);
  });

  it("still refuses to send an empty message", () => {
    // THE CONTROL. Dropping the recipient requirement must not drop the body requirement: there is
    // no message to have sent without one, and the server refuses it too.
    mockUseMessageDetail.mockReturnValue(
      state(detail({ is_editable: true, status: "draft", counterparty: null, body: "   " })),
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

  it("says when it happened, in full, with the label (LP-838)", () => {
    // THE SAME INSTANT THE LIST SHOWS, longer form. Somebody reading one message is looking at that
    // message, and "yesterday" is not enough to put in a note or an audit conversation.
    mockUseMessageDetail.mockReturnValue(
      state(
        detail({
          status: "sent",
          sent_at: "2026-09-04T14:30:00Z",
          created_at: "2026-09-01T10:00:00Z",
        }),
      ),
    );
    render(<MessageDialog fileId="LF-JR4T" messageId="m1" onClose={vi.fn()} />);

    // SENT, not created — and the date is `sent_at`, three days after composition. A dialog reading
    // `created_at` would show 1 Sep and label it Sent, which is two wrong answers that look like one
    // right one.
    expect(screen.getByText(/Sent 4 Sep 2026/)).toBeTruthy();
  });

  it("labels an unsent draft Created, at its composition time", () => {
    mockUseMessageDetail.mockReturnValue(
      state(
        detail({
          is_editable: true,
          status: "draft",
          sent_at: null,
          created_at: "2026-09-01T10:00:00Z",
        }),
      ),
    );
    render(<MessageDialog fileId="LF-JR4T" messageId="m1" onClose={vi.fn()} />);

    expect(screen.getByText(/Created 1 Sep 2026/)).toBeTruthy();
  });

  it("renders nothing when no message is open", () => {
    // THE CONTROL. A dialog that rendered its content regardless would satisfy every assertion
    // above and sit permanently over the timeline.
    mockUseMessageDetail.mockReturnValue(state({ data: undefined }));
    render(<MessageDialog fileId="LF-JR4T" messageId={null} onClose={vi.fn()} />);

    expect(screen.queryByText(/Please send the bank statements/)).toBeNull();
  });
});

/**
 * LP-831 REVIEW — THE TWO CONTROLS THAT ACTUALLY SEND.
 *
 * `OutboundDraftPanel` carried "Copy message" and "Open in mail client", and this ticket took that
 * panel off the page. Nothing in this product transmits mail — LP-828's own analysis says so, and
 * `send_draft`'s docstring says it records rather than sends — so those two were the only ways a
 * message reached anybody. The dialog that replaced the panel offered "Mark as sent" alone, which
 * writes the evidence row, moves every need to REQUESTED and starts LP-814's reminder clock.
 *
 * A processor could therefore record that a borrower was emailed, start the clock on chasing them
 * for a reply, and have had no way to send the message at all.
 */
describe("MessageDialog — a draft can actually be sent", () => {
  it("copies the body, and the copy carries no markup on a plain draft", async () => {
    // LP-855 — THE `mailto:` LINK IS GONE FROM THIS BAR. It was a second control carrying the body
    // in the URL; the primary now copies the rich body and opens the compose window with the body
    // EMPTY, which is `copies AND opens` below. What survives from LP-849 is the half that still
    // matters here: what the clipboard carries.
    mockUseMessageDetail.mockReturnValue(
      state(detail({ is_editable: true, is_open_draft: true, status: "draft" })),
    );
    const writeText = vi.fn().mockResolvedValue(undefined);
    Object.assign(navigator, { clipboard: { writeText } });
    render(<MessageDialog fileId="LF-JR4T" messageId="m1" onClose={vi.fn()} />);

    fireEvent.click(screen.getByRole("button", { name: /copy message/i }));
    const copied = writeText.mock.calls[0]?.[0] as string;
    expect(copied).toContain("Please send the bank statements.");
    expect(copied).not.toContain("<p>");
  });

  it("does not offer them on a message that cannot be edited", () => {
    // The control: a sent message has already gone, and offering to send it again would be a second
    // email the record does not describe.
    mockUseMessageDetail.mockReturnValue(state(detail({ is_editable: false, status: "sent" })));
    render(<MessageDialog fileId="LF-JR4T" messageId="m1" onClose={vi.fn()} />);

    expect(screen.queryByRole("button", { name: /copy message/i })).toBeNull();
    expect(screen.queryByRole("link", { name: /open in mail client/i })).toBeNull();
    // And the positive half: the message itself is still on screen.
    expect(screen.getByText(/Please send the bank statements/)).toBeTruthy();
  });

  it("LP-855 — a long message no longer hides the way to send it", () => {
    // `mailto_max_chars` exists because a long BODY overflows the URL, and `mailto:` does not fail
    // when it is too long — it opens a compose window holding half a message. THERE IS NO LONGER A
    // BODY IN THE URL, so the ceiling has nothing to measure: what remains is the subject and the
    // address, capped by `SendDraftRequest` at 256 each against a ceiling of 1,800.
    //
    // This test asserted the OPPOSITE — that the control was disabled — and the inversion is the
    // ticket. Hiding the only way to send a message because the message is long was the behaviour
    // being removed.
    mockUseMessageDetail.mockReturnValue(
      state(detail({ is_editable: true, status: "draft", mailto_available: false })),
    );
    render(<MessageDialog fileId="LF-JR4T" messageId="m1" onClose={vi.fn()} />);

    const open = screen.getByRole("button", { name: /Copy & open/ });
    expect((open as HTMLButtonElement).disabled).toBe(false);
  });
});

/**
 * LP-855 — Screen 2's button bar.
 *
 * `Copy & open <client>` · `Copy message` · `Mark as sent` … `Delete`, and NO SEND BUTTON.
 */
describe("the button bar", () => {
  function draftOpen() {
    mockUseMessageDetail.mockReturnValue(
      state(detail({ is_editable: true, is_open_draft: true, status: "draft" })),
    );
    render(<MessageDialog fileId="LF-JR4T" messageId="m1" onClose={vi.fn()} />);
  }

  it("has NO Send button, not even disabled", () => {
    // `mail_transport` is an interface with no provider behind it, so a greyed-out Send would be a
    // promise this version cannot keep and the first thing a processor would click.
    draftOpen();

    for (const name of [/^Send$/, /^Send message$/, /^Send email$/, /^Send now$/]) {
      expect(screen.queryByRole("button", { name })).toBeNull();
    }
  });

  it("and the buttons that ARE here are here", () => {
    // THE POSITIVE CONTROL for the absence above, and it is not ceremony: a not-assertion over a
    // whole screen passes on a screen that failed to render, which is exactly what a broken import
    // or a thrown hook produces.
    draftOpen();

    expect(screen.getByRole("button", { name: /Copy & open/ })).toBeTruthy();
    expect(screen.getByRole("button", { name: /Copy message/ })).toBeTruthy();
    expect(screen.getByRole("button", { name: /Mark as sent/ })).toBeTruthy();
  });

  it("the primary names the client, so it says what will happen before it happens", () => {
    draftOpen();
    expect(screen.getByRole("button", { name: "Copy & open Gmail" })).toBeTruthy();
  });

  it("copies AND opens, with the body left empty", async () => {
    // THE WHOLE SEND PATH IN ONE CLICK. Every compose route takes the body as plain text, so
    // filling it would hand the processor a message that LOOKS finished and has quietly lost its
    // structure. An empty body is obviously unfinished, which is the point.
    const writeText = vi.fn().mockResolvedValue(undefined);
    Object.assign(navigator, { clipboard: { writeText } });
    const open = vi.fn().mockReturnValue({});
    Object.defineProperty(window, "open", { configurable: true, value: open });
    draftOpen();

    fireEvent.click(screen.getByRole("button", { name: /Copy & open/ }));
    await vi.waitFor(() => expect(open).toHaveBeenCalled());

    // The clipboard has the message...
    expect(writeText.mock.calls[0]?.[0]).toContain("Please send the bank statements.");
    // ...and the URL does not.
    const url = new URL(open.mock.calls[0]?.[0] as string);
    expect(url.origin + url.pathname).toBe("https://mail.google.com/mail/");
    expect(url.searchParams.get("body")).toBe("");
    expect(url.searchParams.get("to")).toBe("sarah@example.com");
    expect(url.searchParams.get("su")).toBe("Documents we need");
  });

  it("tells the processor to paste, once the window is open", () => {
    draftOpen();
    expect(screen.getByText(/Records that you sent it/)).toBeTruthy();
    expect(screen.queryByText(/Paste into the message/)).toBeNull();
  });

  it("a refused clipboard still opens the window, and says which half is missing", async () => {
    // THE MIRROR IMAGE of the blocked-popup case below, and it was unhandled: `writeText` rejects
    // when the permission is denied outright, so `copyAndOpen` never reached `window.open` and set
    // no state. No copy, no window, no sentence — a primary button that appears broken.
    const writeText = vi.fn().mockRejectedValue(new Error("denied"));
    Object.assign(navigator, { clipboard: { writeText } });
    const open = vi.fn().mockReturnValue({});
    Object.defineProperty(window, "open", { configurable: true, value: open });
    draftOpen();

    fireEvent.click(screen.getByRole("button", { name: /Copy & open/ }));

    // The window opens anyway — To and Subject are worth having without the body.
    await vi.waitFor(() => expect(open).toHaveBeenCalled());
    await vi.waitFor(() => expect(screen.getByText(/refused the copy/)).toBeTruthy());
    expect(screen.getByText(/copy it in yourself/)).toBeTruthy();
  });

  it("a blocked popup still leaves the message on the clipboard, and says so", async () => {
    // ACCEPTANCE 3. The clipboard is written FIRST, so a refusal leaves the processor with the
    // message rather than with neither a window nor a copy — and the sentence says which.
    const writeText = vi.fn().mockResolvedValue(undefined);
    Object.assign(navigator, { clipboard: { writeText } });
    Object.defineProperty(window, "open", { configurable: true, value: () => null });
    draftOpen();

    fireEvent.click(screen.getByRole("button", { name: /Copy & open/ }));

    await vi.waitFor(() => expect(screen.getByText(/blocked the compose window/)).toBeTruthy());
    expect(screen.getByText(/on your clipboard/)).toBeTruthy();
    expect(writeText).toHaveBeenCalled();
  });
});

describe("the secure upload link (LP-834)", () => {
  // LP-857 FLAGS THIS WHOLE FEATURE OUT, and these cases are why it is a flag and not a deletion:
  // LP-834 is written and reviewed and returns with the phase that brings receiving back, so its
  // behaviour keeps being asserted. What LP-857 changed is that it is unreachable by default —
  // asserted in `message-dialog-address.test.tsx`, in both directions.
  beforeEach(() => mockCapabilities.mockReturnValue({ data: { receiving: true } }));

  it("offers to add one, and warns before the click", () => {
    // THE WARNING IS BEFORE, NOT AFTER. Minting expires every other live link on the file, so a
    // borrower already sent one loses it — they click and are refused, with no explanation on their
    // end. That is not a thing to discover afterwards.
    mockUseMessageDetail.mockReturnValue(state(detail({ is_editable: true, status: "draft" })));
    render(<MessageDialog fileId="LF-JR4T" messageId="m1" onClose={vi.fn()} />);

    const button = screen.getByRole("button", { name: "Add a secure upload link" });
    expect(button.getAttribute("title")).toContain("stops working");

    fireEvent.click(button);
    expect(mockAttach).toHaveBeenCalledTimes(1);
  });

  it("says REPLACE once the draft already carries one", () => {
    // Two links in one email is the state this exists to prevent, and a button that still says
    // "Add" is how a processor reaches it believing they are adding a second route rather than
    // killing the first.
    mockUseMessageDetail.mockReturnValue(
      state(
        detail({
          is_editable: true,
          status: "draft",
          body: "Hello Sarah,\n\nUpload here: https://app.test/upload/tok123\n\nDana Reyes",
        }),
      ),
    );
    render(<MessageDialog fileId="LF-JR4T" messageId="m1" onClose={vi.fn()} />);

    expect(screen.getByRole("button", { name: "Replace the secure link" })).toBeTruthy();
    expect(screen.queryByRole("button", { name: "Add a secure upload link" })).toBeNull();
  });

  it("offers nothing on a sent message", () => {
    // LP-821 — the evidence record is what actually went out; a link added afterwards would make
    // the stored message differ from the one the borrower received. The server refuses it too.
    mockUseMessageDetail.mockReturnValue(state(detail({ is_editable: false })));
    render(<MessageDialog fileId="LF-JR4T" messageId="m1" onClose={vi.fn()} />);

    expect(screen.queryByRole("button", { name: /secure/i })).toBeNull();
  });
});

/**
 * LP-844 — the body is read as a letter, and copied in a form that survives the paste.
 */
describe("the rendered body", () => {
  it("shows the document list as a list, not as a monospace dump", async () => {
    mockUseMessageDetail.mockReturnValue(
      state(detail({ body: "Hello,\n\n- Bank statements\n- Pay stubs" })),
    );
    render(<MessageDialog fileId="LF-JR4T" messageId="m1" onClose={vi.fn()} />);
    await screen.findByText("Hello,");

    // SCOPED TO THE BODY. "Bank statements" is also in the "What it asks for" list below, which has
    // been a real `<ul>` all along — an unscoped query would pass against a body still rendered as
    // a monospace dump, which is the exact thing this asserts is gone.
    // `document`, not the render container: the dialog is portalled to document.body, so a
    // container-scoped query finds nothing and an `expect([]).toEqual([])` would have passed.
    const items = [...document.querySelectorAll(".message-body li")].map((li) => li.textContent);
    expect(items).toEqual(["Bank statements", "Pay stubs"]);
    expect(document.querySelector(".message-body p")?.textContent).toBe("Hello,");
    expect(document.querySelector("pre")).toBeNull();
  });

  it("renders a script tag in a body as text", async () => {
    // The reader uses dangerouslySetInnerHTML, so the escape-first renderer is load-bearing HERE and
    // not only in its own unit test. A body carries a borrower's words and a processor's note.
    mockUseMessageDetail.mockReturnValue(
      state(detail({ body: "Please send <script>alert(1)</script> it" })),
    );
    render(<MessageDialog fileId="LF-JR4T" messageId="m1" onClose={vi.fn()} />);

    await screen.findByText(/Please send/);
    expect(document.querySelector("script")).toBeNull();
    // The control: the text really did arrive, so this is not passing on an empty dialog.
    expect(document.querySelector(".message-body")?.textContent).toContain("<script>");
  });
});

/**
 * LP-858 §1 — the picker, wired to the BUTTON.
 *
 * `mail-client-dialog.test.tsx` covers the dialog itself. These are about WHEN it appears, which is
 * the half that lives here — and it is the half the ticket was filed about. It used to open on the
 * first editable draft of a session, so a processor who clicked a draft was asked which mail client
 * they use about a message they had not read. It opens on `Copy & open …` now, and on nothing else.
 */
describe("the mail-client picker", () => {
  function unanswered() {
    mockPreferences.mockReturnValue({
      data: {
        mail_client: null,
        suggested_mail_client: "gmail",
        mail_client_suggestion_reason: "you sign in as priya@gmail.com",
      },
    } as never);
  }

  it("the answer takes effect before the server confirms it", async () => {
    // LP-855 REVIEW — IT DID NOT. `onChoose` closed the picker and fired the save, and the compose
    // route read `preferences.data.mail_client` — still `null` until the PUT returned. So a
    // processor who chose Gmail and clicked straight through, which is the shape of this dialog,
    // got "Copy & open mail app" and a `mailto:` window.
    //
    // The same gap is what a FAILED save leaves permanently: `useUpdatePreferences` has no
    // `onError`, `askedThisSession` is already true so the picker cannot return, and every compose
    // for the rest of the session goes to `mailto:` with nothing saying why.
    //
    // `mutate` here never calls back, which is exactly the in-flight window and exactly a save that
    // failed — one fixture for both.
    unanswered();
    mockUseMessageDetail.mockReturnValue(
      state(detail({ is_editable: true, is_open_draft: true, status: "draft" })),
    );
    const open = vi.fn().mockReturnValue({});
    Object.defineProperty(window, "open", { configurable: true, value: open });
    Object.assign(navigator, { clipboard: { writeText: vi.fn().mockResolvedValue(undefined) } });
    render(<MessageDialog fileId="LF-JR4T" messageId="m1" onClose={vi.fn()} />);

    // LP-858 §1 — the picker is raised by the button now, so the gesture starts here.
    fireEvent.click(screen.getByRole("button", { name: "Copy & open mail app" }));
    fireEvent.click(screen.getByRole("button", { name: "Use Gmail" }));

    // The server still says null — the mock never resolved — and the route has moved anyway.
    expect(mockSavePreferences.mutate).toHaveBeenCalled();
    await vi.waitFor(() => expect(open).toHaveBeenCalled());
    expect(open.mock.calls[0]?.[0] as string).toContain("mail.google.com");
    // AND THE LABEL FOLLOWS, so the next press says where it goes rather than reverting to "mail
    // app" for the rest of a session in which the PUT never landed.
    expect(screen.getByRole("button", { name: "Copy & open Gmail" })).toBeTruthy();
  });

  it("opening a draft does not ask which mail client", () => {
    // THE REPORTED DEFECT, INVERTED. *"on clicking draft, it suddenly asked me to choose what email
    // client you want to open. Basically it should display the email first and later on clicking
    // action button I should get that pop up."*
    //
    // The old shape was `open={open && !needsClient}` — so the picker was not merely ON TOP of the
    // draft, the draft was SUPPRESSED behind it. Both halves are asserted: no question, and the
    // message is on screen.
    unanswered();
    mockUseMessageDetail.mockReturnValue(
      state(detail({ is_editable: true, is_open_draft: true, status: "draft" })),
    );
    render(<MessageDialog fileId="LF-JR4T" messageId="m1" onClose={vi.fn()} />);

    expect(screen.queryByRole("heading", { name: /Which mail app/ })).toBeNull();
    // THE DRAFT IS THE THING ON SCREEN, which is what the processor clicked for. Without this the
    // assertion above also passes on a dialog that rendered nothing at all.
    expect(screen.getByRole("button", { name: "Copy & open mail app" })).toBeTruthy();
    expect(screen.getByLabelText("Send to")).toBeTruthy();
  });

  it("Copy & open asks once, then completes the action", async () => {
    // ANSWERING COMPLETES THE ORIGINAL GESTURE. A picker that asked and then made the processor
    // press the same button a second time would satisfy "ask on the button" and still be the wrong
    // product — they already said what they wanted.
    unanswered();
    mockUseMessageDetail.mockReturnValue(
      state(detail({ is_editable: true, is_open_draft: true, status: "draft" })),
    );
    const open = vi.fn().mockReturnValue({});
    Object.defineProperty(window, "open", { configurable: true, value: open });
    Object.assign(navigator, { clipboard: { writeText: vi.fn().mockResolvedValue(undefined) } });
    render(<MessageDialog fileId="LF-JR4T" messageId="m1" onClose={vi.fn()} />);

    // Nothing has opened yet: the button has not been pressed.
    expect(open).not.toHaveBeenCalled();

    fireEvent.click(screen.getByRole("button", { name: "Copy & open mail app" }));

    // NOW it asks — and still has not opened anything, because it does not know where to.
    expect(screen.getByRole("heading", { name: "Which mail app should this open?" })).toBeTruthy();
    expect(open).not.toHaveBeenCalled();

    // §5 — THE DRAFT STAYS VISIBLE BEHIND THE DIALOG. The shape being replaced did not merely
    // layer the picker on top, it unmounted the message: `open={open && !needsClient}`. Asserted
    // by TEXT rather than by role, deliberately — Radix marks the pane behind the topmost modal
    // `aria-hidden`, which is correct for something that cannot be interacted with, and a role
    // query would fail on a draft that is on screen and readable.
    expect(screen.getByText(/Please send/)).toBeTruthy();

    fireEvent.click(screen.getByRole("button", { name: "Use Gmail" }));

    // ONE gesture: the answer lands, the question goes, and the compose window opens on the client
    // just chosen — not on `mailto:`, which is what reading the unrefreshed preference would give.
    await vi.waitFor(() => expect(open).toHaveBeenCalled());
    expect(open.mock.calls[0]?.[0] as string).toContain("mail.google.com");
    expect(screen.queryByRole("heading", { name: /Which mail app/ })).toBeNull();
  });

  it("Copy message and Mark as sent never raise it", () => {
    // §5: "Never on opening a draft, never on `Copy message`, never on `Mark as sent`, never on
    // mount." The first and last are above; these are the two buttons that share the row with the
    // one that DOES ask, which is where a broad trigger would hide.
    unanswered();
    mockUseMessageDetail.mockReturnValue(
      state(detail({ is_editable: true, is_open_draft: true, status: "draft" })),
    );
    Object.assign(navigator, { clipboard: { writeText: vi.fn().mockResolvedValue(undefined) } });
    render(<MessageDialog fileId="LF-JR4T" messageId="m1" onClose={vi.fn()} />);

    fireEvent.click(screen.getByRole("button", { name: "Copy message" }));
    expect(screen.queryByRole("heading", { name: /Which mail app/ })).toBeNull();

    fireEvent.click(screen.getByRole("button", { name: /Mark as sent/ }));
    expect(screen.queryByRole("heading", { name: /Which mail app/ })).toBeNull();
    // The control: `Mark as sent` did its own job, so this is not passing on a dead button.
    expect(mockSend).toHaveBeenCalled();
  });

  it("ACCEPTANCE 5 — a processor who takes the safe answer gets 'mail app'", () => {
    // "Not now" stores `mailto`, so "never answered" in the ticket's sense is a processor who took
    // the safe option. The button does not claim to know more than they told it.
    mockPreferences.mockReturnValue({
      data: {
        mail_client: "mailto",
        suggested_mail_client: "gmail",
        mail_client_suggestion_reason: "you sign in as priya@gmail.com",
      },
    } as never);
    mockUseMessageDetail.mockReturnValue(
      state(detail({ is_editable: true, is_open_draft: true, status: "draft" })),
    );
    render(<MessageDialog fileId="LF-JR4T" messageId="m1" onClose={vi.fn()} />);

    expect(screen.queryByRole("heading", { name: "Which mail app should this open?" })).toBeNull();
    expect(screen.getByRole("button", { name: "Copy & open mail app" })).toBeTruthy();
  });

  it("does not ask again once it is answered", () => {
    // THE CONTROL on the case above. `mail_client` is "gmail" in the default fixture, so a press
    // goes straight through — asserted by the compose window opening with no question in between.
    mockUseMessageDetail.mockReturnValue(
      state(detail({ is_editable: true, is_open_draft: true, status: "draft" })),
    );
    const open = vi.fn().mockReturnValue({});
    Object.defineProperty(window, "open", { configurable: true, value: open });
    Object.assign(navigator, { clipboard: { writeText: vi.fn().mockResolvedValue(undefined) } });
    render(<MessageDialog fileId="LF-JR4T" messageId="m1" onClose={vi.fn()} />);

    fireEvent.click(screen.getByRole("button", { name: "Copy & open Gmail" }));

    expect(screen.queryByText("Which mail app should this open?")).toBeNull();
    return vi.waitFor(() => expect(open).toHaveBeenCalled());
  });

  it("ACCEPTANCE 4 — the answer is saved as a preference, not held in the page", () => {
    unanswered();
    mockUseMessageDetail.mockReturnValue(
      state(detail({ is_editable: true, is_open_draft: true, status: "draft" })),
    );
    render(<MessageDialog fileId="LF-JR4T" messageId="m1" onClose={vi.fn()} />);

    fireEvent.click(screen.getByRole("button", { name: "Copy & open mail app" }));
    fireEvent.click(screen.getByRole("button", { name: "Use Gmail" }));

    // Persisted per USER, through the preferences API — so it survives a reload, a different file
    // and a different machine, which page state would not.
    expect(mockSavePreferences.mutate).toHaveBeenCalledWith({ mail_client: "gmail" });
  });

  it("does not ask on a message that cannot be edited", () => {
    // A sent message has no send path to configure, and asking there would be a question about
    // nothing.
    unanswered();
    mockUseMessageDetail.mockReturnValue(state(detail({ is_editable: false, status: "sent" })));
    render(<MessageDialog fileId="LF-JR4T" messageId="m1" onClose={vi.fn()} />);

    expect(screen.queryByText("Which mail app should this open?")).toBeNull();
  });

  it("does not ask before the preferences have loaded", () => {
    // A picker that flashed open on an undefined preference and closed again would ask a question
    // nobody had time to read, and `mail_client === null` would be indistinguishable from "not
    // fetched yet".
    mockPreferences.mockReturnValue({ data: undefined } as never);
    mockUseMessageDetail.mockReturnValue(
      state(detail({ is_editable: true, is_open_draft: true, status: "draft" })),
    );
    render(<MessageDialog fileId="LF-JR4T" messageId="m1" onClose={vi.fn()} />);

    expect(screen.queryByText("Which mail app should this open?")).toBeNull();
    // And the button still works, on the safe answer.
    expect(screen.getByRole("button", { name: "Copy & open mail app" })).toBeTruthy();
  });
});
