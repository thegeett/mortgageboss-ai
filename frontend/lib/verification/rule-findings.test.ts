import { describe, expect, it } from "vitest";
import { ruleCategoryLabel } from "./rule-findings";

describe("LP-550 — the word 'Fraud' never reaches a processor", () => {
  it("renames the fraud family to something non-accusatory", () => {
    // FR-1..FR-6 sit in the vocabulary's "Fraud" category. A recurring debit that is not on the 1003
    // is almost always a paperwork omission, and FR-5's own activation bar says the rule "surfaces
    // rather than asserts" and cannot even see the disclosed debts — so the screen must not accuse.
    expect(ruleCategoryLabel("Fraud")).toBe("Anomaly");
    expect(ruleCategoryLabel("fraud")).toBe("Anomaly");
  });

  it("leaves every other category alone", () => {
    expect(ruleCategoryLabel("Income")).toBe("Income");
    expect(ruleCategoryLabel("DTI")).toBe("DTI");
  });
});
