import { describe, expect, it } from "vitest";

import type { ExtractionField } from "@/lib/loan-files/documents";
import type { FieldScrutiny } from "@/lib/types/document";
import {
  buildQueue,
  editableFieldKey,
  isFullyReviewed,
  needsAttention,
  nextAttention,
  stepField,
} from "./review-queue";

const BARE: FieldScrutiny = {
  critical: false,
  distrusted_reason: null,
  sensitive: false,
  verdict: null,
  corrected_value: null,
};

function field(key: string, confidence: number | null): ExtractionField {
  return {
    key,
    label: key,
    value: "x",
    kind: "scalar",
    columns: [],
    rows: [],
    source: null,
    confidence,
  };
}

function listField(key: string): ExtractionField {
  return {
    key,
    label: key,
    value: "3 rows",
    kind: "list",
    columns: [{ key: "date", label: "Date" }],
    rows: [["a"], ["b"], ["c"]],
    source: null,
    confidence: null,
  };
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

describe("list fields stay out of the loop (LP-702)", () => {
  it("does not queue a list field", () => {
    // It would be `unrated`, so the loop WOULD stop on it, and `e` would open a
    // one-line text editor over a fourteen-row table.
    const queue = buildQueue([field("gross_pay", 0.99), listField("earnings_lines")], {});
    expect(queue.map((f) => f.key)).toEqual(["gross_pay"]);
  });

  it("does not let a list field hold a document back from fully reviewed", () => {
    const queue = buildQueue([listField("earnings_lines"), field("gross_pay", 0.99)], {});
    expect(isFullyReviewed(queue)).toBe(true);
  });
});

describe("stepField — the plain motion the arrows use (LP-701)", () => {
  const KEYS = ["employer_name", "gross_pay", "net_pay", "earnings_lines"];

  it("moves exactly one row, skipping nothing", () => {
    expect(stepField(KEYS, "employer_name", 1)).toBe("gross_pay");
    expect(stepField(KEYS, "gross_pay", 1)).toBe("net_pay");
    expect(stepField(KEYS, "net_pay", -1)).toBe("gross_pay");
  });

  it("includes rows the attention queue leaves out", () => {
    // `earnings_lines` is a list field, so `buildQueue` drops it — but it is a
    // row on the screen, and ↓ has to reach what a processor can see.
    expect(stepField(KEYS, "net_pay", 1)).toBe("earnings_lines");
  });

  it("starts at the first row going down, the last going up", () => {
    expect(stepField(KEYS, null, 1)).toBe("employer_name");
    expect(stepField(KEYS, null, -1)).toBe("earnings_lines");
  });

  it("wraps at both ends", () => {
    expect(stepField(KEYS, "earnings_lines", 1)).toBe("employer_name");
    expect(stepField(KEYS, "employer_name", -1)).toBe("earnings_lines");
  });

  it("takes the first row when the selected key is gone", () => {
    expect(stepField(KEYS, "a_field_from_another_document", 1)).toBe("employer_name");
  });

  it("has nothing to move to on an empty list", () => {
    expect(stepField([], null, 1)).toBeNull();
    expect(stepField([], "gross_pay", 1)).toBeNull();
  });
});

describe("editableFieldKey (LP-702 review)", () => {
  /**
   * The keyboard's two verdict paths acted on whatever was selected, while the
   * mark, the queue and the editor had all been gated on `kind === "scalar"`.
   *
   * `E`/`R` on a list field set `editing` to a key whose editor never mounts —
   * and `shortcutsEnabled({helpOpen, editing})` had already switched the keyboard
   * off, so no key could clear it, the three callbacks that would are props of the
   * editor that never mounted, and `goToDocument` is itself keyboard-driven. The
   * reviewer's whole keyboard loop, `?` included, was dead until a page reload.
   */
  const scalar = (key: string) => ({ ...listField(key), kind: "scalar" as const });

  it("returns a selected SCALAR, which is what has an editor", () => {
    expect(editableFieldKey([scalar("gross_pay")], "gross_pay")).toBe("gross_pay");
  });

  it("refuses a selected LIST — no editor mounts, and nothing could clear it", () => {
    expect(editableFieldKey([listField("earnings_lines")], "earnings_lines")).toBeNull();
  });

  it("refuses when nothing is selected", () => {
    expect(editableFieldKey([scalar("gross_pay")], null)).toBeNull();
  });

  it("refuses a key that is not in this document", () => {
    // A `selected` left over from the previous document: it names no field here,
    // so there is nothing to record a verdict against.
    expect(editableFieldKey([scalar("gross_pay")], "net_pay")).toBeNull();
  });
});

describe("Tab from a row the queue does not carry (LP-701 review)", () => {
  /**
   * TWO TICKETS COMPOSING INTO A BUG, neither wrong alone.
   *
   * LP-702 keeps list-valued fields off the queue; LP-701 made the arrows walk
   * every drawn row. So the selection can sit on a row `nextAttention` has never
   * heard of — and resolving against the queue alone read that as "not started",
   * which took the FIRST stop regardless of where the processor actually was.
   *
   * On `[a, b, c, earnings_lines, d]`, four presses of ↓ select `earnings_lines`;
   * Tab then went back to `a` and Shift+Tab forward to `d`. Both inverted.
   */
  const drawn = ["a", "b", "c", "earnings_lines", "d"];
  const fields = [
    { ...listField("a"), kind: "scalar" as const },
    { ...listField("b"), kind: "scalar" as const },
    { ...listField("c"), kind: "scalar" as const },
    listField("earnings_lines"),
    { ...listField("d"), kind: "scalar" as const },
  ];

  it("goes FORWARD to the next stop below the list row", () => {
    const queue = buildQueue(fields, {});
    expect(nextAttention(queue, "earnings_lines", 1, drawn)).toBe("d");
  });

  it("goes BACKWARD to the stop above it", () => {
    const queue = buildQueue(fields, {});
    expect(nextAttention(queue, "earnings_lines", -1, drawn)).toBe("c");
  });

  it("keeps the pre-LP-701 answer when no drawn order is supplied", () => {
    // The default is the queue's own keys, so every existing caller and test is
    // unchanged — the new argument only adds the rows the queue cannot see.
    const queue = buildQueue(fields, {});
    expect(nextAttention(queue, "c", 1)).toBe("d");
  });
});
