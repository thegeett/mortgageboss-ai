// @vitest-environment jsdom
/**
 * LP-858 §2 / §2.1 — the two panes, and what is selected on load.
 *
 * WHAT THIS FILE IS ABOUT is the SPLIT and the SELECTION: which of the three landing states renders,
 * and which draft the right pane opens on. The rail's rows are `timeline-panel.test.tsx`; what the
 * pane does once open is `message-dialog*.test.tsx`. The page decides which, and that decision had
 * no home before this ticket because there was no page-level state — a modal opened from a row.
 *
 * LP-857's cases (two buttons, panels behind the capability) are here too, adapted: the buttons
 * moved into the rail's header and the empty state now has its own copy of them.
 */
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const mockCapabilities = vi.fn(() => ({ data: { receiving: false, polish: false } }));
const mockTimeline = vi.fn();
const mockCompose = vi.fn();
const mockSearchParams = vi.fn(() => new URLSearchParams());
/** Every `(fileId, messageId)` the right pane was asked for, newest last. */
const paneArgs: (string | null)[][] = [];

vi.mock("@/lib/api/capabilities", () => ({ useCapabilities: () => mockCapabilities() }));
vi.mock("@/lib/api/timeline", () => ({ useTimeline: () => mockTimeline() }));
vi.mock("@/lib/api/messages", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/lib/api/messages")>()),
  useComposeDraft: () => ({ mutate: mockCompose, isPending: false }),
}));
vi.mock("@/lib/toast", () => ({ notifySuccess: vi.fn(), notifyError: vi.fn() }));
vi.mock("next/navigation", () => ({
  useParams: () => ({ id: "LF-JR4T" }),
  useSearchParams: () => mockSearchParams(),
}));

vi.mock("@/components/file/communication/upload-link-panel", () => ({
  UploadLinkPanel: () => <div data-testid="upload-link" />,
}));
vi.mock("@/components/file/communication/inbound-messages-panel", () => ({
  InboundMessagesPanel: () => <div data-testid="inbound" />,
}));
vi.mock("@/components/file/communication/compose-request-button", () => ({
  ComposeRequestButton: () => <button type="button">Request documents</button>,
}));
// THE RAIL, STUBBED TO WHAT THE PAGE ACTUALLY TALKS TO: it reports a selection and is told which
// row is current. Its rows are covered in its own suite.
vi.mock("@/components/file/communication/timeline-panel", () => ({
  TimelinePanel: ({
    selectedId,
    onSelect,
    actions,
  }: {
    selectedId: string | null;
    onSelect: (id: string) => void;
    actions?: React.ReactNode;
  }) => (
    <div data-testid="rail" data-selected={selectedId ?? ""}>
      {/* LP-859 §5.6 — the buttons render INSIDE the rail's header now, passed as `actions`. A stub
          that dropped them would make the page's own "exactly two ways to start a message" test
          pass by rendering neither. */}
      {actions}
      <button type="button" onClick={() => onSelect("m-other")}>
        select-other
      </button>
    </div>
  ),
}));
vi.mock("@/components/file/communication/message-dialog", () => ({
  DraftPane: ({
    fileId,
    messageId,
    onClose,
    onDeleted,
  }: {
    fileId: string;
    messageId: string | null;
    onClose: () => void;
    onDeleted?: (id: string) => void;
  }) => {
    paneArgs.push([fileId, messageId]);
    return (
      <div data-testid="pane" data-message={messageId ?? ""}>
        <button type="button" onClick={onClose}>
          close-pane
        </button>
        <button type="button" onClick={() => onDeleted?.(messageId ?? "")}>
          delete-pane
        </button>
      </div>
    );
  },
}));

import CommunicationPage from "./page";

afterEach(cleanup);
beforeEach(() => {
  vi.clearAllMocks();
  paneArgs.length = 0;
  mockSearchParams.mockReturnValue(new URLSearchParams());
  // Back to the jsdom default — absent — which is the wide case and what the page treats as
  // "not narrow".
  Object.defineProperty(window, "matchMedia", { configurable: true, value: undefined });
});

type Row = {
  id: string;
  kind?: string;
  direction?: string;
  status?: string;
  created_at?: string;
};

function entries(rows: Row[]) {
  mockTimeline.mockReturnValue({
    data: {
      entries: rows.map((row) => ({
        kind: "message",
        direction: "outbound",
        status: "draft",
        created_at: "2026-09-13T09:00:00Z",
        ...row,
      })),
      unread_count: 0,
      inbox_address: "lf@imbox.example.test",
    },
    isPending: false,
    isError: false,
  });
}

const selectedMessage = () => screen.queryByTestId("pane")?.getAttribute("data-message") ?? null;

/**
 * Put the page below the ~720px breakpoint.
 *
 * jsdom HAS NO `matchMedia` AT ALL, which is why the page guards for it — and it is why this is a
 * define rather than a spy: there is nothing to spy on. Cleared in `beforeEach` rather than at the
 * end of each case, so a failing assertion cannot leave the next test on a narrow screen.
 */
function stackPanes() {
  Object.defineProperty(window, "matchMedia", {
    configurable: true,
    value: (query: string) => ({ matches: query.includes("720px"), media: query }),
  });
}

describe("the landing state", () => {
  it("selects the newest open draft on load", () => {
    // §2.1 rule 2. The right pane is never a dead panel on a file that has work outstanding.
    //
    // NEWEST IS FIRST, because the timeline is served newest-first — asserted by giving the fixture
    // two drafts, so "the newest" and "the only one" cannot be confused.
    entries([{ id: "d-new" }, { id: "d-old" }]);
    render(<CommunicationPage />);

    expect(selectedMessage()).toBe("d-new");
    // AND THE RAIL IS TOLD, so the list marks the row the pane is showing.
    expect(screen.getByTestId("rail").getAttribute("data-selected")).toBe("d-new");
  });

  it("never auto-selects a sent message", () => {
    // §2.1 rule 3. A read-only record is not what the processor came for, and when receiving
    // returns it would mark inbound mail read that nobody looked at.
    entries([{ id: "s-1", status: "sent" }, { id: "d-1" }]);
    render(<CommunicationPage />);

    expect(selectedMessage()).toBe("d-1");
  });

  it("a file with only sent messages selects nothing and shows the empty state", () => {
    // §2.1 rule 4's second half — THE SPLIT STILL RENDERS. History is worth seeing; the pane
    // carries the empty state inside it.
    entries([
      { id: "s-1", status: "sent" },
      { id: "s-2", status: "sent" },
    ]);
    render(<CommunicationPage />);

    expect(screen.queryByTestId("pane")).toBeNull();
    expect(screen.getByTestId("rail")).toBeTruthy();
    expect(screen.getByText("No drafts on this file")).toBeTruthy();
  });

  it("a file with no drafts renders one full-width empty state and no list rail", () => {
    // §2.1 rule 4's first half, and the distinction from the case above: an EMPTY file is not worth
    // a rail. A 300px column of nothing beside a larger area of nothing is two pieces of furniture
    // for a file with no work on it.
    entries([]);
    render(<CommunicationPage />);

    expect(screen.queryByTestId("rail")).toBeNull();
    expect(screen.queryByTestId("pane")).toBeNull();
    expect(screen.getByText("No drafts on this file")).toBeTruthy();
    // AND IT OFFERS BOTH WAYS OUT, which is what makes it an empty STATE rather than a message.
    expect(screen.getByRole("button", { name: "Request documents" })).toBeTruthy();
    expect(screen.getByRole("button", { name: "+ Compose" })).toBeTruthy();
  });

  it("selects nothing when the panes are stacked", () => {
    // §2.1 rule 5. Below ~720px the panes are vertical, so auto-selecting pushes the list
    // off-screen and hides the thing that orients the processor. The list IS the screen there.
    stackPanes();
    entries([{ id: "d-new" }]);
    render(<CommunicationPage />);

    expect(screen.queryByTestId("pane")).toBeNull();
    // THE LIST IS STILL THERE — this is "nothing selected", not "nothing rendered".
    expect(screen.getByTestId("rail")).toBeTruthy();
  });

  it("a tap still opens a draft when the panes are stacked", () => {
    // THE CONTROL on the case above, and the behaviour rule 5 actually describes: "tapping a row
    // opens the draft". Without this, "selects nothing" also passes on a build where the pane can
    // never be opened on a narrow screen at all.
    stackPanes();
    entries([{ id: "d-new" }, { id: "m-other" }]);
    render(<CommunicationPage />);
    expect(screen.queryByTestId("pane")).toBeNull();

    fireEvent.click(screen.getByRole("button", { name: "select-other" }));

    expect(selectedMessage()).toBe("m-other");
  });

  it("a draft id in the url beats the default selection", () => {
    // §2.1 rule 1. Selection is URL-driven so a toast can link straight to a draft and a reload
    // keeps the same one open. The fixture's newest draft is a DIFFERENT row, so this cannot pass
    // by agreeing with the default.
    mockSearchParams.mockReturnValue(new URLSearchParams("draft=d-old"));
    entries([{ id: "d-new" }, { id: "d-old" }]);
    render(<CommunicationPage />);

    expect(selectedMessage()).toBe("d-old");
  });

  it("stays closed after the processor closes the linked draft", () => {
    // LP-831's defect, carried over with the deep link. The URL parameter is tracked separately
    // from the selection on purpose: compared against the selection instead, closing would set it
    // to null, the parameter would still say d-old, and the next render would re-open it — a pane
    // that cannot be dismissed while the link is in the address bar.
    mockSearchParams.mockReturnValue(new URLSearchParams("draft=d-old"));
    entries([{ id: "d-new" }, { id: "d-old" }]);
    const { rerender } = render(<CommunicationPage />);
    expect(selectedMessage()).toBe("d-old");

    fireEvent.click(screen.getByRole("button", { name: "close-pane" }));
    expect(screen.queryByTestId("pane")).toBeNull();

    // AND IT STAYS SHUT. The re-open would happen on the NEXT render, not on the close itself, so
    // asserting only the line above would pass on the broken version — and here the auto-selection
    // is a second thing that would re-open it.
    rerender(<CommunicationPage />);
    expect(screen.queryByTestId("pane")).toBeNull();
  });

  it("selects the next newest open draft after deleting the selected one", () => {
    // §2.1 rule 6 — NEVER LEAVE THE PANE SHOWING A DELETED ROW.
    //
    // The refetch is not instant: for the frame between the 204 and the new list arriving, the
    // deleted row is still in `entries`, so "select the next newest" would land straight back on
    // it. The fixture is deliberately unchanged here — the page must skip the deleted id rather
    // than wait for the server to stop reporting it.
    entries([{ id: "d-new" }, { id: "d-old" }]);
    render(<CommunicationPage />);
    expect(selectedMessage()).toBe("d-new");

    fireEvent.click(screen.getByRole("button", { name: "delete-pane" }));

    expect(selectedMessage()).toBe("d-old");
  });

  it("falls to the empty state when the last draft is deleted", () => {
    // Rule 6's other half. The pane must not show the row that just went, and there is nothing
    // else to show — so the empty state, inside the split, because the history is still there.
    entries([{ id: "d-only" }, { id: "s-1", status: "sent" }]);
    render(<CommunicationPage />);
    expect(selectedMessage()).toBe("d-only");

    fireEvent.click(screen.getByRole("button", { name: "delete-pane" }));

    expect(screen.queryByTestId("pane")).toBeNull();
    expect(screen.getByTestId("rail")).toBeTruthy();
    expect(screen.getByText("No drafts on this file")).toBeTruthy();
  });

  it("a deleted draft is not re-selected on the next render", () => {
    // THE STICKING HALF, and the same shape as the linked-draft case: the re-select would happen on
    // the NEXT render rather than on the delete, so asserting only the line above would pass on a
    // build where the pane reopens the row a moment later.
    entries([{ id: "d-only" }]);
    const { rerender } = render(<CommunicationPage />);
    fireEvent.click(screen.getByRole("button", { name: "delete-pane" }));

    rerender(<CommunicationPage />);

    expect(screen.queryByTestId("pane")).toBeNull();
  });

  it("a url pointing at a draft deleted this session falls to the next one", () => {
    // THE CASE THAT MAKES THE DELETED-ID GUARD LOAD-BEARING, and it was found by mutation: in the
    // ordinary flow `onDeleted` clears the selection, so nothing ever consults the set and removing
    // the check left every test green.
    //
    // It separates when the URL puts a deleted id BACK — the browser Back button after a delete,
    // which is one keystroke away. Without the guard the pane renders "This message could not be
    // loaded" for a row the processor deleted a moment ago on purpose; with it, they land on the
    // next draft, which is where they were going anyway.
    entries([{ id: "d-new" }, { id: "d-old" }]);
    const { rerender } = render(<CommunicationPage />);
    fireEvent.click(screen.getByRole("button", { name: "select-other" }));
    fireEvent.click(screen.getByRole("button", { name: "delete-pane" }));

    // Back: the address bar names the row that has just gone.
    mockSearchParams.mockReturnValue(new URLSearchParams("draft=m-other"));
    rerender(<CommunicationPage />);

    expect(selectedMessage()).not.toBe("m-other");
    expect(selectedMessage()).toBe("d-new");
  });

  it("a closed pane says no draft is selected, not that the file has none", () => {
    // LP-859 §4 — the screen contradicted itself. Screenshot `04-empty-state-over-a-full-rail.png`:
    // a rail listing four drafts and a sent message, beside a pane reading "No drafts on this
    // file". The half that was wrong had the larger type.
    //
    // One empty state was doing two jobs. Closing sets `closed`, `autoSelected` goes null for the
    // rest of the mount — correct and deliberate, the pane must stay dismissed — and what rendered
    // in its place was a sentence about a file with no drafts.
    entries([{ id: "d-new" }, { id: "d-old" }]);
    render(<CommunicationPage />);
    expect(selectedMessage()).toBe("d-new");

    fireEvent.click(screen.getByRole("button", { name: "close-pane" }));

    expect(screen.getByText("No draft selected")).toBeTruthy();
    // THE SENTENCE THAT WAS FALSE. Absent, and the rail that made it false is still there — a test
    // asserting only the new words would pass on a build that had emptied the list instead.
    expect(screen.queryByText("No drafts on this file")).toBeNull();
    expect(screen.getByTestId("rail")).toBeTruthy();
  });

  it("a file with only sent messages still says the file has no drafts", () => {
    // THE CASE THAT MUST NOT CHANGE, and the control on the case above: with no open drafts the old
    // words are TRUE, and a build that replaced them everywhere would pass the test above while
    // telling a processor to pick from a list that has nothing to pick.
    entries([
      { id: "s-1", status: "sent" },
      { id: "s-2", status: "sent" },
    ]);
    render(<CommunicationPage />);

    expect(screen.getByText("No drafts on this file")).toBeTruthy();
    expect(screen.queryByText("No draft selected")).toBeNull();
  });

  it("says the file has no drafts when the last one is deleted", () => {
    // THE TWO EMPTY STATES MEET HERE. Delete the only draft and the file has none left, so the old
    // words are the true ones — even though the pane also became empty by an action.
    //
    // LP-859 REVIEW — RENAMED. This was called "…only if others remain" and never exercised the
    // "others remain" half; its body is the no-others case alone. A name that claims a case the
    // body does not run is worse than no test for it, because the next reader stops looking. The
    // half it promised is the test below.
    entries([{ id: "d-only" }, { id: "s-1", status: "sent" }]);
    render(<CommunicationPage />);

    fireEvent.click(screen.getByRole("button", { name: "delete-pane" }));

    expect(screen.getByText("No drafts on this file")).toBeTruthy();
    expect(screen.queryByText("No draft selected")).toBeNull();
  });

  it("re-selects another draft when one is deleted and others remain", () => {
    // THE HALF THE NAME ABOVE USED TO CLAIM. Deleting a draft while others are live is not an empty
    // state at all — rule 2 picks the next one — so NEITHER sentence should appear. A change that
    // showed "No draft selected" here would have left the old test green under a title saying it
    // was covered.
    entries([{ id: "d-new" }, { id: "d-old" }, { id: "s-1", status: "sent" }]);
    render(<CommunicationPage />);

    fireEvent.click(screen.getByRole("button", { name: "delete-pane" }));

    expect(screen.queryByText("No draft selected")).toBeNull();
    expect(screen.queryByText("No drafts on this file")).toBeNull();
    // AND THE PANE IS SHOWING ONE, which is what makes the two absences meaningful rather than
    // passing on a page that rendered nothing at all.
    expect(screen.getByTestId("pane")).toBeTruthy();
  });

  it("claims neither empty state while the timeline is still loading", () => {
    // LP-859 REVIEW — THE SENTENCE THIS SECTION REMOVES, ARRIVING BY THE ROUTE IT DID NOT LOOK AT.
    //
    // `isPending` gated only the full-width branch, so a file that HAS drafts fell through to the
    // split with `entries` empty and the pane rendered "No drafts on this file" for a frame, on
    // every visit. Measured before the fix: this assertion found that heading in the document.
    mockTimeline.mockReturnValue({ data: undefined, isPending: true });
    render(<CommunicationPage />);

    expect(screen.queryByText("No drafts on this file")).toBeNull();
    expect(screen.queryByText("No draft selected")).toBeNull();
    // THE CONTROL: something IS on screen, so the two absences are about the claims rather than
    // about a page that failed to render.
    expect(screen.getByText("Loading this file…")).toBeTruthy();
  });

  it("gives every right-pane state the pane's surface, loading included", () => {
    // LP-859 §5.7 REVIEW — §5.7 gave the two empty states a border and a radius so the right half
    // stops reading as a page that failed to render. The `isPending` branch sits between them in the
    // same ternary chain and was left as bare centred text — and it is the state a processor sees
    // FIRST on every visit, so the frame §5.7 exists to fix was the frame it missed.
    //
    // ALL THREE, NOT THE ONE THAT WAS WRONG. Two of three carrying a rule is how the third goes
    // unnoticed, so this asserts the class rather than the instance.
    const surfaced = (text: string) => {
      const node = screen.getByText(text).closest("div");
      // `rounded-lg` specifically: `--radius` (5px) is the CONTROL radius and `--radius-container`
      // (8px) is the one `globals.css` labels "cards, panels, tables". This is a panel, and §5.7
      // shipped it at the control step.
      expect(node?.className).toContain("rounded-lg");
      expect(node?.className).toContain("border");
      cleanup();
    };

    mockTimeline.mockReturnValue({ data: undefined, isPending: true });
    render(<CommunicationPage />);
    surfaced("Loading this file…");

    // Sent history, nothing open: the list arrived and really has no drafts.
    entries([{ id: "m-other", status: "sent" }]);
    render(<CommunicationPage />);
    surfaced("No drafts on this file");

    // A draft exists but the pane was closed.
    entries([{ id: "d-new" }]);
    render(<CommunicationPage />);
    fireEvent.click(screen.getByRole("button", { name: "close-pane" }));
    surfaced("No draft selected");
  });

  it("leaves the rail 300px of content after its gutter", () => {
    // LP-859 §5 REVIEW — THE NUMBER §2's BUDGET IS SPENT AGAINST. Tailwind's preflight is
    // `box-sizing: border-box`, so §5.2's `md:pr-4` and `md:border-r` came out of the 300px the
    // contract promises rather than out of the space beside it: 283px of usable rail, on the one
    // line §2 had to stack because ~438px of fixed content did not fit in 300.
    //
    // DERIVED, NOT PINNED. Asserting the literal `md:w-[316px]` would pass on 316 with the padding
    // deleted, which is a different rail with the same class. This reads the three numbers out of
    // the className and checks the subtraction, so changing any one of them alone fails.
    entries([{ id: "d-new" }]);
    const { container } = render(<CommunicationPage />);

    const rail = container.querySelector<HTMLElement>('[class*="md:w-["]');
    expect(rail).not.toBeNull();
    const cls = rail?.className ?? "";
    const declared = Number(/md:w-\[(\d+)px\]/.exec(cls)?.[1]);
    const padding = Number(/md:pr-(\d+)/.exec(cls)?.[1]) * 4;
    const border = /md:border-r/.test(cls) ? 1 : 0;
    // THE CONTROL: all three were actually found. A failed match is NaN, and NaN arithmetic would
    // report "not 300" for a rail whose classes this test could not read at all.
    expect(Number.isFinite(declared)).toBe(true);
    expect(Number.isFinite(padding)).toBe(true);
    expect(declared - padding - border).toBe(300);
  });

  it("selecting a row swaps the pane and leaves the layout alone", () => {
    // §2 — "Selecting a row swaps the right pane's content and moves nothing." The rail is present
    // before and after, which is the half a list that collapsed on selection would fail.
    entries([{ id: "d-new" }, { id: "m-other" }]);
    render(<CommunicationPage />);
    expect(selectedMessage()).toBe("d-new");

    fireEvent.click(screen.getByRole("button", { name: "select-other" }));

    expect(selectedMessage()).toBe("m-other");
    expect(screen.getByTestId("rail")).toBeTruthy();
  });
});

describe("compose", () => {
  it("creates the row when Compose is pressed, and opens it", async () => {
    // §8 — the row is created on the PRESS, not on the first keystroke, and it appears in the list
    // immediately. The abandoned-empty-draft case is accepted knowingly; no sweep is built.
    entries([{ id: "d-new" }]);
    render(<CommunicationPage />);

    fireEvent.click(screen.getByRole("button", { name: "+ Compose" }));

    expect(mockCompose).toHaveBeenCalledTimes(1);
    // EMPTY. Nothing is defaulted — not a subject, not a recipient. A subject a system invented is
    // one a borrower cannot recognise.
    expect(mockCompose.mock.calls[0]?.[0]).toEqual({});

    // AND THE NEW ROW IS WHAT OPENS, not the draft that was already selected. `waitFor` because the
    // callback fires outside React's act() — the state update is real but has not flushed.
    const opts = mockCompose.mock.calls[0]?.[1] as { onSuccess: (d: { id: string }) => void };
    opts.onSuccess({ id: "d-fresh" });
    await waitFor(() => expect(selectedMessage()).toBe("d-fresh"));
  });
});

describe("what the version cannot do", () => {
  it("hides the upload link and inbound mail while the version cannot receive", () => {
    entries([{ id: "d-1" }]);
    render(<CommunicationPage />);

    expect(screen.queryByTestId("upload-link")).toBeNull();
    expect(screen.queryByTestId("inbound")).toBeNull();
    expect(screen.getByTestId("rail")).toBeTruthy();
  });

  it("shows them again when the version can receive", () => {
    // THE POSITIVE CONTROL for both absences above.
    mockCapabilities.mockReturnValue({ data: { receiving: true, polish: false } });
    entries([{ id: "d-1" }]);
    render(<CommunicationPage />);

    expect(screen.getByTestId("upload-link")).toBeTruthy();
    expect(screen.getByTestId("inbound")).toBeTruthy();
  });

  it("does not offer Write to another party", () => {
    // LP-857's one removal rather than flag. The module it opened is gone, so a re-import would
    // fail the build before this runs.
    entries([{ id: "d-1" }]);
    render(<CommunicationPage />);

    expect(screen.queryByText(/another party/i)).toBeNull();
  });

  it("offers exactly two ways to start a message", () => {
    // LP-857 acceptance 1, in its new home: the buttons moved into the rail's header when the page
    // became two panes. BY NAME AND BY COUNT — names alone pass with a third button beside them,
    // a count alone passes if one is swapped for something else.
    entries([{ id: "d-1" }]);
    render(<CommunicationPage />);

    const buttons = screen
      .getAllByRole("button")
      .map((b) => b.textContent)
      // The stub's own controls are not the page's buttons.
      .filter((label) => !["select-other", "close-pane", "delete-pane"].includes(label ?? ""));
    expect(buttons).toEqual(["Request documents", "+ Compose"]);
  });
});
