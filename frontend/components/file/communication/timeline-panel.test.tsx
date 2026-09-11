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
import { afterEach, describe, expect, it, vi } from "vitest";

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
vi.mock("@/lib/api/communications", () => ({
  useMessageDetail: (...args: unknown[]) => {
    mockMessageDetailArgs.push(args);
    return mockMessageDetail();
  },
  useSendDraft: () => ({ mutate: vi.fn(), isPending: false, isError: false }),
  // LP-834 — the dialog offers a secure link now. These cases are about the LIST; the dialog has
  // its own file.
  useAttachUploadLink: () => ({ mutate: vi.fn(), isPending: false, isError: false }),
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
    expect(screen.getByText("Nothing has happened yet")).toBeDefined();
  });

  it("says the FILTER hides it when one is on", () => {
    // Telling a processor who filtered to Drafts that nothing has ever happened is false, and sends
    // them to look for a bug rather than to clear the filter.
    loaded([]);
    render(<TimelinePanel fileId="f1" />, { wrapper });

    fireEvent.click(screen.getByRole("tab", { name: "Drafts" }));

    expect(screen.getByText("Nothing in drafts")).toBeDefined();
    expect(screen.queryByText("Nothing has happened yet")).toBeNull();
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
  it("labels a draft Created and a sent message Sent", () => {
    // A BARE TIMESTAMP IS AMBIGUOUS IN EXACTLY THE WAY THAT MATTERS. Both rows below show the same
    // kind of value; only the label says whether the borrower has heard from us.
    loaded([
      {
        ...MESSAGE,
        id: "d1",
        direction: "outbound",
        status: "draft",
        summary: "Documents we need",
      },
      { ...MESSAGE, id: "s1", direction: "outbound", status: "sent", summary: "Documents we sent" },
    ]);

    render(<TimelinePanel fileId="LF-JR4T" />, { wrapper });

    expect(screen.getByText(/^Created /)).toBeTruthy();
    expect(screen.getByText(/^Sent /)).toBeTruthy();
  });

  it("shows a time on every row", () => {
    // THE CONTROL on the label: a panel that rendered the word and dropped the time would satisfy
    // the assertions above and tell a processor nothing they came for.
    loaded([{ ...MESSAGE, id: "d1", direction: "outbound", status: "draft" }]);

    render(<TimelinePanel fileId="LF-JR4T" />, { wrapper });

    expect(screen.getByText(/^Created .*ago$/)).toBeTruthy();
  });
});

/**
 * LP-841 — THE PARTY TABS.
 *
 * The reported shape was a request that reached nobody. Routing it to the right party's draft fixes
 * the backend half; a draft in a bucket with no tab is the same invisibility with a different cause,
 * so these assert that what exists is reachable.
 */
describe("the party tabs", () => {
  function entry(over: Partial<TimelineEntry>): TimelineEntry {
    return { ...MESSAGE, ...over };
  }

  it("shows a tab per party on the file and filters the list to it", async () => {
    loaded([
      entry({ id: "b1", party: "borrower", summary: "Documents we need" }),
      entry({ id: "l1", party: "lender", summary: "Credit report request" }),
    ]);
    render(<TimelinePanel fileId="LF-JR4T" />, { wrapper });

    const lender = await screen.findByRole("tab", { name: /Lender/ });
    expect(screen.getByRole("tab", { name: /Borrower/ })).toBeTruthy();
    // Both rows are there before anyone clicks.
    expect(screen.getByText("Documents we need")).toBeTruthy();

    fireEvent.click(lender);

    expect(screen.getByText("Credit report request")).toBeTruthy();
    expect(screen.queryByText("Documents we need")).toBeNull();
  });

  it("offers no tab for a party this file has nothing with", async () => {
    loaded([entry({ id: "b1", party: "borrower" })]);
    render(<TimelinePanel fileId="LF-JR4T" />, { wrapper });
    await screen.findByText(MESSAGE.summary);
    // Five empty tabs on an ordinary purchase is the noise this derivation exists to avoid.
    expect(screen.queryByRole("tab", { name: /Accountant/ })).toBeNull();
  });

  it("reaches a party the ticket never named", async () => {
    // THE ONE THE FOUR-TAB READING WOULD HAVE HIDDEN. The request names borrower, employer, lender
    // and title; the catalog also routes to an accountant, an agent and an insurer. A draft those
    // produce must have a tab, or it exists where nobody can open it — the reported failure again.
    loaded([
      entry({ id: "b1", party: "borrower" }),
      entry({ id: "c1", party: "cpa", summary: "P&L request" }),
    ]);
    render(<TimelinePanel fileId="LF-JR4T" />, { wrapper });

    fireEvent.click(await screen.findByRole("tab", { name: /Accountant/ }));
    expect(screen.getByText("P&L request")).toBeTruthy();
  });

  it("does not tell a processor on a tab that outlived its messages that the file is new", async () => {
    // THE CASE THE PILL VERSION OF THIS TEST COULD NOT REACH. A selected tab is kept alive after
    // its last entry goes (sent, deleted, re-fetched away) so it does not vanish from under the
    // person standing on it — and that is the one state where the party tab alone empties the list
    // while the status pill is still All. Measured: asserting this through the pill instead passed
    // against a build with no party clause at all.
    loaded([
      entry({ id: "b1", party: "borrower" }),
      entry({ id: "l1", party: "lender", status: "draft" }),
    ]);
    const view = render(<TimelinePanel fileId="LF-JR4T" />, { wrapper });

    fireEvent.click(await screen.findByRole("tab", { name: /Lender/ }));
    loaded([entry({ id: "b1", party: "borrower" })]);
    view.rerender(<TimelinePanel fileId="LF-JR4T" />);

    expect(screen.queryByText(/Nothing has happened yet/)).toBeNull();
    expect(screen.getByText(/Nothing with the Lender/)).toBeTruthy();
  });

  it("hides the strip entirely when the file has one correspondent", async () => {
    loaded([entry({ id: "b1", party: "borrower" })]);
    render(<TimelinePanel fileId="LF-JR4T" />, { wrapper });
    await screen.findByText(MESSAGE.summary);
    expect(screen.queryByRole("tab", { name: "Everyone" })).toBeNull();
  });
});
