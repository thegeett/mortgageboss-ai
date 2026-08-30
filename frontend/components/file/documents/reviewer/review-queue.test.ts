import { describe, expect, it } from "vitest";

import type { ExtractionField } from "@/lib/loan-files/documents";
import type { FieldScrutiny } from "@/lib/types/document";
import { buildQueue, isFullyReviewed, needsAttention, nextAttention } from "./review-queue";

const BARE: FieldScrutiny = {
  critical: false,
  distrusted_reason: null,
  sensitive: false,
  verdict: null,
  corrected_value: null,
};

function field(key: string, confidence: number | null): ExtractionField {
  return { key, label: key, value: "x", source: null, confidence };
}

describe("buildQueue", () => {
  it("tiers each field and carries its verdict", () => {
    const queue = buildQueue(
      [field("employer_name", 0.99), field("gross_pay", 0.99), field("hours", null)],
      { gross_pay: { ...BARE, critical: true } },
    );
    expect(queue.map((f) => f.tier)).toEqual(["confident", "check", "unrated"]);
  });

  it("treats an accepted field as human-confirmed", () => {
    const queue = buildQueue([field("gross_pay", 0.2)], {
      gross_pay: { ...BARE, critical: true, verdict: "accepted" },
    });
    expect(queue[0]?.tier).toBe("verified");
  });

  it("treats a corrected field as human-confirmed too", () => {
    // The processor read the document and typed the right answer. That is a
    // stronger confirmation than accepting, not a weaker one.
    const queue = buildQueue([field("gross_pay", 0.99)], {
      gross_pay: { ...BARE, verdict: "corrected", corrected_value: "4250.00" },
    });
    expect(queue[0]?.tier).toBe("verified");
  });

  it("does NOT treat a rejection as confirmation", () => {
    // "I could not verify this" is the opposite of "this is right".
    const queue = buildQueue([field("gross_pay", 0.99)], {
      gross_pay: { ...BARE, critical: true, verdict: "rejected" },
    });
    expect(queue[0]?.tier).not.toBe("verified");
  });
});

describe("needsAttention", () => {
  it("skips a confident field — the whole point of the binding", () => {
    expect(needsAttention({ key: "a", tier: "confident", verdict: null })).toBe(false);
  });

  it("stops on anything flagged or unrated", () => {
    for (const tier of ["check", "unrated"] as const) {
      expect(needsAttention({ key: "a", tier, verdict: null })).toBe(true);
    }
  });

  it("skips a field already decided, whatever its tier", () => {
    // Walking back onto a decided field is how a loop stops feeling like progress.
    for (const verdict of ["accepted", "corrected", "rejected"]) {
      expect(needsAttention({ key: "a", tier: "check", verdict })).toBe(false);
    }
  });
});

describe("nextAttention", () => {
  const queue = [
    { key: "a", tier: "check" as const, verdict: null },
    { key: "b", tier: "confident" as const, verdict: null },
    { key: "c", tier: "unrated" as const, verdict: null },
    { key: "d", tier: "check" as const, verdict: "accepted" },
  ];

  it("starts at the first field wanting attention", () => {
    expect(nextAttention(queue, null)).toBe("a");
  });

  it("skips the confident one in between", () => {
    expect(nextAttention(queue, "a")).toBe("c");
  });

  it("skips the one already decided", () => {
    // Wraps past `d` back to `a` rather than stopping on a finished field.
    expect(nextAttention(queue, "c")).toBe("a");
  });

  it("wraps, so starting halfway down does not hide the fields above", () => {
    expect(nextAttention(queue, "c", 1)).toBe("a");
  });

  it("walks backwards too", () => {
    expect(nextAttention(queue, "c", -1)).toBe("a");
    expect(nextAttention(queue, "a", -1)).toBe("c");
  });

  it("returns null when nothing is left — the signal ⌘Enter waits for", () => {
    const done = queue.map((f) => ({ ...f, verdict: "accepted" }));
    expect(nextAttention(done, null)).toBeNull();
    expect(nextAttention(done, "a")).toBeNull();
  });

  it("stays put when the only field wanting attention is the current one", () => {
    // NOT null: null is read as "nothing left", and a field still wanting a
    // decision is the opposite of that. Completion is `isFullyReviewed`'s job.
    const one = [{ key: "a", tier: "check" as const, verdict: null }];
    expect(nextAttention(one, "a")).toBe("a");
    expect(isFullyReviewed(one)).toBe(false);
  });

  it("recovers when the current field is no longer in the queue", () => {
    expect(nextAttention(queue, "vanished")).toBe("a");
  });

  it("handles an empty queue", () => {
    expect(nextAttention([], null)).toBeNull();
  });
});

describe("isFullyReviewed", () => {
  it("is false while anything still wants a decision", () => {
    expect(isFullyReviewed([{ key: "a", tier: "check", verdict: null }])).toBe(false);
  });

  it("is true when every field is decided or confident", () => {
    expect(
      isFullyReviewed([
        { key: "a", tier: "check", verdict: "accepted" },
        { key: "b", tier: "confident", verdict: null },
      ]),
    ).toBe(true);
  });

  it("is false for a document with no fields at all", () => {
    // Nothing to review is not the same as reviewed, and marking an empty
    // document complete would be a claim nobody made.
    expect(isFullyReviewed([])).toBe(false);
  });
});
