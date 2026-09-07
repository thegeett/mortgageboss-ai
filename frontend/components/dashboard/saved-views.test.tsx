// @vitest-environment jsdom
/**
 * The component that consumes `view-url.ts`.
 *
 * `view-url.ts` had six tests and `SavedViews` had none, which is the wrong half
 * to cover: LP-UI-011's mutation showed a helper can stay green while the
 * component stops calling it. These assert on the rendered nav.
 */
import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

const views = vi.hoisted(() => ({
  data: undefined as unknown,
  isPending: false,
  isError: false,
}));
vi.mock("@/lib/api/saved-views", () => ({ useSavedViews: () => views }));
vi.mock("next/link", () => ({
  default: ({ href, children, ...rest }: { href: string; children: React.ReactNode }) => (
    <a href={href} {...rest}>
      {children}
    </a>
  ),
}));

import { SavedViews } from "./saved-views";

const view = (over: Partial<Record<string, unknown>> = {}) => ({
  id: "v1",
  name: "Blocked to submit",
  filters: { statuses: ["in_conditions"], search: "" },
  sort: "attention",
  is_shared: false,
  is_mine: true,
  count: 3,
  ...over,
});

afterEach(() => {
  cleanup();
  views.data = undefined;
  views.isPending = false;
  views.isError = false;
});

/** The link the nav marks as the current page. */
const current = () =>
  screen
    .queryAllByRole("link")
    .filter((a) => a.getAttribute("aria-current") === "page")
    .map((a) => a.textContent ?? "");

describe("SavedViews", () => {
  it("marks 'All files' current only when nothing is filtered", () => {
    views.data = [view()];
    render(<SavedViews activeViewId={null} filtered={false} />);
    expect(current().join()).toContain("All files");
  });

  it("does NOT mark 'All files' current on a hand-edited filter", () => {
    // The defect the ticket caught: a filter that matches no saved view is not
    // "All files", and saying so tells the reader they are looking at everything
    // when they are not.
    views.data = [view()];
    render(<SavedViews activeViewId={null} filtered />);
    expect(current()).toEqual([]);
  });

  it("marks the selected view, and only it", () => {
    views.data = [view(), view({ id: "v2", name: "Ready to submit" })];
    render(<SavedViews activeViewId="v2" filtered />);
    expect(current()).toHaveLength(1);
    expect(current()[0]).toContain("Ready to submit");
  });

  it("links to a URL that reproduces the view's filters", () => {
    // A view is a PLACE, not a button — the filter has to be in the href or it
    // cannot be pasted to a colleague, which is the whole premise of view-url.
    views.data = [view()];
    render(<SavedViews activeViewId={null} filtered={false} />);
    const link = screen.getByRole("link", { name: /blocked to submit/i });
    const href = link.getAttribute("href") ?? "";
    expect(href).toContain("status=in_conditions");
    expect(href).toContain("view=v1");
  });

  it("separates my views from shared ones", () => {
    views.data = [view(), view({ id: "v2", name: "Team triage", is_mine: false })];
    render(<SavedViews activeViewId={null} filtered={false} />);
    expect(screen.getByText("Saved views")).toBeDefined();
    expect(screen.getByText("Shared")).toBeDefined();
  });

  it("says views are unavailable rather than pretending there are none", () => {
    // "No saved views yet" on a failed request tells a processor their views
    // are gone. The two states are different facts and must read differently.
    views.isError = true;
    render(<SavedViews activeViewId={null} filtered={false} />);
    expect(screen.getByText(/unavailable/i)).toBeDefined();
    expect(screen.queryByText(/no saved views yet/i)).toBeNull();
  });

  it("keeps 'All files' reachable while the list is loading", () => {
    views.isPending = true;
    render(<SavedViews activeViewId={null} filtered={false} />);
    expect(screen.getByRole("link", { name: /all files/i })).toBeDefined();
  });
});
