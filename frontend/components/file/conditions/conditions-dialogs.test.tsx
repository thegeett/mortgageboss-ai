// @vitest-environment jsdom
import type { ConditionRound } from "@/lib/types/conditions";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

/**
 * The two ways conditions arrive without a PDF: pasting them (S1-06) and typing one (S1-12).
 *
 * ⚠️ THE DEFAULT ON THE PASTE DIALOG IS A SAFETY PROPERTY, NOT A PREFERENCE, and it is the first
 * thing asserted here. "Just some conditions" is the answer that can never remove anything; "the
 * lender's full list" is the one that lets Stage 2 later propose conditions as "probably cleared".
 * The API refuses to guess — `completeness` is required with no server default (ADR-404) — so the
 * control defaulting is what makes it a decision a processor saw rather than a fallback they did not.
 *
 * The mutation hooks are mocked; everything else is the real component, because what these tests are
 * about is what the dialog SENDS and what it refuses to send.
 */

const pasteMutate = vi.fn();
const addMutate = vi.fn();

vi.mock("@/lib/api/conditions", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/lib/api/conditions")>()),
  usePasteConditions: () => ({ mutate: pasteMutate, isPending: false }),
  useAddCondition: () => ({ mutate: addMutate, isPending: false }),
}));

vi.mock("@/lib/toast", () => ({
  notifyError: vi.fn(),
  notifyStarted: vi.fn(),
  notifySuccess: vi.fn(),
}));

import { AddConditionDialog } from "./add-condition-dialog";
import { PasteConditionsDialog } from "./paste-conditions-dialog";

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

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
    round_date: "2026-08-28",
    expiry_dates: null,
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
    header: null,
    condition_count: 11,
    created: null,
    seen_again: null,
    created_at: new Date().toISOString(),
    updated_at: new Date().toISOString(),
    ...overrides,
  };
}

// --------------------------------------------------------------------------- //
// S1-06 — the paste dialog
// --------------------------------------------------------------------------- //

describe("pasting conditions (S1-06)", () => {
  function show() {
    render(<PasteConditionsDialog fileId="f1" open onOpenChange={vi.fn()} />);
  }

  it("⚠️ defaults to the answer that can never remove anything", () => {
    show();
    const justSome = screen.getByRole("radio", { name: /Just some conditions/ });
    const fullList = screen.getByRole("radio", { name: /The lender's full list/ });

    expect((justSome as HTMLInputElement).checked).toBe(true);
    expect((fullList as HTMLInputElement).checked).toBe(false);
  });

  it("⚠️ and says what the full list means later, without promising an automatic clear", () => {
    // The distinction ADR-404 turns on. Softening this would have Stage 1 implying a clear the
    // system must never perform on its own.
    show();
    expect(screen.getByText(/never cleared automatically/)).toBeDefined();
  });

  it("counts lines and characters as they are typed", () => {
    show();
    fireEvent.change(screen.getByPlaceholderText(/Paste the lender/), {
      target: { value: "one\ntwo\nthree" },
    });
    expect(screen.getByText(/3 lines · 13 characters/)).toBeDefined();
  });

  it("⚠️ refuses only when genuinely over the server's limit, not near it", () => {
    // The ceiling is `MAX_PASTE_CHARS`, mirrored from the backend and pinned by
    // `test_condition_type_mirror.py`. Refusing at 99% would invent a limit the server does not
    // have — the failure the 20 MB upload ceiling still carries in the other direction.
    show();
    const textarea = screen.getByPlaceholderText(/Paste the lender/);

    fireEvent.change(textarea, { target: { value: "x".repeat(100_000) } });
    // ⚠️ `.disabled).toBe(false)`, NOT `not.toHaveProperty("disabled", true)`. The negative form
    // passes when the property is absent, undefined, or false — so it would hold for a button that
    // does not exist and for one whose disabled state was never wired. Exactly at the limit is the
    // boundary this test is about, so the assertion has to be able to fail on the wrong side of it.
    expect(
      (screen.getByRole("button", { name: "Read conditions" }) as HTMLButtonElement).disabled,
    ).toBe(false);

    fireEvent.change(textarea, { target: { value: "x".repeat(100_001) } });
    expect(screen.getByText(/over the 100,000 limit/)).toBeDefined();
    expect(
      (screen.getByRole("button", { name: "Read conditions" }) as HTMLButtonElement).disabled,
    ).toBe(true);
  });

  it("sends the text, the answer and the round date", () => {
    show();
    fireEvent.change(screen.getByPlaceholderText(/Paste the lender/), {
      target: { value: "1228 Appraisal  Final inspection is required." },
    });
    fireEvent.click(screen.getByRole("radio", { name: /The lender's full list/ }));
    fireEvent.click(screen.getByRole("button", { name: "Read conditions" }));

    expect(pasteMutate).toHaveBeenCalledTimes(1);
    expect(pasteMutate.mock.calls[0]?.[0]).toMatchObject({
      text: "1228 Appraisal  Final inspection is required.",
      completeness: "full",
    });
    // A date is always sent: the control defaults to today rather than leaving the round undated.
    expect(pasteMutate.mock.calls[0]?.[0].round_date).toMatch(/^\d{4}-\d{2}-\d{2}$/);
  });

  it("cannot be submitted empty", () => {
    show();
    expect(
      (screen.getByRole("button", { name: "Read conditions" }) as HTMLButtonElement).disabled,
    ).toBe(true);
  });
});

// --------------------------------------------------------------------------- //
// S1-12 — adding one by hand
// --------------------------------------------------------------------------- //

describe("adding a condition by hand (S1-12)", () => {
  function show(rounds: ConditionRound[] | undefined) {
    render(<AddConditionDialog fileId="f1" rounds={rounds} open onOpenChange={vi.fn()} />);
  }

  it("says which imported round it joins", () => {
    show([round()]);
    expect(
      screen.getByText("Goes into round 1 (08/28/2026), the latest imported round."),
    ).toBeDefined();
  });

  it("⚠️ says it STARTS a round when none has been imported, rather than naming a blank one", () => {
    // `round_number` is null until import, so a file whose only round is still a draft has no
    // number to name. Rendering the first sentence with a gap would describe a round that does not
    // exist; the backend opens one, and the sentence says so.
    show([round({ status: "draft", round_number: null })]);
    expect(screen.getByText("Starts round 1 (typed).")).toBeDefined();
  });

  it("handles a file with no rounds at all", () => {
    show(undefined);
    expect(screen.getByText("Starts round 1 (typed).")).toBeDefined();
  });

  it("requires the lender's wording", () => {
    show([round()]);
    expect(
      (screen.getByRole("button", { name: "Add condition" }) as HTMLButtonElement).disabled,
    ).toBe(true);
  });

  it("⚠️ renders the wording field in serif, because it is the lender's words", () => {
    // Design rule 2: text quoted from a document is IBM Plex Serif. It is the one visual property
    // here that carries meaning rather than taste — it marks whose sentence a processor is reading.
    show([round()]);
    const wording = screen.getByLabelText(/Lender’s wording/);
    expect(wording.className).toContain("font-serif");
  });

  it("sends the wording, the heading and the optional fields", () => {
    show([round()]);
    fireEvent.change(screen.getByLabelText(/Lender’s wording/), {
      target: { value: "Provide a signed letter of explanation for the credit inquiry." },
    });
    fireEvent.change(screen.getByLabelText("Lender code"), { target: { value: "0006" } });
    fireEvent.change(screen.getByLabelText("Heading"), { target: { value: "prior_to_closing" } });
    fireEvent.click(screen.getByRole("button", { name: "Add condition" }));

    expect(addMutate).toHaveBeenCalledTimes(1);
    expect(addMutate.mock.calls[0]?.[0]).toMatchObject({
      verbatim_text: "Provide a signed letter of explanation for the credit inquiry.",
      lender_code: "0006",
      bucket_kind: "prior_to_closing",
      // Untouched optional fields go as null rather than as empty strings — the column is nullable
      // and "" would be a value the lender never wrote.
      lender_category: null,
    });
  });

  it("⚠️ never sends a bucket_heading, because that column is the LENDER's words", () => {
    // THIS TEST USED TO ASSERT THE OPPOSITE AND PINNED A DEFECT. It expected
    // `bucket_heading: "Prior to closing"` — our label for a bucket KIND — written into the column
    // that holds what the lender actually printed. `create_manual_condition` declines to invent one
    // and writes `""` for "filed under no heading", so the client was defeating a rule the server
    // states in a comment.
    //
    // The backend has its own test for this and it passes, because it posts no `bucket_heading` key
    // — a path the real client never took. Two green tests, each covering one layer, and the
    // product violated the property both believed they were protecting.
    show([round()]);
    fireEvent.change(screen.getByLabelText(/Lender’s wording/), {
      target: { value: "Provide the final title commitment." },
    });
    fireEvent.change(screen.getByLabelText("Heading"), { target: { value: "unknown" } });
    fireEvent.click(screen.getByRole("button", { name: "Add condition" }));

    const sent = addMutate.mock.calls[0]?.[0];
    expect(sent.bucket_kind).toBe("unknown");
    // ⚠️ THE WORST CASE, NAMED: `BUCKET_KIND_LABEL.unknown` is "No heading given". Sending it would
    // write that sentence into a column whose EMPTY value already means it.
    //
    // `null` rather than absent, matching `lender_code` and `lender_category` beside it — the
    // server maps it to `""` either way, and asserting the shape keeps the three consistent.
    expect(sent.bucket_heading).toBeNull();
  });
});
