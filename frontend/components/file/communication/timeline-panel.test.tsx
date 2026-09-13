// @vitest-environment jsdom
/**
 * LP-812 — the timeline panel, and the two ways a merged list misleads.
 *
 * THE FILTER IS A QUERY PARAMETER, NOT A CLIENT-SIDE `.filter()`. Sent, received, drafts and
 * activity are defined in `services/timeline.py`; defining them again here would be two definitions
 * of one word that nothing forces to agree, and the first to drift is "sent" — which would start
 * showing drafts and tell a processor they had already asked for something they had not.
 *
 * AND AN EMPTY LIST MEANS TWO DIFFERENT THINGS. "Nothing has ever happened" and "this pill hides
 * everything" send a processor to two different places, which is the distinction `EmptyState` exists
 * to keep.
 */
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const mockTimeline = vi.fn();
const mockReplyContext = vi.fn(async (_fileId: string, _entryId: string) => ({
  recipient: "jane@borrower.example",
  subject: "Re: Docs",
}));

vi.mock("@/lib/api/timeline", () => ({
  useTimeline: (...args: unknown[]) => mockTimeline(...args),
}));

const mockImportant = vi.fn();
const mockRead = vi.fn();
const mockReply = vi.fn();

vi.mock("@/lib/api/messages", () => ({
  useSetImportant: () => ({ mutate: mockImportant, isPending: false }),
  useMarkRead: () => ({ mutate: mockRead, isPending: false }),
  useReply: () => ({ mutate: mockReply, isPending: false }),
  fetchReplyContext: (fileId: string, entryId: string) => mockReplyContext(fileId, entryId),
}));

// LP-831 — the panel now renders `MessageDialog`, which reads the URL and fetches one message.
// Both are mocked here so these cases stay about the LIST; the dialog has its own file.
const mockSearchParams = vi.fn(() => new URLSearchParams());
vi.mock("next/navigation", () => ({
  useSearchParams: () => mockSearchParams(),
}));

const mockMessageDetail = vi.fn(() => ({ data: undefined, isPending: false, isError: false }));
// LP-855 — the dialog this panel opens now reads the mail-client preference. These cases are about
// the LIST; the dialog has its own file.
vi.mock("@/lib/api/preferences", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/lib/api/preferences")>()),
  usePreferences: () => ({ data: { mail_client: "mailto" } }),
  useUpdatePreferences: () => ({ mutate: vi.fn(), isPending: false }),
}));

// LP-857 — the dialog asks whether this version can receive, to decide whether to offer the
// secure-link button. `false` is the product's default and the restrictive answer; the button's
// two states are asserted in `message-dialog-address.test.tsx`.
vi.mock("@/lib/api/capabilities", () => ({
  useCapabilities: () => ({ data: { receiving: false } }),
}));
vi.mock("@/lib/api/communications", () => ({
  useMessageDetail: (...args: unknown[]) => {
    mockMessageDetailArgs.push(args);
    return mockMessageDetail();
  },
  useSendDraft: () => ({ mutate: vi.fn(), isPending: false, isError: false }),
  // LP-834 — the dialog offers a secure link now. These cases are about the LIST; the dialog has
  // its own file.
  useAttachUploadLink: () => ({ mutate: vi.fn(), isPending: false, isError: false }),
  // LP-853 — the dialog autosaves the processor's edit. Same reasoning as the line above: these
  // cases are about the LIST.
  // LP-856 — the modal this panel opens now holds a polish mutation. Resting state only; the ✦
  // button's behaviour is asserted in `message-dialog-polish.test.tsx`.
  usePolishDraft: () => ({ mutate: vi.fn(), isPending: false }),
  useSaveDraftBody: () => ({ mutate: vi.fn(), isPending: false, isError: false }),
  messageMailtoUrl: () => "mailto:someone@example.com",
}));
const mockMessageDetailArgs: unknown[][] = [];

import type { TimelineEntry } from "@/lib/types/timeline";
import { TimelinePanel } from "./timeline-panel";

function wrapper({ children }: { children: ReactNode }) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
}

// Typed as the real thing, so a widened `TimelineEntry` is a type error here rather than a fixture
// that silently stops resembling what the server sends.
const MESSAGE: TimelineEntry = {
  id: "m1",
  kind: "message" as const,
  at: new Date(Date.now() - 3600 * 1000).toISOString(),
  summary: "A message arrived",
  direction: "inbound",
  status: "received",
  subject: "Statements attached",
  counterparty: "jane@borrower.example",
  actor_user_id: null,
  attachments: [{ name: "March_statement.pdf", disposition: "accepted" }],
  is_important: false,
  unread: true,
  party: "borrower",
  documents: [],
  actor_name: null,
  body_edited: false,
  created_at: new Date(Date.now() - 3600 * 1000).toISOString(),
  detail: {},
};

function loaded(entries: TimelineEntry[], overrides: Record<string, unknown> = {}) {
  mockTimeline.mockReturnValue({
    data: { entries, inbox_address: "lf-tok3n@inbox.example.com", ...overrides },
    isPending: false,
    isError: false,
  });
}

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

describe("the filter", () => {
  it("asks the server rather than filtering here", () => {
    loaded([MESSAGE]);
    render(<TimelinePanel fileId="f1" />, { wrapper });

    fireEvent.click(screen.getByRole("tab", { name: "Sent" }));

    expect(mockTimeline).toHaveBeenLastCalledWith("f1", "sent");
  });

  it("starts on all", () => {
    loaded([MESSAGE]);
    render(<TimelinePanel fileId="f1" />, { wrapper });
    expect(mockTimeline).toHaveBeenCalledWith("f1", "all");
  });

  it("marks exactly one pill as selected", () => {
    // Two selected pills means a screen reader announces two current filters, and the visual state
    // stops saying which list you are looking at.
    loaded([MESSAGE]);
    render(<TimelinePanel fileId="f1" />, { wrapper });
    fireEvent.click(screen.getByRole("tab", { name: "Drafts" }));

    const selected = screen
      .getAllByRole("tab")
      .filter((tab) => tab.getAttribute("aria-selected") === "true");

    expect(selected.map((tab) => tab.textContent)).toEqual(["Drafts"]);
  });
});

describe("the empty states", () => {
  it("says nothing has happened when no filter is on", () => {
    loaded([]);
    render(<TimelinePanel fileId="f1" />, { wrapper });
    // Screen 1's words, which say what to DO rather than only what is absent.
    expect(screen.getByText("Nothing has been written on this file.")).toBeDefined();
    expect(
      screen.getByText("Request documents to start a draft, or compose one yourself."),
    ).toBeDefined();
  });

  it("says the FILTER hides it when one is on", () => {
    // Telling a processor who filtered to Drafts that nothing has ever happened is false, and sends
    // them to look for a bug rather than to clear the filter.
    loaded([]);
    render(<TimelinePanel fileId="f1" />, { wrapper });

    fireEvent.click(screen.getByRole("tab", { name: "Drafts" }));

    expect(screen.getByText("Nothing in drafts")).toBeDefined();
    expect(screen.queryByText("Nothing has been written on this file.")).toBeNull();
  });
});

describe("a row", () => {
  it("shows the subject, the counterparty and the manifest", () => {
    loaded([MESSAGE]);
    render(<TimelinePanel fileId="f1" />, { wrapper });

    expect(screen.getByText("A message arrived")).toBeDefined();
    expect(screen.getByText("Statements attached")).toBeDefined();
    expect(screen.getByText(/From jane@borrower.example/)).toBeDefined();
    expect(screen.getByText("March_statement.pdf")).toBeDefined();
  });

  it("renders a filename as text and never as a link", () => {
    // Sender-written text. React escapes by default; what this pins is that nothing builds a URL,
    // a title or an href out of it.
    loaded([{ ...MESSAGE, attachments: [{ name: "../../etc/passwd", disposition: "pending" }] }]);
    const { container } = render(<TimelinePanel fileId="f1" />, { wrapper });

    expect(screen.getByText("../../etc/passwd")).toBeDefined();
    expect(container.querySelectorAll("a")).toHaveLength(0);
  });

  it("distinguishes a bounce from a send", () => {
    // "Sent" and "sent, and bounced" are not the same event, and a column of identical envelopes
    // hides the one that did not arrive.
    loaded([
      { ...MESSAGE, id: "s", direction: "outbound", status: "sent", attachments: [] },
      { ...MESSAGE, id: "f", direction: "outbound", status: "failed", attachments: [] },
    ]);
    const { container } = render(<TimelinePanel fileId="f1" />, { wrapper });

    // Two rows, and their icons differ — the icon is the second channel beside the words.
    const icons = container.querySelectorAll("li > span:first-child svg");
    expect(icons).toHaveLength(2);
    expect(icons[0]?.getAttribute("class")).not.toEqual(icons[1]?.getAttribute("class"));
  });
});

describe("the inbox address", () => {
  it("is shown so a processor can tell a borrower where to send documents", () => {
    loaded([MESSAGE]);
    render(<TimelinePanel fileId="f1" />, { wrapper });
    expect(screen.getByText("lf-tok3n@inbox.example.com")).toBeDefined();
  });

  it("is never a mailto link", () => {
    // It is a bearer capability (ADR-397): anyone holding it can post documents into this file. A
    // link invites a click that opens a compose window addressed to it from the processor's own
    // account, which is not what it is for.
    loaded([MESSAGE]);
    const { container } = render(<TimelinePanel fileId="f1" />, { wrapper });

    expect(container.querySelector('a[href^="mailto:"]')).toBeNull();
  });
});

describe("a truncated timeline", () => {
  it("says older entries are not shown", () => {
    // There is no pagination yet, so the cap drops the OLDEST entries. A page that looks complete
    // and is not is the wrong failure: a processor hunting the message that started a thread finds
    // a whole-looking timeline without it.
    loaded([MESSAGE], { truncated: true });
    render(<TimelinePanel fileId="f1" />, { wrapper });

    expect(screen.getByText(/older entries are not shown/i)).toBeTruthy();
  });

  it("says nothing when the whole history fits — the control", () => {
    // Without this, a panel that always showed the notice would pass the test above while telling
    // every processor their timeline is incomplete.
    loaded([MESSAGE], { truncated: false });
    render(<TimelinePanel fileId="f1" />, { wrapper });

    expect(screen.queryByText(/older entries are not shown/i)).toBeNull();
  });
});

// --------------------------------------------------------------------------------------------- //
// LP-818 — the per-row actions, the badge, and what each of them may act on
// --------------------------------------------------------------------------------------------- //
describe("the unread badge", () => {
  it("shows the count the server sent, not the length of this page", () => {
    // Counted over the WHOLE file. A badge derived from `entries` would shrink when somebody
    // clicked a filter pill, which is a number that teaches its reader to distrust it.
    loaded([MESSAGE], { unread_count: 7 });
    render(<TimelinePanel fileId="f1" />, { wrapper });

    expect(screen.getByLabelText("7 unread")).toBeDefined();
  });

  it("says nothing when everything has been read", () => {
    // THE CONTROL. A badge that always rendered would pass the test above while telling every
    // processor they have mail waiting.
    loaded([MESSAGE], { unread_count: 0 });
    render(<TimelinePanel fileId="f1" />, { wrapper });

    expect(screen.queryByText(/unread/)).toBeNull();
  });
});

describe("the per-row actions", () => {
  it("offers reply and read only on a message that ARRIVED", () => {
    // Replying to our own would address it to whoever we sent it to and read to them as us
    // answering ourselves. The server refuses it; offering the button is a worse way to learn that.
    loaded([
      MESSAGE,
      { ...MESSAGE, id: "out", direction: "outbound", status: "sent", unread: false },
    ]);
    render(<TimelinePanel fileId="f1" />, { wrapper });

    expect(screen.getAllByRole("button", { name: "Reply" })).toHaveLength(1);
    expect(screen.getAllByRole("button", { name: /Mark (read|unread)/ })).toHaveLength(1);
    // Important IS offered on both — a sent message is as worth flagging as a received one.
    expect(screen.getAllByRole("button", { name: /Mark important|Remove the flag/ })).toHaveLength(
      2,
    );
  });

  it("toggles importance rather than only setting it", () => {
    loaded([{ ...MESSAGE, is_important: true }]);
    render(<TimelinePanel fileId="f1" />, { wrapper });

    fireEvent.click(screen.getByRole("button", { name: "Remove the flag" }));

    expect(mockImportant).toHaveBeenCalledWith({ communicationId: "m1", important: false });
  });

  it("marks an unread message read, and a read one unread", () => {
    // Reversible: a processor who opens something they cannot deal with needs to put it back.
    loaded([MESSAGE]);
    const { unmount } = render(<TimelinePanel fileId="f1" />, { wrapper });
    fireEvent.click(screen.getByRole("button", { name: "Mark read" }));
    expect(mockRead).toHaveBeenCalledWith({ communicationId: "m1", read: true });
    unmount();

    loaded([{ ...MESSAGE, unread: false }]);
    render(<TimelinePanel fileId="f1" />, { wrapper });
    fireEvent.click(screen.getByRole("button", { name: "Mark unread" }));

    expect(mockRead).toHaveBeenLastCalledWith({ communicationId: "m1", read: false });
  });
});

describe("the reply box", () => {
  it("opens on the row and says a save is a draft, not a send", () => {
    // A button labelled "Reply" that silently transmitted would be the one outbound message with no
    // guardrails on it — and one that silently did NOT would be worse.
    loaded([MESSAGE]);
    render(<TimelinePanel fileId="f1" />, { wrapper });

    fireEvent.click(screen.getByRole("button", { name: "Reply" }));

    expect(screen.getByLabelText("Reply body")).toBeDefined();
    expect(screen.getByText(/Saved as a draft/)).toBeDefined();
  });

  it("will not save an empty reply", () => {
    loaded([MESSAGE]);
    render(<TimelinePanel fileId="f1" />, { wrapper });
    fireEvent.click(screen.getByRole("button", { name: "Reply" }));

    fireEvent.change(screen.getByLabelText("Reply body"), { target: { value: "   " } });

    expect(screen.getByRole("button", { name: "Save reply" })).toHaveProperty("disabled", true);
  });
});

describe("the reply box's context fetch", () => {
  it("fires once, not once per render while the response is pending", async () => {
    // Measured before the fix: one fetch on open, THREE after two keystrokes. The guard was
    // `context === null` in the render body, and the fetch is async — so every re-render while the
    // response was outstanding re-fired it, and typing re-renders on each keystroke.
    let calls = 0;
    mockReplyContext.mockImplementation(() => {
      calls += 1;
      return new Promise(() => {}); // never resolves: the box stays in the pending state
    });
    loaded([MESSAGE]);
    render(<TimelinePanel fileId="f1" />, { wrapper });

    const replyButton = screen.getAllByRole("button", { name: /repl/i })[0];
    expect(replyButton).toBeTruthy();
    fireEvent.click(replyButton as HTMLElement);
    expect(calls).toBe(1);

    const box = screen.getByRole("textbox");
    fireEvent.change(box, { target: { value: "a" } });
    fireEvent.change(box, { target: { value: "ab" } });

    expect(calls).toBe(1);
  });
});

/**
 * LP-825 REVIEW — WHAT BECAME OF THE ATTACHMENT, on the screen that shows it arrived.
 *
 * `inbound_triage` writes "A document arrived by email and was accepted" as a DOCUMENT_UPLOADED
 * activity, and LP-825 stopped this timeline reading the activity log — on the reasoning that every
 * activity about a message is named COMMUNICATION_* and already carried by the Communication row.
 * That one is neither: it is about an inbound attachment (its detail names `inbound_attachment_id`)
 * and the manifest carried only filenames, so an accepted document rendered identically to one
 * nobody had looked at.
 */
describe("TimelinePanel — the attachment manifest says what happened to each file", () => {
  it("distinguishes an accepted document from one still waiting", () => {
    loaded([
      {
        ...MESSAGE,
        attachments: [
          { name: "March_statement.pdf", disposition: "accepted" },
          { name: "selfie.heic", disposition: "pending" },
        ],
      },
    ]);
    render(<TimelinePanel fileId="f1" />, { wrapper });

    const accepted = screen.getByText("March_statement.pdf").closest("li");
    const waiting = screen.getByText("selfie.heic").closest("li");

    expect(accepted?.textContent).toContain("accepted");
    // The half that makes the first assertion mean something: the two rows must not read alike.
    expect(waiting?.textContent).toContain("not yet accepted");
    expect(waiting?.textContent).not.toContain("· accepted");
  });

  it("renders an unrecognised disposition as itself rather than as nothing", () => {
    // A manifest that silently drops the answer is the defect this exists to stop, so a value this
    // build does not know must still say something.
    loaded([{ ...MESSAGE, attachments: [{ name: "x.pdf", disposition: "quarantined" }] }]);
    render(<TimelinePanel fileId="f1" />, { wrapper });

    expect(screen.getByText("x.pdf").closest("li")?.textContent).toContain("quarantined");
  });
});

describe("the ?draft deep link (LP-831)", () => {
  it("opens the linked message on arrival", () => {
    // LP-837's header popover navigates HERE and expects the modal open when the page loads.
    // Landing on the list with it shut looks exactly like a mis-click, which is how that feature
    // fails quietly — so the parameter is read here rather than retrofitted there.
    mockSearchParams.mockReturnValue(new URLSearchParams("draft=m-1"));
    loaded([{ ...MESSAGE, id: "m-1", summary: "Documents we need" }]);
    mockMessageDetailArgs.length = 0;

    render(<TimelinePanel fileId="LF-JR4T" />, { wrapper });

    expect(mockMessageDetailArgs.at(-1)).toEqual(["LF-JR4T", "m-1"]);
  });

  it("stays closed after the processor dismisses the linked message", async () => {
    // LP-831 REVIEW — RUN, NOT REASONED. The build found this by thinking about it and asked for it
    // to be exercised, and it was the one behaviour of the deep link with no test.
    //
    // The URL parameter is tracked separately from the open state on purpose. Compared against
    // `openMessage` instead, closing would set it to null, the parameter would still say "m-1", and
    // the next render would re-open it — a dialog that cannot be dismissed while the link is in the
    // address bar, which is where a processor lands from LP-837's popover.
    mockSearchParams.mockReturnValue(new URLSearchParams("draft=m-1"));
    loaded([{ ...MESSAGE, id: "m-1", summary: "Documents we need" }]);
    mockMessageDetailArgs.length = 0;

    const { rerender } = render(<TimelinePanel fileId="LF-JR4T" />, { wrapper });
    expect(mockMessageDetailArgs.at(-1)).toEqual(["LF-JR4T", "m-1"]);

    fireEvent.keyDown(document.body, { key: "Escape", code: "Escape" });
    await waitFor(() => expect(mockMessageDetailArgs.at(-1)).toEqual(["LF-JR4T", null]));

    // AND IT STAYS SHUT. The re-open would happen on the NEXT render, not on the close itself, so
    // asserting only the line above would pass on the broken version.
    rerender(<TimelinePanel fileId="LF-JR4T" />);
    expect(mockMessageDetailArgs.at(-1)).toEqual(["LF-JR4T", null]);
  });

  it("renders normally with no parameter", () => {
    // THE CONTROL. A panel that always opened a dialog would satisfy the test above and put a modal
    // over the list every time somebody visited the page.
    mockSearchParams.mockReturnValue(new URLSearchParams());
    loaded([{ ...MESSAGE, id: "m-1", summary: "Documents we need" }]);
    mockMessageDetailArgs.length = 0;

    render(<TimelinePanel fileId="LF-JR4T" />, { wrapper });

    expect(mockMessageDetailArgs.at(-1)).toEqual(["LF-JR4T", null]);
  });
});

describe("when it happened (LP-838)", () => {
  it("says Draft, and ATTRIBUTES a send to the person who claimed it", () => {
    // A BARE TIMESTAMP IS AMBIGUOUS IN EXACTLY THE WAY THAT MATTERS (LP-838), and LP-852 adds the
    // name. Nothing in this version observed a send — what a processor pressed was a claim that
    // they sent it from their own mail client — so "Sent" alone reads as something the system did
    // and watched happen, which is the confusion this epic exists to fence off.
    loaded([
      {
        ...MESSAGE,
        id: "d1",
        direction: "outbound",
        status: "draft",
        summary: "Documents we need",
      },
      {
        ...MESSAGE,
        id: "s1",
        direction: "outbound",
        status: "sent",
        summary: "Documents we sent",
        actor_name: "Priya",
      },
    ]);

    render(<TimelinePanel fileId="LF-JR4T" />, { wrapper });

    expect(screen.getByText(/^Draft · /)).toBeTruthy();
    expect(screen.getByText(/^Marked sent by Priya · /)).toBeTruthy();
    // AND NEVER THE BARE WORD. This is the assertion that would fail if somebody "tidied" the
    // status line back to `Sent`.
    expect(screen.queryByText(/^Sent /)).toBeNull();
  });

  it("says Marked sent without a name rather than inventing one", () => {
    // A draft sent before this column existed, or by a user row that has since gone. The claim is
    // still a claim; it simply has no claimant to name.
    loaded([{ ...MESSAGE, id: "s1", direction: "outbound", status: "sent", actor_name: null }]);

    render(<TimelinePanel fileId="LF-JR4T" />, { wrapper });

    expect(screen.getByText(/^Marked sent · /)).toBeTruthy();
  });

  it("does not call a queued message a draft", () => {
    // LP-852 REVIEW — `draft` and `queued` were one branch, so the one thing that produces a queued
    // row (`auto_reply.record_auto_reply`, an automated nudge carrying an upload link) would have
    // read "Draft · …" under the compose pen: a message nobody wrote, nobody can edit and nobody
    // needs to act on, filed under the word that means the opposite.
    //
    // Unreachable today — `record_auto_reply` has no caller, because the nudge is one of the things
    // this epic's fence defers — and live again the moment it comes back, which is what makes it
    // worth a test rather than a note.
    loaded([{ ...MESSAGE, id: "q1", direction: "outbound", status: "queued", body_edited: false }]);
    render(<TimelinePanel fileId="LF-JR4T" />, { wrapper });

    expect(screen.getByText(/^Queued · /)).toBeTruthy();
    // Scoped to the STATUS LINE's shape — a bare /^Draft/ also matches the "Drafts" filter pill,
    // which is a button that is always on screen and has nothing to do with this row.
    expect(screen.queryByText(/^Draft · /)).toBeNull();
  });

  it("still calls a draft a draft", () => {
    // THE POSITIVE CONTROL for the assertion above. Without it, `queryByText(/^Draft/)` being null
    // is also satisfied by a build where no status line renders at all.
    loaded([{ ...MESSAGE, id: "d1", direction: "outbound", status: "draft", body_edited: false }]);
    render(<TimelinePanel fileId="LF-JR4T" />, { wrapper });

    expect(screen.getByText(/^Draft · /)).toBeTruthy();
  });

  it("says a draft has been edited when it has", () => {
    loaded([{ ...MESSAGE, id: "d1", direction: "outbound", status: "draft", body_edited: true }]);
    render(<TimelinePanel fileId="LF-JR4T" />, { wrapper });
    expect(screen.getByText(/^Draft · edited · /)).toBeTruthy();
  });

  it("says an unaddressed draft cannot be sent yet", () => {
    // LP-857 — A PARTY DRAFT IS CREATED EVEN WHEN THE FILE HAS NO ADDRESS for that party (LP-841 —
    // "the message is the part a processor wants"), and until this it read "Draft · 2m" like any
    // other: identical on the list to one that is ready, with the difference visible only after
    // opening it. Of 166 document types, 13 across title, agent, CPA, insurer and employer had no
    // address anywhere (LP-820), so for those this is the common case rather than an edge.
    loaded([
      {
        ...MESSAGE,
        id: "d1",
        direction: "outbound",
        status: "draft",
        party: "title",
        counterparty: null,
      },
    ]);
    render(<TimelinePanel fileId="LF-JR4T" />, { wrapper });

    expect(screen.getByText(/^Draft · cannot be sent yet · /)).toBeTruthy();
  });

  it("does not say it about an inbound message whose sender we could not read", () => {
    // `counterparty` IS THE SENDER ON AN INBOUND ROW. Mail that arrived from an address nobody on
    // the file recognises is not a draft that cannot be sent, and the direction is what tells them
    // apart. Nothing else on the row would.
    loaded([{ ...MESSAGE, id: "i1", direction: "inbound", status: "draft", counterparty: null }]);
    render(<TimelinePanel fileId="LF-JR4T" />, { wrapper });

    expect(screen.queryByText(/cannot be sent yet/)).toBeNull();
    expect(screen.getByText(/^Draft · /)).toBeTruthy();
  });

  it("does not say it about a draft that has a recipient", () => {
    // THE OTHER HALF of the control: the fixture's default carries an address, so "Draft · 2m" here
    // proves the new branch is reached only by the case it is for.
    loaded([{ ...MESSAGE, id: "d1", direction: "outbound", status: "draft" }]);
    render(<TimelinePanel fileId="LF-JR4T" />, { wrapper });

    expect(screen.queryByText(/cannot be sent yet/)).toBeNull();
  });

  it("shows a time on every row", () => {
    // THE CONTROL on the label: a panel that rendered the word and dropped the time would satisfy
    // the assertions above and tell a processor nothing they came for.
    loaded([{ ...MESSAGE, id: "d1", direction: "outbound", status: "draft" }]);

    render(<TimelinePanel fileId="LF-JR4T" />, { wrapper });

    expect(screen.getByText(/^Draft · .*ago$/)).toBeTruthy();
  });
});

/**
 * LP-852 — THE PARTY IS A COLUMN, NEVER A TAB AND NEVER A HEADING.
 *
 * LP-841 put the parties in a tab strip, and the report is what that cost: *"in some instance Not
 * from the borrower go bottom of the list and processor may not realize that draft has been created
 * for non borrower"*. A tab is a region that can be left unclicked; a heading is one that can be
 * scrolled past. Both put a title-company draft where nobody looks, and a draft nobody looks at is
 * never sent.
 *
 * These replace the tab tests rather than sitting beside them. The property they protected —
 * "what exists is reachable" — is the same one; what changed is that it is now true without anybody
 * clicking anything.
 */
describe("the party column", () => {
  function entry(over: Partial<TimelineEntry>): TimelineEntry {
    return { ...MESSAGE, ...over };
  }

  it("offers no party tabs at all", () => {
    loaded([
      entry({ id: "b1", party: "borrower", summary: "Documents we need" }),
      entry({ id: "t1", party: "title", summary: "Title commitment request" }),
    ]);
    render(<TimelinePanel fileId="LF-JR4T" />, { wrapper });

    // The status pills remain — they answer "what happened to it", a different question a processor
    // asks deliberately. What is gone is the axis that could hide a row.
    expect(screen.queryByRole("tab", { name: /Title/ })).toBeNull();
    expect(screen.queryByRole("tab", { name: "Everyone" })).toBeNull();
    expect(screen.getByRole("tab", { name: "Drafts" })).toBeTruthy();
  });

  it("names the party on EVERY row, with nothing to click first", () => {
    loaded([
      entry({ id: "b1", party: "borrower", summary: "Documents we need" }),
      entry({ id: "t1", party: "title", summary: "Title commitment request" }),
      entry({ id: "l1", party: "lender", summary: "Credit report request" }),
    ]);
    render(<TimelinePanel fileId="LF-JR4T" />, { wrapper });

    expect(screen.getByText("Borrower")).toBeTruthy();
    expect(screen.getByText("Title co.")).toBeTruthy();
    expect(screen.getByText("Lender")).toBeTruthy();
    // And every row is present at once.
    expect(screen.getByText("Documents we need")).toBeTruthy();
    expect(screen.getByText("Title commitment request")).toBeTruthy();
    expect(screen.getByText("Credit report request")).toBeTruthy();
  });

  it("ACCEPTANCE 1 — a title-company draft is visible on a file with ten drafts", () => {
    // The reported case, at the size it was reported at. Nine borrower drafts and one to the title
    // company, and the tenth row must be in the document without a click — no tab, no heading, no
    // group to expand.
    const rows = [
      ...Array.from({ length: 9 }, (_, i) =>
        entry({ id: `b${i}`, party: "borrower", summary: `Borrower request ${i}` }),
      ),
      entry({ id: "t1", party: "title", summary: "Title commitment request" }),
    ];
    loaded(rows);
    render(<TimelinePanel fileId="LF-JR4T" />, { wrapper });

    expect(screen.getByText("Title commitment request")).toBeTruthy();
    expect(screen.getByText("Title co.")).toBeTruthy();
    // THE CONTROL: there is no heading or tab between it and the top that could hide it.
    expect(screen.queryAllByRole("tab", { name: /Title/ })).toHaveLength(0);
    expect(screen.queryAllByRole("heading", { name: /Title/ })).toHaveLength(0);
  });

  it("ACCEPTANCE 4 — a screen reader reads the party before the subject", () => {
    // The party cell is the first thing in the row after the icon, so it is first in the
    // accessibility tree too. Asserted on document order rather than on a label, because that is
    // what a screen reader actually follows.
    loaded([entry({ id: "t1", party: "title", summary: "Title commitment request" })]);
    render(<TimelinePanel fileId="LF-JR4T" />, { wrapper });

    const row = screen.getByText("Title commitment request").closest("li");
    expect(row).not.toBeNull();
    const text = row?.textContent ?? "";
    expect(text.indexOf("Title co.")).toBeGreaterThanOrEqual(0);
    expect(text.indexOf("Title co.")).toBeLessThan(text.indexOf("Title commitment request"));
  });

  it("still gives a row with no party a cell, rather than shifting the column", () => {
    // An inbound message from an address nobody on the file recognises belongs to no party (LP-841
    // decided that deliberately). Dropping its cell would slide its subject into the party column
    // and break the alignment the column exists for.
    loaded([entry({ id: "x1", party: null, summary: "A message arrived" })]);
    render(<TimelinePanel fileId="LF-JR4T" />, { wrapper });

    expect(screen.getByText("—")).toBeTruthy();
  });

  it("renders a party the vocabulary does not know as itself", () => {
    // LP-841's rule, kept: a party we have no word for is still a party the processor must be told
    // about. Rendering nothing would be the invisibility this ticket is about, with a new cause.
    loaded([entry({ id: "z1", party: "escrow", summary: "Something" })]);
    render(<TimelinePanel fileId="LF-JR4T" />, { wrapper });

    expect(screen.getByText("escrow")).toBeTruthy();
  });
});

describe("what is inside a draft, without opening it", () => {
  it("names the documents and counts them", () => {
    // Four rows reading "A document request is being prepared", identical but for a timestamp, is
    // the screenshot that started this ticket.
    loaded([
      {
        ...MESSAGE,
        id: "d1",
        direction: "outbound",
        status: "draft",
        documents: ["Bank statement — March", "Pay stub"],
      },
    ]);
    render(<TimelinePanel fileId="LF-JR4T" />, { wrapper });

    expect(screen.getByText(/2 documents · Bank statement — March, Pay stub/)).toBeTruthy();
  });

  it("caps a long list rather than printing nine lines of prose", () => {
    loaded([
      {
        ...MESSAGE,
        id: "d1",
        direction: "outbound",
        status: "draft",
        documents: ["A", "B", "C", "D", "E"],
      },
    ]);
    render(<TimelinePanel fileId="LF-JR4T" />, { wrapper });

    expect(screen.getByText(/5 documents · A, B, C and 2 more/)).toBeTruthy();
  });

  it("says nothing about documents on a row that has none", () => {
    // THE CONTROL. An inbound message asks for nothing, and a row that said "0 documents" would be
    // noise on every one of them.
    loaded([{ ...MESSAGE, id: "m1", documents: [] }]);
    render(<TimelinePanel fileId="LF-JR4T" />, { wrapper });

    expect(screen.queryByText(/document/)).toBeNull();
  });
});

/**
 * LP-852 — "SINCE YOU LAST LOOKED", not "unread".
 *
 * Nothing is received in this version, so "unread" would be a claim about somebody ELSE's
 * behaviour — whether a borrower opened a message. The dot is a claim about THIS processor: a draft
 * appeared while they were not looking, and a draft they never learn about is never sent.
 */
describe("the since-you-last-looked dot", () => {
  const KEY = "mbai:comm-last-seen:LF-JR4T";

  /**
   * A REAL `localStorage`, INSTALLED HERE AND NOWHERE ELSE.
   *
   * This project's jsdom provides `window.localStorage` as a plain object with NO METHODS — calling
   * `getItem` on it throws `TypeError`. That is why `last-seen.ts` guards every access, and it is
   * also why the other tests in this file exercise the unavailable path for free: leaving the
   * global environment alone keeps that true. A shim in `vitest.setup.ts` would quietly remove a
   * condition the product has to survive.
   */
  let store: Map<string, string>;
  beforeEach(() => {
    store = new Map();
    Object.defineProperty(window, "localStorage", {
      configurable: true,
      value: {
        getItem: (key: string) => store.get(key) ?? null,
        setItem: (key: string, value: string) => void store.set(key, value),
        removeItem: (key: string) => void store.delete(key),
        clear: () => store.clear(),
      },
    });
  });
  afterEach(() => {
    Object.defineProperty(window, "localStorage", { configurable: true, value: {} });
  });

  function draftRow(over: Partial<TimelineEntry> = {}): TimelineEntry {
    return {
      ...MESSAGE,
      id: "d1",
      direction: "outbound",
      status: "draft",
      summary: "Documents we need",
      party: "title",
      ...over,
    };
  }

  it("ACCEPTANCE 3 — marks a draft created since the last visit", () => {
    // "Created by another session" is, from this browser's point of view, exactly "created after
    // the last time this page recorded that it was open".
    window.localStorage.setItem(KEY, new Date(Date.now() - 7200 * 1000).toISOString());
    loaded([draftRow({ created_at: new Date(Date.now() - 60 * 1000).toISOString() })]);

    render(<TimelinePanel fileId="LF-JR4T" />, { wrapper });

    expect(screen.getByLabelText("New since you last looked")).toBeTruthy();
  });

  it("and clears it when the row is opened", () => {
    window.localStorage.setItem(KEY, new Date(Date.now() - 7200 * 1000).toISOString());
    loaded([draftRow({ created_at: new Date(Date.now() - 60 * 1000).toISOString() })]);
    render(<TimelinePanel fileId="LF-JR4T" />, { wrapper });

    fireEvent.click(screen.getByRole("button", { name: /Documents we need/ }));

    expect(screen.queryByLabelText("New since you last looked")).toBeNull();
  });

  it("does NOT mark a draft that predates the last visit", () => {
    // THE CONTROL. A dot on every row is a dot that means nothing, and it would be indistinguishable
    // from a working one in the test above.
    window.localStorage.setItem(KEY, new Date(Date.now() - 60 * 1000).toISOString());
    loaded([draftRow({ created_at: new Date(Date.now() - 7200 * 1000).toISOString() })]);

    render(<TimelinePanel fileId="LF-JR4T" />, { wrapper });

    expect(screen.queryByLabelText("New since you last looked")).toBeNull();
  });

  it("marks nothing on a first visit", () => {
    // No stored timestamp. Ten dots saying "all of this is new to you" is true, useless, and it
    // teaches a processor that the dot means nothing.
    loaded([draftRow({ created_at: new Date().toISOString() })]);

    render(<TimelinePanel fileId="LF-JR4T" />, { wrapper });

    expect(screen.queryByLabelText("New since you last looked")).toBeNull();
  });

  it("records the visit, so the next one has something to compare against", () => {
    loaded([draftRow()]);
    render(<TimelinePanel fileId="LF-JR4T" />, { wrapper });

    expect(window.localStorage.getItem(KEY)).not.toBeNull();
  });

  it("renders when localStorage throws", () => {
    // It throws outright behind a few privacy settings, and in this project's jsdom it throws by
    // default. A drafts list that failed to render because a decoration could not be stored would
    // be a far worse outcome than no decoration.
    Object.defineProperty(window, "localStorage", {
      configurable: true,
      value: {
        getItem: () => {
          throw new Error("denied");
        },
        setItem: () => {
          throw new Error("denied");
        },
      },
    });

    loaded([draftRow()]);
    render(<TimelinePanel fileId="LF-JR4T" />, { wrapper });

    expect(screen.getByText("Documents we need")).toBeTruthy();
    expect(screen.queryByLabelText("New since you last looked")).toBeNull();
  });
});
