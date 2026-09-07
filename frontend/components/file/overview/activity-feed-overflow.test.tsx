// @vitest-environment jsdom
/**
 * LP-825 — Recent activity is now the file's whole non-message history.
 *
 * The Communication page used to carry every non-message activity: on LF-JR4T, ten of eleven recent
 * rows were document classifications, DTI overrides and field reviews. It no longer does, which
 * makes this feed the only place that history can be read — and it was capped at twenty with
 * nothing on screen saying so. A list that stops without a way past it is the same silent
 * truncation LP-812's review already fixed once, on the other panel.
 */
import { ActivityFeed } from "@/components/file/overview/activity-feed";
import type { ActivityPublic } from "@/lib/types/activity";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

afterEach(cleanup);

function entries(count: number): ActivityPublic[] {
  return Array.from({ length: count }, (_, index) => ({
    id: `a${index}`,
    activity_type: "document_processed",
    summary: `Classified document ${index}`,
    created_at: "2026-09-07T13:00:00Z",
    actor_user_id: null,
    detail: {},
  })) as unknown as ActivityPublic[];
}

describe("ActivityFeed — the way past the first page", () => {
  it("offers See more when the file has history past what is shown", () => {
    const onSeeMore = vi.fn();
    render(
      <ActivityFeed
        activity={entries(20)}
        isPending={false}
        isError={false}
        hasMore
        onSeeMore={onSeeMore}
      />,
    );

    fireEvent.click(screen.getByRole("button", { name: "See more" }));

    expect(onSeeMore).toHaveBeenCalledTimes(1);
  });

  it("does not offer it when there is nothing past the page", () => {
    // THE CONTROL. A "See more" that is always there tells a processor there is more history on a
    // file whose history they have already read in full — and clicking it changes nothing, which
    // reads as a broken button rather than as an empty result.
    render(
      <ActivityFeed activity={entries(3)} isPending={false} isError={false} onSeeMore={vi.fn()} />,
    );

    expect(screen.queryByRole("button", { name: "See more" })).toBeNull();
  });

  it("renders the rows it was given", () => {
    // The second control: a feed that rendered nothing would satisfy the absence assertion above
    // and show an empty card on a file with history.
    render(<ActivityFeed activity={entries(2)} isPending={false} isError={false} />);

    expect(screen.getByText("Classified document 0")).toBeTruthy();
    expect(screen.getByText("Classified document 1")).toBeTruthy();
  });
});
