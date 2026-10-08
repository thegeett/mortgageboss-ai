// @vitest-environment jsdom
import type { Condition, ConditionRound, ReadingState, RoundPlan } from "@/lib/types/conditions";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

/**
 * LP-964 — after Import the conditions page shows one step at a time: the reading, then the plan,
 * then the list (the owner, 2026-10-06). Asserted on `ConditionsListView` itself, the layer where the
 * owner saw the list and the plan on screen together.
 *
 * EVERY "THE LIST IS HIDDEN" ASSERTION HAS A POSITIVE CONTROL. The list's marker is the lender's
 * wording of a condition. The plan shows the reading's summary instead, falling back to the wording
 * only when there is no reading, so wherever the plan is on screen the fixture carries a summary. The
 * confirmed-plan test proves the marker DOES appear when the list shows, so its absence elsewhere
 * means the list is held back, not that the marker never renders.
 */

const state: {
  reading: { data: ReadingState | undefined; isPending: boolean };
  plan: { data: RoundPlan | undefined; isPending: boolean };
  rows: Condition[];
} = {
  reading: { data: undefined, isPending: false },
  plan: { data: undefined, isPending: false },
  rows: [],
};

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: vi.fn(), replace: vi.fn() }),
  usePathname: () => "/loan-files/f1/conditions",
  useSearchParams: () => new URLSearchParams(),
}));

vi.mock("@/lib/api/conditions", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/lib/api/conditions")>()),
  useReadingState: () => state.reading,
  useRoundPlan: () => state.plan,
  useConditions: () => ({ data: { rows: state.rows, capped: false }, isPending: false }),
  useConditionsSummary: () => ({ data: undefined, isPending: false, isError: false }),
  useReadAgain: () => ({ mutate: vi.fn(), isPending: false }),
  useConfirmPlan: () => ({ mutate: vi.fn(), isPending: false }),
  useAddItem: () => ({ mutate: vi.fn(), isPending: false }),
  useConditionDrafts: () => ({ data: [] }),
  useConditionDraft: () => ({ data: undefined }),
  useMarkConditionDraftSent: () => ({ mutate: vi.fn(), isPending: false }),
  useDeleteConditionDraft: () => ({ mutate: vi.fn(), isPending: false }),
  useSetConditionDraftAddress: () => ({ mutate: vi.fn(), isPending: false }),
  useSetConditionDraftDueDate: () => ({ mutate: vi.fn(), isPending: false }),
  useFiguresCheck: () => ({ data: undefined }),
  useApplyFigures: () => ({ mutate: vi.fn(), isPending: false }),
  useConditionPackage: () => ({ data: undefined }),
  useBuildPackage: () => ({ mutate: vi.fn(), isPending: false }),
  useUpdatePackageRow: () => ({ mutate: vi.fn(), isPending: false }),
  useMarkDuRerunDone: () => ({ mutate: vi.fn(), isPending: false }),
  useSubmitPackage: () => ({ mutate: vi.fn(), isPending: false }),
  downloadConditionPackage: vi.fn(),
  useWithdrawnConditions: () => ({ data: [] }),
  useWithdrawCondition: () => ({ mutate: vi.fn(), isPending: false }),
  useRestoreCondition: () => ({ mutate: vi.fn(), isPending: false }),
  useSetNextStep: () => ({ mutate: vi.fn(), isPending: false }),
  useUpdateItem: () => ({ mutate: vi.fn(), isPending: false }),
  useConfirmReading: () => ({ mutate: vi.fn(), isPending: false }),
  useLibraryDefaultReading: () => ({ mutate: vi.fn(), isPending: false }),
  useAttachPdf: () => ({ mutate: vi.fn(), isPending: false }),
  usePrepStatus: () => ({ mutate: vi.fn(), isPending: false }),
  useOwner: () => ({ mutate: vi.fn(), isPending: false }),
  useVerdict: () => ({ mutate: vi.fn(), isPending: false }),
  useReopen: () => ({ mutate: vi.fn(), isPending: false }),
  useCondition: () => ({ data: undefined, isPending: false, isError: false }),
  useConditionEvents: () => ({ data: [], isPending: false, isError: false }),
  useRoundEvents: () => ({ data: [], isPending: false, isError: false }),
  useBulkConditions: () => ({ mutate: vi.fn(), isPending: false }),
  useConfirmCleared: () => ({ mutate: vi.fn(), isPending: false }),
  useResolveReworded: () => ({ mutate: vi.fn(), isPending: false }),
  useSwitchCompleteness: () => ({ mutate: vi.fn(), isPending: false }),
}));

vi.mock("@/lib/toast", () => ({
  notifyError: vi.fn(),
  notifySuccess: vi.fn(),
  notifyStarted: vi.fn(),
}));

import { ConditionsListView } from "./conditions-list-view";

afterEach(() => {
  cleanup();
  state.reading = { data: undefined, isPending: false };
  state.plan = { data: undefined, isPending: false };
  state.rows = [];
});

/** The lender's wording: rendered by the list; the plan shows `SUMMARY` when there is a reading. */
const LENDERS_WORDS = "Final inspection is required (lender's wording).";
const SUMMARY = "Final inspection (summary).";
const read = { reading: { summary: SUMMARY } as never };

function condition(overrides: Partial<Condition> = {}): Condition {
  return {
    id: "c1",
    lender_code: "1228",
    lender_category: "Appraisal",
    bucket_heading: "UW - Prior To Final Approval (PTD)",
    bucket_kind: "prior_to_docs",
    verbatim_text: LENDERS_WORDS,
    underwriter_notes: [],
    owner_hint: "unknown",
    owner_hint_source: "none",
    info_only: false,
    canonical_type_id: null,
    origin: "sheet",
    sequence: 1,
    first_round_id: "r1",
    last_seen_round_id: "r1",
    round_numbers: [1],
    created_at: "2026-09-10T10:00:00Z",
    prep_status: "to_do",
    lender_status: "open",
    waiting_on: null,
    waiting_on_when_sent: null,
    routes: [],
    chosen_route: null,
    updated_at: "2026-09-10T10:00:00Z",
    effective_owner: "unknown",
    effective_owner_source: "none",
    latest_note: null,
    is_open: true,
    days_open: 0,
    came_back: false,
    verdict: null,
    superseded_by_id: null,
    reading: null,
    reading_status: "ready",
    reading_confidence: 0.95,
    library_type: null,
    next_step: "ask_third_party",
    plan_reason: null,
    items: [],
    question_draft: null,
    evidence: [],
    ...overrides,
  } as Condition;
}

function round(overrides: Partial<ConditionRound> = {}): ConditionRound {
  return {
    id: "r1",
    round_number: 1,
    status: "imported",
    completeness: "full",
    sheet_format: "uwm_approval_letter",
    sources: [
      {
        kind: "pdf_upload",
        at: null,
        document_id: null,
        inbound_attachment_id: null,
        user_id: null,
        has_bytes: true,
      },
    ],
    date_printed: null,
    round_date: "2026-09-10",
    expiry_dates: null,
    draft_rows: [],
    parse_report: null,
    header: null,
    comparison: null,
    condition_count: 1,
    created: 1,
    seen_again: 0,
    created_at: "2026-09-10T10:00:00Z",
    updated_at: "2026-09-10T10:00:00Z",
    ...overrides,
  } as ConditionRound;
}

function plan(overrides: Partial<RoundPlan> = {}): RoundPlan {
  return {
    round_id: "r1",
    round_number: 1,
    round_date: "2026-09-10",
    planned: 1,
    ready_at: "2026-10-06T12:00:00Z",
    confirmed_at: null,
    nothing_sent: true,
    drafts: [{ recipient: "title", label: "Title/attorney", codes: ["1228"] }],
    your_tasks: 0,
    already_in_file: 0,
    push_back: 0,
    lender_doing_it: 0,
    needs_confirmation: 0,
    blocking_codes: [],
    ...overrides,
  };
}

const done: ReadingState = { state: "done", unread: 0, error: null };

function show(rounds: ConditionRound[] = [round()]) {
  render(
    <ConditionsListView
      fileId="f1"
      rounds={rounds}
      onPaste={vi.fn()}
      onAddByHand={vi.fn()}
      onUploadAnother={vi.fn()}
    />,
  );
}

describe("LP-964 — one step at a time after Import", () => {
  it("shows the list once the plan is confirmed (the positive control for every test below)", () => {
    state.rows = [condition()];
    state.reading = { data: done, isPending: false };
    state.plan = { data: plan({ confirmed_at: "2026-10-06T12:05:00Z" }), isPending: false };
    show();

    expect(screen.getByText(LENDERS_WORDS)).toBeTruthy();
    expect(screen.queryByText(/The list opens when you confirm/)).toBeNull();
  });

  it("shows a placeholder, not the list, while the reading and plan are still loading", () => {
    state.rows = [condition()];
    state.reading = { data: undefined, isPending: true };
    state.plan = { data: undefined, isPending: true };
    show();

    expect(screen.getByLabelText("Loading the plan")).toBeTruthy();
    expect(screen.queryByText(LENDERS_WORDS)).toBeNull();
    // Nothing about the conditions while loading, not even the one-line count (the owner).
    expect(screen.queryByText(/conditions? (is|are) on the file/)).toBeNull();
    expect(screen.queryByRole("button", { name: "Show them now" })).toBeNull();
  });

  it("shows only the reading while the AI reads: no list and no one-line count", () => {
    state.rows = [condition({ next_step: null, reading_status: "unread" })];
    state.reading = { data: { state: "reading", unread: 1, error: null }, isPending: false };
    state.plan = { data: plan({ planned: 0 }), isPending: false };
    show();

    expect(screen.getByText(/Reading 1 condition…/)).toBeTruthy();
    expect(screen.queryByText(/conditions? (is|are) on the file/)).toBeNull();
    expect(screen.queryByText(LENDERS_WORDS)).toBeNull();
  });

  it("keeps the one-line way to the list when the reading failed", () => {
    state.rows = [condition({ next_step: null, reading_status: "unread" })];
    state.reading = { data: { state: "failed", unread: 1, error: "stalled" }, isPending: false };
    state.plan = { data: plan({ planned: 0 }), isPending: false };
    show();

    expect(screen.getByText(/The conditions could not be read/)).toBeTruthy();
    expect(screen.getByRole("button", { name: "Show them now" })).toBeTruthy();
    expect(screen.queryByText(LENDERS_WORDS)).toBeNull();
  });

  it("shows only the plan once it is ready: no list, no filters", () => {
    state.rows = [condition(read)];
    state.reading = { data: done, isPending: false };
    state.plan = { data: plan(), isPending: false };
    show();

    expect(screen.getByText("Plan for round 1")).toBeTruthy();
    expect(screen.getByText(SUMMARY)).toBeTruthy();
    expect(screen.queryByText(LENDERS_WORDS)).toBeNull();
    expect(screen.queryByPlaceholderText(/Search/)).toBeNull();
    // No second copy and no link to one: the plan alone (the owner, 2026-10-07).
    expect(screen.queryByText(/conditions? (is|are) on the file/)).toBeNull();
    expect(screen.queryByRole("button", { name: "Show them now" })).toBeNull();
  });

  it("the plan has no Hide, so the list waits for Confirm (LP-966)", () => {
    state.rows = [condition(read)];
    state.reading = { data: done, isPending: false };
    state.plan = { data: plan(), isPending: false };
    show();

    expect(screen.getByText("Plan for round 1")).toBeTruthy();
    expect(screen.queryByRole("button", { name: "Hide" })).toBeNull();
    expect(screen.queryByText(LENDERS_WORDS)).toBeNull();
  });

  it("on round 2, a failed reading's line names the earlier rounds' conditions", () => {
    state.rows = [
      condition({ id: "c-old", first_round_id: "r1", last_seen_round_id: "r1" }),
      condition({ id: "c-new", sequence: 2, first_round_id: "r2", last_seen_round_id: "r2" }),
    ];
    state.reading = { data: { state: "failed", unread: 1, error: "stalled" }, isPending: false };
    state.plan = { data: plan({ round_id: "r2", round_number: 2, planned: 0 }), isPending: false };
    show([round({ id: "r2", round_number: 2, created_at: "2026-09-20T10:00:00Z" }), round()]);

    expect(screen.getByText(/2 conditions are on the file, 1 from earlier rounds\./)).toBeTruthy();
  });

  it("marks only the new round's conditions as not confirmed: one seen again keeps its plan", () => {
    state.rows = [
      condition({ id: "c-old", first_round_id: "r1", last_seen_round_id: "r2" }),
      condition({
        id: "c-new",
        sequence: 2,
        lender_code: "1947",
        first_round_id: "r2",
        last_seen_round_id: "r2",
      }),
    ];
    // Reached through the one way left to open the list early: a failed reading's "Show them now".
    state.reading = { data: { state: "failed", unread: 1, error: "stalled" }, isPending: false };
    state.plan = { data: plan({ round_id: "r2", round_number: 2, planned: 0 }), isPending: false };
    show([round({ id: "r2", round_number: 2 }), round()]);

    fireEvent.click(screen.getByRole("button", { name: "Show them now" }));

    expect(screen.getAllByText("Plan not confirmed yet")).toHaveLength(1);
  });

  it("shows the list when the plan request fails, rather than hiding the conditions", () => {
    state.rows = [condition()];
    state.reading = { data: undefined, isPending: false };
    state.plan = { data: undefined, isPending: false };
    show();

    expect(screen.getByText(LENDERS_WORDS)).toBeTruthy();
  });
});

describe("LP-964 — discarded rounds fold beside a live one", () => {
  it("folds a discarded draft into a link, and opens it in place", () => {
    state.rows = [condition()];
    state.reading = { data: done, isPending: false };
    state.plan = { data: plan({ confirmed_at: "2026-10-06T12:05:00Z" }), isPending: false };
    show([round({ id: "r-gone", round_number: null, status: "discarded" }), round()]);

    expect(screen.queryByText("Not imported yet")).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "1 discarded · show" }));
    expect(screen.getByText("Not imported yet")).toBeTruthy();
  });
});
