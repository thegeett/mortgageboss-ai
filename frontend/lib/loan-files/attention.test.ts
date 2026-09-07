import { ATTENTION_STRIPE } from "@/components/dashboard/attention-cell";
import { byAttention } from "@/lib/loan-files/attention";
import type { AttentionTone, LoanFileSummary } from "@/lib/types/loan-file";
import { describe, expect, it } from "vitest";

const TONES: AttentionTone[] = ["blocking", "attention", "verified", "neutral"];

function file(over: Partial<LoanFileSummary> & { id: string }): LoanFileSummary {
  return {
    display_id: over.id,
    status: "in_processing",
    loan_program: "conventional",
    loan_purpose: "purchase",
    loan_amount: null,
    lender_id: null,
    lender_name: null,
    property_address: null,
    primary_borrower_name: null,
    created_at: "2026-01-01T00:00:00Z",
    updated_at: "2026-01-01T00:00:00Z",
    attention: null,
    ...over,
  } as LoanFileSummary;
}

const withTone = (id: string, tone: AttentionTone, updated: string) =>
  file({
    id,
    updated_at: updated,
    attention: { tone, label: "x", needs_total: 0, needs_satisfied: 0 },
  });

describe("byAttention", () => {
  it("puts what blocks submission first and what is clear last", () => {
    const sorted = byAttention([
      withTone("clear", "verified", "2026-01-05T00:00:00Z"),
      withTone("closed", "neutral", "2026-01-05T00:00:00Z"),
      withTone("chase", "attention", "2026-01-05T00:00:00Z"),
      withTone("blocked", "blocking", "2026-01-01T00:00:00Z"),
    ]);
    expect(sorted.map((f) => f.id)).toEqual(["blocked", "chase", "closed", "clear"]);
  });

  it("breaks ties by most recently touched", () => {
    const sorted = byAttention([
      withTone("older", "attention", "2026-01-01T00:00:00Z"),
      withTone("newer", "attention", "2026-02-01T00:00:00Z"),
    ]);
    expect(sorted.map((f) => f.id)).toEqual(["newer", "older"]);
  });

  it("sorts a file with no attention payload LAST, not first", () => {
    // A version-skewed backend must not float unknown files to the top of a
    // triage list, where they would read as the most urgent thing on the screen.
    const sorted = byAttention([
      file({ id: "unknown" }),
      withTone("clear", "verified", "2026-01-01T00:00:00Z"),
    ]);
    expect(sorted.map((f) => f.id)).toEqual(["clear", "unknown"]);
  });

  it("does not reorder the caller's array", () => {
    // The array belongs to the query cache; sorting in place reorders the cached
    // page for every other reader of it.
    const input = [
      withTone("b", "verified", "2026-01-01T00:00:00Z"),
      withTone("a", "blocking", "2026-01-01T00:00:00Z"),
    ];
    const before = input.map((f) => f.id);
    byAttention(input);
    expect(input.map((f) => f.id)).toEqual(before);
  });

  it("ranks every tone the backend can send", () => {
    const ranked = byAttention(TONES.map((t, i) => withTone(t, t, `2026-01-0${i + 1}T00:00:00Z`)));
    expect(new Set(ranked.map((f) => f.id))).toEqual(new Set(TONES));
  });
});

describe("ATTENTION_STRIPE", () => {
  it("names every tone, so none falls through to no stripe", () => {
    expect(Object.keys(ATTENTION_STRIPE).sort()).toEqual([...TONES].sort());
  });

  it("writes each class out in FULL, never assembled", () => {
    // Tailwind scans source text for complete class names, so `border-l-${tone}`
    // is never emitted and the stripe silently renders as the default border —
    // LP-UI-002's undefined `danger` again: present, resolves to nothing, and
    // nothing fails. A literal here is what makes the class exist.
    for (const [tone, classes] of Object.entries(ATTENTION_STRIPE)) {
      expect(classes, `${tone} must carry a 2px rail`).toContain("border-l-2");
      expect(classes, `${tone} must name its colour literally`).toMatch(/border-l-[a-z-]+$/);
      expect(classes, "a template literal leaves a brace behind").not.toContain("$");
    }
  });
});
