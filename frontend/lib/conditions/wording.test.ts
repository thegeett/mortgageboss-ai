import { describe, expect, it } from "vitest";
import { displayWording, wordingWithoutNotes } from "./wording";

describe("wordingWithoutNotes", () => {
  it("removes a dated note span that runs to the end of the text", () => {
    expect(wordingWithoutNotes("A full 2 year history is required. **8/28 Not in Upload")).toBe(
      "A full 2 year history is required.",
    );
  });

  it("removes a closed span from the middle without leaving a gap", () => {
    expect(wordingWithoutNotes("Bank statement **8/28 Received** signed by the borrower.")).toBe(
      "Bank statement signed by the borrower.",
    );
  });

  it("⚠️ leaves ***NOTE*** alone — three asterisks and no date is not a note span", () => {
    // Condition `0132` on the real sheet. The reader emits no chip for it, so removing it here would
    // take text off the screen that nothing else shows.
    expect(wordingWithoutNotes("***NOTE*** Payoff must be current.")).toBe(
      "***NOTE*** Payoff must be current.",
    );
  });

  it("⚠️ does not lower-case what remains", () => {
    // `note_stripped` in readers/uwm.py lower-cases because it feeds a fingerprint. This is display:
    // rewriting the lender's casing is the thing ADR-405 exists to prevent.
    expect(wordingWithoutNotes("CPL and Wire Instructions REQUIRED. **9/2 sent**")).toBe(
      "CPL and Wire Instructions REQUIRED.",
    );
  });
});

describe("displayWording", () => {
  it("strips when the row carries a note", () => {
    expect(displayWording("History required. **8/28 Not in Upload", 1)).toBe("History required.");
  });

  it("⚠️ keeps a matching span when the row carries NO notes", () => {
    // The divergence guard, and the reason this function exists rather than a bare call to the one
    // above. If this regex ever matches a span `_NOTE` did not, the text stays visible instead of
    // vanishing with no chip beside it — spec rule 2, nothing silently dropped.
    expect(displayWording("History required. **8/28 Not in Upload", 0)).toBe(
      "History required. **8/28 Not in Upload",
    );
  });
});
