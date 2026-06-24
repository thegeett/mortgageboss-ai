// @vitest-environment jsdom
import type { GenericAnalysis } from "@/lib/types/document";
import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";
import { GenericAnalysisView } from "./generic-analysis-view";

afterEach(cleanup);

describe("GenericAnalysisView (Tier 3 — LP-72)", () => {
  it("renders findings, parties, dates, and amounts", () => {
    const analysis: GenericAnalysis = {
      key_parties: [{ name: "Jane Doe", role: "Grantor" }],
      key_dates: [{ date: "2026-03-01", description: "Effective date" }],
      key_amounts: [{ value: "250000", context: "Trust corpus" }],
      key_findings: [
        {
          finding_type: "obligation",
          description: "Monthly support",
          amount: "1200",
          frequency: "monthly",
        },
      ],
      summary: "A revocable living trust.",
    };
    render(<GenericAnalysisView analysis={analysis} />);
    expect(screen.getByText("Findings")).toBeDefined();
    expect(screen.getByText(/Monthly support/)).toBeDefined();
    expect(screen.getByText("Jane Doe")).toBeDefined();
    expect(screen.getByText("Effective date")).toBeDefined();
    expect(screen.getByText("Trust corpus")).toBeDefined();
  });

  it("shows a calm note when there are no structured findings", () => {
    render(<GenericAnalysisView analysis={{ key_parties: [], key_findings: [] }} />);
    expect(screen.getByText(/No structured findings/)).toBeDefined();
  });
});
