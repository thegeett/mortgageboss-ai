// @vitest-environment jsdom
import type { ConditionRound, ConditionSource, DraftRow } from "@/lib/types/conditions";
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
  // ⚠️ MOCKED BECAUSE THE SCREEN NOW READS THE FILE'S CONDITIONS. S1-07's "just some" callout names
  // how many are already on the file, and the real hook is a `useQuery` with no `QueryClientProvider`
  // in this file's `render` — so omitting this throws inside `RoundReview` before a single assertion
  // runs, and all 28 tests fail as one missing line. `imported-view.test.tsx` already mocks it for
  // the same reason. Empty by default: these cases pin the screen WITHOUT the callout's first clause,
  // which is the round-1 shape anyway.
  useConditions: () => ({ data: [], isPending: false, isError: false }),
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
        has_bytes: true,
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
    created: null,
    seen_again: null,
    created_at: "2026-08-28T10:00:00Z",
    updated_at: "2026-08-28T10:05:00Z",
    ...overrides,
  };
}

function show(overrides: Partial<ConditionRound> = {}) {
  render(<RoundReview round={round(overrides)} fileId="f1" onDiscard={vi.fn()} />);
}

/**
 * One arrival, with `has_bytes` stated rather than inferred from `kind`.
 *
 * ⚠️ THE PAIR IS THE POINT. The format line asks `hasPdf`, which reads `has_bytes` — so a fixture
 * that derived the flag from the kind would pass against a screen still keying on the kind, which is
 * the bug `has_bytes` was added to close.
 */
function source(kind: ConditionSource["kind"], hasBytes: boolean): ConditionSource {
  return {
    kind,
    at: null,
    document_id: null,
    inbound_attachment_id: null,
    user_id: null,
    has_bytes: hasBytes,
  };
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

  it("⚠️ says a recognised PASTE was recognised in the pasted text, not that a letter arrived (S1-07)", () => {
    // `read_pasted_text` returns `UWM_APPROVAL_LETTER` for a paste whose columns survived the
    // clipboard — the SAME `sheet_format` an uploaded letter carries. So this header named a
    // document nobody sent us, and `sheet_format` alone can never tell the two apart.
    show({ sources: [source("paste", false)] });

    expect(screen.getByText("UWM layout · recognised in the pasted text")).toBeDefined();
    expect(screen.queryByText("UWM · Loan Approval Conditions")).toBeNull();
  });

  it("⚠️ and calls it the letter again once the PDF has been attached", () => {
    // The other direction, and the reason this keys on BYTES rather than on `kind`: a pasted round
    // that has been enriched carries BOTH arrivals, and it genuinely does have the letter now.
    // A `kind === "paste"` test would keep calling it a paste forever.
    show({ sources: [source("paste", false), source("pdf_upload", true)] });

    expect(screen.getByText("UWM · Loan Approval Conditions")).toBeDefined();
    expect(screen.queryByText(/recognised in the pasted text/)).toBeNull();
  });

  it("⚠️ marks a partial round with a Just some chip, and a full one with none (S1-07, S1-10)", () => {
    // ⚠️ THE CHIP IS IDENTIFIED BY WHAT IT IS NOT — THE TOGGLE. Both say "Just some": every review
    // mock carries the toggle, and S1-07/S1-10 additionally carry a partial chip among the source
    // chips, so an unscoped query matches two elements on a partial round.
    //
    // This scoped by `{ selector: "span" }` until the toggle became a native radio group, whose
    // visible label is ALSO a span — the discriminator stopped discriminating in the same edit that
    // made the markup semantic, and the test then failed on correct code. Keying on
    // `closest("fieldset")` uses the structural difference between them, which is what actually
    // separates a source chip from a form control rather than a tag they happen to share.
    const chipsOutsideToggle = (text: string) =>
      screen.queryAllByText(text).filter((el) => el.closest("fieldset") === null);

    show({ completeness: "partial" });
    expect(chipsOutsideToggle("Just some")).toHaveLength(1);

    cleanup();
    show({ completeness: "full" });
    expect(chipsOutsideToggle("Just some")).toHaveLength(0);
    expect(chipsOutsideToggle("Full list")).toHaveLength(0);
  });

  it("⚠️ the toggle starts on the server's answer, never on a guess by this screen", () => {
    show({ completeness: "partial" });

    // ⚠️ REAL `checked`, NOT AN `aria-checked` MIRROR OF IT. The control is a native radio, so this
    // asserts the state the browser actually holds; an ARIA attribute that disagrees with its own
    // control is the failure the semantic element removes the possibility of.
    expect((screen.getByRole("radio", { name: "Just some" }) as HTMLInputElement).checked).toBe(
      true,
    );
    expect((screen.getByRole("radio", { name: "Full list" }) as HTMLInputElement).checked).toBe(
      false,
    );
  });

  it("⚠️ THE TOGGLE'S ANSWER REACHES THE SERVER, not merely the screen (S1-04)", () => {
    // The first control on this screen that WRITES. `completeness` is what `import_round` reads to
    // decide whether conditions absent from a later round are left alone or compared — so a toggle
    // that changed only local state would be decorative on the one value that decides what import
    // means. Asserting the payload, not the rendered state, is the whole point.
    show({ completeness: "full" });

    fireEvent.click(screen.getByRole("radio", { name: "Just some" }));
    fireEvent.click(screen.getByRole("button", { name: /Import 1 condition/ }));

    const sent = saveMutate.mock.calls[0]?.[0];
    expect(sent.completeness).toBe("partial");
    // And it rides the frozen token with the rows, as ONE draft rather than two writes.
    expect(sent.expected_updated_at).toBe("2026-08-28T10:05:00Z");
  });

  it("⚠️ draws a named owner as a chip with its glyph, and an unknown one as plain text (S1-04)", () => {
    // ⚠️ SCOPED WITHIN THE ROW, BECAUSE "Title" IS ALSO AN EXPIRY KEY in the side panel — the same
    // trap the provenance test below documents.
    show({
      draft_rows: [
        draftRow({ sequence: 1, owner_hint: "title", owner_hint_source: "prefix" }),
        draftRow({
          sequence: 2,
          owner_hint: "unknown",
          owner_hint_source: "none",
          verbatim_text: "Nobody obvious owns this one.",
        }),
      ],
    });

    const named = screen
      .getByText("Final inspection is required.")
      .closest("div.grid") as HTMLElement;
    const chip = within(named).getByText("Title");
    expect(chip.querySelector("svg")).not.toBeNull();

    // ⚠️ THE ABSENCE IS THE DESIGN, NOT A MISSING ICON. "Owner not known" draws as plain muted text
    // with no chip and no glyph: a chip says "here is who acts", and an absence of evidence does not
    // belong in the same container as a named party.
    const anonymous = screen
      .getByText("Nobody obvious owns this one.")
      .closest("div.grid") as HTMLElement;
    const plain = within(anonymous).getByText("Owner not known");
    expect(plain.querySelector("svg")).toBeNull();
    expect(plain.className).not.toContain("border");
  });

  it("⚠️ names the AI split without doubling the reader into its own version", () => {
    // `SPLIT_VERSION` is "split_v1" because it names the prompt file, so joining reader and version
    // printed "(split split_v1)". The design's line is "(split v1)".
    show({
      parse_report: {
        ...round().parse_report,
        reader: "split",
        reader_version: "split_v1",
        ai_used: true,
      },
    });
    expect(screen.getByText("Split by AI (split v1) · rules found no rows")).toBeDefined();
  });

  it("⚠️ and leaves no gap inside the parens when there is no version at all", () => {
    // The old AI arm produced "Split by AI (split ) · …". The stray space is INSIDE the parens,
    // where the `.trim()` it carried could never reach — while the rules arm patched its own copy
    // with `.replace(" )", ")")` and the fix was never carried across.
    show({
      parse_report: {
        ...round().parse_report,
        reader: "split",
        reader_version: null,
        ai_used: true,
      },
    });
    expect(screen.getByText("Split by AI (split) · rules found no rows")).toBeDefined();
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
    //
    // ⚠️ THE NOTE IS IN BOTH PLACES, WHICH IS THE READER'S ACTUAL OUTPUT AND WAS THE BUG IN THIS
    // TEST. It used to set `verbatim_text` to a clean sentence and the note only as structure — so
    // "never merged into the wording" held over a fixture with nothing to merge, and passed for the
    // whole period the three screens were in fact rendering the note twice. Spec rule 1 keeps the
    // lender's string exactly as written, notes included; the cut belongs to display.
    show({
      draft_rows: [
        draftRow({
          verbatim_text: "Provide an additional bank statement. **8/28 Not in Upload",
          underwriter_notes: [
            { date: "2026-08-28", text: "Not in Upload", first_seen_round_id: null },
          ],
        }),
      ],
    });

    // An EXACT match, so the note being merged back in changes this text and fails the lookup.
    const wording = screen.getByText("Provide an additional bank statement.");
    expect(wording.textContent).not.toContain("Not in Upload");
    expect(wording.textContent).not.toContain("**");

    // Once, as the chip.
    expect(screen.getByText("Not in Upload")).toBeDefined();
    expect(screen.getByText("8/28")).toBeDefined();
  });

  it("⚠️ but the EDITOR shows the stored string whole, note included", () => {
    // The other half of the same rule, and the one that protects the data: what this box holds is
    // what imports. Strip the note here too and an untouched Save would delete the lender's words —
    // a display concern quietly becoming a write.
    show({
      draft_rows: [
        draftRow({
          verbatim_text: "Provide an additional bank statement. **8/28 Not in Upload",
          underwriter_notes: [
            { date: "2026-08-28", text: "Not in Upload", first_seen_round_id: null },
          ],
        }),
      ],
    });

    fireEvent.click(screen.getByRole("button", { name: "Edit the wording" }));
    expect((screen.getByLabelText("The lender's wording") as HTMLTextAreaElement).value).toBe(
      "Provide an additional bank statement. **8/28 Not in Upload",
    );
  });

  it("⚠️ shows no kind chip when the lender's heading already says it (S1-04)", () => {
    // The chip vocabulary has to be the SHORT one for this to be reachable at all:
    // `BUCKET_KIND_LABEL.master` is "Master (applies to the whole file)", which can never equal a
    // heading of "Master", so the comparison always said "different" and S1-11 drew a chip the
    // design omits. Asserting the long form's ABSENCE is what fails if the long map comes back.
    show({
      draft_rows: [draftRow({ bucket_heading: "Master", bucket_kind: "master" })],
    });

    expect(screen.getByText("Master")).toBeDefined();
    expect(screen.queryByText("Master (applies to the whole file)")).toBeNull();
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
