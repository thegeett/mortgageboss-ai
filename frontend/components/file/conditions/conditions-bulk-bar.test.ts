/**
 * The bulk report line (S2-02 / spec §LP-913): "4 updated · 1 skipped: information only".
 *
 * A PURE FUNCTION WITH A MUST-MATCH STRING, so it is tested rather than eyeballed. The grouping is
 * real logic — eleven rows refused for one reason must read as one clause, not eleven — and the
 * fallback for an unrecognised code is the kind of branch that only ever runs in production.
 */
import { describe, expect, it } from "vitest";
import { bulkResultSummary } from "./conditions-bulk-bar";

describe("what a bulk write did", () => {
  it("says only the count when nothing was refused", () => {
    expect(bulkResultSummary({ applied: ["a", "b", "c"], refused: [] })).toBe("3 updated");
  });

  it("matches the design's line", () => {
    // The spec quotes this exactly: "4 updated · 1 skipped: information only".
    const line = bulkResultSummary({
      applied: ["a", "b", "c", "d"],
      refused: [
        {
          code: "info_only_has_no_status",
          message: "This line is information from the lender — there is nothing to track.",
        },
      ],
    });

    expect(line).toBe("4 updated · 1 skipped: information only");
  });

  it("groups rows refused for the same reason into one clause", () => {
    // ELEVEN ROWS, ONE REASON, ONE CLAUSE. Listing each refusal separately turns a summary into the
    // wall of text the summary exists to replace.
    const line = bulkResultSummary({
      applied: [],
      refused: Array.from({ length: 11 }, () => ({
        code: "info_only_has_no_status",
        message: "This line is information from the lender — there is nothing to track.",
      })),
    });

    expect(line).toBe("0 updated · 11 skipped: information only");
  });

  it("keeps different reasons apart", () => {
    const line = bulkResultSummary({
      applied: ["a"],
      refused: [
        { code: "info_only_has_no_status", message: "…" },
        { code: "backward_move_needs_reason", message: "…" },
        { code: "backward_move_needs_reason", message: "…" },
      ],
    });

    expect(line).toContain("1 updated");
    expect(line).toContain("1 skipped: information only");
    expect(line).toContain("2 skipped: needs a reason");
  });

  it("never prints a raw code at a processor", () => {
    // An unrecognised value in front of a processor is exactly what the closed vocabularies exist to
    // prevent. A code this build has not heard of degrades to something honest instead.
    const line = bulkResultSummary({
      applied: [],
      refused: [{ code: "some_future_code", message: "…" }],
    });

    expect(line).toBe("0 updated · 1 skipped: not allowed");
    expect(line).not.toContain("some_future_code");
  });
});
