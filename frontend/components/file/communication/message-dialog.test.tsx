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
// LP-831 REVIEW — THE REAL `messageMailtoUrl`, not a stub. What the "Open in mail client" link
// carries is the assertion; a mocked builder would let the button exist while the link was wrong.
// Only the two hooks are replaced.
vi.mock("@/lib/api/communications", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/lib/api/communications")>()),
  useMessageDetail: (...args: unknown[]) => mockUseMessageDetail(...args),
  useSendDraft: () => sendState,
  useAttachUploadLink: () => attachState,
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
    expect(sent.body).not.toContain("<p>");
    expect(sent.body).not.toContain("<strong>");
    expect(sent.body).toContain("Please send the bank statements.");
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
  it("offers both ways a message leaves, on the edited body", async () => {
    mockUseMessageDetail.mockReturnValue(
      state(detail({ is_editable: true, is_open_draft: true, status: "draft" })),
    );
    const writeText = vi.fn().mockResolvedValue(undefined);
    Object.assign(navigator, { clipboard: { writeText } });
    render(<MessageDialog fileId="LF-JR4T" messageId="m1" onClose={vi.fn()} />);

    // LP-849 — BOTH ROUTES CARRY THE BODY THE EDITOR HOLDS, which is plain text. This drove the
    // field with `fireEvent.change`, which does nothing to a contenteditable — so it would now
    // assert the unedited body while appearing to test an edit. What matters here is that copy and
    // mailto: both take the SAME body the send would, and that neither carries HTML.
    fireEvent.click(screen.getByRole("button", { name: /copy message/i }));
    const copied = writeText.mock.calls[0]?.[0] as string;
    expect(copied).toContain("Please send the bank statements.");
    expect(copied).not.toContain("<p>");

    const href =
      screen.getByRole("link", { name: /open in mail client/i }).getAttribute("href") ?? "";
    // `encodeURIComponent` percent-encodes the `@`, as `mailtoUrl` has since LP-811a — assert what
    // the link IS rather than what it reads like.
    expect(href.slice(0, href.indexOf("?"))).toBe("mailto:sarah%40example.com");
    // PARSED, NOT SUBSTRING-MATCHED. `URLSearchParams` encodes a space as `+`, which
    // `decodeURIComponent` does not undo — so a naive `toContain("Edited before sending.")` fails on
    // a link that is perfectly correct. Found by instrumenting; the first version of this assertion
    // was wrong about the code rather than the other way round.
    const params = new URLSearchParams(href.slice(href.indexOf("?") + 1));
    // THE SAME BODY AS THE COPY, so the two routes cannot disagree about what was sent — which is
    // the thing a processor would never notice until a borrower replied to the wrong list.
    expect(params.get("body")).toBe(copied);
    expect(params.get("bcc")).toBe("lf-abc@imbox.example.test");
    expect(params.get("subject")).toBe("Documents we need");
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

  it("disables the mail link when the server says it will not carry", () => {
    // `mailto:` does not fail when it is too long — it opens a compose window holding half a
    // message. A disabled control is the honest answer; a link that truncates is not.
    mockUseMessageDetail.mockReturnValue(
      state(detail({ is_editable: true, status: "draft", mailto_available: false })),
    );
    render(<MessageDialog fileId="LF-JR4T" messageId="m1" onClose={vi.fn()} />);

    expect(screen.queryByRole("link", { name: /open in mail client/i })).toBeNull();
    const disabled = screen.getByRole("button", { name: /open in mail client/i });
    expect((disabled as HTMLButtonElement).disabled).toBe(true);
  });
});

describe("the secure upload link (LP-834)", () => {
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
