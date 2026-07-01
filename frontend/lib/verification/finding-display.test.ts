import type { VerificationFinding } from "@/lib/types/verification";
import { describe, expect, it } from "vitest";
import {
  canApply,
  findingDetail,
  findingHeadline,
  findingType,
  findingTypeLabel,
} from "./finding-display";

function finding(over: Partial<VerificationFinding>): VerificationFinding {
  return {
    id: "f",
    rule_id: "cross_source.income_variance",
    origin: "ai_cross_source",
    status: "yellow",
    category: "income",
    message: "Stated income is 8% over the pay stubs.",
    confidence: 0.8,
    source_page: 1,
    source_snippet: "snip",
    resolution_status: "open",
    resolution_note: null,
    applied_record: null,
    details: {},
    ...over,
  };
}

describe("finding-display — templated wording (re-run stability)", () => {
  it("known cross-source types get a deterministic headline (reads identically every run)", () => {
    // The AI message varies run to run; the headline does not.
    const a = finding({ message: "Stated income is 8% over." });
    const b = finding({ message: "The applicant's income looks ~8% high vs docs." });
    expect(findingHeadline(a)).toBe("Stated income doesn’t match the documents");
    expect(findingHeadline(a)).toBe(findingHeadline(b)); // identical despite different AI wording
  });

  it("shows the AI description as SECONDARY detail for templated types", () => {
    const f = finding({ message: "Stated income is 8% over the pay stubs." });
    expect(findingDetail(f)).toBe("Stated income is 8% over the pay stubs.");
  });

  it("novel ('other') findings keep the AI description as the headline", () => {
    const f = finding({ rule_id: "cross_source.other", message: "An unusual cross-doc mismatch." });
    expect(findingHeadline(f)).toBe("An unusual cross-doc mismatch.");
    expect(findingDetail(f)).toBeNull(); // no template → not duplicated
  });

  it("deterministic-rule findings keep their (already deterministic) message", () => {
    const f = finding({
      rule_id: "conv.dti.back_end_max",
      origin: "deterministic_rule",
      message: "Back-end DTI 52% over the 50% cap.",
    });
    expect(findingType(f)).toBeNull();
    expect(findingHeadline(f)).toBe("Back-end DTI 52% over the 50% cap.");
  });

  it("deterministic cross-source (xsrc.*) findings get a READABLE meta-label, not the raw rule_id (LP-92)", () => {
    const f = finding({
      rule_id: "xsrc.income.employer_count_matches_items",
      origin: "deterministic_rule",
      category: "income",
      message: "Stated employer count (2) does not match the income-item count (3).",
    });
    // The ugly prettified raw rule_id ("Xsrc Income Employer Count Matches Items") is gone.
    expect(findingTypeLabel(f)).toBe("Income · Cross-source check");
    expect(findingTypeLabel(f)).not.toContain("Xsrc");
    // The xsrc. namespace is now recognized (no longer null), but the headline is unchanged.
    expect(findingType(f)).not.toBeNull();
    expect(findingHeadline(f)).toBe(
      "Stated employer count (2) does not match the income-item count (3).",
    );
  });

  it("an xsrc.* identity finding labels by its own category (LP-92)", () => {
    const f = finding({
      rule_id: "xsrc.identity.name_consistency",
      origin: "deterministic_rule",
      category: "credit",
    });
    expect(findingTypeLabel(f)).toBe("Credit · Cross-source check");
  });

  it("AI cross-source (cross_source.*) findings keep their existing readable label (no regression)", () => {
    const f = finding({ rule_id: "cross_source.income_variance", category: "income" });
    expect(findingTypeLabel(f)).toBe("Income Variance");
  });

  it("any unmatched rule_id falls back to a readable category label, never the raw rule_id (LP-92)", () => {
    const f = finding({
      rule_id: "conv.dti.back_end_max",
      origin: "deterministic_rule",
      category: "income",
      message: "Back-end DTI 52% over the 50% cap.",
    });
    expect(findingTypeLabel(f)).toBe("Income");
    expect(findingTypeLabel(f)).not.toContain("Conv");
    // A novel category still degrades to a readable generic, never a rule_id.
    const g = finding({ rule_id: "fha.mip.something", category: "mystery" });
    expect(findingTypeLabel(g)).toBe("Verification check");
  });

  it("canApply reflects whether the finding declares a structured-data change", () => {
    expect(canApply(finding({ details: { apply: { action: "add_liability" } } }))).toBe(true);
    expect(canApply(finding({ details: {} }))).toBe(false);
  });
});
