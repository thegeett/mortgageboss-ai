import type { EvaluationOutcome, RuleFinding } from "@/lib/types/verification";
// @vitest-environment jsdom
/**
 * The five §8 tabs (LP-376) — the honesty contract + the quarantine, in tests.
 *
 * Enforces what the engine fought five tickets for: `couldnt_check` lives in Tab 1 (never Tab 2/4); Tab 3 ≠
 * Tab 4; the three Tab-1 outcomes are distinguishable; the two finding systems never merge (a legacy row
 * never in tabs 1-4, a rule row never in Tab 5, their counts never summed); the detail card shows the AI's
 * REASONING + the spec's guideline; and there are NO §10 actions on tabs 1-4 (LP-377).
 */
import { cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";
import { RuleFindingsTabs } from "./rule-findings-tabs";

afterEach(cleanup);

function ruleFinding(overrides: Partial<RuleFinding> = {}): RuleFinding {
  return {
    id: overrides.id ?? "rf-1",
    rule_id: overrides.rule_id ?? "ID-4",
    evaluation_outcome: overrides.evaluation_outcome ?? "couldnt_check",
    status: overrides.status ?? "yellow",
    category: overrides.category ?? "identity",
    message: overrides.message ?? "the address-type classification is unknown",
    subject_key: overrides.subject_key ?? "b-1",
    subject_label: overrides.subject_label ?? "Dana Sample",
    guideline: overrides.guideline ?? "Fannie B3-4.1: the borrower's residence must be consistent.",
    load_bearing_tags: overrides.load_bearing_tags ?? [
      {
        tag_id: "id.current_address_type",
        value: "unknown",
        confidence: 0.9,
        reasoning: "the document states no address type",
        source_facts: ["doc1"],
      },
    ],
    ratification_pending: overrides.ratification_pending ?? false,
    how_to_fix: overrides.how_to_fix ?? null,
    confidence: overrides.confidence ?? 1,
    resolution_status: overrides.resolution_status ?? "open",
  };
}

function renderTabs(ruleFindings: RuleFinding[], legacyCount = 0, ruleFindingsStale = false) {
  return render(
    <RuleFindingsTabs
      ruleFindings={ruleFindings}
      ruleFindingsStale={ruleFindingsStale}
      legacyCount={legacyCount}
      legacy={<div>LEGACY-SWEEP-CONTENT</div>}
    />,
  );
}

const OUTCOMES: EvaluationOutcome[] = [
  "open",
  "couldnt_check",
  "needs_review",
  "satisfied",
  "no_longer_applies",
];

function tab(name: RegExp) {
  return screen.getByRole("tab", { name });
}

describe("the §8 tabs — the honesty contract", () => {
  it("puts couldnt_check in Tab 1 (Needs attention), never Tab 2 or Tab 4", () => {
    renderTabs([ruleFinding({ evaluation_outcome: "couldnt_check", message: "a gap here" })]);

    // Default tab is Needs attention → the couldnt_check finding shows.
    expect(screen.getByText("a gap here")).toBeDefined();

    // Tab 2 (Satisfied) does NOT contain it.
    fireEvent.click(tab(/satisfied/i));
    expect(screen.queryByText("a gap here")).toBeNull();

    // Tab 4 (Not applicable) is a by-design empty state — it never absorbs the couldnt_check.
    fireEvent.click(tab(/not applicable/i));
    expect(screen.queryByText("a gap here")).toBeNull();
    expect(screen.getByText(/structurally empty on every file/i)).toBeDefined();
  });

  it("keeps Tab 3 (No longer applies) distinct from Tab 4 (Not applicable)", () => {
    renderTabs([]);
    fireEvent.click(tab(/no longer applies/i));
    expect(screen.getByText(/subject leaves the file between runs/i)).toBeDefined();
    fireEvent.click(tab(/not applicable/i));
    expect(screen.getByText(/not recorded as findings/i)).toBeDefined();
    // The two empty states say DIFFERENT things — they are not merged for tidiness.
    expect(screen.queryByText(/subject leaves the file between runs/i)).toBeNull();
  });

  it("distinguishes the three Tab-1 outcomes, with the violations (open) group first", () => {
    renderTabs([
      ruleFinding({ id: "cc", evaluation_outcome: "couldnt_check", message: "cc msg" }),
      ruleFinding({ id: "nr", evaluation_outcome: "needs_review", message: "nr msg" }),
      ruleFinding({ id: "op", evaluation_outcome: "open", message: "op msg", status: "red" }),
    ]);
    // The three outcome group headers are all present and named differently.
    expect(screen.getByRole("heading", { name: "Violation" })).toBeDefined();
    expect(screen.getByRole("heading", { name: "Couldn't check" })).toBeDefined();
    expect(screen.getByRole("heading", { name: "Needs review" })).toBeDefined();
    // `open` (Violation) renders BEFORE `couldnt_check` — the real signal isn't buried.
    const headings = screen.getAllByRole("heading").map((h) => h.textContent);
    expect(headings.indexOf("Violation")).toBeLessThan(headings.indexOf("Couldn't check"));
  });

  it("Tab 2 (Satisfied) is reachable — a pass is visible, not assumed", () => {
    renderTabs([ruleFinding({ evaluation_outcome: "satisfied", message: "the address agrees" })]);
    fireEvent.click(tab(/satisfied/i));
    expect(screen.getByText("the address agrees")).toBeDefined();
  });

  it("collapses N findings sharing a rule + reason into one summary, expandable to WHICH ones (LP-376-C)", () => {
    // 4 unclassified documents each yield ID-7's identical couldnt_check → ONE row, not four.
    const reason =
      "a document in the file could not be classified — it may be the title commitment";
    renderTabs(
      ["s1", "s2", "s3", "s4"].map((sid) =>
        ruleFinding({
          id: sid,
          rule_id: "ID-7",
          evaluation_outcome: "couldnt_check",
          message: reason,
          subject_key: sid,
        }),
      ),
    );
    // The reason renders ONCE (a summary), with the count — not four identical lines.
    expect(screen.getAllByText(reason)).toHaveLength(1);
    expect(screen.getByText("4 findings")).toBeDefined();
    // Expanding reveals the individual findings (the model is intact — which four is recoverable).
    fireEvent.click(screen.getByText("4 findings"));
    expect(screen.getAllByText(reason).length).toBeGreaterThan(1);
  });
});

describe("the quarantine — the two systems never merge", () => {
  it("a legacy finding never appears in tabs 1-4; a rule finding never in Tab 5", () => {
    renderTabs([ruleFinding({ message: "GOVERNED-RULE-FINDING" })], 5);

    // Tabs 1-4: the governed finding shows, the legacy content does NOT.
    expect(screen.getByText("GOVERNED-RULE-FINDING")).toBeDefined();
    expect(screen.queryByText("LEGACY-SWEEP-CONTENT")).toBeNull();

    // Tab 5: the legacy content shows, the governed finding does NOT.
    fireEvent.click(tab(/old findings/i));
    expect(screen.getByText("LEGACY-SWEEP-CONTENT")).toBeDefined();
    expect(screen.queryByText("GOVERNED-RULE-FINDING")).toBeNull();
  });

  it("never sums the two systems' counts — each tab shows only its own list's count", () => {
    // 2 governed (Needs attention) + a legacy count of 7 → the tabs read 2 and 7, NEVER 9.
    renderTabs(
      [
        ruleFinding({ id: "a", evaluation_outcome: "open", status: "red" }),
        ruleFinding({ id: "b", evaluation_outcome: "couldnt_check" }),
      ],
      7,
    );
    expect(within(tab(/needs attention/i)).getByText("2")).toBeDefined();
    expect(within(tab(/old findings/i)).getByText("7")).toBeDefined();
    // 9 (the sum) appears nowhere.
    expect(screen.queryByText("9")).toBeNull();
  });

  it("labels Tab 5 truthfully as two legacy, deprecated systems", () => {
    renderTabs([], 3);
    fireEvent.click(tab(/old findings/i));
    expect(screen.getByText(/two deprecated systems/i)).toBeDefined();
    expect(screen.getByText(/scheduled for removal/i)).toBeDefined();
  });
});

describe("the provenance card — the reasoning IS the product", () => {
  it("shows the AI's reasoning and the SPEC's guideline when a row is expanded", () => {
    renderTabs([
      ruleFinding({
        message: "the address-type is unknown",
        guideline: "Fannie B3-4.1 — residence must be consistent.",
        load_bearing_tags: [
          {
            tag_id: "id.current_address_type",
            value: "unknown",
            confidence: 0.88,
            reasoning: "the bank statement states no address type",
            source_facts: ["doc1"],
          },
        ],
      }),
    ]);
    // Expand the row.
    fireEvent.click(screen.getByRole("button", { name: /the address-type is unknown/i }));

    // The reasoning is shown prominently (not hidden), and the guideline is the spec's.
    expect(screen.getByText("the bank statement states no address type")).toBeDefined();
    expect(screen.getByText(/Fannie B3-4.1 — residence must be consistent./)).toBeDefined();
    expect(screen.getByText(/from the rule spec/i)).toBeDefined();
  });

  it("marks a needs_review finding as ratification-pending — not a violation", () => {
    renderTabs([
      ruleFinding({
        evaluation_outcome: "needs_review",
        ratification_pending: true,
        message: "occupancy is reasonable",
      }),
    ]);
    expect(screen.getAllByText(/ratification pending/i).length).toBeGreaterThan(0);
  });

  it("has NO §10 action affordances on tabs 1-4 (Accept risk / Request docs / Override / Note — LP-377)", () => {
    renderTabs([ruleFinding({ message: "expand me" })]);
    fireEvent.click(screen.getByRole("button", { name: /expand me/i }));
    for (const label of [/accept risk/i, /request docs/i, /override/i, /add note/i, /apply/i]) {
      expect(screen.queryByRole("button", { name: label })).toBeNull();
    }
  });
});

describe("the subject label (LP-377-B) — the read path's label, never a raw content-id", () => {
  it("renders the subject_label on the row and NEVER the raw subject_key", () => {
    renderTabs([
      ruleFinding({
        rule_id: "AS-1",
        evaluation_outcome: "open",
        status: "red",
        subject_key: "txn54c6369affffffffffff",
        subject_label: "Deposit of $20,000 on 3/27",
        message: "a large deposit needs sourcing",
      }),
    ]);
    const row = screen.getByRole("button", { name: /a large deposit needs sourcing/i });
    expect(within(row).getByText(/Deposit of \$20,000 on 3\/27/)).toBeDefined();
    expect(within(row).queryByText(/txn54c6369a/)).toBeNull(); // the hash is never a user-facing identity
  });

  it("names the document in the provenance card, never the content-id hash", () => {
    renderTabs([
      ruleFinding({
        rule_id: "ID-7",
        evaluation_outcome: "couldnt_check",
        subject_key: "doc067c28e496b10b5f",
        subject_label: "Statement_Mar2026.pdf",
        message: "a document in the file could not be classified",
      }),
    ]);
    fireEvent.click(screen.getByRole("button", { name: /could not be classified/i }));
    // The filename names the subject on BOTH the row chip and the detail card; the raw content-id is gone.
    expect(screen.getAllByText(/Statement_Mar2026\.pdf/).length).toBeGreaterThanOrEqual(2);
    expect(screen.queryByText(/doc067c28e496b10b5f/)).toBeNull();
  });

  it("a collapsed group expands to WHICH documents (each member's label)", () => {
    renderTabs([
      ruleFinding({
        id: "rf-a",
        rule_id: "ID-7",
        evaluation_outcome: "couldnt_check",
        subject_key: "docaaaa",
        subject_label: "March_Statement.pdf",
        message: "a document in the file could not be classified",
      }),
      ruleFinding({
        id: "rf-b",
        rule_id: "ID-7",
        evaluation_outcome: "couldnt_check",
        subject_key: "docbbbb",
        subject_label: "April_Statement.pdf",
        message: "a document in the file could not be classified",
      }),
    ]);
    // Two identical-reason rows collapse to one summary; expanding names WHICH documents.
    fireEvent.click(screen.getByRole("button", { name: /2 findings/i }));
    expect(screen.getByText("March_Statement.pdf")).toBeDefined();
    expect(screen.getByText("April_Statement.pdf")).toBeDefined();
  });
});

describe("LP-377-C — the stale-findings notice", () => {
  it("warns when the latest run's rule engine did not complete but findings are shown", () => {
    renderTabs([ruleFinding({ evaluation_outcome: "couldnt_check" })], 0, /* stale */ true);
    expect(screen.getByText(/from an earlier run/i)).toBeDefined();
  });

  it("shows no notice when the findings are current (not stale)", () => {
    renderTabs([ruleFinding({ evaluation_outcome: "couldnt_check" })], 0, /* stale */ false);
    expect(screen.queryByText(/from an earlier run/i)).toBeNull();
  });

  it("shows no notice when stale but there are no governed findings to mislead about", () => {
    renderTabs([], 0, /* stale */ true);
    expect(screen.queryByText(/from an earlier run/i)).toBeNull();
  });
});

// A guard so a new outcome can't silently fall outside the model.
describe("every outcome maps to a governed tab", () => {
  it.each(OUTCOMES)("routes %s without crashing", (outcome) => {
    expect(() => renderTabs([ruleFinding({ evaluation_outcome: outcome })])).not.toThrow();
  });
});
