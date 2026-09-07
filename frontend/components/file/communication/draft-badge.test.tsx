// @vitest-environment jsdom
/**
 * LP-826 — the persistent half of "a draft was created".
 *
 * The count is DERIVED from the draft's contents, never from counting clicks: a click counter
 * drifts the moment somebody removes a line from the email, and would keep claiming the draft holds
 * something it does not.
 */
import { DraftBadge } from "@/components/file/communication/draft-badge";
import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

const mockUseOutboundDraft = vi.fn();
vi.mock("@/lib/api/communications", () => ({
  useOutboundDraft: (...args: unknown[]) => mockUseOutboundDraft(...args),
}));

afterEach(cleanup);

describe("DraftBadge", () => {
  it("says how many documents the draft holds", () => {
    mockUseOutboundDraft.mockReturnValue({ data: { needs_item_count: 3 } });
    render(<DraftBadge fileId="LF-JR4T" />);

    expect(screen.getByText("3 documents in the draft")).toBeTruthy();
  });

  it("reads as English for one", () => {
    mockUseOutboundDraft.mockReturnValue({ data: { needs_item_count: 1 } });
    render(<DraftBadge fileId="LF-JR4T" />);

    expect(screen.getByText("1 document in the draft")).toBeTruthy();
  });

  it("renders nothing when the file has no draft", () => {
    // ABSENT RATHER THAN ZERO. `GET /outbound/draft` 404s with no open draft, which the hook
    // returns as null. "0 documents in the draft" would be a claim about an email that does not
    // exist — and it would sit on every file that has never requested anything.
    mockUseOutboundDraft.mockReturnValue({ data: null });
    const { container } = render(<DraftBadge fileId="LF-JR4T" />);

    expect(container.textContent).toBe("");
  });

  it("is a way to the draft, not just a number", () => {
    // A count nobody can act on is a decoration. The ticket asked for it to be reachable.
    mockUseOutboundDraft.mockReturnValue({ data: { needs_item_count: 2 } });
    render(<DraftBadge fileId="LF-JR4T" />);

    expect(screen.getByRole("link").getAttribute("href")).toBe("/loan-files/LF-JR4T/communication");
  });
});
