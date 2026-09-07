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
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import type { ReactNode } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";

const mockTimeline = vi.fn();

vi.mock("@/lib/api/timeline", () => ({
  useTimeline: (...args: unknown[]) => mockTimeline(...args),
}));

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
  attachments: ["March_statement.pdf"],
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
    loaded([{ ...MESSAGE, attachments: ["../../etc/passwd"] }]);
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
