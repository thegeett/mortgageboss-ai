// @vitest-environment jsdom
import type { ConditionRound, ParseReport } from "@/lib/types/conditions";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

/**
 * The three Conditions screens that exist before a round is reviewed (LP-909 §3).
 *
 * ⚠️ WHAT THESE PIN IS THE DECISIONS, NOT THE MARKUP. Every assertion below corresponds to a choice
 * that could be silently undone: the refusal sentences are the design's exact words rather than
 * paraphrases, the failure line shows only provenance the API actually records, a stranded round
 * offers a way out instead of a spinner with no exit, and a button that cannot work is absent rather
 * than present-and-dead. Asserting "it renders" would survive all four being reversed.
 *
 * ⚠️ `isStranded` IS THE REAL ONE. The module is partially mocked — only the hooks that would hit
 * the network are replaced — because the stranded bound is the behaviour under test in two of these
 * cases. Mocking it would leave the tests asserting against a constant I wrote in the same file.
 */

const { uploadMutate } = vi.hoisted(() => ({ uploadMutate: vi.fn() }));
const useTimeline = vi.fn();

vi.mock("@/lib/api/conditions", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/lib/api/conditions")>()),
  useUploadConditionSheet: () => ({ mutate: uploadMutate, isPending: false }),
}));

vi.mock("@/lib/api/timeline", () => ({
  useTimeline: (...args: unknown[]) => useTimeline(...args),
}));

const { notifyError } = vi.hoisted(() => ({ notifyError: vi.fn() }));
vi.mock("@/lib/toast", () => ({
  notifyError: (...args: unknown[]) => notifyError(...args),
  notifyStarted: vi.fn(),
  notifySuccess: vi.fn(),
}));

import { ConditionsEmpty, refuseSheet } from "./conditions-empty";
import { RoundFailed } from "./round-failed";
import { RoundReading } from "./round-reading";

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

function report(overrides: Partial<ParseReport> = {}): ParseReport {
  return {
    reader: null,
    reader_version: null,
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

function round(overrides: Partial<ConditionRound> = {}): ConditionRound {
  return {
    id: "r1",
    round_number: null,
    status: "parsing",
    completeness: "full",
    sheet_format: "generic",
    sources: [
      {
        kind: "pdf_upload",
        at: null,
        document_id: null,
        inbound_attachment_id: null,
        user_id: null,
      },
    ],
    date_printed: null,
    round_date: "2026-09-24",
    expiry_dates: null,
    draft_rows: null,
    parse_report: report(),
    header: null,
    condition_count: 0,
    created_at: new Date().toISOString(),
    updated_at: new Date().toISOString(),
    ...overrides,
  };
}

// --------------------------------------------------------------------------- //
// The pre-round refusal (S1-01 / S1-03)
// --------------------------------------------------------------------------- //

describe("a file refused before a round exists", () => {
  it("uses the design's exact sentence for a non-PDF", () => {
    // ⚠️ THE WORDING IS THE ASSERTION. S1-03 specifies what a refusal says, and a paraphrase would
    // pass any test that merely checked "something was returned".
    const problem = refuseSheet(new File(["x"], "invoice.png", { type: "image/png" }));
    expect(problem).toBe(
      "That file isn’t a PDF. Upload the lender’s PDF, or paste the conditions.",
    );
  });

  it("uses the design's exact sentence for an oversized PDF", () => {
    const big = new File(["x"], "sheet.pdf", { type: "application/pdf" });
    Object.defineProperty(big, "size", { value: 21 * 1024 * 1024 });
    expect(refuseSheet(big)).toBe("This PDF is larger than 20 MB.");
  });

  it("accepts a PDF inside the limit", () => {
    expect(refuseSheet(new File(["x"], "sheet.pdf", { type: "application/pdf" }))).toBeNull();
  });

  it("⚠️ refuses an empty PDF as empty, not as oversized", () => {
    // Not a design sentence — the server 422s zero bytes and this is the instant version of that.
    // Ordered BEFORE the ceiling on purpose: "larger than 20 MB" about a 0-byte file would send a
    // processor hunting for a smaller copy of a file that has no contents.
    expect(refuseSheet(new File([], "sheet.pdf", { type: "application/pdf" }))).toBe(
      "That file is empty. Check it opens, then upload it again.",
    );
  });

  it("⚠️ refuses a PDF whose MIME type is upper-case, and one with no type at all", () => {
    // Both were live differences between this function and a duplicate the conditions page grew:
    // it skipped `.toLowerCase()` and short-circuited on an empty `file.type`, so a browser that
    // reported no type for an unrecognised extension got past it. Neither shape is theoretical.
    expect(refuseSheet(new File(["x"], "SHEET.PDF", { type: "APPLICATION/PDF" }))).toBeNull();
    expect(refuseSheet(new File(["x"], "sheet", { type: "" }))).toBe(
      "That file isn’t a PDF. Upload the lender’s PDF, or paste the conditions.",
    );
  });
});

// --------------------------------------------------------------------------- //
// S1-01 — the empty state
// --------------------------------------------------------------------------- //

describe("the Conditions tab with no rounds (S1-01)", () => {
  function renderEmpty(address: string | null = "lf-k7q2m9@in.example.test") {
    useTimeline.mockReturnValue({ data: address ? { inbox_address: address } : undefined });
    const onPaste = vi.fn();
    const onAddByHand = vi.fn();
    render(<ConditionsEmpty fileId="f1" onPaste={onPaste} onAddByHand={onAddByHand} />);
    return { onPaste, onAddByHand };
  }

  it("offers all four ways in, with upload recommended", () => {
    renderEmpty();
    // ⚠️ BY ROLE, NOT BY TEXT. "Paste conditions" is BOTH a card heading and the button inside it —
    // straight from the design — so `getByText` matches two nodes and throws. Asking for the heading
    // is unambiguous and is the stronger claim anyway: it pins that these titles are headings.
    for (const title of [
      "Upload the approval letter",
      "Paste conditions",
      "Forward the lender’s email",
      "Add one by hand",
    ]) {
      expect(screen.getByRole("heading", { name: title })).toBeDefined();
    }
    // The badge is what makes one of four the suggested path; without it the grid is four equals.
    expect(screen.getByText("Recommended")).toBeDefined();
    expect(screen.getByText("PDF only · up to 20 MB")).toBeDefined();
  });

  it("shows the file's own inbox address to forward to", () => {
    renderEmpty("lf-abc123@in.example.test");
    expect(screen.getByText("lf-abc123@in.example.test")).toBeDefined();
    expect(useTimeline).toHaveBeenCalledWith("f1", "all");
  });

  it("says the address is still loading rather than rendering an empty one", () => {
    // ⚠️ AN EMPTY ADDRESS IS NOT A STATE TO SHOW. A Copy button beside nothing copies nothing, and a
    // blank line reads as "this file has no address", which is never true.
    renderEmpty(null);
    expect(screen.getByText("Loading this file’s address…")).toBeDefined();
    expect(screen.queryByRole("button", { name: /copy/i })).toBeNull();
  });

  it("hands the paste and add actions to the parent", () => {
    // They open dialogs built in §4. Pinning the callbacks is what stops them becoming buttons that
    // silently do nothing when the dialogs land.
    const { onPaste, onAddByHand } = renderEmpty();
    fireEvent.click(screen.getByRole("button", { name: "Paste conditions" }));
    fireEvent.click(screen.getByRole("button", { name: "Add a condition" }));
    expect(onPaste).toHaveBeenCalledTimes(1);
    expect(onAddByHand).toHaveBeenCalledTimes(1);
  });
});

// --------------------------------------------------------------------------- //
// S1-02 — reading, and the state the design has no screen for
// --------------------------------------------------------------------------- //

describe("a round being read (S1-02)", () => {
  it("names the work and says the page can be left", () => {
    render(<RoundReading round={round()} />);
    expect(screen.getByText("Reading the condition sheet…")).toBeDefined();
    for (const step of [
      "Stored",
      "Finding conditions",
      "Reading the letter details",
      "Ready to review",
    ]) {
      expect(screen.getByText(step)).toBeDefined();
    }
    expect(screen.getByText(/You can leave this page/)).toBeDefined();
  });

  it("offers a way out once the round is stranded", () => {
    // ⚠️ THE CASE THE DESIGN DOES NOT DRAW. A round is committed `parsing` before its task is
    // enqueued, so a broker that is down strands it forever. Without this the card polls and spins
    // with no exit — S1-02's "poll until DRAFT or PARSE_FAILED" does not contemplate never.
    const old = new Date(Date.now() - 10 * 60 * 1000).toISOString();
    const onRetry = vi.fn();
    render(<RoundReading round={round({ created_at: old })} onRetry={onRetry} />);

    expect(screen.getByText("Still reading the condition sheet")).toBeDefined();
    fireEvent.click(screen.getByRole("button", { name: "Try again" }));
    expect(onRetry).toHaveBeenCalledTimes(1);
    // The reassurance belongs to the healthy case; repeating it here would say "this is fine".
    expect(screen.queryByText(/You can leave this page/)).toBeNull();
  });
});

// --------------------------------------------------------------------------- //
// S1-03 — read failed, for the kinds that actually exist
// --------------------------------------------------------------------------- //

describe("a round that could not be read (S1-03)", () => {
  const actions = { onUploadAnother: vi.fn(), onPaste: vi.fn(), onDiscard: vi.fn() };

  it("names the failure in the processor's words and shows the server's reason", () => {
    render(
      <RoundFailed
        round={round({
          status: "parse_failed",
          parse_report: report({
            failure_kind: "unreadable",
            failure_detail: "This PDF is password-protected.",
          }),
        })}
        {...actions}
      />,
    );
    expect(screen.getByText("We couldn’t open this PDF")).toBeDefined();
    expect(screen.getByText("This PDF is password-protected.")).toBeDefined();
  });

  it("omits the reader clause when no reader ran", () => {
    // ⚠️ THE FAILURE PATH WRITES `reader: None`. Printing "reader null" — or inventing the
    // readers-tried list the mockup shows — would be fabricating provenance, which is worse than
    // showing less.
    render(
      <RoundFailed
        round={round({ parse_report: report({ failure_kind: "no_text" }) })}
        {...actions}
      />,
    );
    expect(screen.getByText("reason: no_text")).toBeDefined();
  });

  it("names the reader and version when one did run", () => {
    render(
      <RoundFailed
        round={round({
          parse_report: report({
            failure_kind: "parse_failed",
            reader: "uwm",
            reader_version: "v1",
          }),
        })}
        {...actions}
      />,
    );
    expect(screen.getByText("reason: parse_failed · reader uwm v1")).toBeDefined();
  });

  it("⚠️ shows Try again only when a caller supplies it, and this test used to prove nothing", () => {
    // THE OLD VERSION WAS TAUTOLOGICAL AND READ AS MEANINGFUL. It rendered `round()` — an upload,
    // not a paste — asserted no Try again, and explained the absence as "a pasted round has no
    // stored PDF to re-read". The fixture had no such property: the button was missing purely
    // because `actions` omits `onRetry`, so the test asserted the consequence of its own setup
    // while appearing to assert a rule about pasted rounds.
    //
    // The real rule is this one, and it is worth pinning because the screen is now reached BOTH
    // ways: the dashboard passes `onRetry` for a stored sheet, and the prop stays optional because
    // the server refuses a reparse where there is nothing stored to re-read.
    const { unmount } = render(<RoundFailed round={round()} {...actions} />);
    expect(screen.queryByRole("button", { name: "Try again" })).toBeNull();
    expect(screen.getByRole("button", { name: "Paste instead" })).toBeDefined();
    expect(screen.getByRole("button", { name: "Discard" })).toBeDefined();
    unmount();

    const onRetry = vi.fn();
    render(<RoundFailed round={round()} {...actions} onRetry={onRetry} />);
    fireEvent.click(screen.getByRole("button", { name: "Try again" }));
    expect(onRetry).toHaveBeenCalledTimes(1);
  });
});
