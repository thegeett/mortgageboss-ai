// @vitest-environment jsdom
import type { ConditionRound, ConditionSourceKind, ParseReport } from "@/lib/types/conditions";
import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

/**
 * Which screen the Conditions tab shows, and why (LP-909 §3).
 *
 * ⚠️ EACH TEST NAMES THE SENTENCE IT EXPECTS, never merely that "a notice rendered" — the screens
 * tell a processor different things to do, and an assertion that survives them being swapped is not
 * an assertion about which screen showed.
 *
 * This paragraph used to justify that by the ORDER of two competing predicates: a zero-row draft
 * whose reader also asked for the AI satisfied both `isAbandonedByAi` and `isEmptyDraft`. The first
 * of those is gone — every door now queues the split, so the state it described is unreachable —
 * and with it the conflict. The discipline outlives the reason for it.
 *
 * The API module is mocked; every predicate under test is the real one, because the predicates ARE
 * the subject. Mocking one of them would leave these asserting against constants written here.
 */

const useConditionRounds = vi.fn();

vi.mock("@/lib/api/conditions", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/lib/api/conditions")>()),
  useConditionRounds: (...args: unknown[]) => useConditionRounds(...args),
  // ⚠️ THE EMPTY-STATE BRANCH MOUNTS A REAL `useMutation` OTHERWISE. `ConditionsEmpty` owns the
  // upload, so rendering it here without this fails with "No QueryClient set" — which is a fact
  // about the child's data layer, not about which branch this component chose.
  //
  // Mocked rather than wrapped in a `QueryClientProvider`: the subject of this file is WHICH screen
  // renders, the child has its own tests for the upload, and a provider here would let a real
  // mutation reach for the network to prove something neither file is asking.
  useUploadConditionSheet: () => ({ mutate: vi.fn(), isPending: false }),
}));

vi.mock("@/lib/api/timeline", () => ({
  useTimeline: () => ({ data: { inbox_address: "lf-x@in.example.test" } }),
}));

vi.mock("@/lib/toast", () => ({
  notifyError: vi.fn(),
  notifyStarted: vi.fn(),
  notifySuccess: vi.fn(),
}));

import { ConditionsDashboard } from "./conditions-dashboard";

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

function report(overrides: Partial<ParseReport> = {}): ParseReport {
  return {
    reader: "uwm",
    reader_version: "v1",
    warnings: [],
    unassigned_lines: [],
    duplicates_dropped: 0,
    ai_used: false,
    needs_ai: false,
    failure_kind: null,
    failure_detail: null,
    ...overrides,
  };
}

function round(
  overrides: Partial<ConditionRound> = {},
  sourceKind: ConditionSourceKind = "pdf_upload",
): ConditionRound {
  return {
    id: "r1",
    round_number: null,
    status: "draft",
    completeness: "full",
    sheet_format: "uwm_approval_letter",
    sources: [
      { kind: sourceKind, at: null, document_id: null, inbound_attachment_id: null, user_id: null },
    ],
    date_printed: null,
    round_date: "2026-09-24",
    expiry_dates: null,
    draft_rows: [],
    parse_report: report(),
    header: null,
    condition_count: 0,
    created_at: new Date().toISOString(),
    ...overrides,
  };
}

/** A draft row is only ever counted here, so a stub with the right shape is enough. */
function rows(count: number) {
  return Array.from({ length: count }, (_, i) => ({ sequence: i + 1 })) as never;
}

const handlers = {
  onPaste: vi.fn(),
  onAddByHand: vi.fn(),
  onUploadAnother: vi.fn(),
  onDiscard: vi.fn(),
};

function show(data: ConditionRound[] | undefined, state: "ok" | "pending" | "error" = "ok") {
  useConditionRounds.mockReturnValue({
    data,
    isPending: state === "pending",
    isError: state === "error",
    refetch: vi.fn(),
  });
  render(<ConditionsDashboard fileId="f1" {...handlers} />);
}

describe("which screen the Conditions tab shows", () => {
  it("offers the four ways in when the file has no rounds", () => {
    show([]);
    expect(screen.getByRole("heading", { name: "Upload the approval letter" })).toBeDefined();
  });

  it("⚠️ treats a file whose only round was DISCARDED as having none", () => {
    // Discarded rounds stay in the list on purpose — a processor who threw a draft away should see
    // that they did. So "is there anything to work on" has to exclude them rather than take the
    // newest row, or the tab shows a thrown-away draft as the current work.
    show([round({ status: "discarded", draft_rows: rows(6) })]);
    expect(screen.getByRole("heading", { name: "Upload the approval letter" })).toBeDefined();
  });

  it("shows the reading card while the sheet is being read", () => {
    show([round({ status: "parsing" })]);
    expect(screen.getByText("Reading the condition sheet…")).toBeDefined();
  });

  it("shows the failure card with the server's own reason", () => {
    show([
      round({
        status: "parse_failed",
        parse_report: report({ failure_kind: "unreadable", failure_detail: "Password-protected." }),
      }),
    ]);
    expect(screen.getByText("We couldn’t open this PDF")).toBeDefined();
    expect(screen.getByText("Password-protected.")).toBeDefined();
  });

  it("⚠️ never offers Try again, because no route re-reads a round", () => {
    // `parse_condition_round.delay()` is called from creation paths only. Both child screens take
    // `onRetry` optionally so they need no change the day a route exists; today none is passed.
    show([round({ status: "parse_failed", parse_report: report({ failure_kind: "no_text" }) })]);
    expect(screen.queryByRole("button", { name: "Try again" })).toBeNull();
  });

  it("⚠️ shows a round waiting for the AI split as being read, at every door", () => {
    // This file used to assert the opposite, and the assertion was correct when written:
    // `split_condition_round.delay()` was reachable only from `paste_conditions`, so an uploaded
    // sheet whose reader asked for the AI waited forever, and the dashboard said so.
    //
    // `parse_round` now queues the split for every door and leaves the round PARSING while it runs,
    // so "waiting for a reader that will not come" describes a state that no longer exists. The
    // screen for it was deleted rather than narrowed — a screen for an unreachable state looks
    // maintained while describing a bug that is gone.
    show([round({ status: "parsing", parse_report: report({ needs_ai: true }) }, "pdf_upload")]);
    expect(screen.getByText("Reading the condition sheet…")).toBeDefined();
  });

  it("⚠️ and a split that genuinely failed is a failure, not a limbo", () => {
    // The case the deleted notice was sometimes right about. `split_round` settles PARSE_FAILED with
    // `ai_unavailable` when the model is unreachable, so it lands on the failure screen with the
    // server's own sentence — which is where a processor can act on it.
    show([
      round({
        status: "parse_failed",
        parse_report: report({
          needs_ai: true,
          failure_kind: "ai_unavailable",
          failure_detail: "The reader is unavailable right now.",
        }),
      }),
    ]);
    expect(screen.getByText("The reader couldn’t finish this one")).toBeDefined();
  });

  it("distinguishes a sheet read successfully with nothing in it", () => {
    // Still reachable, and by two routes now: a non-condition PDF the rules read cleanly, and a
    // split that ran and found nothing (`needs_ai` with `ai_used` true, zero rows).
    show([round({ draft_rows: [] })]);
    expect(screen.getByText("We read this sheet and found no conditions in it")).toBeDefined();
  });

  it("⚠️ treats a split that ran and found nothing as an empty sheet, not as pending AI", () => {
    // The pair (needs_ai, ai_used) is what distinguishes "waiting for the AI" from "the AI has run".
    // A round carrying both with zero rows has finished, so it must read as an empty sheet rather
    // than as work still in flight.
    show([round({ draft_rows: [], parse_report: report({ needs_ai: true, ai_used: true }) })]);
    expect(screen.getByText("We read this sheet and found no conditions in it")).toBeDefined();
  });

  it("says the review screen is unbuilt rather than rendering a blank tab", () => {
    show([round({ draft_rows: rows(11) })]);
    expect(screen.getByText(/11 conditions read, awaiting review/)).toBeDefined();
  });

  it("names what the failure means for their work rather than apologising", () => {
    show(undefined, "error");
    expect(screen.getByText("The conditions couldn’t be loaded")).toBeDefined();
    expect(screen.getByText(/Nothing was changed, and no sheet was lost/)).toBeDefined();
  });
});
