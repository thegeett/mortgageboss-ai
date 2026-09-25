// @vitest-environment jsdom
import type { ConditionRound, DraftRow } from "@/lib/types/conditions";
import { cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

/**
 * The review screen (S1-04, S1-07, S1-10, S1-11).
 *
 * ⚠️ THE FIRST TEST IS THE SPEC'S OWN ACCEPTANCE CRITERION — "a frontend test that editing a row
 * and importing sends the edited text" (§LP-909 done-when). It is asserted through the component
 * rather than against the hook, because the failure it guards is a screen that shows an edit and
 * imports the reader's original: every piece works alone and nothing joins them.
 *
 * The mutation hooks are mocked; the predicates, grouping and gating are all real, because those
 * are the subject.
 */

const saveMutate = vi.fn();
const importMutate = vi.fn();

vi.mock("@/lib/api/conditions", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/lib/api/conditions")>()),
  useUpdateDraft: () => ({ mutate: saveMutate, isPending: false }),
  useImportRound: () => ({ mutate: importMutate, isPending: false }),
}));

vi.mock("@/lib/toast", () => ({
  notifyError: vi.fn(),
  notifySuccess: vi.fn(),
  notifyStarted: vi.fn(),
}));

import { RoundReview } from "./round-review";

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

function draftRow(overrides: Partial<DraftRow> = {}): DraftRow {
  return {
    sequence: 1,
    lender_code: "1228",
    lender_category: "Appraisal",
    bucket_heading: "UW - Prior To Final Approval (PTD)",
    bucket_kind: "prior_to_docs",
    verbatim_text: "Final inspection is required.",
    underwriter_notes: [],
    owner_hint: "unknown",
    owner_hint_source: "none",
    processor_assist: false,
    confidence: 1,
    source_line_numbers: [12],
    ...overrides,
  };
}

function round(overrides: Partial<ConditionRound> = {}): ConditionRound {
  return {
    id: "r1",
    round_number: null,
    status: "draft",
    completeness: "full",
    sheet_format: "uwm_approval_letter",
    sources: [
      {
        kind: "pdf_upload",
        at: null,
        document_id: null,
        inbound_attachment_id: null,
        user_id: null,
      },
    ],
    date_printed: "2026-08-28",
    round_date: "2026-08-28",
    expiry_dates: { close_by: "2026-10-30", appraisal: null },
    draft_rows: [draftRow()],
    parse_report: {
      reader: "uwm",
      reader_version: "v1",
      warnings: [],
      unassigned_lines: [],
      duplicates_dropped: 0,
      ai_used: false,
      needs_ai: false,
      failure_kind: null,
      failure_detail: null,
    },
    header: { lender_team: [], loan_facts: {} },
    condition_count: 0,
    created_at: "2026-08-28T10:00:00Z",
    updated_at: "2026-08-28T10:05:00Z",
    ...overrides,
  };
}

function show(overrides: Partial<ConditionRound> = {}) {
  render(<RoundReview round={round(overrides)} fileId="f1" onDiscard={vi.fn()} />);
}

describe("reviewing a draft round", () => {
  it("⚠️ THE SPEC'S ACCEPTANCE TEST: editing a row and importing sends the edited text", () => {
    show();

    fireEvent.click(screen.getByRole("button", { name: "Edit the wording" }));
    fireEvent.change(screen.getByLabelText("The lender's wording"), {
      target: { value: "Final inspection is required before docs." },
    });
    fireEvent.click(screen.getByRole("button", { name: "Save wording" }));
    fireEvent.click(screen.getByRole("button", { name: /Import 1 condition/ }));

    const sent = saveMutate.mock.calls[0]?.[0];
    expect(sent.draft_rows[0].verbatim_text).toBe("Final inspection is required before docs.");
    // ⚠️ AND THE STALE-WRITE GUARD IS ACTUALLY POPULATED. `expected_updated_at` was unreachable
    // until `updated_at` was exposed on the round — every client sent null, so the 409 that exists
    // for two tabs on one draft could never fire.
    expect(sent.expected_updated_at).toBe("2026-08-28T10:05:00Z");
  });

  it("⚠️ sends the token that belongs to the rows it holds, not the freshest one", () => {
    // THE GUARD WAS BYPASSED RATHER THAN TRIPPED (LP-909 review). `rows` is seeded once; the
    // dashboard renders this component with NO `key`, so a refetch swaps the `round` prop under a
    // mounted component without resetting them. Sending `round.updated_at` therefore paired STALE
    // rows with a FRESH token — `update_draft` found the token current and wrote, so the 409 for
    // "someone else changed this" could never fire and the other writer's work vanished silently.
    //
    // Re-rendering with a newer `updated_at` is exactly what a mid-review enrich or reparse does.
    const { rerender } = render(<RoundReview round={round()} fileId="f1" onDiscard={vi.fn()} />);

    rerender(
      <RoundReview
        round={round({ updated_at: "2026-08-28T11:00:00Z" })}
        fileId="f1"
        onDiscard={vi.fn()}
      />,
    );
    fireEvent.click(screen.getByRole("button", { name: /Import 1 condition/ }));

    // The ORIGINAL token, so the server can tell the rows are stale and refuse.
    expect(saveMutate.mock.calls[0]?.[0].expected_updated_at).toBe("2026-08-28T10:05:00Z");
  });

  it("⚠️ imports only after the save resolves, never in parallel", () => {
    // The import reads `draft_rows` from the ROW, so firing both at once would race: the import
    // could read the pre-edit rows and a processor would have no way to tell.
    show();
    fireEvent.click(screen.getByRole("button", { name: /Import 1 condition/ }));

    expect(saveMutate).toHaveBeenCalledTimes(1);
    expect(importMutate).not.toHaveBeenCalled();

    // Let the save succeed the way the mutation would.
    saveMutate.mock.calls[0]?.[1].onSuccess();
    expect(importMutate).toHaveBeenCalledWith("r1", expect.anything());
  });

  it("saves even when nothing was edited, rather than importing the row it never sent", () => {
    show();
    fireEvent.click(screen.getByRole("button", { name: /Import 1 condition/ }));
    expect(saveMutate).toHaveBeenCalledTimes(1);
  });

  it("counts the conditions live in the import button", () => {
    show({ draft_rows: [draftRow(), draftRow({ sequence: 2 }), draftRow({ sequence: 3 })] });
    expect(screen.getByRole("button", { name: "Import 3 conditions" })).toBeDefined();

    fireEvent.click(screen.getAllByRole("button", { name: "Remove this row" })[0] as HTMLElement);
    expect(screen.getByRole("button", { name: "Import 2 conditions" })).toBeDefined();
  });
});

describe("the flagged-rows gate (S1-10)", () => {
  it("⚠️ disables import until the checkbox is ticked when a row is below 0.80", () => {
    show({ draft_rows: [draftRow({ confidence: 0.6 })] });

    const importButton = screen.getByRole("button", { name: /Import 1 condition/ });
    expect((importButton as HTMLButtonElement).disabled).toBe(true);

    fireEvent.click(screen.getByLabelText("I checked the flagged rows"));
    expect((importButton as HTMLButtonElement).disabled).toBe(false);
  });

  it("gates on an unassigned line too, not only on confidence", () => {
    show({
      parse_report: { ...round().parse_report, unassigned_lines: ["EXPIRATION DATES"] },
    });
    expect(
      (screen.getByRole("button", { name: /Import 1 condition/ }) as HTMLButtonElement).disabled,
    ).toBe(true);
  });

  it("⚠️ and does not show the checkbox at all when there is nothing to check", () => {
    // A checkbox that is always present is one a processor learns to tick without reading, which
    // is worse than none — so its ABSENCE on a clean sheet is the property, not just its presence
    // on a flagged one.
    show();
    expect(screen.queryByLabelText("I checked the flagged rows")).toBeNull();
    expect(
      (screen.getByRole("button", { name: /Import 1 condition/ }) as HTMLButtonElement).disabled,
    ).toBe(false);
  });
});

describe("what the screen says about the sheet", () => {
  it("names the format and the reader, and marks it as not imported", () => {
    show();
    expect(screen.getByText("Review · not imported yet")).toBeDefined();
    expect(screen.getByText("UWM · Loan Approval Conditions")).toBeDefined();
    expect(screen.getByText("Read by rules (uwm v1) — no AI")).toBeDefined();
  });

  it("⚠️ omits the Date printed chip when the sheet has none (S1-07, S1-11)", () => {
    // A paste has no letter and the page-break fixture has no header, so the chip would claim a
    // field exists and is blank.
    show({ date_printed: null });
    expect(screen.queryByText(/Date printed/)).toBeNull();
  });

  it("carries both trust sentences beside the import button (design rule 6)", () => {
    show();
    expect(
      screen.getByText(
        /Nothing is saved to the file until you import\. Import never removes or clears a condition\./,
      ),
    ).toBeDefined();
  });

  it("⚠️ says a paste has no letter rather than rendering empty lender fields (S1-07)", () => {
    show({ header: null });
    expect(screen.getByText(/A paste has no letter/)).toBeDefined();
  });

  it("shows all twelve expiry rows, with — for the empty ones", () => {
    // S1-04: "all 12 keys in the lender's order, '—' where empty". A missing row and an empty row
    // mean different things on a lender's table.
    show();
    expect(screen.getByText("Close by")).toBeDefined();
    expect(screen.getByText("10/30/2026")).toBeDefined();
    expect(screen.getByText("VOB")).toBeDefined();
    expect(screen.getByText("Short sale")).toBeDefined();
  });
});

describe("how the rows are grouped and ordered", () => {
  it("⚠️ groups by the LENDER's heading, not by the bucket kind", () => {
    // Two headings that happen to share a kind stay separate: the kind is WHEN a condition is due,
    // the heading is what the lender printed. Grouping by kind would merge two of their sections.
    show({
      draft_rows: [
        draftRow({ sequence: 1, bucket_heading: "UW - Prior To Final Approval (PTD)" }),
        draftRow({ sequence: 2, bucket_heading: "Compliance - Prior To Closing (PTD)" }),
      ],
    });

    expect(screen.getByText("UW - Prior To Final Approval (PTD)")).toBeDefined();
    expect(screen.getByText("Compliance - Prior To Closing (PTD)")).toBeDefined();
  });

  it("⚠️ puts rows below 0.80 first within their group (S1-10)", () => {
    show({
      draft_rows: [
        draftRow({ sequence: 1, confidence: 1, verbatim_text: "Read by the rules." }),
        draftRow({ sequence: 2, confidence: 0.6, verbatim_text: "Split by the AI." }),
      ],
    });

    const wordings = screen.getAllByText(/Read by the rules\.|Split by the AI\./);
    expect(wordings[0]?.textContent).toBe("Split by the AI.");
  });

  it("marks an AI row with its confidence, and leaves a rules row unmarked", () => {
    show({
      draft_rows: [
        draftRow({ sequence: 1, confidence: 0.6 }),
        draftRow({ sequence: 2, confidence: 1 }),
      ],
    });
    expect(screen.getAllByText(/Split by AI · 0\.60/)).toHaveLength(1);
  });

  it("⚠️ renders underwriter notes as chips, never merged into the lender's wording", () => {
    // Design rule 5. The lender wrote one string and the reader carried the note out of it as
    // structure; putting it back would make the underwriter's aside look like the condition.
    show({
      draft_rows: [
        draftRow({
          verbatim_text: "Provide an additional bank statement.",
          underwriter_notes: [
            { date: "2026-08-28", text: "Not in Upload", first_seen_round_id: null },
          ],
        }),
      ],
    });

    expect(screen.getByText("Provide an additional bank statement.")).toBeDefined();
    expect(screen.getByText("Not in Upload")).toBeDefined();
    expect(screen.getByText("8/28")).toBeDefined();
  });

  it("shows the owner hint with where it came from, because the hints are not equally good", () => {
    show({
      draft_rows: [draftRow({ owner_hint: "title", owner_hint_source: "prefix" })],
    });

    // ⚠️ SCOPED TO THE ROW, BECAUSE "Title" IS ALSO AN EXPIRY KEY. The side panel renders all twelve
    // of the lender's expiry rows — Title among them — so an unscoped `getByText("Title")` finds two
    // elements and fails. Loosening it to `getAllByText` would have passed while asserting nothing
    // about WHERE the label appeared, which is the whole point: the hint belongs on the row.
    const row = screen.getByText("Final inspection is required.").closest("div.grid");
    expect(row).not.toBeNull();
    expect(within(row as HTMLElement).getByText("Title")).toBeDefined();
    expect(within(row as HTMLElement).getByText(/from .TC:. prefix/)).toBeDefined();
  });
});
