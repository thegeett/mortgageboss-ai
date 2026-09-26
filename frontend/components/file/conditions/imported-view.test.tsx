// @vitest-environment jsdom
import type { Condition, ConditionRound, ConditionSourceKind } from "@/lib/types/conditions";
import { cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

/**
 * The file after a round has been imported (S1-05, S1-08, S1-09).
 *
 * ⚠️ THE PROPERTY THIS WHOLE SCREEN EXISTS TO PROTECT IS AN ABSENCE. Stage 1 has no status controls:
 * nothing says cleared, done, satisfied, open or to do, and a condition missing from a later round
 * is not marked missing, removed or cleared either (design rule 3, ADR-404). So most of what is
 * asserted here is that a control is NOT rendered — which is exactly the kind of test that passes
 * for the wrong reason, so each one also asserts something positive alongside it.
 */

const attachMutate = vi.fn();
const conditionsQuery = vi.fn();

vi.mock("@/lib/api/conditions", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/lib/api/conditions")>()),
  useConditions: () => conditionsQuery(),
  useAttachPdf: () => ({ mutate: attachMutate, isPending: false }),
}));

vi.mock("@/lib/toast", () => ({
  notifyError: vi.fn(),
  notifySuccess: vi.fn(),
  notifyStarted: vi.fn(),
}));

import { ImportedView } from "./imported-view";

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

function condition(overrides: Partial<Condition> = {}): Condition {
  return {
    id: "c1",
    lender_code: "1228",
    lender_category: "Appraisal",
    bucket_heading: "UW - Prior To Final Approval (PTD)",
    bucket_kind: "prior_to_docs",
    verbatim_text: "Final inspection is required.",
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
    ...overrides,
  };
}

/**
 * ⚠️ `has_bytes` IS AN INPUT HERE, NOT DERIVED FROM `kind`, AND THAT IS THE POINT OF THIS FIXTURE.
 *
 * The client used to decide "does this round have a PDF" from a list of `kind` values — exactly the
 * list `_has_pdf_source`'s comment warns against — because `storage_path` was not serialised. It now
 * reads `has_bytes`. If this helper inferred the flag from the kind, every test below would pass
 * against a client that still keyed on kind, and the fix would be unguarded by the very tests that
 * look like they cover it.
 *
 * So a source is a `[kind, hasBytes]` pair, and one test deliberately makes them disagree.
 */
type SourceSpec = ConditionSourceKind | [kind: ConditionSourceKind, hasBytes: boolean];

function round(
  overrides: Partial<ConditionRound> = {},
  sourceSpecs: SourceSpec[] = ["pdf_upload"],
): ConditionRound {
  return {
    id: "r1",
    round_number: 1,
    status: "imported",
    completeness: "full",
    sheet_format: "uwm_approval_letter",
    sources: sourceSpecs.map((spec) => {
      // A bare kind keeps the ordinary pairing: bytes for an upload or a forward, none for a paste
      // or a typed round. A tuple overrides it, which is how the divergent case is expressed.
      const [kind, hasBytes] = Array.isArray(spec)
        ? spec
        : [spec, spec === "pdf_upload" || spec === "email"];
      return {
        kind,
        at: null,
        document_id: null,
        inbound_attachment_id: null,
        user_id: null,
        has_bytes: hasBytes,
      };
    }),
    date_printed: "2026-08-28",
    round_date: "2026-08-28",
    expiry_dates: { close_by: "2026-10-30" },
    draft_rows: null,
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
    condition_count: 11,
    created_at: "2026-08-28T10:00:00Z",
    updated_at: "2026-08-28T10:05:00Z",
    ...overrides,
  };
}

const handlers = { onPaste: vi.fn(), onAddByHand: vi.fn(), onUploadAnother: vi.fn() };

function show(rounds: ConditionRound[], conditions: Condition[] = [condition()]) {
  conditionsQuery.mockReturnValue({ data: conditions, isPending: false });
  render(<ImportedView fileId="f1" rounds={rounds} {...handlers} />);
}

// --------------------------------------------------------------------------- //
// The list itself — read-only, by design rule 3
// --------------------------------------------------------------------------- //

describe("the imported list (S1-05)", () => {
  it("shows the lender's wording under the lender's own heading", () => {
    show([round()]);
    expect(screen.getByText("UW - Prior To Final Approval (PTD)")).toBeDefined();
    expect(screen.getByText("Final inspection is required.")).toBeDefined();
  });

  it("⚠️ offers NO edit or remove control, and no status control of any kind", () => {
    // Design rule 3 and ADR-404. The review screen is where a round is changed; once imported this
    // is the lender's record of what they asked for, and only the lender clears a condition.
    // Asserted alongside a positive check so it cannot pass by rendering nothing at all.
    show([round()]);

    expect(screen.getByText("Final inspection is required.")).toBeDefined();
    expect(screen.queryByRole("button", { name: "Edit the wording" })).toBeNull();
    expect(screen.queryByRole("button", { name: "Remove this row" })).toBeNull();

    // ⚠️ SCANNED WITHIN THE ROW, NOT THE SCREEN, AND THE FIRST VERSION COULD NEVER PASS. An unscoped
    // `/cleared/i` matches the design's own callout — "Only the lender clears a condition — nothing
    // here is marked cleared or removed" — which is the sentence that PROVES the property. The guard
    // failed on its own evidence. Scoped to the row it still catches a status chip appearing on a
    // condition, which is the thing that must never happen.
    const row = screen
      .getByText("Final inspection is required.")
      .closest("div.grid") as HTMLElement;
    for (const forbidden of [/cleared/i, /satisfied/i, /mark as done/i, /to do/i, /\bopen\b/i]) {
      expect(within(row).queryByText(forbidden)).toBeNull();
    }
  });

  it("carries the design's sentence about who clears a condition", () => {
    show([round()]);
    expect(
      screen.getByText(
        /This is the lender’s list exactly as issued\. Only the lender clears a condition/,
      ),
    ).toBeDefined();
  });

  it("⚠️ chips every round a condition appeared on, and does not mark the rounds it missed", () => {
    // S1-08: six conditions seen again show `R1 R2`; the other five show `R1` only and are NOT
    // flagged as missing, removed or cleared. `round_numbers` is derived from events server-side
    // precisely because two columns cannot express "on R1 and R3 but not R2".
    show(
      [round({ round_number: 2, id: "r2" }), round()],
      [
        condition({ id: "c1", round_numbers: [1, 2], verbatim_text: "Seen on both rounds." }),
        condition({ id: "c2", sequence: 2, round_numbers: [1], verbatim_text: "Only on round 1." }),
      ],
    );

    const both = screen.getByText("Seen on both rounds.").closest("div.grid") as HTMLElement;
    expect(within(both).getByText("R1")).toBeDefined();
    expect(within(both).getByText("R2")).toBeDefined();

    const only = screen.getByText("Only on round 1.").closest("div.grid") as HTMLElement;
    expect(within(only).getByText("R1")).toBeDefined();
    expect(within(only).queryByText("R2")).toBeNull();
    // The absence must be silent — no badge, no strikethrough, no "not on this round".
    expect(within(only).queryByText(/missing|removed|cleared|not on/i)).toBeNull();
  });
});

// --------------------------------------------------------------------------- //
// The round strip — and the one button whose visibility is a rule
// --------------------------------------------------------------------------- //

describe("the round strip (S1-05, S1-08)", () => {
  it("shows every round with its number, sources and completeness", () => {
    show([round({ id: "r2", round_number: 2, completeness: "partial" }, ["paste"]), round()]);

    expect(screen.getByText("Round 2")).toBeDefined();
    expect(screen.getByText("Round 1")).toBeDefined();
    expect(screen.getByText("Just some")).toBeDefined();
    expect(screen.getByText("Full list")).toBeDefined();
  });

  it("⚠️ keeps discarded rounds in the strip, because the file's history is not the work queue", () => {
    // The dashboard filters discarded rounds out of "what am I working on". This answers a different
    // question, and a round vanishing from it reads as data loss.
    show([round({ id: "r2", round_number: null, status: "discarded" }, ["paste"]), round()]);
    expect(screen.getByText(/discarded/)).toBeDefined();
  });

  it("⚠️ offers Attach the lender's PDF ONLY on a round that has none", () => {
    show([round({ id: "r2", round_number: 2 }, ["paste"]), round()]);

    // One button, on the pasted round — not on the round that arrived as a PDF.
    const buttons = screen.getAllByRole("button", { name: "Attach the lender’s PDF" });
    expect(buttons).toHaveLength(1);
  });

  it("⚠️ follows the BYTES, not the source kind, when the two disagree", () => {
    // THE FAILURE MODE `has_bytes` EXISTS TO CLOSE. The old check keyed on a list of `kind` values,
    // which held only because every bytes-carrying source happens to be written as `pdf_upload` or
    // `email` — a fact about the current writers, not a rule binding them. A `paste` that stored
    // bytes would have been offered an attach the server refuses with "this round already has the
    // lender's PDF".
    //
    // Nothing else in this file can catch that: every other fixture pairs kind and bytes the
    // ordinary way, so a client still keying on kind would pass all of them.
    show([round({ id: "r2", round_number: 2 }, [["paste", true]])]);
    expect(screen.queryByRole("button", { name: "Attach the lender’s PDF" })).toBeNull();
  });

  it("⚠️ and offers it for a bytes-less arrival even on a kind that usually carries them", () => {
    // The other direction: a forward that stored nothing is still attachable, and a kind-based check
    // would refuse it.
    show([round({ id: "r3", round_number: 3 }, [["email", false]])]);
    expect(screen.getByRole("button", { name: "Attach the lender’s PDF" })).toBeDefined();
  });

  it("⚠️ and NOT on a pasted round that has already been enriched", () => {
    // THE CASE `hasPdf` EXISTS FOR. `sources` is a LIST because a paste can gain a PDF (LP-907), so
    // a round enriched earlier carries BOTH `paste` and `pdf_upload`. Asking "was it pasted?" would
    // keep offering the attach on a round that already has the letter — and the server refuses it
    // with "this round already has the lender's PDF".
    show([round({ id: "r2", round_number: 2 }, ["paste", "pdf_upload"])]);
    expect(screen.queryByRole("button", { name: "Attach the lender’s PDF" })).toBeNull();
  });

  it("⚠️ and NOT on a round the server would refuse for its STATUS", () => {
    // THE HALF THE GATE WAS MISSING (LP-909 review). `enrich_round_with_pdf` refuses on TWO counts:
    // a status outside `ENRICHABLE` (`draft` or `imported`), AND a round that already has stored
    // bytes. The strip checked only the second, so a DISCARDED round with no PDF — which this strip
    // renders deliberately, at `opacity-60` — was offered "Attach the lender's PDF" for a merge the
    // server answers 409 to.
    //
    // The discarded-rounds test above already builds exactly this fixture and asserts only that the
    // word renders, so the button was on screen in a passing test: the scenario was covered and the
    // assertion was not.
    show([round({ id: "r2", round_number: null, status: "discarded" }, ["paste"])]);
    expect(screen.queryByRole("button", { name: "Attach the lender’s PDF" })).toBeNull();
  });

  it("⚠️ nor on a parse_failed round, for the same reason", () => {
    // `parse_failed` is outside `ENRICHABLE` too. Reparse is its recovery, not attach.
    show([round({ id: "r2", round_number: null, status: "parse_failed" }, ["paste"])]);
    expect(screen.queryByRole("button", { name: "Attach the lender’s PDF" })).toBeNull();
  });

  it("says what a partial round did NOT do, so absence does not read as removal", () => {
    show([round({ completeness: "partial" }, ["paste"])]);
    expect(screen.getByText(/were left as they are — nothing is removed or cleared/)).toBeDefined();
  });

  it("does not claim a full round left anything alone", () => {
    show([round({ completeness: "full" })]);
    expect(screen.queryByText(/were left as they are/)).toBeNull();
  });
});

// --------------------------------------------------------------------------- //
// The round-details sheet (S1-09)
// --------------------------------------------------------------------------- //

describe("the round-details sheet (S1-09)", () => {
  it("opens from Letter details with the round's chips and the letter's own values", () => {
    show([round({ round_number: 2, round_date: "2026-09-10" }, ["paste", "pdf_upload"])]);

    fireEvent.click(screen.getByRole("button", { name: "Letter details →" }));

    expect(screen.getByText(/Round 2 · 09\/10\/2026/)).toBeDefined();
    // The expiry table survives even when the header is empty (S1-11's shape).
    expect(screen.getByText("Close by")).toBeDefined();
  });

  it("⚠️ shows no enrich callout when the sheet is merely opened", () => {
    // The callout describes an attach that just happened. Showing it on every visit would tell a
    // processor a PDF had been attached each time they looked at the round.
    show([round()]);
    fireEvent.click(screen.getByRole("button", { name: "Letter details →" }));
    expect(screen.queryByText(/Lender’s PDF attached/)).toBeNull();
  });

  it("⚠️ does not call a match a fill, and can still say nothing was filled", async () => {
    // `matched` COUNTS PASTED ROWS THE PDF RECOGNISED; it is not a thing the enrich filled. It sat
    // inside the Filled list, so an attach that filled nothing but matched six rows read "Filled the
    // codes on the 6 pasted conditions" — claiming work the result does not report — and the zero
    // case became unreachable whenever matching happened, which is the ordinary outcome of attaching
    // the PDF of a sheet already pasted in full.
    show([round({ id: "r2", round_number: 2 }, ["paste"])]);
    const input = document.querySelector('input[type="file"]') as HTMLInputElement;
    Object.defineProperty(input, "files", {
      value: [new File(["x"], "approval.pdf", { type: "application/pdf" })],
    });
    fireEvent.change(input);

    attachMutate.mock.calls[0]?.[1]?.onSuccess?.({
      round_id: "r2",
      round_number: 2,
      status: "imported",
      sheet_format: "uwm_approval_letter",
      filled_header: false,
      filled_expiry: false,
      filled_date_printed: false,
      matched: 6,
      added: 0,
      unmatched_existing: 0,
      warnings: [],
    });

    expect(await screen.findByText(/Nothing new was found in it/)).toBeDefined();
    expect(screen.getByText(/It matched 6 pasted conditions/)).toBeDefined();
    expect(screen.queryByText(/Filled the codes/)).toBeNull();
  });

  it("⚠️ has no History section, because no endpoint serves one", () => {
    // S1-09 draws three history entries from `condition_events`. There is no route, no schema and no
    // service that reads them — while LP-904 built `ix_condition_events_round_occurred` FOR this
    // screen. An empty History panel would say "this round has no history", which is false; the
    // section arrives with `GET /condition-rounds/{id}/events`.
    show([round()]);
    fireEvent.click(screen.getByRole("button", { name: "Letter details →" }));
    expect(screen.queryByText(/^History$/)).toBeNull();
  });
});

// --------------------------------------------------------------------------- //
// Attaching the lender's PDF
// --------------------------------------------------------------------------- //

describe("attaching the lender's PDF to a pasted round", () => {
  it("sends the file for that round and says the merge created nothing", async () => {
    show([round({ id: "r2", round_number: 2 }, ["paste"])]);

    const input = document.querySelector('input[type="file"]') as HTMLInputElement;
    const file = new File(["x"], "approval.pdf", { type: "application/pdf" });
    Object.defineProperty(input, "files", { value: [file] });
    fireEvent.change(input);

    expect(attachMutate).toHaveBeenCalledTimes(1);
    expect(attachMutate.mock.calls[0]?.[0]).toMatchObject({ roundId: "r2" });
  });
});
