// @vitest-environment jsdom
/**
 * LP-837 — how many drafts are waiting, wherever a processor is standing.
 *
 * The two things that fail quietly: a count that is present when there is nothing to count, and a
 * link that navigates to the page without opening the draft — which looks exactly like a mis-click
 * rather than like a broken feature.
 */
import { DraftsIndicator } from "@/components/file/communication/drafts-indicator";
import type { TimelineEntry } from "@/lib/types/timeline";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const mockTimeline = vi.fn();
vi.mock("@/lib/api/timeline", () => ({
  useTimeline: (...args: unknown[]) => mockTimeline(...args),
}));

afterEach(cleanup);
beforeEach(() => vi.clearAllMocks());

function draft(over: Partial<TimelineEntry> = {}): TimelineEntry {
  return {
    id: "d1",
    kind: "message",
    at: new Date(Date.now() - 3600 * 1000).toISOString(),
    summary: "A document request",
    direction: "outbound",
    status: "draft",
    subject: "Documents we need",
    counterparty: null,
    actor_user_id: null,
    attachments: [],
    is_important: false,
    unread: false,
    party: "borrower",
    detail: {},
    ...over,
  };
}

function loaded(entries: TimelineEntry[], { truncated = false } = {}) {
  mockTimeline.mockReturnValue({
    data: { entries, inbox_address: "lf-t@imbox.example.test", truncated },
    isPending: false,
    isError: false,
  });
}

// `user-event` is not a dependency here, and adding one to open a menu would be a heavier answer
// than the question. Radix opens on a real pointer-down/up pair; `fireEvent.click` alone does not
// reach it, which is why this is spelled out rather than a one-liner.
async function openMenu() {
  const trigger = screen.getByRole("button");
  fireEvent.pointerDown(trigger, { button: 0, ctrlKey: false, pointerType: "mouse" });
  fireEvent.pointerUp(trigger, { button: 0, pointerType: "mouse" });
  fireEvent.click(trigger);
  await waitFor(() => expect(screen.queryByRole("menu")).not.toBeNull());
}

describe("DraftsIndicator", () => {
  it("asks the server for drafts rather than filtering here", () => {
    // LP-812 put the filter on the server so one word has one definition. Deciding again on the
    // client is how the header and the mailbox start disagreeing about what a file contains.
    loaded([draft()]);
    render(<DraftsIndicator fileId="LF-JR4T" />);

    expect(mockTimeline).toHaveBeenCalledWith("LF-JR4T", "drafts");
  });

  it("shows the count", () => {
    loaded([draft({ id: "a" }), draft({ id: "b" }), draft({ id: "c" })]);
    render(<DraftsIndicator fileId="LF-JR4T" />);

    expect(screen.getByRole("button", { name: "3 drafts on this file" })).toBeTruthy();
  });

  it("is absent, not zero, when the file has no drafts", () => {
    // A "0" badge is a permanent decoration on every file that has never requested anything.
    loaded([]);
    const { container } = render(<DraftsIndicator fileId="LF-JR4T" />);

    expect(container.textContent).toBe("");
  });

  it("renders nothing while the count is unknown", () => {
    // THE CONTROL on the absence above: a badge that appeared before its data would flash a wrong
    // number, and one that never appeared would satisfy the empty case forever.
    mockTimeline.mockReturnValue({ data: undefined, isPending: true, isError: false });
    const { container } = render(<DraftsIndicator fileId="LF-JR4T" />);

    expect(container.textContent).toBe("");
  });
});

describe("the menu", () => {
  it("links each draft so the page opens it", async () => {
    // THE HALF THAT FAILS QUIETLY. Navigating is visible; opening the modal on arrival is a second
    // thing, and if it is missed a processor lands on a list and assumes they mis-clicked. The
    // `?draft` parameter is what LP-831 built the panel to read.
    loaded([draft({ id: "d-42", subject: "Documents we need" })]);
    render(<DraftsIndicator fileId="LF-JR4T" />);
    await openMenu();

    expect(screen.getByRole("menuitem").getAttribute("href")).toBe(
      "/loan-files/LF-JR4T/communication?draft=d-42",
    );
  });

  it("shows at most five, with a way to the rest", async () => {
    loaded(Array.from({ length: 7 }, (_, index) => draft({ id: `d${index}` })));
    render(<DraftsIndicator fileId="LF-JR4T" />);
    await openMenu();

    // Six links: five drafts and the overflow.
    expect(screen.getAllByRole("menuitem")).toHaveLength(5);
    expect(screen.getByText("See all 7 drafts")).toBeTruthy();
  });

  it("offers no overflow when everything fits", async () => {
    // A "see more" leading to the same rows is the LP-825 pill again: a control that always says
    // nothing.
    loaded([draft({ id: "a" }), draft({ id: "b" })]);
    render(<DraftsIndicator fileId="LF-JR4T" />);
    await openMenu();

    expect(screen.queryByText(/See all/)).toBeNull();
  });

  it("says when each draft was made", async () => {
    // LP-838's requirement, which moved into this ticket because the surface did not exist yet. The
    // guard in `message-time.test.ts` scans this file, so a local format fails before review does.
    loaded([draft({ id: "a" })]);
    render(<DraftsIndicator fileId="LF-JR4T" />);
    await openMenu();

    expect(screen.getByText(/^Created .*ago$/)).toBeTruthy();
  });
});

/**
 * LP-837 REVIEW — THE COUNT CAN BE A PAGE RATHER THAN A TOTAL.
 *
 * `build_timeline` takes `limit: int = 200` and returns `matched[:limit], len(matched) > limit`, so
 * `entries.length` is capped. `TimelinePublic.truncated` says when that happened, the client type
 * declares it, and `timeline-panel.tsx` — the component beside this one, reading the same query —
 * already renders it. This one read the length and said "See all 200 drafts": a number that looks
 * like a total and is a limit, which is the silent truncation LP-812 refused.
 */
describe("DraftsIndicator — a capped count does not claim to be a total", () => {
  const many = Array.from({ length: 200 }, (_, i) => draft({ id: `d-${i}` }));

  it("marks the badge and the accessible name as a floor", () => {
    loaded(many, { truncated: true });
    render(<DraftsIndicator fileId="LF-JR4T" />);

    const trigger = screen.getByRole("button", { name: /at least 200 drafts on this file/i });
    expect(trigger.textContent).toContain("200+");
  });

  it("drops the number from the overflow link when it would be a limit", async () => {
    loaded(many, { truncated: true });
    render(<DraftsIndicator fileId="LF-JR4T" />);
    await openMenu();

    expect(screen.getByRole("link", { name: "See all drafts" })).toBeTruthy();
    expect(screen.queryByRole("link", { name: /See all 200 drafts/ })).toBeNull();
  });

  it("still states the exact total when nothing was capped", async () => {
    // THE CONTROL. A component that never printed a number would satisfy both cases above, and the
    // ordinary file — which is every file today — is the one that must read exactly.
    loaded([draft({ id: "a" }), draft({ id: "b" })], { truncated: false });
    render(<DraftsIndicator fileId="LF-JR4T" />);

    const trigger = screen.getByRole("button", { name: "2 drafts on this file" });
    expect(trigger.textContent).toContain("2");
    expect(trigger.textContent).not.toContain("+");
  });
});
