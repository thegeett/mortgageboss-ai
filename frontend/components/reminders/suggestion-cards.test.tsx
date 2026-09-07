// @vitest-environment jsdom
/**
 * LP-814 — the suggestion cards, and the one thing they must not appear to do.
 *
 * SPEC 4.5: SUGGESTS ONLY, NEVER SENDS. The card is the surface where that promise is easiest to
 * break — not by sending, but by offering a button that reads as having sent. "Remind" would; the
 * two actions here are "put it off" and "stop telling me", and a test asserts nothing on the card
 * says otherwise.
 *
 * AND THE SNOOZE AND THE DISMISS ARE ONE DECISION AT TWO DISTANCES, which is why they send the same
 * request with a different `until` rather than hitting two endpoints.
 */
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import type { ReactNode } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";

const mockSnooze = vi.fn();

vi.mock("@/lib/api/reminders", () => ({
  useSnooze: () => ({ mutate: mockSnooze, isPending: false }),
}));
vi.mock("@/lib/toast", () => ({ notifySuccess: vi.fn(), notifyError: vi.fn() }));

import type { Suggestion } from "@/lib/types/reminder";
import { SuggestionCard, SuggestionList } from "./suggestion-cards";

function wrapper({ children }: { children: ReactNode }) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
}

const PENDING: Suggestion = {
  loan_file_id: "file-1",
  display_id: "LF-7K3M",
  kind: "needs_item_pending",
  subject_id: "need-1",
  summary: "Bank statements was requested 9 days ago",
  days: 9,
  since: new Date(Date.now() - 9 * 24 * 3600 * 1000).toISOString(),
};

const UNTOUCHED: Suggestion = {
  ...PENDING,
  kind: "file_untouched",
  subject_id: null,
  summary: "Nothing has happened on this file for 8 days",
};

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

describe("what a card offers", () => {
  it("offers to put it off or stop, and nothing that reads as sending", () => {
    render(<SuggestionCard suggestion={PENDING} />, { wrapper });

    expect(screen.getByRole("button", { name: /Snooze/ })).toBeDefined();
    expect(screen.getByRole("button", { name: "Dismiss" })).toBeDefined();
    // The promise spec 4.5 makes. A "Remind" or "Send" button would read as having sent something
    // even if it only opened a draft.
    expect(screen.queryByRole("button", { name: /Send|Remind|Chase|Email/i })).toBeNull();
  });

  it("shows our own summary and links to the file", () => {
    render(<SuggestionCard suggestion={PENDING} />, { wrapper });

    expect(screen.getByText("Bank statements was requested 9 days ago")).toBeDefined();
    expect(screen.getByRole("link", { name: "LF-7K3M" })).toHaveProperty(
      "href",
      expect.stringContaining("/loan-files/file-1/communication"),
    );
  });

  it("does not repeat the file name on the file's own page", () => {
    render(<SuggestionCard suggestion={PENDING} showFile={false} />, { wrapper });
    expect(screen.queryByRole("link", { name: "LF-7K3M" })).toBeNull();
  });
});

describe("snooze and dismiss", () => {
  it("snoozes with a future date", () => {
    render(<SuggestionCard suggestion={PENDING} />, { wrapper });

    fireEvent.click(screen.getByRole("button", { name: /Snooze/ }));

    const [payload] = mockSnooze.mock.calls[0] as [
      { kind: string; subject_id: string | null; until: string | null },
    ];
    expect(payload.kind).toBe("needs_item_pending");
    expect(payload.subject_id).toBe("need-1");
    expect(payload.until).not.toBeNull();
    expect(new Date(payload.until as string).getTime()).toBeGreaterThan(Date.now());
  });

  it("dismisses with null, which is the difference between the two", () => {
    render(<SuggestionCard suggestion={PENDING} />, { wrapper });

    fireEvent.click(screen.getByRole("button", { name: "Dismiss" }));

    const [payload] = mockSnooze.mock.calls[0] as [{ until: string | null }];
    expect(payload.until).toBeNull();
  });

  it("carries a null subject for a rule about the file itself", () => {
    // `subject_id` is null for "this file has gone quiet", and the server's unique index carries
    // NULLS NOT DISTINCT for exactly that. Sending an id here would snooze the wrong thing.
    render(<SuggestionCard suggestion={UNTOUCHED} />, { wrapper });

    fireEvent.click(screen.getByRole("button", { name: "Dismiss" }));

    const [payload] = mockSnooze.mock.calls[0] as [{ subject_id: string | null }];
    expect(payload.subject_id).toBeNull();
  });
});

describe("the list", () => {
  it("calls an empty list correct rather than incomplete", () => {
    // "structural", not "nothing-yet": nothing to chase is the RIGHT state and gets no action.
    // Offering one would imply a processor should go and find something.
    render(<SuggestionList suggestions={[]} />, { wrapper });

    expect(screen.getByText("Nothing needs chasing")).toBeDefined();
    expect(screen.queryByRole("button")).toBeNull();
  });

  it("renders one card per suggestion, including two on the same file", () => {
    // Two suggestions on ONE file is the ordinary case — a request overdue on a file that has also
    // gone quiet — and a list keyed on the file alone would give them the same React key.
    //
    // MEASURED: that does NOT drop a card. React warns and renders both, so this test passes with
    // colliding keys, and it is not claimed as a test of the key. What a collision actually costs is
    // reconciliation reusing component state between the two — a pending snooze showing on the
    // wrong card — which is a render-order artefact this cannot reach. The key includes the kind and
    // the subject anyway, and this pins the count.
    render(<SuggestionList suggestions={[PENDING, UNTOUCHED]} />, { wrapper });

    expect(screen.getAllByRole("listitem")).toHaveLength(2);
  });

  it("gives each rule its own icon", () => {
    // Three rules lead to three different actions; a column of identical icons makes them one thing
    // to scroll past.
    const { container } = render(<SuggestionList suggestions={[PENDING, UNTOUCHED]} />, {
      wrapper,
    });

    // lucide stamps the icon's name into the class (`lucide-clock` vs `lucide-moon`), which is a
    // stabler signal than comparing rendered paths.
    const icons = container.querySelectorAll("li > svg");
    expect(icons).toHaveLength(2);
    expect(icons[0]?.getAttribute("class")).toContain("lucide-clock");
    expect(icons[1]?.getAttribute("class")).toContain("lucide-moon");
  });
});
