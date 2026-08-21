import type { RuleFinding } from "@/lib/types/verification";
// @vitest-environment jsdom
import { describe, expect, it } from "vitest";
import { compareRuleIds, groupByRule } from "./rule-findings";

/**
 * LP-613 — findings ordered by rule id, in every section of every tab.
 *
 * They arrived in whatever order the API returned, so "Must fix", "Couldn't check", "In the file" and
 * "Needs review" each listed their rules differently and none of them matched the others. A processor
 * working down a file could not learn where anything sits.
 */

function finding(rule_id: string, id = rule_id): RuleFinding {
  return {
    id,
    rule_id,
    rule_name: rule_id,
    evaluation_outcome: "open",
    severity: "yellow",
    category: "assets",
    subject_label: "Whole file",
    message: "m",
    how_to_fix: null,
    resolution_status: "open",
    load_bearing_tags: [],
    confidence: 1,
  } as unknown as RuleFinding;
}

describe("compareRuleIds", () => {
  it("orders the number NUMERICALLY, not as text", () => {
    // THE POINT. A string sort gives AS-1, AS-10, AS-4 — the tenth rule second, which reads as a bug.
    const sorted = ["AS-10", "AS-4", "AS-1", "AS-8"].sort(compareRuleIds);

    expect(sorted).toEqual(["AS-1", "AS-4", "AS-8", "AS-10"]);
  });

  it("orders by family first", () => {
    const sorted = ["ID-1", "AS-9", "CR-6", "AS-1"].sort(compareRuleIds);

    expect(sorted).toEqual(["AS-1", "AS-9", "CR-6", "ID-1"]);
  });

  it("puts the legacy ids after the governed rules", () => {
    // `cross_source.*` and `xsrc.*` are a different generation of check. Interleaving them with
    // AS/CR/ID would suggest they belong to the same sequence.
    const sorted = [
      "cross_source.income_variance",
      "PR-2",
      "xsrc.identity.ssn_consistency",
      "AS-1",
    ];
    sorted.sort(compareRuleIds);

    expect(sorted).toEqual([
      "AS-1",
      "PR-2",
      "cross_source.income_variance",
      "xsrc.identity.ssn_consistency",
    ]);
  });

  it("is a total order — equal ids compare equal", () => {
    expect(compareRuleIds("AS-1", "AS-1")).toBe(0);
  });
});

describe("groupByRule", () => {
  it("returns the rule groups in rule-id order whatever order they arrived in", () => {
    const groups = groupByRule([
      finding("IN-2"),
      finding("AS-10"),
      finding("CR-6", "a"),
      finding("AS-1"),
      finding("CR-6", "b"),
    ]);

    expect(groups.map((g) => g[0]?.rule_id)).toEqual(["AS-1", "AS-10", "CR-6", "IN-2"]);
  });

  it("still groups every finding of one rule together", () => {
    // The sort must not scatter a rule's findings — CR-6 fires once per liability, and four separate
    // rows for one rule is what the grouping exists to prevent.
    const groups = groupByRule([
      finding("CR-6", "a"),
      finding("AS-1"),
      finding("CR-6", "b"),
      finding("CR-6", "c"),
    ]);

    expect(groups).toHaveLength(2);
    expect(groups[1]).toHaveLength(3);
  });

  it("keeps each rule's findings in their arrival order", () => {
    // Ordering is applied to the RULES, not within a rule: the four CR-6 rows are four different
    // liabilities and the API's order for them is the one the read path chose.
    const groups = groupByRule([finding("CR-6", "first"), finding("CR-6", "second")]);

    expect(groups[0]?.map((f) => f.id)).toEqual(["first", "second"]);
  });
});
