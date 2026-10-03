// @vitest-environment jsdom
/**
 * LP-921 — S3-12's list: Next step where Owner was (M3), "Lender is doing it" inline and neutral with
 * no select (M4), and "Waiting on LO" in the status select (M5).
 */
import { EMPTY_LIST_URL_STATE } from "@/lib/conditions/list-url";
import type { Condition, ConditionItem } from "@/lib/types/conditions";
import { cleanup, render, screen, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { ConditionsList } from "./conditions-list";

afterEach(cleanup);

function item(overrides: Partial<ConditionItem>): ConditionItem {
  return {
    id: "i1",
    key: "k",
    name: "Item",
    acceptable: "",
    performer: "borrower",
    performers: ["borrower"],
    option: "ask_borrower",
    status: "open",
    origin: "reading",
    need_id: null,
    need_title: null,
    shared_with_codes: [],
    document_id: null,
    document_name: null,
    document_page: null,
    waits_on_condition_id: null,
    waits_on_code: null,
    due_date: null,
    specifics: { amounts: [], account_bank: null, account_last4: null, month: null, names: [] },
    task: null,
    draft: null,
    ...overrides,
  };
}

function condition(overrides: Partial<Condition>): Condition {
  return {
    id: "c1",
    lender_code: "1228",
    lender_category: null,
    bucket_heading: "UW - Prior To Final Approval (PTD)",
    bucket_kind: "prior_to_docs",
    verbatim_text: "Words.",
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
    created_at: "2026-08-28T10:00:00Z",
    prep_status: "to_do",
    lender_status: "open",
    waiting_on: null,
    waiting_on_when_sent: null,
    routes: [],
    chosen_route: null,
    updated_at: "2026-08-28T10:00:00Z",
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
    reading_confidence: null,
    library_type: null,
    next_step: null,
    plan_reason: null,
    items: [],
    question_draft: null,
    evidence: [],
    ...overrides,
  };
}

const ROWS = [
  condition({ id: "a", lender_code: "1228", sequence: 1, next_step: "lender_doing_it" }),
  condition({
    id: "b",
    lender_code: "0132",
    sequence: 2,
    prep_status: "waiting",
    waiting_on: "broker",
    items: [item({ performers: ["borrower", "lo"], option: "ask_third_party" })],
  }),
  condition({
    id: "c",
    lender_code: "1582",
    sequence: 3,
    items: [item({ option: "i_will_do_it", performer: "processor", task: "upload the invoice" })],
  }),
];

function row(code: string): HTMLElement {
  const button = screen.getByText(code).closest("[data-condition-row]");
  const container = button?.parentElement;
  if (!container) throw new Error(`no row for ${code}`);
  return container;
}

describe("ConditionsList (S3-12)", () => {
  it("has a Next step column where Owner was", () => {
    render(
      <ConditionsList
        conditions={ROWS}
        state={EMPTY_LIST_URL_STATE}
        search=""
        capped={false}
        selected={new Set()}
        onSelectedChange={vi.fn()}
        onOpen={vi.fn()}
        onMovePrepStatus={vi.fn()}
        onClearFilters={vi.fn()}
      />,
    );
    expect(screen.getByText("Next step")).toBeDefined();
    expect(screen.queryByText("Owner")).toBeNull();
    expect(within(row("1582")).getByText("Your task · upload the invoice")).toBeDefined();
    expect(within(row("0132")).getByText("In LO email")).toBeDefined();
  });

  it("shows 1228 as Lender is doing it, with no status select", () => {
    render(
      <ConditionsList
        conditions={ROWS}
        state={EMPTY_LIST_URL_STATE}
        search=""
        capped={false}
        selected={new Set()}
        onSelectedChange={vi.fn()}
        onOpen={vi.fn()}
        onMovePrepStatus={vi.fn()}
        onClearFilters={vi.fn()}
      />,
    );
    const lenders = within(row("1228"));
    // Once as the next step and once in place of the status.
    expect(lenders.getAllByText("Lender is doing it")).toHaveLength(2);
    expect(lenders.queryByRole("combobox")).toBeNull();
    expect(within(row("1582")).getByRole("combobox")).toBeDefined();
  });

  it("names the LO while we wait on the broker", () => {
    render(
      <ConditionsList
        conditions={ROWS}
        state={EMPTY_LIST_URL_STATE}
        search=""
        capped={false}
        selected={new Set()}
        onSelectedChange={vi.fn()}
        onOpen={vi.fn()}
        onMovePrepStatus={vi.fn()}
        onClearFilters={vi.fn()}
      />,
    );
    const select = within(row("0132")).getByRole("combobox") as HTMLSelectElement;
    expect(select.selectedOptions[0]?.textContent).toBe("Waiting on LO");
  });
});

describe("ConditionsList — Lender's answer (LP-958)", () => {
  function renderWith(rows: Condition[], onRecordAnswer = vi.fn()) {
    render(
      <ConditionsList
        conditions={rows}
        state={EMPTY_LIST_URL_STATE}
        search=""
        capped={false}
        selected={new Set()}
        onSelectedChange={vi.fn()}
        onOpen={vi.fn()}
        onMovePrepStatus={vi.fn()}
        onRecordAnswer={onRecordAnswer}
        onClearFilters={vi.fn()}
      />,
    );
    return onRecordAnswer;
  }

  it("names the column as an answer and an open one as Not cleared yet, with Record", () => {
    const ready = condition({ id: "r", lender_code: "0006", prep_status: "ready" });
    const onRecordAnswer = renderWith([ready]);
    expect(screen.getByText("Lender’s answer")).toBeDefined();
    expect(screen.queryByText("Lender")).toBeNull();
    const cells = within(row("0006"));
    expect(cells.getByText("Not cleared yet")).toBeDefined();
    expect(cells.queryByText("Open")).toBeNull();
    cells.getByRole("button", { name: "Record the lender’s answer for 0006" }).click();
    expect(onRecordAnswer).toHaveBeenCalledWith(ready);
    // Ready says where it goes, not what the plan once asked.
    expect(cells.getByText("Goes in the lender package")).toBeDefined();
  });

  it("offers Record only while the lender owes an answer, and never on a replaced row", () => {
    renderWith([
      condition({ id: "x", lender_code: "0007", lender_status: "not_cleared" }),
      condition({ id: "y", lender_code: "0008", superseded_by_id: "x" }),
    ]);
    expect(within(row("0007")).getByText("Came back")).toBeDefined();
    expect(
      within(row("0007")).getByRole("button", { name: /Record the lender’s answer/ }),
    ).toBeDefined();
    expect(
      within(row("0008")).queryByRole("button", { name: /Record the lender’s answer/ }),
    ).toBeNull();
  });

  it("a sent row waits for the lender's answer", () => {
    renderWith([condition({ id: "s", lender_code: "1947", prep_status: "with_underwriter" })]);
    expect(
      within(row("1947")).getByText("Sent to lender · waiting for their answer"),
    ).toBeDefined();
  });
});
