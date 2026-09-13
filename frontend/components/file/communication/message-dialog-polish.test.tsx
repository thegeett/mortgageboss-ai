// @vitest-environment jsdom
/**
 * LP-856 — ✦ polish, acceptance 2, 3 and 4.
 *
 * A SEPARATE FILE BECAUSE THE EDITOR IS STUBBED HERE, for the reason `message-dialog-autosave.test
 * .tsx` gives: a real ProseMirror document cannot be driven from jsdom, and these cases are about
 * what the DIALOG does with the model's answer, not about Tiptap.
 *
 * EVERY "THE TEXT IS UNCHANGED" HAS A CONTROL. A test that asserts the original is still on screen
 * passes against a dialog where the button does nothing at all, against one where the mutation is
 * never called, and against a tree where the editor has not resolved yet — that last one is not
 * hypothetical, it is what made five assertions in the autosave file vacuous. So the accepting case
 * runs first and proves the same stub CAN replace the body.
 */
import type { MessageDetail } from "@/lib/types/communication";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const mockUseMessageDetail = vi.fn();
const mockSave = vi.fn();
const mockPolish = vi.fn();
const mockSend = vi.fn();

vi.mock("@/lib/api/preferences", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/lib/api/preferences")>()),
  usePreferences: () => ({ data: { mail_client: "gmail", suggested_mail_client: "gmail" } }),
  useUpdatePreferences: () => ({ mutate: vi.fn(), isPending: false }),
}));

// LP-857 — the dialog asks whether this version can receive, to decide whether to offer the
// secure-link button. `false` is the product's default and the restrictive answer; the button's
// two states are asserted in `message-dialog-address.test.tsx`.
vi.mock("@/lib/api/capabilities", () => ({
  // LP-858 §5 — POLISH IS WIRED IN THIS SUITE, deliberately. The button is hidden when the
  // capability says otherwise, and that half is asserted in `message-dialog.test.tsx`. These cases
  // are about what the button DOES once it exists — the flagged-out feature keeps its tests rather
  // than rotting, which is the same shape LP-857 used for LP-834's suite.
  useCapabilities: () => ({ data: { receiving: false, polish: true } }),
}));
vi.mock("@/lib/api/communications", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/lib/api/communications")>()),
  useMessageDetail: (...args: unknown[]) => mockUseMessageDetail(...args),
  useSendDraft: () => ({ mutate: mockSend, isPending: false, isError: false }),
  useAttachUploadLink: () => ({ mutate: vi.fn(), isPending: false, isError: false }),
  useSaveDraftBody: () => ({ mutate: mockSave, isPending: false, isError: false }),
  usePolishDraft: () => ({ mutate: mockPolish, isPending: false }),
}));

vi.mock("@/components/file/communication/message-editor", () => ({
  MessageEditor: ({ value }: { value: string }) => (
    // The seed is RENDERED, not just held: "Undo restores the original exactly" is a claim about
    // what the processor sees, and a stub that showed nothing could not tell a restore from a wipe.
    <div data-testid="editor">{value}</div>
  ),
}));

import { MessageDialog } from "./message-dialog";

afterEach(cleanup);
beforeEach(() => vi.clearAllMocks());

const ORIGINAL = "Hi Sarah,\n\nCould you send the March statement.\n\nDana";

function draft(overrides: Partial<MessageDetail> = {}): { data: MessageDetail } {
  return {
    data: {
      id: "m1",
      direction: "outbound",
      status: "draft",
      subject: "Documents we need",
      body: ORIGINAL,
      body_format: "plain",
      counterparty: "sarah@example.com",
      // NULL, which is what `create_compose_draft` actually writes — `custom.v1` is a real
      // template but the compose path does not render it (LP-856, "Not done"). A fixture claiming
      // otherwise would make this file agree with a draft the product does not produce.
      template_key: null,
      template_version: "v1",
      created_at: "2026-09-12T10:00:00Z",
      sent_at: null,
      read_at: null,
      is_important: false,
      error_detail: null,
      documents: [],
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

/** Render and WAIT FOR THE STUBBED EDITOR — `next/dynamic` resolves after the first paint. */
async function open(detail = draft()) {
  mockUseMessageDetail.mockReturnValue({ ...detail, isPending: false, isError: false });
  render(<MessageDialog fileId="LF-JR4T" messageId="m1" onClose={vi.fn()} />);
  await screen.findByTestId("editor");
  return screen.getByRole("button", { name: /polish/i });
}

/** Answer the pending `polish` call the way the server would. */
function answer(result: { polished: string | null; refusal: string | null }) {
  const opts = mockPolish.mock.calls[0]?.[1] as { onSuccess: (r: unknown) => void };
  opts.onSuccess(result);
}

/**
 * What "Mark as sent" would carry, right now.
 *
 * THE EDITOR IS NOT THE WHOLE ANSWER. A proposal written into the dialog's working body would leave
 * the visible editor alone — it is seeded from `data.body` — and still go out in the model's words
 * on the next click. Both "unchanged" cases below passed against exactly that mutant until this
 * existed, which is the silent replacement the ticket forbids, arriving through the only door that
 * matters.
 */
function bodyThatWouldGoOut(): string {
  fireEvent.click(screen.getByRole("button", { name: /Mark as sent/i }));
  const sent = mockSend.mock.calls.at(-1)?.[0] as { body: string } | undefined;
  if (!sent) throw new Error("Mark as sent recorded nothing");
  return sent.body;
}

const POLISHED = "Dear Sarah,\n\nWould you kindly send the March statement.\n\nThank you,\nDana";

describe("✦ polish", () => {
  it("shows the rewrite as a proposal, and accepting it saves HTML", async () => {
    // THE POSITIVE CONTROL for every "unchanged" assertion below, and acceptance 4.
    const button = await open();
    fireEvent.click(button);
    expect(mockPolish).toHaveBeenCalledTimes(1);
    expect((mockPolish.mock.calls[0]?.[0] as { draftId: string }).draftId).toBe("m1");

    answer({ polished: POLISHED, refusal: null });

    // It is labelled as a proposal, and labelled as UNSAVED. A rewrite the processor believed was
    // already stored is the failure this screen exists to prevent.
    const heading = await screen.findByText(/After ✦ polish — not saved yet/i);
    expect(heading).toBeTruthy();
    expect(screen.getByText(/Would you kindly send the March statement/)).toBeTruthy();

    fireEvent.click(screen.getByRole("button", { name: /Keep this/i }));
    await waitFor(() => expect(mockSave).toHaveBeenCalledTimes(1));
    const saved = mockSave.mock.calls[0]?.[0] as { body: string };
    // ACCEPTING IS AUTHORING. LP-853's rule is that the stored body becomes `html` the moment a
    // person decides on it, and `_regenerate` then refuses it — correct, because there is nothing
    // to regenerate on a message somebody chose.
    expect(saved.body.startsWith("<p>")).toBe(true);
    expect(saved.body).toContain("Would you kindly send the March statement");
  });

  it("Undo restores the original exactly, and saves nothing", async () => {
    // Acceptance 3.
    const button = await open();
    // EXACTLY means byte-identical, so the comparison is against what the editor was actually
    // handed — not against a re-derivation of it, which would agree with itself however the seed
    // changed. The seed carries the processor's paragraph breaks as `<p>` elements, and asserting
    // that here is what makes "including formatting" a claim rather than a word in a comment.
    const seed = screen.getByTestId("editor").innerHTML;
    expect(seed).toContain("&lt;p&gt;Could you send the March statement.&lt;/p&gt;");

    fireEvent.click(button);
    answer({ polished: POLISHED, refusal: null });
    await screen.findByText(/After ✦ polish — not saved yet/i);
    // The proposal really did displace the editor — otherwise "it came back" proves nothing.
    expect(screen.queryByTestId("editor")).toBeNull();

    fireEvent.click(screen.getByRole("button", { name: /Undo — put mine back/i }));

    const editor = await screen.findByTestId("editor");
    expect(editor.innerHTML).toBe(seed);
    expect(screen.queryByText(/Would you kindly/)).toBeNull();
    expect(mockSave).not.toHaveBeenCalled();
    expect(bodyThatWouldGoOut()).not.toContain("Would you kindly");
  });

  it("says so when the model is unavailable, and leaves the text alone", async () => {
    // LP-856 acceptance 2. NO LONGER THE ORDINARY OUTCOME: LP-858 §5 hides the button entirely
    // when polish is not wired, so reaching this means the capability changed underneath a page
    // already open, or the request failed.
    const button = await open();
    fireEvent.click(button);
    answer({ polished: null, refusal: "unavailable" });

    const message = await screen.findByText(/didn’t run/i);
    expect(message.textContent).toMatch(/your message is unchanged/i);
    // AND IT DOES NOT NAME THE ENVIRONMENT. LP-858 §5 — that wording described a permanent state a
    // processor can do nothing about and read as breakage. With the button hidden when polish is
    // not wired, the case that survives here is a race or a failed request, and "try again" is
    // true of that and was false of the old sentence.
    expect(message.textContent).not.toMatch(/environment/i);
    // NOT A PROPOSAL. Returning the text untouched under the proposal header would read as "the
    // model looked and changed nothing", which is a different claim and a false one.
    expect(screen.queryByText(/After ✦ polish/i)).toBeNull();
    expect(screen.getByTestId("editor").innerHTML).toContain("Could you send the March statement");
    expect(mockSave).not.toHaveBeenCalled();
    expect(bodyThatWouldGoOut()).toContain("Could you send the March statement");
  });

  it("says so when the rewrite invented something, without repeating the invention", async () => {
    const button = await open();
    fireEvent.click(button);
    answer({ polished: null, refusal: "invented_date:friday" });

    const message = await screen.findByText(/added something that was not in your message/i);
    // A REFUSED REWRITE IS NOT A BUG REPORT. The processor did nothing wrong and the guard's
    // internals would only invite them to wonder what they did.
    expect(message.textContent).not.toMatch(/friday/i);
    expect(mockSave).not.toHaveBeenCalled();
  });

  it("renders the model's rewrite as text, never as markup", async () => {
    // MODEL OUTPUT IS THE LEAST TRUSTED STRING ON THIS SCREEN. Polish writes nothing, so this text
    // has never been near the server's allowlist — the proposal is the one place on the page where
    // an unsanitised string reaches a `dangerouslySetInnerHTML`, and what makes that safe is the
    // escape-first renderer rather than any claim about where the text came from.
    const button = await open();
    fireEvent.click(button);
    answer({
      polished: "Dear Sarah,<script>alert(1)</script><img src=x onerror=alert(1)>",
      refusal: null,
    });

    const shown = await screen.findByText(/Dear Sarah/);
    const panel = shown.closest("[class*=message-body]") ?? shown;
    expect(panel.querySelector("script")).toBeNull();
    expect(panel.querySelector("img")).toBeNull();
    // The tags are still VISIBLE — escaped, not silently dropped, so a processor sees exactly what
    // the model produced and can judge it.
    expect(panel.textContent).toContain("<script>");
  });

  it("is offered on a generated request too, not only a free draft", async () => {
    // The ticket is explicit: a generated request a processor has rewritten by hand is exactly
    // where it is wanted. A branch on `template_key` here would be the "second kind of object" the
    // free draft is not allowed to become.
    const button = await open(
      draft({ template_key: "initial_documentation_request", documents: ["Bank statements"] }),
    );
    expect(button).toBeTruthy();
  });
});

describe("the copy door", () => {
  /**
   * THE THIRD DOOR, and it was unasserted.
   *
   * `bodyThatWouldGoOut` goes through "Mark as sent". Copy-to-clipboard reads the same
   * `bodyForSend` expression, so today one proves the other — but only because they share one
   * derivation, which is a fact about the current code rather than a property anything holds to.
   * A change that made the copy button read `proposal` directly would put the model's words on a
   * processor's clipboard with every existing assertion still green, and pasting is how the message
   * actually leaves this product.
   */
  it("copies the processor's words while a proposal is on screen, not the model's", async () => {
    const writeText = vi.fn().mockResolvedValue(undefined);
    Object.assign(navigator, { clipboard: { writeText } });
    const button = await open();
    fireEvent.click(button);
    answer({ polished: POLISHED, refusal: null });
    await screen.findByText(/After ✦ polish — not saved yet/i);

    const copy = screen.getAllByRole("button", { name: /Copy message/i })[0];
    if (!copy) throw new Error("no copy button while a proposal is on screen");
    fireEvent.click(copy);
    await waitFor(() => expect(writeText).toHaveBeenCalled());

    const copied = writeText.mock.calls.at(-1)?.[0] as string;
    expect(copied).toContain("Could you send the March statement");
    expect(copied).not.toContain("Would you kindly");
  });

  it("copies the model's words once they have been accepted", async () => {
    // THE POSITIVE CONTROL. Without it the assertion above also passes on a copy button that is
    // wired to nothing, or one that always copies the seed whatever the processor decided.
    const writeText = vi.fn().mockResolvedValue(undefined);
    Object.assign(navigator, { clipboard: { writeText } });
    const button = await open();
    fireEvent.click(button);
    answer({ polished: POLISHED, refusal: null });
    await screen.findByText(/After ✦ polish — not saved yet/i);
    fireEvent.click(screen.getByRole("button", { name: /Keep this/i }));
    await screen.findByTestId("editor");

    const copy = screen.getAllByRole("button", { name: /Copy message/i })[0];
    if (!copy) throw new Error("no copy button after accepting");
    fireEvent.click(copy);
    await waitFor(() => expect(writeText).toHaveBeenCalled());

    const copied = writeText.mock.calls.at(-1)?.[0] as string;
    expect(copied).toContain("Would you kindly");
  });
});
