import type { ReadingState, RoundPlan } from "@/lib/types/conditions";
import { describe, expect, it } from "vitest";
import { planGatePhase } from "./plan-gate";

function plan(overrides: Partial<RoundPlan> = {}): RoundPlan {
  return {
    round_id: "r1",
    round_number: 1,
    round_date: "2026-09-10",
    planned: 6,
    ready_at: "2026-10-06T12:00:00Z",
    confirmed_at: null,
    nothing_sent: true,
    drafts: [],
    your_tasks: 3,
    already_in_file: 0,
    push_back: 0,
    lender_doing_it: 0,
    needs_confirmation: 0,
    blocking_codes: [],
    ...overrides,
  };
}

function reading(state: ReadingState["state"], unread = 0): ReadingState {
  return { state, unread, error: null };
}

const settled = { readingPending: false, planPending: false };

describe("planGatePhase", () => {
  it("is the list when no round has been imported", () => {
    expect(
      planGatePhase({ hasImportedRound: false, reading: undefined, plan: undefined, ...settled }),
    ).toBe("list");
  });

  it("is loading while either request is still pending, so the list never flashes first", () => {
    expect(
      planGatePhase({
        hasImportedRound: true,
        reading: undefined,
        readingPending: true,
        plan: plan(),
        planPending: false,
      }),
    ).toBe("loading");
    expect(
      planGatePhase({
        hasImportedRound: true,
        reading: reading("done"),
        readingPending: false,
        plan: undefined,
        planPending: true,
      }),
    ).toBe("loading");
  });

  it("is reading while the AI reads the round", () => {
    for (const state of ["queued", "reading"] as const) {
      expect(
        planGatePhase({
          hasImportedRound: true,
          reading: reading(state, 6),
          plan: plan({ planned: 0 }),
          ...settled,
        }),
      ).toBe("reading");
    }
  });

  it("is reading while a reading runs again over a plan that is partly built", () => {
    // Read again after a partial failure: some conditions are planned and the plan is still
    // changing, so the step is the reading, not a plan she could confirm mid-way.
    expect(
      planGatePhase({
        hasImportedRound: true,
        reading: reading("reading", 0),
        plan: plan({ planned: 3 }),
        ...settled,
      }),
    ).toBe("reading");
  });

  it("is reading when the reading failed or never started and nothing is planned", () => {
    for (const state of ["failed", "not_queued"] as const) {
      expect(
        planGatePhase({
          hasImportedRound: true,
          reading: reading(state, 6),
          plan: plan({ planned: 0 }),
          ...settled,
        }),
      ).toBe("reading");
    }
  });

  it("is the plan once it is ready and unconfirmed", () => {
    expect(
      planGatePhase({ hasImportedRound: true, reading: reading("done"), plan: plan(), ...settled }),
    ).toBe("plan");
  });

  it("is the list once the plan is confirmed, even if a reading runs again", () => {
    expect(
      planGatePhase({
        hasImportedRound: true,
        reading: reading("reading", 1),
        plan: plan({ confirmed_at: "2026-10-06T12:05:00Z" }),
        ...settled,
      }),
    ).toBe("list");
  });

  it("is the list when everything is read and nothing needed planning", () => {
    expect(
      planGatePhase({
        hasImportedRound: true,
        reading: reading("done"),
        plan: plan({ planned: 0 }),
        ...settled,
      }),
    ).toBe("list");
  });

  it("fails open: an errored request is not pending and has no data, so the list shows", () => {
    expect(
      planGatePhase({
        hasImportedRound: true,
        reading: undefined,
        readingPending: false,
        plan: undefined,
        planPending: false,
      }),
    ).toBe("list");
  });

  it("treats an unknown pending flag as settled, not as loading", () => {
    expect(
      planGatePhase({
        hasImportedRound: true,
        reading: undefined,
        readingPending: undefined,
        plan: undefined,
        planPending: undefined,
      }),
    ).toBe("list");
  });
});
