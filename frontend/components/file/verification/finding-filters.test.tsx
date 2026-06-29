// @vitest-environment jsdom
import type { VerificationFinding } from "@/lib/types/verification";
import { DEFAULT_FILTERS } from "@/lib/verification/finding-filters";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { FindingFilterPills } from "./finding-filters";

function f(over: Partial<VerificationFinding> & { id: string }): VerificationFinding {
  return {
    rule_id: "r",
    origin: "deterministic_rule",
    status: "yellow",
    category: "income",
    message: "m",
    confidence: 0.9,
    source_page: null,
    source_snippet: null,
    resolution_status: "open",
    resolution_note: null,
    details: {},
    ...over,
  };
}

afterEach(() => cleanup());

describe("FindingFilterPills", () => {
  const findings = [
    f({ id: "1", status: "red", category: "credit" }),
    f({ id: "2", status: "yellow", category: "income" }),
    f({ id: "3", status: "yellow", category: "property" }),
  ];

  it("renders severity + category pills and reports selection (orthogonal to the dial)", () => {
    const onChange = vi.fn();
    render(
      <FindingFilterPills findings={findings} filters={DEFAULT_FILTERS} onChange={onChange} />,
    );
    // Severity pills.
    expect(screen.getByRole("button", { name: "Blocking" })).toBeDefined();
    // Category pills built from the categories present.
    expect(screen.getByRole("button", { name: "Credit" })).toBeDefined();
    expect(screen.getByRole("button", { name: "Property" })).toBeDefined();

    fireEvent.click(screen.getByRole("button", { name: "Blocking" }));
    expect(onChange).toHaveBeenCalledWith({ severity: "red", category: "all" });

    fireEvent.click(screen.getByRole("button", { name: "Credit" }));
    expect(onChange).toHaveBeenCalledWith({ severity: "all", category: "credit" });
  });

  it("renders nothing when there's nothing to slice", () => {
    const { container } = render(
      <FindingFilterPills
        findings={[f({ id: "1" })]}
        filters={DEFAULT_FILTERS}
        onChange={vi.fn()}
      />,
    );
    expect(container.firstChild).toBeNull();
  });
});
